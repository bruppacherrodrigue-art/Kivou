"""PR2b tâche 5 — `/a/{token}` dépose le prospect sur le signal promis.

Ce que ces tests tiennent, et qu'aucun autre ne tient :

    Le lien du cold mail est un LIEN MAGIQUE. Il ouvre une session sans mot de
    passe. Il ne doit donc ouvrir QUE le compte qu'il a lui-même créé, jamais
    un compte où quelqu'un s'est inscrit, et jamais rien du tout quand il est
    périmé.
"""

from __future__ import annotations

import datetime as dt
import logging
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_assisted_prospect_preparation import seed_directory
from test_assisted_prospect_preparation import signal as assisted_signal
from test_conversion_attribution import NOW, prepared
from test_saas_company_api import _insert_directory_company

from signals.accounts import service as accounts
from signals.accounts.schema import account, account_landing_signal, target_icp
from signals.api.app import create_app
from signals.api.config import ATTRIBUTION_COOKIE_NAME, ApiConfig
from signals.api.routes_auth import SESSION_COOKIE_NAME
from signals.billing.access import feed_access
from signals.billing.catalogue import DISCOVERY_GRANT_LIMIT
from signals.billing.discovery import grants, remaining_slots
from signals.companies.schema import saas_company
from signals.conversion import qa_token
from signals.conversion.source import AttributionSourceResolver
from signals.conversion.token import AttributionTokenKeyring
from signals.engagement.schema import product_event
from signals.ingestion.backfill import (
    _landing_families,
    materialize_landing_opportunity_in_transaction,
)
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_conversion_journey,
    contract_award,
    for_you_sentence,
    materialized_signal,
    opportunity_representation,
    prospect_target,
    source_event,
    supplier_directory,
)
from signals.prospection_actions.attribution import AttributionProspectLinkIssuer
from signals.prospection_actions.preparation import ProspectPreparationService

CLICKED_AT = NOW + dt.timedelta(hours=1)
TOKEN_SECRET = b"synthetic-attribution-secret"


def client_for(engine, service, *, now: dt.datetime, welcome_delivery=None) -> TestClient:
    return TestClient(
        create_app(
            engine,
            ApiConfig(
                cookie_secure=True,
                attribution_hmac_key=TOKEN_SECRET,
                attribution_hmac_key_version="attribution-test-v1",
            ),
            now_override=lambda: now,
            conversion_attribution_service=service,
            welcome_delivery=welcome_delivery,
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


def family_bait_token(engine, service, token):
    """Turn the shared fixture into the assisted charpentry signal contract."""
    with engine.begin() as connection:
        connection.execute(
            sa.update(acquisition_campaign).values(
                selected_need_category="timber_carpentry",
                selected_need_version="supplier-families-v1",
            )
        )
        bait_awards = sa.select(opportunity_representation.c.award_key).where(
            opportunity_representation.c.opportunity_key == token.payload.opportunity_key
        )
        connection.execute(
            sa.update(contract_award).values(
                award_date=CLICKED_AT.date() - dt.timedelta(days=90),
                contract_notification_date=None,
            )
        )
        connection.execute(
            sa.update(contract_award).where(contract_award.c.award_key.in_(bait_awards)).values(
                title="26A0076 LOT 01 CHARPENTE / ISOLATION / COUVERTURE / ZINGUERIE",
                description=None,
                cpv_main="45261920",
                award_date=None,
                contract_notification_date=CLICKED_AT.date() - dt.timedelta(days=1),
                place_of_performance={
                    "country": "FR",
                    "subdivision_code": "FR-38",
                    "subdivision_scheme": "ISO-3166-2",
                    "locality": None,
                    "postal_code": "38000",
                },
            )
        )
    with engine.connect() as connection:
        payload = AttributionSourceResolver(engine).for_member(
            connection, token.payload.member_ref
        )
    return service.keyring.issue(payload)


def facade_bait_token(engine, service, token):
    """Turn the shared fixture into the Bardage métallique landing contract."""
    with engine.begin() as connection:
        connection.execute(
            sa.update(acquisition_campaign).values(
                selected_need_category="facade_cladding",
                selected_need_version="supplier-families-v1",
            )
        )
        bait_awards = sa.select(opportunity_representation.c.award_key).where(
            opportunity_representation.c.opportunity_key == token.payload.opportunity_key
        )
        connection.execute(
            sa.update(contract_award).values(
                award_date=CLICKED_AT.date() - dt.timedelta(days=90),
                contract_notification_date=None,
            )
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key.in_(bait_awards))
            .values(
                title="Bardage métallique du bâtiment communal",
                description=None,
                cpv_main="45262650",
                award_date=None,
                contract_notification_date=CLICKED_AT.date() - dt.timedelta(days=1),
                place_of_performance={
                    "country": "FR",
                    "subdivision_code": "FR-41",
                    "subdivision_scheme": "ISO-3166-2",
                    "locality": None,
                    "postal_code": "41000",
                },
            )
        )
    with engine.connect() as connection:
        payload = AttributionSourceResolver(engine).for_member(
            connection, token.payload.member_ref
        )
    return service.keyring.issue(payload)


def seed_landing_neighbours(
    engine, neighbours: tuple[tuple[str, str, str, int], ...]
) -> None:
    """Persist candidate procedures beside the shared landing bait."""

    with engine.begin() as connection:
        source = dict(connection.execute(sa.select(source_event)).mappings().one())
        award = dict(connection.execute(sa.select(contract_award)).mappings().one())
        for suffix, title, cpv, age in neighbours:
            event_key = f"manual:landing-neighbour-{suffix}:"
            event = {
                **source,
                "event_key": event_key,
                "source_system": "manual",
                "source_notice_id": f"landing-neighbour-{suffix}",
                "source_procedure_id": f"landing-procedure-{suffix}",
                "published_at_raw": CLICKED_AT.date().isoformat(),
                "published_on": CLICKED_AT.date(),
            }
            connection.execute(sa.insert(source_event).values(**event))
            award_key = f"landing-award-{suffix}"
            candidate = {
                **award,
                "award_key": award_key,
                "event_key": event_key,
                "title": title,
                "cpv_main": cpv,
                "award_date": CLICKED_AT.date() - dt.timedelta(days=age),
                "awardee_parties": [
                    {
                        "name": f"Titulaire {suffix}",
                        "members": [
                            {
                                "organization": {
                                    "legal_name": f"Titulaire {suffix}",
                                    "identifiers": [],
                                    "country": "FR",
                                    "address": None,
                                    "website": None,
                                },
                                "role": "sole",
                            }
                        ],
                    }
                ],
            }
            connection.execute(sa.insert(contract_award).values(**candidate))
            connection.execute(
                sa.insert(opportunity_representation).values(
                    award_key=award_key,
                    opportunity_key=f"landing-opportunity-{suffix}",
                    created_at=CLICKED_AT,
                )
            )


def test_landing_family_falls_back_to_public_cpv_when_trade_domain_is_missing() -> None:
    families = _landing_families(
        {
            "award": SimpleNamespace(
                title="Travaux de rénovation",
                description=None,
                cpv_main=SimpleNamespace(code="45262650"),
                cpv_additional=(),
            ),
            "understanding": SimpleNamespace(trade_domain=None),
        }
    )

    assert "facade_cladding" in {family.key for family in families}


def test_landing_opens_the_promised_signal_with_a_provisional_profile(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, token.raw_token)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/app/signals/")
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
    # Le profil est techniquement exploitable pour tenir la promesse, mais reste
    # explicitement provisoire jusqu'à la confirmation client.
    assert [icp.status for icp in icps] == ["active"]
    assert icps[0].customer_input.territories == ("FR",)
    assert icps[0].customer_input.sector_cpv_prefixes
    assert icps[0].customer_input.minimum_contract_value.minimum_amount == 0
    assert promise["opportunity_key"] == token.payload.opportunity_key
    assert promise["signal_key"] is not None
    assert response.headers["location"] == f'/app/signals/{promise["signal_key"]}'
    assert len(journeys) == 1
    assert journeys[0]["account_id"] == account_id
    assert [event["event_type"] for event in events] == ["attribution_landed"]
    assert events[0]["properties"] == {
        "has_signal": True,
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
    assert me.json()["provisional_profile"] is True
    feed = client.get("/signals?freshness=all")
    assert feed.status_code == 200
    assert feed.json()["provisional_profile"] is True
    assert [item["signal_id"] for item in feed.json()["items"]]
    assert feed.json()["landing_cohort"] == {
        "signal_id": response.headers["location"].removeprefix("/app/signals/"),
        "expected": 3,
        "materialized": 1,
    }


def test_kqa1_and_kat1_share_the_provisional_product_landing(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    payload = qa_token.QaTokenPayload(
        opportunity_key=token.payload.opportunity_key,
        wedge=token.payload.wedge,
        country=token.payload.country,
        sector="travaux de construction",
        need=token.payload.need_ref,
        issued_at=NOW,
        expires_at=NOW + dt.timedelta(days=7),
    )
    raw = qa_token.issue(
        payload,
        keyring=AttributionTokenKeyring(
            current_key_version="attribution-test-v1",
            keys={"attribution-test-v1": TOKEN_SECRET},
        ),
    )
    assert qa_token.issue_url(
        payload,
        keyring=AttributionTokenKeyring(
            current_key_version="v1",
            keys={"v1": TOKEN_SECRET},
        ),
    ).startswith("https://kivou.eu/a/kqa1.v1.")
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, raw)
    pin_session_cookie(client, response)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/app/signals/")
    me = client.get("/me").json()
    assert me["onboarding_status"] == "icp_incomplete"
    assert me["provisional_profile"] is True
    body = client.get("/signals?freshness=all").json()
    assert body["provisional_profile"] is True
    assert len(body["items"]) >= 1
    with engine.connect() as connection:
        landing = connection.execute(sa.select(account_landing_signal)).mappings().one()
        assert landing["qa"] is True
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_conversion_journey)
        ) == 0


