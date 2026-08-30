from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from signals.api import ApiConfig, create_app
from signals.persistence.database import create_database_engine, migrate_to_latest

ORIGIN = "https://kivou.test"
PASSWORD = "un-mot-de-passe-assez-long"


@pytest.fixture
def engine(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'locale.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def app(engine):
    def now():
        return dt.datetime(2026, 8, 29, 9, 0, tzinfo=dt.UTC)

    return create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN),
        now_override=now,
    )


@pytest.fixture
def client(app):
    return TestClient(app, headers={"Origin": ORIGIN})


def signup(client):
    response = client.post(
        "/auth/signup",
        json={
            "email": "locale@example.com",
            "password": PASSWORD,
            "company_name": "Locale SA",
            "locale": "fr",
        },
    )
    assert response.status_code == 201
    return response


def test_authenticated_account_can_change_its_locale(client):
    signup(client)
    changed = client.patch("/me", json={"locale": "en"})
    assert changed.status_code == 200
    assert changed.json()["locale"] == "en"
    assert client.get("/me").json()["locale"] == "en"


def test_locale_update_rejects_unknown_values_and_fields(client):
    signup(client)
    assert client.patch("/me", json={"locale": "de"}).status_code == 422
    assert client.patch("/me", json={"locale": "en", "account_id": "other"}).status_code == 422
    assert client.get("/me").json()["locale"] == "fr"


def test_locale_update_requires_session_and_same_origin(app):
    anonymous = TestClient(app, headers={"Origin": ORIGIN})
    assert anonymous.patch("/me", json={"locale": "en"}).status_code == 401
    owner = TestClient(app, headers={"Origin": ORIGIN})
    signup(owner)
    assert owner.patch(
        "/me", json={"locale": "en"}, headers={"Origin": "https://attacker.example"}
    ).status_code == 403
