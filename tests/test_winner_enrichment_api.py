"""Signal GETs consume enrichment state but never perform enrichment."""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from billing_helpers import subscribe
from fastapi.testclient import TestClient
from feed_helpers import COMPLETE_ICP_INPUT, ORIGIN, PASSWORD, materialize_simap

from signals.api import ApiConfig, create_app
from signals.companies.enrichment import run_winner_enrichment_batch
from signals.companies.schema import saas_company
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)


@pytest.fixture
def engine(tmp_path):
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'winner-api.db'}")
    migrate_to_latest(value)
    return value


@pytest.fixture
def client(engine):
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=lambda: NOW,
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={
            "email": "winner-api@kivou.eu",
            "password": PASSWORD,
            "company_name": "Winner API",
            "locale": "fr",
        },
    )
    assert response.status_code == 201, response.text
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="scale",
            subscription_id="sub_winner_api",
            now=NOW,
        )
    return client


def _seed(engine, client: TestClient, fixture: str = "33112-02") -> str:
    icp_id = client.post(
        "/target-icps",
        json={"label": fixture, "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]
    with engine.begin() as connection:
        return materialize_simap(connection, fixture, target_icp_id=icp_id).signal_key


def _card(client: TestClient, signal_key: str) -> dict:
    response = client.get("/signals", params={"view": "history", "limit": 50})
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["signal_id"] == signal_key)


def test_feed_and_detail_gets_do_not_create_a_company(engine, client) -> None:
    signal_key = _seed(engine, client)

    card = _card(client, signal_key)
    detail = client.get(f"/signals/{signal_key}")

    with engine.connect() as connection:
        count = connection.scalar(sa.select(sa.func.count()).select_from(saas_company))
    assert count == 0
    assert card["winner_enrichment"]["status"] == "pending"
    assert detail.json()["winner_enrichment"]["status"] == "pending"
    assert "company_key" not in card
    assert "company_key" not in detail.json()


def test_explicit_worker_makes_the_sourced_company_available(engine, client) -> None:
    signal_key = _seed(engine, client)
    with engine.begin() as connection:
        batch = run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="api-test", limit=10
        )

    card = _card(client, signal_key)
    detail = client.get(f"/signals/{signal_key}").json()

    assert batch.processed == 1
    assert card["company_key"].startswith("cmp_")
    assert detail["company_key"] == card["company_key"]
    enrichment = detail["winner_enrichment"]
    assert enrichment["status"] in {"completed", "partial"}
    assert enrichment["source"]["kind"] == "public_notice"
    assert enrichment["source"]["connector"] == "simap"
    assert enrichment["source"]["notice_id"]
    assert enrichment["source"]["retrieved_at"]
    assert "provider" not in str(enrichment).lower()


def test_locked_teaser_exposes_neither_company_nor_enrichment(engine, client) -> None:
    # A fresh Discovery account is needed because the fixture above is Scale.
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=lambda: NOW,
    )
    discovery = TestClient(app, headers={"Origin": ORIGIN})
    signup = discovery.post(
        "/auth/signup",
        json={
            "email": "winner-locked@kivou.eu",
            "password": PASSWORD,
            "company_name": "Locked",
            "locale": "fr",
        },
    )
    assert signup.status_code == 201, signup.text
    icp_id = discovery.post(
        "/target-icps",
        json={"label": "Locked", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]
    with engine.begin() as connection:
        for fixture in ("29997-02", "33112-02", "33885-03", "34794-02"):
            materialize_simap(connection, fixture, target_icp_id=icp_id)
        run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="locked-test", limit=50
        )

    cards = discovery.get("/signals", params={"view": "history", "limit": 50}).json()[
        "items"
    ]
    locked = next(card for card in cards if card["locked"])

    assert "company_key" not in locked
    assert "winner_enrichment" not in locked


def test_another_tenant_cannot_resolve_a_known_company_key(engine, client) -> None:
    signal_key = _seed(engine, client)
    with engine.begin() as connection:
        run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="tenant-test", limit=10
        )
    company_key = _card(client, signal_key)["company_key"]

    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=lambda: NOW,
    )
    other = TestClient(app, headers={"Origin": ORIGIN})
    assert other.post(
        "/auth/signup",
        json={
            "email": "winner-other@kivou.eu",
            "password": PASSWORD,
            "company_name": "Other",
            "locale": "fr",
        },
    ).status_code == 201

    response = other.get(f"/companies/{company_key}")

    assert response.status_code == 404
    assert "egli" not in response.text.lower()