def test_public_discovery_preview_opens_a_three_signal_facade_cohort(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    facade_bait_token(engine, service, token)
    seed_landing_neighbours(
        engine,
        (
            ("facade-one", "Bardage, Façade — patinoire communautaire", "45443000", 2),
            ("facade-two", "Habillage métallique de façade", "45262650", 3),
        ),
    )
    client = client_for(engine, service, now=CLICKED_AT)

    response = client.post(
        "/auth/discovery-preview",
        headers={"Origin": "https://testserver"},
        json={"zone": "FR-41", "sector": "facade_cladding"},
    )
    pin_session_cookie(client, response)

    assert response.status_code == 201, response.text
    assert response.json()["signal_id"]
    assert response.json()["landing_cohort"] == {"expected": 3, "materialized": 3}
    assert client.get("/me").json()["temporary_access"] is True
    feed = client.get("/signals", params={"freshness": "all"}).json()
    assert feed["landing_cohort"]["materialized"] == 3
    assert len([item for item in feed["items"] if not item["locked"]]) == 3


def test_claimed_discovery_activation_backfills_a_landing_cohort_immediately(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    facade_bait_token(engine, service, token)
    seed_landing_neighbours(
        engine,
        (
            ("facade-one", "Bardage, Façade — patinoire communautaire", "45443000", 2),
            ("facade-two", "Habillage métallique de façade", "45262650", 3),
        ),
    )
    client = client_for(engine, service, now=CLICKED_AT)
    signup = client.post(
        "/auth/signup",
        headers={"Origin": "https://testserver"},
        json={
            "email": "artisan-facade@example.fr",
            "password": "password-long-enough",
            "company_name": "Artisan façade",
            "locale": "fr",
        },
    )
    assert signup.status_code == 201, signup.text
    pin_session_cookie(client, signup)
    assert client.get("/me").status_code == 200, (
        signup.headers.get_list("set-cookie"),
        client.cookies,
    )

    created = client.post(
        "/target-icps",
        headers={"Origin": "https://testserver"},
        json={
            "label": "Bardage métallique",
            "customer_input": {
                "offer_summary": "Bardage métallique",
                "offers": ["specialist_subcontracting"],
                "territories": ["FR"],
                "territory_subdivisions": ["FR-41"],
                "sector_cpv_prefixes": ["45"],
                "minimum_contract_value": {
                    "currency": "EUR",
                    "minimum_amount": 0,
                    "maximum_amount": None,
                },
            },
        },
    )

    assert created.status_code == 201
    feed = client.get("/signals", params={"freshness": "all"}).json()
    assert len([item for item in feed["items"] if not item["locked"]]) == 3
    with engine.connect() as connection:
        assert len(grants(connection, account_id=only_account_id(engine))) == 2


def test_qa_prospect_claims_with_a_real_email_and_keeps_the_landing_cohort(tmp_path) -> None:
    engine, attribution, token, _ = prepared(tmp_path)
    token = family_bait_token(engine, attribution, token)
    seed_landing_neighbours(
        engine,
        (
            ("timber-one", "Réfection de la charpente bois", "45261100", 1),
            ("timber-two", "Construction d'une ossature bois", "45261100", 2),
        ),
    )
    qa_raw = qa_token.issue(
        qa_token.QaTokenPayload(
            opportunity_key=token.payload.opportunity_key,
            wedge=token.payload.wedge,
            country="FR",
            sector="Bois et charpente",
            need="timber_carpentry",
            issued_at=NOW,
            expires_at=NOW + dt.timedelta(days=7),
        ),
        keyring=AttributionTokenKeyring(
            current_key_version="attribution-test-v1",
            keys={"attribution-test-v1": TOKEN_SECRET},
        ),
    )
    client = client_for(engine, attribution, now=CLICKED_AT)
    landed = land(client, qa_raw)
    pin_session_cookie(client, landed)

    before_me = client.get("/me").json()
    before_feed = client.get("/signals", params={"view": "history", "limit": 20}).json()
    before_ids = [item["signal_id"] for item in before_feed["items"] if not item["locked"]]
    assert before_me["claim_email"] is None
    assert before_me["temporary_access"] is True
    assert len(before_ids) == 3

    claimed = client.post(
        "/auth/claim-access",
        headers={"Origin": "https://testserver"},
        json={"email": "claire@acme.test", "password": "une-phrase-secrete"},
    )

    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["temporary_access"] is False
    assert claimed.json()["email"] == "claire@acme.test"
    assert claimed.json()["claim_email"] is None
    after_feed = client.get("/signals", params={"view": "history", "limit": 20}).json()
    assert [item["signal_id"] for item in after_feed["items"] if not item["locked"]] == before_ids
    assert after_feed["landing_cohort"] == before_feed["landing_cohort"]


@pytest.mark.parametrize(
    ("email", "expected_status", "expected_code"),
    [
        ("landing+other@landing.kivou.invalid", 422, "invalid_claim_email"),
        ("already@acme.test", 409, "email_already_used"),
    ],
)
def test_qa_claim_rejects_a_temporary_or_already_used_email(
    tmp_path, email: str, expected_status: int, expected_code: str
) -> None:
    engine, attribution, token, _ = prepared(tmp_path)
    if email == "already@acme.test":
        with engine.begin() as connection:
            accounts.sign_up(
                connection,
                email=email,
                password="une-autre-phrase-secrete",
                company_name="Compte existant",
                locale="fr",
                now=CLICKED_AT,
                session_ttl=dt.timedelta(days=1),
            )
    client = client_for(engine, attribution, now=CLICKED_AT)
    landed = land(client, token.raw_token)
    pin_session_cookie(client, landed)

    claimed = client.post(
        "/auth/claim-access",
        headers={"Origin": "https://testserver"},
        json={"email": email, "password": "une-phrase-secrete"},
    )

    assert claimed.status_code == expected_status
    assert claimed.json()["detail"]["code"] == expected_code
    assert client.get("/me").json()["temporary_access"] is True


def test_kqa1_and_kat1_prefill_the_same_family_profile(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    family_token = family_bait_token(engine, service, token)
    qa_payload = qa_token.QaTokenPayload(
        opportunity_key=family_token.payload.opportunity_key,
        wedge=family_token.payload.wedge,
        country="FR",
        sector="Bois et charpente",
        need="timber_carpentry",
        issued_at=NOW,
        expires_at=NOW + dt.timedelta(days=7),
    )
    qa_raw = qa_token.issue(
        qa_payload,
        keyring=AttributionTokenKeyring(
            current_key_version="attribution-test-v1",
            keys={"attribution-test-v1": TOKEN_SECRET},
        ),
    )

    for raw_token, query in ((family_token.raw_token, "?qa=true"), (qa_raw, "")):
        client = client_for(engine, service, now=CLICKED_AT)
        response = client.get(f"/a/{raw_token}{query}", follow_redirects=False)
        pin_session_cookie(client, response)

        assert response.status_code == 303
        profile = client.get("/target-icps").json()[0]
        assert profile["provisional"] is True
        assert profile["label"] == "Bois et charpente"
        assert profile["customer_input"]["territory_subdivisions"] == ["FR-38"]
        assert profile["customer_input"]["sector_cpv_prefixes"] == ["452611"]
        assert profile["customer_input"]["offer_summary"] == "Bois et charpente"


def test_kqa1_prefills_the_sector_wording_carried_by_the_token(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    family_token = family_bait_token(engine, service, token)
    qa_raw = qa_token.issue(
        qa_token.QaTokenPayload(
            opportunity_key=family_token.payload.opportunity_key,
            wedge=family_token.payload.wedge,
            country="FR",
            sector="Bardage métallique",
            need="timber_carpentry",
            issued_at=NOW,
            expires_at=NOW + dt.timedelta(days=7),
        ),
        keyring=AttributionTokenKeyring(
            current_key_version="attribution-test-v1",
            keys={"attribution-test-v1": TOKEN_SECRET},
        ),
    )
    client = client_for(engine, service, now=CLICKED_AT)

    response = client.get(f"/a/{qa_raw}", follow_redirects=False)
    pin_session_cookie(client, response)
    profile = client.get("/target-icps").json()[0]

    assert profile["label"] == "Bardage métallique"
    assert profile["customer_input"]["offer_summary"] == "Bardage métallique"
    assert profile["customer_input"]["sector_cpv_prefixes"] == ["452611"]
    assert client.get("/dashboard").json()["profile"]["sector_label"] == "Bardage métallique"


def test_kqa1_normalizes_a_boamp_nuts_department_before_prefilling_profile(
    tmp_path,
) -> None:
    engine, service, token, _ = prepared(tmp_path)
    family_token = family_bait_token(engine, service, token)
    with engine.begin() as connection:
        bait_awards = sa.select(opportunity_representation.c.award_key).where(
            opportunity_representation.c.opportunity_key
            == family_token.payload.opportunity_key
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key.in_(bait_awards))
            .values(
                place_of_performance={
                    "country": "FR",
                    "subdivision_code": "FRK24",
                    "subdivision_scheme": "NUTS",
                    "locality": "Grenoble",
                    "postal_code": "38000",
                }
            )
        )
    qa_raw = qa_token.issue(
        qa_token.QaTokenPayload(
            opportunity_key=family_token.payload.opportunity_key,
            wedge=family_token.payload.wedge,
            country="FR",
            sector="Bois et charpente",
            need="timber_carpentry",
            issued_at=NOW,
            expires_at=NOW + dt.timedelta(days=7),
        ),
        keyring=AttributionTokenKeyring(
            current_key_version="attribution-test-v1",
            keys={"attribution-test-v1": TOKEN_SECRET},
        ),
    )
    client = client_for(engine, service, now=CLICKED_AT)

    response = client.get(f"/a/{qa_raw}", follow_redirects=False)
    pin_session_cookie(client, response)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/app/signals/")
    profile = client.get("/target-icps").json()[0]
    assert profile["customer_input"]["territory_subdivisions"] == ["FR-38"]


def test_kat1_qa_uses_the_same_landing_without_recording_a_campaign_click(
    tmp_path,
) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=CLICKED_AT)

    response = client.get(
        f"/a/{token.raw_token}?qa=true",
        follow_redirects=False,
    )
    pin_session_cookie(client, response)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/app/signals/")
    assert client.get("/me").json()["provisional_profile"] is True
    assert client.get("/signals?freshness=all").json()["items"]
    with engine.connect() as connection:
        landing = connection.execute(sa.select(account_landing_signal)).mappings().one()
        assert landing["qa"] is True
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_conversion_journey)
        ) == 0


