"""Email possession is independent of a prospect token or a login session."""
from __future__ import annotations

import datetime as dt
from urllib.parse import urlsplit

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from signals.accounts.schema import auth_user
from signals.api.app import create_app
from signals.api.config import ApiConfig
from signals.persistence import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 9, 7, 12, tzinfo=dt.UTC)
ORIGIN = {"Origin": "https://kivou.test"}
EMAIL = "recipient@example.com"


class Mailbox:
    def __init__(self):
        self.messages = []
        self.fail = False

    def send(self, message):
        if self.fail:
            raise RuntimeError("private SMTP failure must not escape")
        self.messages.append(message)


@pytest.fixture
def prepared_email(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'email.db'}")
    migrate_to_latest(engine)
    clock = [NOW]
    app = create_app(engine, ApiConfig(cookie_secure=True, public_app_url="https://kivou.test",
                                     allowed_origin="https://kivou.test"),
                     now_override=lambda: clock[0])
    mailbox = Mailbox()
    app.state.email_verification_gateway = mailbox
    client = TestClient(app, base_url="https://kivou.test")
    created = client.post("/auth/signup", headers=ORIGIN, json={
        "email": EMAIL, "password": "Synthetic-password-2026!", "company_name": "Recette",
    })
    assert created.status_code == 201, created.text
    yield engine, client, mailbox, clock, created.json()
    engine.dispose()


def request_proof(client, email=EMAIL):
    return client.post("/auth/email/request", headers=ORIGIN, json={"email": email})


def token_from(mailbox):
    link = next(line for line in mailbox.messages[-1].text_body.splitlines()
                if line.startswith("https://"))
    return urlsplit(link).fragment


def test_new_account_is_not_verified(prepared_email):
    _, client, _, _, _ = prepared_email
    response = client.get("/auth/email")
    assert response.status_code == 200
    assert response.json() == {"email": EMAIL, "verified": False, "pending_email": None}


def test_proof_verifies_exact_address_once_and_revokes_old_sessions(prepared_email):
    engine, client, mailbox, _, user = prepared_email
    assert request_proof(client).status_code == 200
    old_cookies = dict(client.cookies)
    token = token_from(mailbox)
    from signals.accounts.email_verification import email_identity, is_verified_recipient
    with engine.connect() as connection:
        row = connection.execute(sa.select(email_identity)).one()
        assert row.token_hash != token and token not in str(row)
        assert not is_verified_recipient(connection, account_id=user["account_id"], email=EMAIL)
    response = client.post("/auth/email/verify", headers=ORIGIN, json={"token": token})
    assert response.status_code == 200
    assert client.get("/auth/email").json()["verified"] is True
    with engine.connect() as connection:
        assert is_verified_recipient(connection, account_id=user["account_id"], email=EMAIL)
        assert not is_verified_recipient(connection, account_id=user["account_id"], email="other@example.com")
    with TestClient(client.app, base_url="https://kivou.test", cookies=old_cookies) as old:
        assert old.get("/me").status_code == 401
    assert client.post("/auth/email/verify", headers=ORIGIN, json={"token": token}).status_code == 400


def test_address_change_pauses_alerts_and_requires_fresh_proof(prepared_email):
    engine, client, mailbox, clock, user = prepared_email
    assert request_proof(client).status_code == 200
    old_token = token_from(mailbox)
    assert client.post("/auth/email/verify", headers=ORIGIN, json={"token": old_token}).status_code == 200
    clock[0] += dt.timedelta(minutes=2)
    assert request_proof(client, "changed@example.com").status_code == 200
    assert client.get("/me").json()["email"] == EMAIL
    from signals.accounts.email_verification import is_verified_recipient
    with engine.connect() as connection:
        assert not is_verified_recipient(connection, account_id=user["account_id"], email=EMAIL)
    assert client.post("/auth/email/verify", headers=ORIGIN,
                       json={"token": token_from(mailbox)}).status_code == 200
    assert client.get("/me").json()["email"] == "changed@example.com"


