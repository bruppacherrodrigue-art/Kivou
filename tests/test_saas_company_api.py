from __future__ import annotations

import datetime as dt

import pytest
from billing_helpers import subscribe
from engagement_helpers import events
from fastapi.testclient import TestClient
from feed_helpers import (
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    SIMAP_RICH,
    materialize_simap,
)

from signals.api import ApiConfig, create_app
from signals.companies.enrichment import run_winner_enrichment_batch
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 25, 9, tzinfo=dt.UTC)


@pytest.fixture
def engine(tmp_path):
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    migrate_to_latest(value)
    return value


@pytest.fixture
def app(engine):
    return create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            allowed_origin=ORIGIN,
            session_ttl=dt.timedelta(days=365),
        ),
        now_override=lambda: NOW,
    )


def _signup(app, *, email: str, locale: str = "fr") -> TestClient:
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "company_name": "Entreprise cliente",
            "locale": locale,
        },
    )
    assert response.status_code == 201
    return client


def _icp(client: TestClient) -> str:
    response = client.post(
        "/target-icps",
        json={"label": "Intrants", "customer_input": COMPLETE_ICP_INPUT},
    )
    assert response.status_code == 201
    return response.json()["target_icp_id"]


def _pay(engine, client: TestClient) -> None:
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="scale",
            subscription_id=f"sub_{account_id}",
            now=NOW,
        )


def _seed_unlocked(engine, client: TestClient) -> str:
    icp_id = _icp(client)
    _pay(engine, client)
    with engine.begin() as connection:
        signal_key = materialize_simap(
            connection, SIMAP_RICH, target_icp_id=icp_id
        ).signal_key
        run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="company-api-test", limit=10
        )
        return signal_key


def test_company_endpoint_requires_authentication(app) -> None:
    anonymous = TestClient(app, headers={"Origin": ORIGIN})

    response = anonymous.get("/companies/cmp_0000000000000000")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


def test_unlocked_signal_detail_links_to_the_official_company_profile(app, engine) -> None:
    client = _signup(app, email="company-api@example.com")
    signal_key = _seed_unlocked(engine, client)

    detail = client.get(f"/signals/{signal_key}")
    company_key = detail.json()["company_key"]
    response = client.get(f"/companies/{company_key}")

    assert detail.status_code == 200
    assert detail.json()["locked"] is False
    assert company_key.startswith("cmp_")
    assert response.status_code == 200
    body = response.json()
    assert body["company_key"] == company_key
    assert body["official_identity"]["name"] == "Egli Gartenbau AG Sursee"
    assert body["official_identity"]["source"] == "public_notice"
    assert body["related_signals"][0]["signal_id"] == signal_key
    assert "apollo" not in response.text.lower()
    assert "contact_ref" not in response.text.lower()


def test_unlocked_feed_links_to_company_without_opening_every_signal_detail(app, engine) -> None:
    client = _signup(app, email="company-feed-api@example.com")
    signal_key = _seed_unlocked(engine, client)

    feed = client.get("/signals?freshness=all&limit=50")

    assert feed.status_code == 200
    card = next(item for item in feed.json()["items"] if item["signal_id"] == signal_key)
    assert card["locked"] is False
    assert card["company_key"].startswith("cmp_")
    profile = client.get(f"/companies/{card['company_key']}")
    assert profile.status_code == 200
    assert profile.json()["company_key"] == card["company_key"]
    assert events(engine, event_type="signal_detail_viewed") == []


def test_known_company_key_is_not_an_inter_account_oracle(app, engine) -> None:
    alice = _signup(app, email="alice-company-api@example.com")
    signal_key = _seed_unlocked(engine, alice)
    company_key = alice.get(f"/signals/{signal_key}").json()["company_key"]
    bob = _signup(app, email="bob-company-api@example.com")
    _icp(bob)
    _pay(engine, bob)

    response = bob.get(f"/companies/{company_key}")

    assert response.status_code == 404
    assert response.json() == {
        "detail": {"code": "company_not_found", "message": "entreprise introuvable"}
    }
    assert "egli" not in response.text.lower()


def test_locked_signal_detail_never_reveals_a_company_key(app, engine) -> None:
    client = _signup(app, email="locked-company-api@example.com")
    icp_id = _icp(client)
    with engine.begin() as connection:
        keys = [
            materialize_simap(connection, name, target_icp_id=icp_id).signal_key
            for name in ("29997-02", "33112-02", "33885-03", "34794-02")
        ]
    cards = client.get("/signals?freshness=all&limit=50").json()["items"]
    locked_key = next(card["signal_id"] for card in cards if card["locked"])

    response = client.get(f"/signals/{locked_key}")

    assert locked_key in keys
    locked_card = next(card for card in cards if card["signal_id"] == locked_key)
    assert "company_key" not in locked_card
    assert response.status_code == 200
    assert response.json()["locked"] is True
    assert "company_key" not in response.json()


def test_missing_and_malformed_company_keys_share_the_same_not_found_shape(app, engine) -> None:
    client = _signup(app, email="missing-company-api@example.com")
    _icp(client)
    _pay(engine, client)

    missing = client.get("/companies/cmp_0000000000000000")
    malformed = client.get("/companies/not-a-company-key")

    assert missing.status_code == malformed.status_code == 404
    assert missing.json() == malformed.json() == {
        "detail": {"code": "company_not_found", "message": "entreprise introuvable"}
    }