def test_assisted_landing_freezes_the_exact_mail_relevance_sentence(tmp_path) -> None:
    engine, service, token, opportunity_id = prepared(tmp_path)
    seed_directory(engine, 5)
    keyring = AttributionTokenKeyring(
        current_key_version="attribution-test-v1",
        keys={"attribution-test-v1": TOKEN_SECRET},
    )
    preparation = ProspectPreparationService(
        engine,
        link_issuer=AttributionProspectLinkIssuer(
            public_site_url="https://kivou.eu",
            keyring=keyring,
        ),
        clock=lambda: NOW,
    )
    result = preparation.prepare(
        assisted_signal(
            opportunity_key=token.payload.opportunity_key,
            acquisition_opportunity_id=opportunity_id,
            procedure_key="assisted-mail-parity",
            holder="CONSTRUCTION DE MAISONS ET CHARPENTES DU DAUPHINE - CMCD",
            decision_date=NOW.date(),
            families=(("ready_mix_concrete", "Béton prêt à l'emploi"),),
        ),
        cycle_ref="assisted-mail-parity",
    )
    assert result.prepared == 1
    with engine.connect() as connection:
        target = connection.execute(sa.select(prospect_target)).mappings().one()
    expected = (
        "Sur ce type de lot, le titulaire sous-traite souvent le béton prêt à "
        "l'emploi, et vous êtes fournisseur de béton prêt à l'emploi à Moulins."
    )
    assert expected in target["mail_text"]
    raw_token = urlsplit(target["attribution_url"]).path.removeprefix("/a/")
    client = client_for(engine, service, now=CLICKED_AT)

    response = client.get(f"/a/{raw_token}?qa=true", follow_redirects=False)
    pin_session_cookie(client, response)

    assert response.status_code == 303
    signal_key = response.headers["location"].removeprefix("/app/signals/")
    with engine.connect() as connection:
        stored = connection.scalar(
            sa.select(for_you_sentence.c.sentence).where(
                for_you_sentence.c.signal_key == signal_key
            )
        )
    assert stored == expected
    drawer = client.get(f"/signals/{signal_key}")
    assert drawer.status_code == 200
    assert drawer.json()["commercial_context"]["reason"] == expected

    # A later ingestion revision creates a new ordinary `for_you_sentence`.
    # The mail promise must survive independently from that mutable revision.
    with engine.begin() as connection:
        account_id = only_account_id(engine)
        profile_id = accounts.list_target_icps(
            connection, account_id=account_id
        )[0].target_icp_id
        bait_awards = sa.select(opportunity_representation.c.award_key).where(
            opportunity_representation.c.opportunity_key == token.payload.opportunity_key
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key.in_(bait_awards))
            .values(description="Version publique enrichie après l'envoi du mail")
        )
        rematerialized_key = materialize_landing_opportunity_in_transaction(
            connection,
            target_icp_id=profile_id,
            opportunity_key=token.payload.opportunity_key,
            as_of=CLICKED_AT.date(),
            materialized_at=CLICKED_AT + dt.timedelta(minutes=5),
        )
        current_fingerprint = connection.scalar(
            sa.select(materialized_signal.c.content_fingerprint).where(
                materialized_signal.c.signal_key == signal_key
            )
        )
        current_sentence = connection.scalar(
            sa.select(for_you_sentence.c.sentence).where(
                for_you_sentence.c.signal_key == signal_key,
                for_you_sentence.c.signal_fingerprint == current_fingerprint,
            )
        )
    assert rematerialized_key == signal_key
    assert current_sentence != expected
    assert client.get(f"/signals/{signal_key}").json()["commercial_context"]["reason"] == expected


