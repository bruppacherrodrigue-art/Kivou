"""PR2b tâche 5 — `/a/{token}` dépose le prospect sur le signal promis.

Ce que ces tests tiennent, et qu'aucun autre ne tient :

    Le lien du cold mail est un LIEN MAGIQUE. Il ouvre une session sans mot de
    passe. Il ne doit donc ouvrir QUE le compte qu'il a lui-même créé, jamais
    un compte où quelqu'un s'est inscrit, et jamais rien du tout quand il est
    périmé.
"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_conversion_attribution import NOW, prepared

from signals.accounts import service as accounts
from signals.accounts.schema import account, account_landing_signal, target_icp
from signals.api.app import create_app
from signals.api.config import ATTRIBUTION_COOKIE_NAME, ApiConfig
from signals.api.routes_auth import SESSION_COOKIE_NAME
from signals.billing.access import feed_access
from signals.billing.catalogue import DISCOVERY_GRANT_LIMIT
from signals.billing.discovery import remaining_slots
from signals.conversion import source
from signals.conversion.token import AttributionTokenKeyring
from signals.engagement.schema import product_event
from signals.persistence.schema import (
    acquisition_conversion_journey,
    contract_award,
    materialized_signal,
)

CLICKED_AT = NOW + dt.timedelta(hours=1)


def client_for(engine, service, *, now: dt.datetime) -> TestClient:
    return TestClient(
        create_app(
            engine,
            ApiConfig(cookie_secure=True),
            now_override=lambda: now,
            conversion_attribution_service=service,
        ),
        base_url="https://testserver",
    )


def pin_session_cookie(client: TestClient, response) -> None:
    """Désamorce la bombe des deux horloges (classe rtl-02).

    Le cookie est daté par l'horloge métier figée du test ; le porte-cookies du
    client l'évalue à l'heure RÉELLE. Sans date, les deux ne se croisent plus.
    """
    for header in response.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        if name == SESSION_COOKIE_NAME:
            client.cookies.set(name, rest.split(";")[0], domain="testserver", path="/")


def land(client: TestClient, token: str):
    return client.get(f"/a/{token}", follow_redirects=False)


def only_account_id(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(sa.select(account.c.account_id)).scalar_one()


def test_landing_opens_a_session_a_draft_profile_and_records_the_promise(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, token.raw_token)

    assert response.status_code == 303
    assert response.headers["location"] == "/app/signals"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith(f"{SESSION_COOKIE_NAME}="))
    assert "HttpOnly" in session_cookie
    assert "Secure" in session_cookie
    assert "SameSite=lax" in session_cookie
    assert "Path=/" in session_cookie

    account_id = only_account_id(engine)
    with engine.connect() as connection:
        stored = connection.execute(sa.select(account)).mappings().one()
        icps = accounts.list_target_icps(connection, account_id=account_id)
        promise = connection.execute(sa.select(account_landing_signal)).mappings().one()
        journeys = connection.execute(
            sa.select(acquisition_conversion_journey)
        ).mappings().all()
        events = connection.execute(sa.select(product_event)).mappings().all()

    # L'identité est un remplacement non délivrable : le jeton ne porte aucune
    # adresse, et en inventer une devinable serait pire que de ne rien mettre.
    assert stored["display_name"] == "Compte à confirmer"
    assert stored["onboarding_status"] == "icp_incomplete"
    # Le profil est un BROUILLON : `FEEDING_ICP_STATUS = "active"` garantit donc
    # qu'aucun signal n'est matérialisé avant confirmation du client.
    assert [icp.status for icp in icps] == ["draft"]
    assert icps[0].customer_input.territories == ("FR",)
    assert icps[0].customer_input.minimum_contract_value is None
    # La promesse est enregistrée même sans signal : l'opportunité est connue,
    # le signal ne l'est pas encore (aucun profil actif, donc aucun signal).
    assert promise["opportunity_key"] == token.payload.opportunity_key
    assert promise["signal_key"] is None
    assert len(journeys) == 1
    assert journeys[0]["account_id"] == account_id
    assert [event["event_type"] for event in events] == ["attribution_landed"]
    assert events[0]["properties"] == {
        "has_signal": False,
        "replayed": False,
        "campaign_ref": token.payload.campaign_ref,
    }
    # §9 — aucune propriété ne contient le jeton ni une adresse.
    assert token.raw_token not in repr(events[0])


def test_the_landing_session_really_opens_the_product(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, token.raw_token)
    pin_session_cookie(client, response)

    me = client.get("/me")
    assert me.status_code == 200
    assert me.json()["account_id"] == only_account_id(engine)
    assert me.json()["onboarding_status"] == "icp_incomplete"


def test_a_replayed_link_returns_to_the_same_account_without_duplicating_it(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    first = client_for(engine, service, now=CLICKED_AT)
    second = client_for(engine, service, now=CLICKED_AT + dt.timedelta(days=2))

    assert land(first, token.raw_token).status_code == 303
    replayed = land(second, token.raw_token)

    assert replayed.status_code == 303
    assert replayed.headers["location"] == "/app/signals"
    with engine.connect() as connection:
        accounts_created = connection.execute(
            sa.select(sa.func.count()).select_from(account)
        ).scalar_one()
        journeys = connection.execute(
            sa.select(sa.func.count()).select_from(acquisition_conversion_journey)
        ).scalar_one()
        profiles = connection.execute(
            sa.select(sa.func.count()).select_from(target_icp)
        ).scalar_one()
        landings = connection.execute(
            sa.select(sa.func.count()).select_from(account_landing_signal)
        ).scalar_one()
        events = connection.execute(sa.select(product_event)).mappings().all()
    assert accounts_created == 1
    assert journeys == 1
    assert profiles == 1
    assert landings == 1
    # Deux arrivées, deux observations : la répétition EST l'information.
    assert [event["properties"]["replayed"] for event in events] == [False, True]

    pin_session_cookie(second, replayed)
    assert second.get("/me").status_code == 200


def _materialize_promise(engine, *, opportunity_key: str, target_icp_id: str) -> str:
    """Un signal matérialisé pour CE profil, écrit sans passer par le moteur.

    Le moteur ne matérialise que pour un profil actif ; ici le profil est un
    brouillon. On écrit donc la ligne directement : ce qui est testé est la
    RÉSOLUTION, pas la matérialisation.
    """
    signal_key = "9" * 64
    with engine.begin() as connection:
        award_key = connection.execute(sa.select(contract_award.c.award_key)).scalars().first()
        connection.execute(
            sa.insert(materialized_signal).values(
                signal_key=signal_key,
                opportunity_key=opportunity_key,
                materialization_award_key=award_key,
                target_icp_id=target_icp_id,
                target_icp_revision=1,
                revision=1,
                content_fingerprint="a" * 64,
                materialized_recency_status="recent_award",
                materialized_award_clock_status="known",
                materialized_notification_clock_status="unknown",
                materialized_publication_clock_status="known",
                materialized_as_of=CLICKED_AT.date(),
                recency_policy_version="recency-test-v1",
                plausible_needs=[],
                icp_matched_needs=[],
                engine_versions={},
                materialized_at=CLICKED_AT,
                created_at=CLICKED_AT,
            )
        )
    return signal_key


def test_a_materialized_promise_lands_on_the_signal_and_costs_no_discovery_slot(
    tmp_path,
) -> None:
    engine, service, token, _ = prepared(tmp_path)
    first = client_for(engine, service, now=CLICKED_AT)
    assert land(first, token.raw_token).status_code == 303
    account_id = only_account_id(engine)
    with engine.connect() as connection:
        target_icp_id = accounts.list_target_icps(
            connection, account_id=account_id
        )[0].target_icp_id
    signal_key = _materialize_promise(
        engine,
        opportunity_key=token.payload.opportunity_key,
        target_icp_id=target_icp_id,
    )

    second = client_for(engine, service, now=CLICKED_AT + dt.timedelta(days=1))
    response = land(second, token.raw_token)

    assert response.status_code == 303
    assert response.headers["location"] == f"/app/signals/{signal_key}"
    with engine.connect() as connection:
        promise = connection.execute(sa.select(account_landing_signal)).mappings().one()
        access = feed_access(connection, account_id=account_id, as_of=CLICKED_AT.date())
        slots = remaining_slots(connection, account_id=account_id)
    assert promise["signal_key"] == signal_key
    # Ouvert nominativement, et sans consommer une des trois places offertes :
    # la promesse est antérieure au compte, la facturer serait la reprendre.
    assert signal_key in access.granted
    assert slots == DISCOVERY_GRANT_LIMIT


def test_an_expired_link_opens_nothing_at_all(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    expired = token.payload.expires_at + dt.timedelta(seconds=1)
    client = client_for(engine, service, now=expired)

    response = land(client, token.raw_token)

    assert response.status_code == 303
    assert response.headers["location"] == "/signup?attribution=expired"
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    with engine.connect() as connection:
        assert connection.execute(
            sa.select(sa.func.count()).select_from(account)
        ).scalar_one() == 0
    assert client.get("/me").status_code == 401


def test_a_tampered_link_opens_nothing_at_all(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, f"{token.raw_token}x")

    assert response.status_code == 303
    assert response.headers["location"] == "/signup?attribution=expired"
    assert "set-cookie" not in response.headers
    with engine.connect() as connection:
        assert connection.execute(
            sa.select(sa.func.count()).select_from(account)
        ).scalar_one() == 0


def _legacy_token(token):
    """Le jeton tel qu'il était émis AVANT `opportunity_key`.

    La charge n'est pas dans le lien : elle est reconstruite en base à la
    vérification. Un champ ajouté à la charge invaliderait donc tous les liens
    déjà partis si la forme signée le contenait — d'où l'omission des champs
    facultatifs absents dans `token._canonical`.
    """
    keyring = AttributionTokenKeyring(
        current_key_version="attribution-test-v1",
        keys={
            "attribution-test-old": b"old-synthetic-attribution-secret",
            "attribution-test-v1": b"synthetic-attribution-secret",
        },
    )
    return keyring.issue(token.payload.model_copy(update={"opportunity_key": None}))


def test_a_link_issued_before_the_promise_still_verifies(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    legacy = _legacy_token(token)
    assert legacy.raw_token != token.raw_token

    with engine.connect() as connection:
        verified = service.verify_in_transaction(
            connection, raw_token=legacy.raw_token, at=CLICKED_AT
        )

    # L'empreinte reste celle de la forme RÉELLEMENT signée : un clic d'hier et
    # une inscription de demain doivent continuer de se rejoindre.
    assert verified.token_fingerprint == legacy.token_fingerprint
    assert verified.token_fingerprint != token.token_fingerprint
    assert verified.payload.opportunity_key == token.payload.opportunity_key


def test_a_link_issued_before_the_promise_still_lands(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, _legacy_token(token).raw_token)

    assert response.status_code == 303
    assert response.headers["location"] == "/app/signals"
    pin_session_cookie(client, response)
    assert client.get("/me").status_code == 200


def _unresolved_token(engine, token, *, monkeypatch):
    """Un jeton dont `AttributionSourceResolver` n'a PU attacher aucune
    opportunité — pas un jeton légataire, un jeton émis aujourd'hui pour lequel
    la résolution a simplement échoué (référence de signal non reconnue,
    opportunité invalidée entretemps, …). Forcé comme la revue l'a fait :
    `opportunity_key_of` renvoyé à `None`.
    """
    monkeypatch.setattr(source, "opportunity_key_of", lambda signal_ref: None)
    with engine.connect() as connection:
        payload = source.AttributionSourceResolver(engine).for_member(
            connection, token.payload.member_ref
        )
    assert payload.opportunity_key is None
    keyring = AttributionTokenKeyring(
        current_key_version="attribution-test-v1",
        keys={
            "attribution-test-old": b"old-synthetic-attribution-secret",
            "attribution-test-v1": b"synthetic-attribution-secret",
        },
    )
    return keyring.issue(payload)


def test_a_promise_the_resolver_could_not_attach_still_lands_and_replays_the_same_account(
    tmp_path, monkeypatch
) -> None:
    """Finding de revue PR2b tâche 5 : `record_landing_signal` n'écrivait la
    ligne d'atterrissage QUE si `opportunity_key` était résolue. Un jeton dont
    la résolution échoue reste pourtant parfaitement valide (ni falsifié, ni
    périmé) — son REJEU doit donc retrouver le même compte, pas tomber sur le
    garde-fou d'identité déjà utilisée faute de ligne à rejoindre.
    """
    engine, service, token, _ = prepared(tmp_path)
    unresolved = _unresolved_token(engine, token, monkeypatch=monkeypatch)

    first = client_for(engine, service, now=CLICKED_AT)
    first_response = land(first, unresolved.raw_token)
    assert first_response.status_code == 303
    assert first_response.headers["location"] == "/app/signals"
    pin_session_cookie(first, first_response)
    first_account_id = first.get("/me").json()["account_id"]

    with engine.connect() as connection:
        promise = connection.execute(
            sa.select(account_landing_signal).where(
                account_landing_signal.c.account_id == first_account_id
            )
        ).mappings().one()
    assert promise["opportunity_key"] is None
    assert promise["signal_key"] is None

    second = client_for(engine, service, now=CLICKED_AT + dt.timedelta(days=2))
    replayed = land(second, unresolved.raw_token)

    assert replayed.status_code == 303
    assert replayed.headers["location"] == "/app/signals"
    pin_session_cookie(second, replayed)
    me = second.get("/me")
    assert me.status_code == 200
    assert me.json()["account_id"] == first_account_id

    with engine.connect() as connection:
        accounts_created = connection.execute(
            sa.select(sa.func.count()).select_from(account)
        ).scalar_one()
        landings = connection.execute(
            sa.select(sa.func.count()).select_from(account_landing_signal)
        ).scalar_one()
    assert accounts_created == 1
    assert landings == 1


def test_the_landing_still_carries_the_attribution_cookie_for_a_real_signup(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, token.raw_token)

    attribution = next(
        cookie
        for cookie in response.headers.get_list("set-cookie")
        if cookie.startswith(f"{ATTRIBUTION_COOKIE_NAME}=")
    )
    assert "Path=/auth/signup" in attribution
    assert "HttpOnly" in attribution
    assert "Secure" in attribution
