from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from signals.api.app import create_app
from signals.api.config import COCKPIT_OPERATOR_ACCOUNT_IDS_ENV, ApiConfig
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 23, 10, tzinfo=dt.UTC)
PASSWORD = "a-long-synthetic-password"


def _engine(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'cockpit.db'}")
    migrate_to_latest(engine)
    return engine


def _signup(client: TestClient, email: str = "operator@example.com") -> str:
    response = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "company_name": "Synthetic Operator",
            "locale": "fr",
        },
    )
    assert response.status_code == 201
    return response.json()["account_id"]


def _login(client: TestClient, email: str = "operator@example.com") -> None:
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200


def test_cockpit_is_server_authorized_and_default_deny(tmp_path) -> None:
    engine = _engine(tmp_path)
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False),
        now_override=lambda: NOW,
    )
    anonymous = TestClient(app)
    assert anonymous.get("/internal/commercial-cockpit").status_code == 401

    customer = TestClient(app)
    _signup(customer)
    me = customer.get("/me")
    assert me.status_code == 200
    assert me.json()["capabilities"] == {"commercial_cockpit": False}
    denied = customer.get("/internal/commercial-cockpit")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "cockpit_forbidden"


def test_configured_operator_gets_latest_or_bounded_historical_completed_week(tmp_path) -> None:
    engine = _engine(tmp_path)
    bootstrap = TestClient(
        create_app(engine, ApiConfig(cookie_secure=False), now_override=lambda: NOW)
    )
    account_id = _signup(bootstrap)
    operator = TestClient(
        create_app(
            engine,
            ApiConfig(
                cookie_secure=False,
                cockpit_operator_account_ids=frozenset({account_id}),
            ),
            now_override=lambda: NOW,
        )
    )
    _login(operator)

    assert operator.get("/me").json()["capabilities"] == {"commercial_cockpit": True}
    latest = operator.get("/internal/commercial-cockpit")
    previous = operator.get("/internal/commercial-cockpit?week_offset=1")

    assert latest.status_code == previous.status_code == 200
    assert latest.json()["week_start"].startswith("2026-08-10T00:00:00+02:00")
    assert latest.json()["week_end"].startswith("2026-08-17T00:00:00+02:00")
    assert previous.json()["week_start"].startswith("2026-08-03T00:00:00+02:00")
    assert latest.json()["funnel"]["delivered_proxy_count"] == 0
    assert latest.json()["analytical_rows"] == []
    assert operator.get("/internal/commercial-cockpit?week_offset=52").status_code == 422
    assert operator.get("/internal/commercial-cockpit?week_offset=-1").status_code == 422


def test_operator_allowlist_environment_is_bounded_normalized_and_absent_by_default(
    monkeypatch,
) -> None:
    monkeypatch.delenv(COCKPIT_OPERATOR_ACCOUNT_IDS_ENV, raising=False)
    assert ApiConfig.from_environment().cockpit_operator_account_ids == frozenset()

    monkeypatch.setenv(
        COCKPIT_OPERATOR_ACCOUNT_IDS_ENV,
        " account-b ,account-a,account-b ",
    )
    assert ApiConfig.from_environment().cockpit_operator_account_ids == frozenset(
        {"account-a", "account-b"}
    )