def test_assisted_prospect_can_create_a_durable_access_and_receives_one_welcome(
    tmp_path,
) -> None:
    engine, attribution, token, opportunity_id = prepared(tmp_path)
    seed_directory(engine, 5)
    preparation = ProspectPreparationService(
        engine,
        link_issuer=AttributionProspectLinkIssuer(
            public_site_url="https://kivou.eu",
            keyring=AttributionTokenKeyring(
                current_key_version="attribution-test-v1",
                keys={"attribution-test-v1": TOKEN_SECRET},
            ),
        ),
        clock=lambda: NOW,
    )
    assert preparation.prepare(
        assisted_signal(
            opportunity_key=token.payload.opportunity_key,
            acquisition_opportunity_id=opportunity_id,
            procedure_key="claim-access",
            holder="CONSTRUCTION DE MAISONS ET CHARPENTES DU DAUPHINE - CMCD",
            decision_date=NOW.date(),
            families=(("ready_mix_concrete", "Béton prêt à l'emploi"),),
        ),
        cycle_ref="claim-access",
    ).prepared == 1
    with engine.connect() as connection:
        target = connection.execute(sa.select(prospect_target)).mappings().one()

    class WelcomeSpy:
        def __init__(self) -> None:
            self.deliveries: list[dict[str, object]] = []

        def deliver(self, **values) -> None:
            self.deliveries.append(values)

    welcome = WelcomeSpy()
    raw_token = urlsplit(target["attribution_url"]).path.removeprefix("/a/")
    client = client_for(
        engine,
        attribution,
        now=CLICKED_AT,
        welcome_delivery=welcome,
    )
    landed = client.get(f"/a/{raw_token}?qa=true", follow_redirects=False)
    pin_session_cookie(client, landed)

    before = client.get("/me").json()
    assert before["temporary_access"] is True
    assert before["claim_email"] == target["email_address"]

    claimed = client.post(
        "/auth/claim-access",
        headers={"Origin": "https://testserver"},
        json={"password": "une-phrase-secrete"},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["temporary_access"] is False
    assert claimed.json()["claim_email"] is None
    assert claimed.json()["email"] == target["email_address"]
    assert claimed.json()["account_display_name"] == target["company_name"]
    assert welcome.deliveries == [
        {
            "email": target["email_address"],
            "locale": "fr",
            "signal_key": landed.headers["location"].removeprefix("/app/signals/"),
            "signal_holder": target["signal_holder"],
            "signal_subject": target["signal_subject"],
            "signal_location": target["signal_location"],
            "unsubscribe_url": target["unsubscribe_url"],
        }
    ]

    replay = client.post(
        "/auth/claim-access",
        headers={"Origin": "https://testserver"},
        json={"password": "une-autre-phrase-secrete"},
    )
    assert replay.status_code == 200
    assert len(welcome.deliveries) == 1

    other = client_for(engine, attribution, now=CLICKED_AT)
    login = other.post(
        "/auth/login",
        headers={"Origin": "https://testserver"},
        json={"email": target["email_address"], "password": "une-phrase-secrete"},
    )
    assert login.status_code == 200


def test_kat1_replay_repairs_a_legacy_generic_provisional_profile(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    token = family_bait_token(engine, service, token)
    first = client_for(engine, service, now=CLICKED_AT)
    response = first.get(f"/a/{token.raw_token}?qa=true", follow_redirects=False)
    pin_session_cookie(first, response)
    account_id = first.get("/me").json()["account_id"]
    with engine.begin() as connection:
        profile = accounts.list_target_icps(connection, account_id=account_id)[0]
        legacy_input = profile.customer_input.model_copy(
            update={
                "offer_summary": "legacy-sector-fingerprint",
                "sector_cpv_prefixes": ("45",),
            }
        )
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == profile.target_icp_id)
            .values(
                label="Travaux de construction",
                customer_input=legacy_input.model_dump(mode="json"),
            )
        )

    replay = client_for(engine, service, now=CLICKED_AT + dt.timedelta(hours=1))
    response = replay.get(f"/a/{token.raw_token}?qa=true", follow_redirects=False)
    pin_session_cookie(replay, response)
    repaired = replay.get("/target-icps").json()[0]

    assert repaired["label"] == "Bois et charpente"
    assert repaired["customer_input"]["offer_summary"] == "Bois et charpente"
    assert repaired["customer_input"]["sector_cpv_prefixes"] == ["452611"]


