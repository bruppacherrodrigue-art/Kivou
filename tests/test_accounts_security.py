"""SPEC-011 §16 — les invariants de sécurité, un par test.

Ce ne sont pas des tests de fonctionnalité. Chacun décrit une manière précise
dont un compte pourrait être compromis, et vérifie que le chemin est fermé.

Le temps est toujours explicite : l'application reçoit une horloge injectable,
et les tests d'expiration avancent l'heure au lieu d'attendre. Une expiration
qu'on ne peut pas tester est une expiration qu'on ne peut pas promettre.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from argon2 import PasswordHasher
from argon2.low_level import Type
from fastapi.testclient import TestClient

from signals.accounts import service as account_service
from signals.accounts.passwords import (
    MINIMUM_PASSWORD_LENGTH,
    hash_password,
    needs_rehash,
    verify_password,
)
from signals.accounts.schema import account, auth_session, auth_user, password_reset
from signals.accounts.tokens import token_hash
from signals.api import SESSION_COOKIE_NAME, ApiConfig, create_app
from signals.persistence.database import create_database_engine, migrate_to_latest

#: Origine synthétique pour la validation CSRF (CLOSEOUT §3).
ORIGIN = "https://kivou.test"
PASSWORD = "un-mot-de-passe-assez-long"
EMAIL = "fondateur@negoce-romand.ch"


class RecordingDelivery:
    """Faux adaptateur d'envoi : il garde le jeton en clair pour le test."""

    def __init__(self) -> None:
        self.delivered: list[dict[str, str]] = []

    def deliver(self, *, email: str, locale: str, reset_token: str) -> None:
        self.delivered.append({"email": email, "locale": locale, "reset_token": reset_token})

    @property
    def last_token(self) -> str:
        return self.delivered[-1]["reset_token"]


class Clock:
    """Une horloge que le test avance lui-même."""

    def __init__(self, start: dt.datetime) -> None:
        self.now = start

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, delta: dt.timedelta) -> None:
        self.now += delta


@pytest.fixture
def clock() -> Clock:
    return Clock(dt.datetime(2026, 8, 18, 9, 0, tzinfo=dt.UTC))


@pytest.fixture
def delivery() -> RecordingDelivery:
    return RecordingDelivery()


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def client(engine, clock: Clock, delivery: RecordingDelivery) -> TestClient:
    app = create_app(
        engine,
        ApiConfig(
            session_ttl=dt.timedelta(days=14),
            password_reset_ttl=dt.timedelta(hours=1),
            cookie_secure=False,
            allowed_origin=ORIGIN,
        ),
        now_override=clock,
        password_reset_delivery=delivery,
    )
    return TestClient(app, headers={"Origin": ORIGIN})


def signup(client: TestClient, *, email: str = EMAIL, company: str = "Negoce Romand SA"):
    return client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "company_name": company,
            "locale": "fr",
        },
    )


# ─── 1, 2 — mots de passe ──────────────────────────────────────────────────────


def test_a_password_is_never_stored_in_clear_text(client: TestClient, engine):
    signup(client)
    with engine.connect() as connection:
        stored = connection.execute(sa.select(auth_user.c.password_hash)).scalar_one()
    assert PASSWORD not in stored
    assert stored.startswith("$argon2id$")


def test_a_password_hash_verifies_the_right_password_and_only_it():
    digest = hash_password(PASSWORD)
    assert verify_password(digest, PASSWORD)
    assert not verify_password(digest, PASSWORD + "x")
    assert not verify_password(digest, "")


def test_a_corrupted_hash_is_a_failed_verification_not_a_crash():
    """Un échec de vérification est un résultat, pas une exception à journaliser."""
    assert not verify_password("pas-une-empreinte", PASSWORD)


def test_a_short_password_is_refused_by_the_api(client: TestClient):
    response = client.post(
        "/auth/signup",
        json={
            "email": "court@negoce-romand.ch",
            "password": "x" * (MINIMUM_PASSWORD_LENGTH - 1),
            "company_name": "Test",
            "locale": "fr",
        },
    )
    assert response.status_code == 422


