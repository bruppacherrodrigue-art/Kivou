"""Phase 1 — la hiérarchie client est construite uniquement avec des faits."""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import subscribe
from fastapi.testclient import TestClient
from feed_helpers import (
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    materialize,
    pin_session_cookie,
    simap_award,
)

from signals.api import ApiConfig, create_app
from signals.feed.factual_display import _headline
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import materialized_signal

NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def client(engine) -> TestClient:
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=lambda: NOW,
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={
            "email": "factual-display@kivou.eu",
            "password": PASSWORD,
            "company_name": "Factual Display",
            "locale": "fr",
        },
    )
    assert response.status_code == 201, response.text
    pin_session_cookie(client, response)
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="scale",
            subscription_id="sub_factual_display",
            now=NOW,
        )
    return client


@pytest.fixture
def icp(client: TestClient) -> str:
    return client.post(
        "/target-icps",
        json={"label": "Faits", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]


def _feed_item(client: TestClient, signal_key: str) -> dict:
    response = client.get("/signals", params={"view": "history", "limit": 50})
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["signal_id"] == signal_key)


def test_rich_title_starts_with_the_winner_and_never_with_an_identifier(
    client, engine, icp
) -> None:
    event, awards = simap_award("33112-02")
    with engine.begin() as connection:
        signal_key = materialize(
            connection, event, awards[0], target_icp_id=icp
        ).signal_key

    item = _feed_item(client, signal_key)
    display = item["factual_display"]

    assert display["headline"].startswith(item["company"]["name"])
    assert "remporte" in display["headline"]
    assert display["market_summary"] == item["contract"]["title"]
    assert display["date"] == {
        "value": item["event"]["date"],
        "kind": item["event"]["clock"],
    }
    identifier = item["company"]["identifier"]
    if identifier is not None:
        assert identifier["value"] not in display["headline"]


def test_missing_object_amount_and_place_use_the_published_buyer_fallback(
    client, engine, icp
) -> None:
    event, awards = simap_award("29997-02")
    award = awards[0].model_copy(
        update={"title": None, "value": None, "place_of_performance": None}
    )
    with engine.begin() as connection:
        signal_key = materialize(connection, event, award, target_icp_id=icp).signal_key

    item = _feed_item(client, signal_key)
    display = item["factual_display"]
    buyer = item["contract"]["buyer"]["name"]

    assert display["headline"] == (
        f"{item['company']['name']} remporte un marché attribué par {buyer}"
    )
    assert display["market_summary"] is None
    assert set(display["missing_fields"]) >= {"market_object", "amount", "location"}
    assert display["completeness"] == "partial"


def test_fallback_never_reads_analysis_or_adds_a_person_or_urgency(client, engine, icp) -> None:
    event, awards = simap_award("33885-03")
    event = event.model_copy(update={"procedure_buyers": ()})
    award = awards[0].model_copy(
        update={"title": None, "value": None, "place_of_performance": None}
    )
    with engine.begin() as connection:
        signal_key = materialize(connection, event, award, target_icp_id=icp).signal_key
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == signal_key)
            .values(
                inferred_contract_summary="URGENT : contacter Jean Dupont",
                plausible_needs=[
                    {
                        "category": "workforce_capacity",
                        "statement": "Recruter immédiatement une équipe",
                    }
                ],
            )
        )

    item = _feed_item(client, signal_key)
    display_text = str(item["factual_display"])

    assert item["factual_display"]["headline"] == (
        f"Marché attribué à {item['company']['name']}"
    )
    assert "Jean Dupont" not in display_text
    assert "URGENT" not in display_text
    assert "Recruter" not in display_text


def test_notification_date_is_never_presented_as_an_award_date(client, engine, icp) -> None:
    event, awards = simap_award("34794-02")
    award = awards[0].model_copy(
        update={
            "award_date": None,
            "contract_notification_date": dt.date(2026, 8, 12),
        }
    )
    with engine.begin() as connection:
        signal_key = materialize(connection, event, award, target_icp_id=icp).signal_key

    display = _feed_item(client, signal_key)["factual_display"]

    assert display["date"] == {"value": "2026-08-12", "kind": "notification"}


def test_fact_copy_uses_the_account_language_without_changing_facts(client, engine, icp) -> None:
    event, awards = simap_award("38918-02")
    with engine.begin() as connection:
        signal_key = materialize(
            connection, event, awards[0], target_icp_id=icp
        ).signal_key

    french = _feed_item(client, signal_key)
    response = client.patch("/me", json={"locale": "en"})
    assert response.status_code == 200, response.text
    english = _feed_item(client, signal_key)

    assert "remporte" in french["factual_display"]["headline"]
    assert "wins" in english["factual_display"]["headline"]
    assert french["company"] == english["company"]
    assert french["contract"] == english["contract"]


def test_headline_is_bounded_after_composing_published_facts() -> None:
    headline = _headline(
        company="Entreprise " + "très longue " * 80,
        market_object="Objet " + "documenté " * 80,
        amount=None,
        location=None,
        buyer=None,
        lang="fr",
    )

    assert len(headline) <= 220
    assert headline.endswith("…")