def test_bardage_landing_lists_only_relevant_trade_signals(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    token = facade_bait_token(engine, service, token)
    seed_landing_neighbours(
        engine,
        (
            ("facade", "Bardage, Façade — patinoire communautaire", "45443000", 1),
            ("zinc", "Couverture métallique et zinguerie", "45261210", 2),
            ("cladding", "Habillage métallique de façade", "45262650", 3),
            ("terrace", "Étanchéité de terrasse", "45261920", 4),
            ("green", "Aménagement des espaces verts du Tzen", "45112710", 5),
            ("joinery", "Menuiseries bois et vestiaires", "45421000", 6),
            ("timber", "Charpente bois isolée", "45261100", 7),
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            sa.update(source_event)
            .where(
                source_event.c.event_key.in_(
                    (
                        "manual:landing-neighbour-facade:",
                        "manual:landing-neighbour-joinery:",
                    )
                )
            )
            .values(source_procedure_id="landing-procedure-multilot-patinoire")
        )
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, token.raw_token)
    pin_session_cookie(client, response)
    body = client.get("/signals", params={"view": "history", "limit": 20}).json()

    assert len(body["items"]) == 3
    assert body["profile_total_30d"] == 3
    assert body["landing_cohort"] == {
        "signal_id": response.headers["location"].removeprefix("/app/signals/"),
        "expected": 3,
        "materialized": 3,
    }
    assert response.headers["location"].removeprefix("/app/signals/") in {
        item["signal_id"] for item in body["items"]
    }
    assert sum(item["locked"] is False for item in body["items"]) == 3
    assert all(item["locked"] is False for item in body["items"])
    bait_detail = client.get(response.headers["location"].removeprefix("/app")).json()
    assert bait_detail["landing_history_offer"] is True
    assert client.get("/billing/status").json()["discovery"] == {
        "granted_signal_count": 3,
        "remaining_slots": 0,
        "limit": 3,
    }
    account_id = only_account_id(engine)
    with engine.connect() as connection:
        persisted_neighbours = grants(connection, account_id=account_id)
        profile_id = accounts.list_target_icps(
            connection, account_id=account_id
        )[0].target_icp_id
        active_titles = set(
            connection.execute(
                sa.select(contract_award.c.title)
                .select_from(
                    materialized_signal.join(
                        contract_award,
                        materialized_signal.c.materialization_award_key
                        == contract_award.c.award_key,
                    )
                )
                .where(
                    materialized_signal.c.target_icp_id == profile_id,
                    materialized_signal.c.invalidated_at.is_(None),
                )
            ).scalars()
        )
    assert len(persisted_neighbours) == 2
    assert active_titles == {
        "Bardage métallique du bâtiment communal",
        "Bardage, Façade — patinoire communautaire",
        "Habillage métallique de façade",
    }


def test_landing_multilot_uses_the_lot_and_fine_cpv_not_the_notice_title(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    token = facade_bait_token(engine, service, token)
    seed_landing_neighbours(
        engine,
        (
            (
                "multilot-vestiaires",
                "Patinoire : CHARPENTE BARDAGE COUVERTURE, vestiaires et espaces verts",
                "45421000",
                1,
            ),
            (
                "multilot-bardage",
                "Patinoire : CHARPENTE BARDAGE COUVERTURE, vestiaires et espaces verts",
                "45443000",
                2,
            ),
            (
                "multilot-green",
                "Patinoire : CHARPENTE BARDAGE COUVERTURE, vestiaires et espaces verts",
                "45112710",
                3,
            ),
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            sa.update(source_event)
            .where(source_event.c.event_key.like("manual:landing-neighbour-multilot-%"))
            .values(source_procedure_id="landing-procedure-strict-multilot")
        )
        for suffix, lot_title in (
            ("multilot-vestiaires", "Menuiseries intérieures et vestiaires"),
            ("multilot-bardage", "Bardage, Façade"),
            ("multilot-green", "Aménagement des espaces verts"),
        ):
            connection.execute(
                sa.update(contract_award)
                .where(contract_award.c.award_key == f"landing-award-{suffix}")
                .values(lot_identifier=suffix, lot_title=lot_title)
            )
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, token.raw_token)
    pin_session_cookie(client, response)
    body = client.get("/signals", params={"view": "history", "limit": 20}).json()

    assert {item["headline"] for item in body["items"] if item["locked"]} == set()
    assert {
        item["contract"]["lot_title"] or item["contract"]["title"]
        for item in body["items"]
        if not item["locked"]
    } == {"Bardage métallique du bâtiment communal", "Bardage, Façade"}


def test_landing_locked_stock_prefers_old_local_then_recent_adjacent(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    token = facade_bait_token(engine, service, token)
    seed_landing_neighbours(
        engine,
        (
            ("local-open-one", "Bardage du gymnase", "45262650", 2),
            ("local-open-two", "Façade du groupe scolaire", "45262650", 3),
            ("local-old", "Habillage métallique de la mairie", "45262650", 45),
            ("adjacent", "Bardage du centre technique", "45262650", 4),
            ("national", "Façade métallique de la médiathèque", "45262650", 5),
        ),
    )
    with engine.begin() as connection:
        for suffix, subdivision in (("adjacent", "FR-37"), ("national", "FR-29")):
            connection.execute(
                sa.update(contract_award)
                .where(contract_award.c.award_key == f"landing-award-{suffix}")
                .values(
                    place_of_performance={
                        "country": "FR",
                        "subdivision_code": subdivision,
                        "subdivision_scheme": "ISO-3166-2",
                        "locality": None,
                        "postal_code": None,
                    }
                )
            )
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, token.raw_token)
    pin_session_cookie(client, response)
    body = client.get("/signals", params={"view": "history", "limit": 20}).json()

    assert sum(not item["locked"] for item in body["items"]) == 3
    locked = [item for item in body["items"] if item["locked"]]
    assert {item["headline"] for item in locked} == {
        "Habillage métallique de la mairie",
        "Bardage du centre technique",
    }
    older = next(item for item in locked if item["headline"].startswith("Habillage"))
    adjacent = next(item for item in locked if item["headline"].startswith("Bardage"))
    assert older["teaser"]["date"] == (
        CLICKED_AT.date() - dt.timedelta(days=45)
    ).isoformat()
    assert older["teaser"]["department"] == "Loir-et-Cher"
    assert adjacent["teaser"]["department"] == "Indre-et-Loire"
    assert body["profile_total_30d"] == 4


def test_landing_locked_stock_uses_recent_national_only_as_last_resort(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    token = facade_bait_token(engine, service, token)
    seed_landing_neighbours(
        engine,
        (
            ("local-open-one", "Bardage du gymnase", "45262650", 2),
            ("local-open-two", "Façade du groupe scolaire", "45262650", 3),
            ("local-old", "Habillage métallique de la mairie", "45262650", 45),
            ("national", "Façade métallique de la médiathèque", "45262650", 5),
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == "landing-award-national")
            .values(
                place_of_performance={
                    "country": "FR",
                    "subdivision_code": "FR-29",
                    "subdivision_scheme": "ISO-3166-2",
                    "locality": None,
                    "postal_code": None,
                }
            )
        )
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, token.raw_token)
    pin_session_cookie(client, response)
    body = client.get("/signals", params={"view": "history", "limit": 20}).json()

    assert {item["headline"] for item in body["items"] if item["locked"]} == {
        "Habillage métallique de la mairie",
        "Façade métallique de la médiathèque",
    }
    assert body["profile_total_30d"] == 4


def test_only_the_bait_opens_the_complete_contact_demo_and_journal(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    token = family_bait_token(engine, service, token)
    seed_landing_neighbours(
        engine,
        (
            ("timber-one", "Réfection de la charpente bois de l'école", "45261100", 3),
            ("timber-two", "Construction d'une ossature bois", "45261100", 4),
            ("timber-three", "Extension en structure bois", "45261100", 5),
        ),
    )
    with engine.begin() as connection:
        bait_awards = sa.select(opportunity_representation.c.award_key).where(
            opportunity_representation.c.opportunity_key == token.payload.opportunity_key
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key.in_(bait_awards))
            .values(
                awardee_parties=[
                    {
                        "name": "Titulaire Démonstration",
                        "members": [
                            {
                                "organization": {
                                    "legal_name": "Titulaire Démonstration",
                                    "identifiers": [
                                        {"scheme": "SIREN", "value": "562136036"}
                                    ],
                                    "country": "FR",
                                    "address": None,
                                    "website": None,
                                },
                                "role": "sole",
                            }
                        ],
                    }
                ]
            )
        )
        _insert_directory_company(
            connection,
            siren="562136036",
            name="Titulaire Démonstration",
        )
        connection.execute(
            sa.update(supplier_directory)
            .where(supplier_directory.c.siren == "562136036")
            .values(
                director_display_name="Anna Egli",
                director_source="registre",
                director_observed_at=CLICKED_AT,
                phone="04 76 00 00 00",
                phone_source="site",
                phone_observed_at=CLICKED_AT,
                professional_email="contact@egli.example",
                email_source="site",
                email_evidence_url="https://egli.example/contact",
                email_observed_at=CLICKED_AT,
            )
        )
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, token.raw_token)
    pin_session_cookie(client, response)
    bait_key = response.headers["location"].removeprefix("/app/signals/")
    # Some notices expose an unusable winner identifier even though the
    # reconciled company already carries an exact register identity.  The
    # complete demo must prefer that exact identity.
    with engine.begin() as connection:
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == bait_key)
            .values(winner_identifier_scheme="eu", winner_identifier_value="opaque-reference")
        )
        signal_identity = connection.execute(
            sa.select(
                materialized_signal.c.company_identity_fingerprint,
                materialized_signal.c.materialization_award_key,
            ).where(materialized_signal.c.signal_key == bait_key)
        ).one()
        connection.execute(
            sa.insert(saas_company).values(
                company_key="cmp_landing_demo",
                identity_fingerprint=signal_identity.company_identity_fingerprint,
                identity_method="official_identifier",
                identity_validation={},
                source_award_key=signal_identity.materialization_award_key,
                origin_signal_key=bait_key,
                official_name="Titulaire Démonstration",
                official_country="FR",
                official_address=None,
                official_identifiers=[{"scheme": "SIRET", "value": "56213603600018"}],
                official_website_url=None,
                official_source="official_register",
                official_observed_at=CLICKED_AT,
                created_at=CLICKED_AT,
                updated_at=CLICKED_AT,
            )
        )
    items = client.get("/signals", params={"view": "history", "limit": 20}).json()["items"]
    assert all(
        item["landing_example_holder"] == "Titulaire Démonstration"
        for item in items
    )
    other_key = next(item["signal_id"] for item in items if not item["locked"] and item["signal_id"] != bait_key)
    locked_key = next(item["signal_id"] for item in items if item["locked"])
    assert next(item for item in items if item["locked"])["landing_example_holder"] == (
        "Titulaire Démonstration"
    )

    other = client.get(f"/signals/{other_key}").json()
    with engine.connect() as connection:
        assert connection.scalar(sa.select(account_landing_signal.c.signal_opened_at)) is None
    assert other["landing_demo"] is False
    assert other["landing_example_holder"] == "Titulaire Démonstration"

    bait = client.get(f"/signals/{bait_key}").json()
    assert bait["landing_demo"] is True
    assert bait["landing_example_holder"] == "Titulaire Démonstration"
    assert bait["landing_directory"]["fields_locked"] is False
    assert bait["landing_directory"]["director_display_name"] == "Anna Egli"
    assert bait["landing_directory"]["phone"] == "04 76 00 00 00"
    assert bait["landing_directory"]["published_email"] == "contact@egli.example"
    with engine.connect() as connection:
        opened_at = connection.scalar(sa.select(account_landing_signal.c.signal_opened_at))
    assert opened_at is not None

    assert client.get(f"/signals/{bait_key}").status_code == 200
    with engine.connect() as connection:
        assert connection.scalar(sa.select(account_landing_signal.c.signal_opened_at)) == opened_at

    locked = client.get(f"/signals/{locked_key}").json()
    assert locked["landing_example_holder"] == "Titulaire Démonstration"