# ─── 3 à 7 — sessions ──────────────────────────────────────────────────────────


def test_the_raw_session_token_is_never_stored(client: TestClient, engine):
    response = signup(client)
    raw = response.cookies[SESSION_COOKIE_NAME]
    with engine.connect() as connection:
        rows = connection.execute(sa.select(auth_session.c.token_hash)).scalars().all()
    assert raw not in rows
    assert rows == [token_hash(raw)]


def test_an_unknown_session_token_is_rejected(client: TestClient):
    client.cookies.set(SESSION_COOKIE_NAME, "jeton-inexistant")
    assert client.get("/me").status_code == 401


def test_an_expired_session_is_rejected(client: TestClient, clock: Clock):
    signup(client)
    assert client.get("/me").status_code == 200
    clock.advance(dt.timedelta(days=15))
    assert client.get("/me").status_code == 401


def test_a_revoked_session_is_rejected(client: TestClient, engine, clock: Clock):
    signup(client)
    with engine.begin() as connection:
        connection.execute(sa.update(auth_session).values(revoked_at=clock.now))
    assert client.get("/me").status_code == 401


def test_logging_out_revokes_the_session_server_side(client: TestClient, engine):
    signup(client)
    assert client.post("/auth/logout").status_code == 204
    with engine.connect() as connection:
        revoked = connection.execute(sa.select(auth_session.c.revoked_at)).scalar_one()
    assert revoked is not None
    assert client.get("/me").status_code == 401


def test_the_session_cookie_is_http_only(client: TestClient):
    header = signup(client).headers["set-cookie"].lower()
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "path=/" in header
    assert "max-age=1209600" in header


def test_the_cookie_is_marked_secure_when_configured(engine, clock: Clock):
    app = create_app(
        engine,
        ApiConfig(cookie_secure=True, allowed_origin=ORIGIN),
        now_override=clock,
    )
    with TestClient(app, headers={"Origin": ORIGIN}, base_url=ORIGIN) as secure:
        header = signup(secure).headers["set-cookie"].lower()
    assert "secure" in header


# ─── 8, 9, 10 — réinitialisation ───────────────────────────────────────────────


def request_reset(client: TestClient, email: str = EMAIL):
    return client.post("/auth/password-reset/request", json={"email": email})


def test_a_reset_token_is_stored_only_as_a_hash(
    client: TestClient, engine, delivery: RecordingDelivery
):
    signup(client)
    request_reset(client)
    with engine.connect() as connection:
        stored = connection.execute(sa.select(password_reset.c.token_hash)).scalar_one()
    assert stored == token_hash(delivery.last_token)
    assert stored != delivery.last_token