def test_expired_and_superseded_proofs_cannot_verify(prepared_email):
    _, client, mailbox, clock, _ = prepared_email
    assert request_proof(client).status_code == 200
    first = token_from(mailbox)
    clock[0] += dt.timedelta(minutes=2)
    assert request_proof(client, "new@example.com").status_code == 200
    assert client.post("/auth/email/verify", headers=ORIGIN, json={"token": first}).status_code == 400
    clock[0] += dt.timedelta(days=2)
    assert client.post("/auth/email/verify", headers=ORIGIN,
                       json={"token": token_from(mailbox)}).status_code == 400


def test_errors_are_visible_and_do_not_leak_transport_details(prepared_email):
    _, client, mailbox, _, _ = prepared_email
    assert request_proof(client, "not-an-email").status_code == 422
    assert client.post("/auth/email/request", json={"email": EMAIL}).status_code == 403
    mailbox.fail = True
    response = request_proof(client)
    assert response.status_code == 503
    assert "private SMTP" not in response.text
    assert request_proof(client).status_code == 429


def test_existing_address_is_never_taken_over(prepared_email):
    engine, client, mailbox, _, _ = prepared_email
    from signals.accounts import service
    with engine.begin() as connection:
        service.sign_up(connection, email="existing@example.com", password="Different-password-2026!",
                        company_name="Existing", locale="fr", now=NOW, session_ttl=dt.timedelta(days=1))
    assert request_proof(client, "existing@example.com").status_code == 409
    assert mailbox.messages == []
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(auth_user)) == 2


def test_address_claimed_after_request_cannot_be_overwritten(prepared_email):
    engine, client, mailbox, _, _ = prepared_email
    assert request_proof(client, "claimed@example.com").status_code == 200
    from signals.accounts import service
    with engine.begin() as connection:
        service.sign_up(connection, email="claimed@example.com", password="Different-password-2026!",
                        company_name="Other", locale="fr", now=NOW, session_ttl=dt.timedelta(days=1))
    assert client.post("/auth/email/verify", headers=ORIGIN,
                       json={"token": token_from(mailbox)}).status_code == 409
    assert client.get("/me").json()["email"] == EMAIL
    assert client.get("/auth/email").json()["verified"] is False


def test_deactivated_account_cannot_be_reopened_by_email_proof(prepared_email):
    engine, client, mailbox, _, user = prepared_email
    assert request_proof(client).status_code == 200
    with engine.begin() as connection:
        connection.execute(sa.update(auth_user).where(auth_user.c.user_id == user["user_id"])
                           .values(is_active=False))
    assert client.post("/auth/email/verify", headers=ORIGIN,
                       json={"token": token_from(mailbox)}).status_code == 400
    assert client.get("/me").status_code == 401


def test_scanner_get_does_not_consume_verification(prepared_email):
    _, client, mailbox, _, _ = prepared_email
    assert request_proof(client).status_code == 200
    token = token_from(mailbox)
    assert client.get("/auth/email/verify").status_code == 405
    assert client.get("/auth/email").json()["verified"] is False
    assert client.post("/auth/email/verify", headers=ORIGIN, json={"token": token}).status_code == 200


def test_runtime_wires_real_smtp_without_startup_migrations(monkeypatch):
    from signals.alerts.gateway import SmtpAlertGateway
    from signals.api import asgi

    config = ApiConfig(public_app_url="https://kivou.test", smtp_host="smtp.example.com",
                       smtp_from_email="sender@example.com")
    sentinel = object()
    monkeypatch.setattr(asgi.ApiConfig, "from_environment", lambda: config)
    monkeypatch.setattr(asgi, "create_database_engine", lambda **kwargs: sentinel)
    monkeypatch.setattr(asgi, "load_instantly_webhook_runtime_config", lambda **kwargs: None)
    monkeypatch.setattr(asgi, "create_app", lambda engine, configuration, **kwargs: kwargs)
    wired = asgi.build_application()
    assert isinstance(wired["email_verification_gateway"], SmtpAlertGateway)