def test_landing_cohort_does_not_fill_with_a_neighbouring_family(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    token = family_bait_token(engine, service, token)
    seed_landing_neighbours(
        engine,
        (
            ("roofing-only", "Réfection complète de la couverture", "45261210", 1),
            ("timber-only", "Réfection de la charpente bois", "45261920", 2),
        ),
    )
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, token.raw_token)
    pin_session_cookie(client, response)
    body = client.get("/signals", params={"view": "history", "limit": 20}).json()

    assert len(body["items"]) == 2
    assert body["profile_total_30d"] == 2
    assert body["landing_cohort"] == {
        "signal_id": response.headers["location"].removeprefix("/app/signals/"),
        "expected": 3,
        "materialized": 2,
    }
    account_id = only_account_id(engine)
    with engine.connect() as connection:
        profile_id = accounts.list_target_icps(
            connection, account_id=account_id
        )[0].target_icp_id
        active_titles = set(
            connection.execute(
                sa.select(contract_award.c.title)
                .select_from(
                    materialized_signal.join(
                        contract_award,
                        materialized_signal.c.materialization_award_key
                        == contract_award.c.award_key,
                    )
                )
                .where(
                    materialized_signal.c.target_icp_id == profile_id,
                    materialized_signal.c.invalidated_at.is_(None),
                )
            ).scalars()
        )
    assert active_titles == {
        "26A0076 LOT 01 CHARPENTE / ISOLATION / COUVERTURE / ZINGUERIE",
        "Réfection de la charpente bois",
    }