def test_a_reset_token_expires(client: TestClient, clock: Clock, delivery: RecordingDelivery):
    signup(client)
    request_reset(client)
    clock.advance(dt.timedelta(hours=2))
    response = client.post(
        "/auth/password-reset/confirm",
        json={"reset_token": delivery.last_token, "new_password": "un-nouveau-mot-de-passe"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_reset_token"


def test_a_reset_token_works_exactly_once(client: TestClient, delivery: RecordingDelivery):
    signup(client)
    request_reset(client)
    token = delivery.last_token
    first = client.post(
        "/auth/password-reset/confirm",
        json={"reset_token": token, "new_password": "un-nouveau-mot-de-passe"},
    )
    second = client.post(
        "/auth/password-reset/confirm",
        json={"reset_token": token, "new_password": "encore-un-autre-mot-de-passe"},
    )
    assert first.status_code == 200
    assert second.status_code == 400


def test_a_reset_token_can_only_be_claimed_by_one_concurrent_confirmation(
    client: TestClient,
    engine,
    clock: Clock,
    delivery: RecordingDelivery,
) -> None:
    signup(client)
    request_reset(client)
    token = delivery.last_token
    start = threading.Barrier(2)

    def confirm(password: str) -> tuple[str, str]:
        start.wait(timeout=5)
        try:
            with engine.begin() as connection:
                account_service.confirm_password_reset(
                    connection,
                    reset_token=token,
                    new_password=password,
                    now=clock.now,
                )
        except account_service.InvalidResetToken:
            return "invalid", password
        return "accepted", password

    passwords = ("premier-mot-de-passe-concurrent", "second-mot-de-passe-concurrent")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(confirm, passwords))

    assert sorted(result for result, _password in outcomes) == ["accepted", "invalid"]
    accepted_password = next(
        password for result, password in outcomes if result == "accepted"
    )
    with engine.connect() as connection:
        stored_hash = connection.execute(sa.select(auth_user.c.password_hash)).scalar_one()
    assert verify_password(stored_hash, accepted_password)


def test_a_password_reset_invalidates_every_existing_session(
    client: TestClient, delivery: RecordingDelivery
):
    """Une réinitialisation sert quand on soupçonne un accès illégitime."""
    signup(client)
    assert client.get("/me").status_code == 200
    request_reset(client)
    client.post(
        "/auth/password-reset/confirm",
        json={"reset_token": delivery.last_token, "new_password": "un-nouveau-mot-de-passe"},
    )
    assert client.get("/me").status_code == 401


def test_the_new_password_works_and_the_old_one_does_not(
    client: TestClient, delivery: RecordingDelivery
):
    signup(client)
    request_reset(client)
    client.post(
        "/auth/password-reset/confirm",
        json={"reset_token": delivery.last_token, "new_password": "un-nouveau-mot-de-passe"},
    )
    assert (
        client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 401
    )
    assert (
        client.post(
            "/auth/login", json={"email": EMAIL, "password": "un-nouveau-mot-de-passe"}
        ).status_code
        == 200
    )


def test_a_second_reset_request_invalidates_the_first_undelivered_token(
    engine, clock: Clock
) -> None:
    from urllib.parse import parse_qs, urlsplit

    from signals.accounts.reset_delivery import SmtpPasswordResetDelivery
    from signals.alerts.gateway import AlertDeliveryError, DeliveryResult

    class FailOnceGateway:
        def __init__(self) -> None:
            self.attempted = []
            self.accepted = []

        def send(self, message):
            self.attempted.append(message)
            if len(self.attempted) == 1:
                raise AlertDeliveryError("smtp_unavailable", retryable=True)
            self.accepted.append(message)
            return DeliveryResult(provider_message_id=message.message_id)

    gateway = FailOnceGateway()
    reset_delivery = SmtpPasswordResetDelivery(
        gateway,
        site_url="https://staging.kivou.test",
        ttl=dt.timedelta(hours=1),
    )
    app = create_app(
        engine,
        ApiConfig(
            password_reset_ttl=dt.timedelta(hours=1),
            cookie_secure=False,
            allowed_origin=ORIGIN,
        ),
        now_override=clock,
        password_reset_delivery=reset_delivery,
    )
    browser = TestClient(app, headers={"Origin": ORIGIN})
    signup(browser)

    assert request_reset(browser).status_code == 202
    assert request_reset(browser).status_code == 202
    assert len(gateway.attempted) == 2
    assert len(gateway.accepted) == 1
    assert gateway.attempted[0].message_id != gateway.attempted[1].message_id

    def token_at(index: int) -> str:
        link = next(
            line
            for line in gateway.attempted[index].text_body.splitlines()
            if line.startswith("https://")
        )
        return parse_qs(urlsplit(link).query)["token"][0]

    first_token = token_at(0)
    second_token = token_at(1)
    first = browser.post(
        "/auth/password-reset/confirm",
        json={"reset_token": first_token, "new_password": "premier-mot-de-passe-refuse"},
    )
    second = browser.post(
        "/auth/password-reset/confirm",
        json={"reset_token": second_token, "new_password": "second-mot-de-passe-accepte"},
    )

    assert first.status_code == 400
    assert first.json()["detail"]["code"] == "invalid_reset_token"
    assert second.status_code == 200


# ─── 11, 12 — inscription ──────────────────────────────────────────────────────


def test_a_duplicate_email_cannot_create_a_second_account(client: TestClient, engine):
    assert signup(client).status_code == 201
    duplicate = signup(client, company="Une autre société")
    assert duplicate.status_code == 409
    with engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(account)).scalar() == 1


def test_a_duplicate_email_leaves_no_orphan_account(client: TestClient, engine):
    """§9 — un échec à mi-chemin ne laisse ni compte partiel ni utilisateur partiel."""
    signup(client)
    signup(client, company="Une autre société")
    with engine.connect() as connection:
        accounts = connection.execute(sa.select(sa.func.count()).select_from(account)).scalar()
        users = connection.execute(sa.select(sa.func.count()).select_from(auth_user)).scalar()
    assert accounts == users == 1


def test_a_failed_signup_rolls_back_the_account_creation(engine, clock: Clock):
    """Un mot de passe refusé APRÈS la création du compte ne doit rien laisser."""
    from signals.accounts.service import sign_up

    with (
        pytest.raises(Exception),  # noqa: B017 — la nature de l'erreur importe peu ici
        engine.begin() as connection,
    ):
        sign_up(
            connection,
            email=EMAIL,
            password="trop-court",
            company_name="Negoce",
            locale="fr",
            now=clock.now,
            session_ttl=dt.timedelta(days=1),
        )
    with engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(account)).scalar() == 0


def test_the_email_is_normalized_so_case_cannot_duplicate_an_account(client: TestClient, engine):
    signup(client, email="Fondateur@Negoce-Romand.CH")
    assert signup(client, email="fondateur@negoce-romand.ch").status_code == 409
    with engine.connect() as connection:
        stored = connection.execute(sa.select(auth_user.c.email_normalized)).scalar_one()
    assert stored == "fondateur@negoce-romand.ch"


# ─── 13, 14 — aucune énumération de comptes ────────────────────────────────────


def test_login_gives_the_same_answer_for_unknown_email_and_wrong_password(
    client: TestClient,
):
    signup(client)
    unknown = client.post(
        "/auth/login", json={"email": "personne@negoce-romand.ch", "password": PASSWORD}
    )
    wrong = client.post("/auth/login", json={"email": EMAIL, "password": "mauvais-mot-de-passe"})

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_a_reset_request_answers_the_same_whether_the_account_exists(
    client: TestClient, delivery: RecordingDelivery
):
    signup(client)
    known = request_reset(client)
    unknown = request_reset(client, "personne@negoce-romand.ch")

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(delivery.delivered) == 1, "seul le compte réel reçoit un jeton"


def test_no_secret_ever_appears_in_a_response(client: TestClient):
    body = signup(client).text + client.get("/me").text
    for forbidden in ("password", "hash", "token", "argon2"):
        assert forbidden not in body.lower()


# ─── 18 — CSRF ─────────────────────────────────────────────────────────────────