def test_landing_cohort_expands_the_same_family_to_adjacent_departments(
    tmp_path, caplog
) -> None:
    engine, service, token, _ = prepared(tmp_path)
    token = family_bait_token(engine, service, token)
    seed_landing_neighbours(
        engine,
        (
            ("timber-ain", "Charpente bois dans l’Ain", "45261100", 1),
            ("timber-rhone", "Charpente bois dans le Rhône", "45261100", 2),
        ),
    )
    with engine.begin() as connection:
        for suffix, subdivision in (("timber-ain", "FR-01"), ("timber-rhone", "FR-69")):
            connection.execute(
                sa.update(contract_award)
                .where(contract_award.c.award_key == f"landing-award-{suffix}")
                .values(
                    place_of_performance={
                        "country": "FR",
                        "subdivision_code": subdivision,
                        "subdivision_scheme": "ISO-3166-2",
                        "locality": None,
                        "postal_code": None,
                    }
                )
            )
    client = client_for(engine, service, now=CLICKED_AT)

    caplog.set_level(logging.WARNING, logger="signals.ingestion.backfill")
    response = land(client, token.raw_token)
    pin_session_cookie(client, response)
    body = client.get("/signals", params={"view": "history", "limit": 20}).json()

    assert len(body["items"]) == 3
    assert body["landing_cohort"]["materialized"] == 3
    assert {
        record.expansion_reason
        for record in caplog.records
        if record.getMessage()
        == "landing cohort expanded: same_family_adjacent_department"
    } == {"same_family_adjacent_department"}


def test_landing_without_a_known_department_does_not_invent_neighbours(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    token = family_bait_token(engine, service, token)
    with engine.begin() as connection:
        bait_awards = sa.select(opportunity_representation.c.award_key).where(
            opportunity_representation.c.opportunity_key == token.payload.opportunity_key
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key.in_(bait_awards))
            .values(place_of_performance=None)
        )
    seed_landing_neighbours(
        engine,
        (("timber-zoned", "Réfection de la charpente bois", "45261100", 1),),
    )
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, token.raw_token)
    pin_session_cookie(client, response)
    body = client.get("/signals", params={"view": "history", "limit": 20}).json()

    assert len(body["items"]) == 1
    assert body["landing_cohort"]["materialized"] == 1