def test_a_state_changing_request_from_a_foreign_origin_is_rejected(client: TestClient):
    signup(client)
    response = client.post(
        "/target-icps", json={"label": "Vol"}, headers={"Origin": "https://attaquant.example"}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "csrf_origin_rejected"


def test_a_state_changing_request_without_any_origin_is_rejected(engine, clock: Clock):
    """Accepter l'absence d'origine offrirait le contournement en clair."""
    app = create_app(
        engine, ApiConfig(cookie_secure=False, allowed_origin=ORIGIN), now_override=clock
    )
    bare = TestClient(app)
    assert (
        bare.post(
            "/auth/signup",
            json={"email": EMAIL, "password": PASSWORD, "company_name": "X", "locale": "fr"},
        ).status_code
        == 403
    )


def test_a_read_only_request_is_not_blocked_by_the_origin_check(client: TestClient):
    signup(client)
    client.headers.pop("Origin", None)
    assert client.get("/me").status_code == 200


def test_a_referer_from_the_allowed_origin_is_accepted(client: TestClient):
    signup(client)
    client.headers.pop("Origin", None)
    response = client.post(
        "/target-icps",
        json={"label": "Depuis referer"},
        headers={"Referer": f"{ORIGIN}/onboarding"},
    )
    assert response.status_code == 201


def test_the_login_endpoint_is_also_protected(client: TestClient):
    """Un login CSRF connecterait la victime sur le compte de l'attaquant."""
    signup(client)
    response = client.post(
        "/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"Origin": "https://attaquant.example"},
    )
    assert response.status_code == 403


# ─── closeout §4 — remise à niveau de l'empreinte à la connexion ───────────────


def stored_hash(engine, email: str = EMAIL) -> str:
    with engine.connect() as connection:
        return connection.execute(
            sa.select(auth_user.c.password_hash).where(auth_user.c.email_normalized == email)
        ).scalar_one()


def install_outdated_hash(engine, email: str = EMAIL) -> str:
    """Remplace l'empreinte par une empreinte Argon2id à paramètres anciens.

    Les paramètres sont volontairement plus faibles que les défauts courants,
    donc `check_needs_rehash` les déclare périmés de façon déterministe : le
    test ne dépend pas d'un changement futur de la bibliothèque.
    """
    outdated = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, type=Type.ID).hash(
        PASSWORD
    )
    assert needs_rehash(outdated), "les paramètres choisis doivent être périmés"
    with engine.begin() as connection:
        connection.execute(
            sa.update(auth_user)
            .where(auth_user.c.email_normalized == email)
            .values(password_hash=outdated)
        )
    return outdated


def test_an_outdated_hash_is_replaced_on_a_successful_login(client: TestClient, engine):
    signup(client)
    outdated = install_outdated_hash(engine)
    client.post("/auth/logout")

    response = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 200, "la connexion réussit avec l'ancienne empreinte"
    replaced = stored_hash(engine)
    assert replaced != outdated
    assert not needs_rehash(replaced), "l'empreinte réécrite est aux paramètres courants"
    assert verify_password(replaced, PASSWORD), "le mot de passe fonctionne toujours"


def test_the_session_is_created_normally_when_the_hash_is_upgraded(client: TestClient, engine):
    signup(client)
    install_outdated_hash(engine)
    client.post("/auth/logout")

    client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert client.get("/me").status_code == 200
    with engine.connect() as connection:
        live = connection.execute(
            sa.select(sa.func.count())
            .select_from(auth_session)
            .where(auth_session.c.revoked_at.is_(None))
        ).scalar_one()
    assert live == 1


def test_a_current_hash_is_not_rewritten_on_every_login(client: TestClient, engine):
    """Réécrire sans raison ferait payer un hachage supplémentaire à chaque connexion."""
    signup(client)
    before = stored_hash(engine)
    client.post("/auth/logout")

    client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert stored_hash(engine) == before


def test_a_wrong_password_never_rewrites_the_hash(client: TestClient, engine):
    signup(client)
    outdated = install_outdated_hash(engine)

    assert (
        client.post(
            "/auth/login", json={"email": EMAIL, "password": "mauvais-mot-de-passe"}
        ).status_code
        == 401
    )
    assert stored_hash(engine) == outdated, "un échec ne doit rien réécrire"


def test_a_corrupted_hash_is_never_rewritten(client: TestClient, engine):
    """Une empreinte illisible est un incident, pas une occasion de la remplacer."""
    signup(client)
    with engine.begin() as connection:
        connection.execute(
            sa.update(auth_user)
            .where(auth_user.c.email_normalized == EMAIL)
            .values(password_hash="ceci-n-est-pas-une-empreinte")
        )

    assert (
        client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 401
    )
    assert stored_hash(engine) == "ceci-n-est-pas-une-empreinte"


def test_an_unknown_email_writes_nothing_at_all(client: TestClient, engine):
    signup(client)
    before = stored_hash(engine)

    assert (
        client.post(
            "/auth/login", json={"email": "personne@negoce-romand.ch", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert stored_hash(engine) == before
    with engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(auth_user)).scalar() == 1