def test_a_replayed_link_returns_to_the_same_account_without_duplicating_it(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    first = client_for(engine, service, now=CLICKED_AT)
    second = client_for(engine, service, now=CLICKED_AT + dt.timedelta(days=2))

    assert land(first, token.raw_token).status_code == 303
    replayed = land(second, token.raw_token)

    assert replayed.status_code == 303
    assert replayed.headers["location"].startswith("/app/signals/")
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


def test_a_materialized_promise_counts_as_one_of_three_discovery_signals(
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
    with engine.connect() as connection:
        signal_key = connection.scalar(
            sa.select(materialized_signal.c.signal_key).where(
                materialized_signal.c.target_icp_id == target_icp_id,
                materialized_signal.c.opportunity_key == token.payload.opportunity_key,
            )
        )
    assert signal_key is not None

    second = client_for(engine, service, now=CLICKED_AT + dt.timedelta(days=1))
    response = land(second, token.raw_token)

    assert response.status_code == 303
    assert response.headers["location"] == f"/app/signals/{signal_key}"
    with engine.connect() as connection:
        promise = connection.execute(sa.select(account_landing_signal)).mappings().one()
        access = feed_access(connection, account_id=account_id, as_of=CLICKED_AT.date())
        slots = remaining_slots(connection, account_id=account_id)
    assert promise["signal_key"] == signal_key
    # Ouvert nominativement et compté dans les trois signaux visibles promis.
    assert signal_key in access.granted
    assert slots == DISCOVERY_GRANT_LIMIT - 1


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
    assert verified.payload.opportunity_key is None


def test_a_link_issued_before_the_promise_still_lands(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=CLICKED_AT)

    response = land(client, _legacy_token(token).raw_token)

    assert response.status_code == 303
    assert response.headers["location"] == "/app/signals"
    pin_session_cookie(client, response)
    assert client.get("/me").status_code == 200


def test_a_legacy_keyless_token_still_lands_and_replays_the_same_account(tmp_path) -> None:
    """Les jetons déjà émis sans clé restent en mode feed et sont rejouables."""
    engine, service, token, _ = prepared(tmp_path)
    unresolved = _legacy_token(token)

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


def test_landing_confirmation_produces_a_non_empty_dashboard_and_complete_journal(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=CLICKED_AT)
    response = land(client, token.raw_token)
    pin_session_cookie(client, response)
    signal_key = response.headers["location"].rsplit("/", 1)[1]

    detail = client.get(f"/signals/{signal_key}")
    assert detail.status_code == 200
    profile = client.get("/target-icps").json()[0]
    customer_input = {**profile["customer_input"], "offer_summary": "Travaux paysagers"}
    confirmed = client.patch(
        f'/target-icps/{profile["target_icp_id"]}',
        headers={"Origin": "https://testserver"},
        json={"label": "Paysage", "customer_input": customer_input},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "active"
    assert confirmed.json()["provisional"] is False
    assert confirmed.json()["customer_input"] == customer_input
    assert client.get("/me").json()["onboarding_status"] == "ready_for_signals"
    assert client.get("/me").json()["provisional_profile"] is False
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["top3"]

    with engine.connect() as connection:
        journal = connection.execute(sa.select(account_landing_signal)).mappings().one()
    assert journal["token_fingerprint"] == token.token_fingerprint
    assert journal["signal_opened_at"] is not None
    assert journal["confirmation_started_at"] is not None
    assert journal["profile_confirmed_at"] is not None
    assert journal["dashboard_ready_at"] is not None


@pytest.mark.parametrize("incomplete_save", [False, True], ids=["rename", "incomplete-form"])
def test_landing_requires_complete_customer_input_before_confirmation(
    tmp_path, incomplete_save: bool
) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=CLICKED_AT)
    response = land(client, token.raw_token)
    pin_session_cookie(client, response)
    profile = client.get("/target-icps").json()[0]
    payload = {"label": "Mon profil"}
    if incomplete_save:
        # The previous confirmation form erased these required matching fields.
        payload["customer_input"] = {
            **profile["customer_input"],
            "offers": [],
            "minimum_contract_value": None,
        }

    saved = client.patch(
        f'/target-icps/{profile["target_icp_id"]}',
        headers={"Origin": "https://testserver"},
        json=payload,
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == ("draft" if incomplete_save else "active")
    assert saved.json()["provisional"] is True
    me = client.get("/me").json()
    assert me["onboarding_status"] == "icp_incomplete"
    assert me["provisional_profile"] is True
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(account_landing_signal.c.profile_confirmed_at)
        ) is None

    confirmed = client.patch(
        f'/target-icps/{profile["target_icp_id"]}',
        headers={"Origin": "https://testserver"},
        json={"customer_input": profile["customer_input"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "active"
    assert confirmed.json()["provisional"] is False
    assert client.get("/me").json()["onboarding_status"] == "ready_for_signals"
    assert len(client.get("/target-icps").json()) == 1
    # A repaired profile opens the dashboard even if rematching finds no signal.
    assert client.get("/dashboard").status_code == 200


@pytest.mark.parametrize(
    "changed_filter",
    [
        {"sector_cpv_prefixes": ["72"]},
        {"territory_subdivisions": ["FR-75"]},
    ],
    ids=["sector", "department"],
)
def test_confirmation_rematches_signals_after_a_sector_or_department_change(
    tmp_path, changed_filter: dict
) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=CLICKED_AT)
    response = land(client, token.raw_token)
    pin_session_cookie(client, response)
    signal_key = response.headers["location"].rsplit("/", 1)[1]
    profile = client.get("/target-icps").json()[0]

    confirmed = client.patch(
        f'/target-icps/{profile["target_icp_id"]}',
        headers={"Origin": "https://testserver"},
        json={"customer_input": {**profile["customer_input"], **changed_filter}},
    )

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["matching_revision"] == profile["matching_revision"] + 1
    assert confirmed.json()["status"] == "active"
    assert client.get("/me").json()["onboarding_status"] == "ready_for_signals"
    assert all(item["signal_id"] != signal_key for item in client.get("/dashboard").json()["top3"])
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(materialized_signal.c.invalidated_at).where(
                materialized_signal.c.signal_key == signal_key
            )
        ) is not None


def test_confirmation_drops_a_promised_signal_that_no_longer_matches(tmp_path) -> None:
    engine, service, token, _ = prepared(tmp_path)
    client = client_for(engine, service, now=CLICKED_AT)
    response = land(client, token.raw_token)
    pin_session_cookie(client, response)
    signal_key = response.headers["location"].rsplit("/", 1)[1]
    profile = client.get("/target-icps").json()[0]
    incompatible = {**profile["customer_input"], "territories": ["CH"]}

    confirmed = client.patch(
        f'/target-icps/{profile["target_icp_id"]}',
        headers={"Origin": "https://testserver"},
        json={"label": "Suisse", "customer_input": incompatible},
    )

    assert confirmed.status_code == 200
    assert all(item["signal_id"] != signal_key for item in client.get("/dashboard").json()["top3"])
