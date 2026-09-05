"""PR1 §3 — `GET /companies` : l'agrégat par titulaire résolu.

Les fixtures et l'aveu (« un `company_key` n'apparaît qu'après
`run_winner_enrichment_batch` ») sont copiés de `test_company_engagement.py`.
"""

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
    SIMAP_RICH,
    materialize_simap,
    pin_session_cookie,
)

from signals.api import ApiConfig, create_app
from signals.billing.schema import discovery_signal_grant
from signals.companies.enrichment import run_winner_enrichment_batch
from signals.companies.service import ensure_companies_for_signal_keys
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import materialized_signal

NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)

#: Trois avis SIMAP, trois titulaires distincts (test_feed_pagination.py::SIMAP_NAMES[:3]).
THREE_WINNERS = ("29997-02", "33112-02", "33885-03")


class Clock:
    def __init__(self, start: dt.datetime = NOW) -> None:
        self.now = start

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, delta: dt.timedelta) -> None:
        self.now += delta


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def app(engine, clock: Clock):
    return create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=clock,
    )


@pytest.fixture
def client(app, engine) -> TestClient:
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={
            "email": "companies-list@kivou.eu",
            "password": PASSWORD,
            "company_name": "Companies List",
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
            subscription_id="sub_companies_list",
            now=NOW,
        )
    return client


@pytest.fixture
def icp(client: TestClient) -> str:
    return client.post(
        "/target-icps",
        json={"label": "Suivi", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]


def _match_band(engine, signal_key: str) -> str | None:
    with engine.begin() as connection:
        row = connection.execute(
            sa.select(materialized_signal.c.icp_match_band).where(
                materialized_signal.c.signal_key == signal_key
            )
        ).one()
    return row.icp_match_band


def _expected_fit(band: str | None) -> str:
    return band if band in {"strong", "promising", "weak"} else "unknown"


def _seed_three_winners(engine, icp: str) -> list[str]:
    """Trois avis, trois titulaires distincts, projetés vers leur entreprise."""
    keys = []
    with engine.begin() as connection:
        for name in THREE_WINNERS:
            keys.append(materialize_simap(connection, name, target_icp_id=icp).signal_key)
        run_winner_enrichment_batch(connection, now=NOW, worker_ref="companies-list-test", limit=10)
    return keys


def _companies(client: TestClient, **params) -> dict:
    query = "&".join(f"{name}={value}" for name, value in params.items())
    suffix = f"?{query}" if query else ""
    response = client.get(f"/companies{suffix}")
    assert response.status_code == 200, response.text
    return response.json()


def test_three_distinct_winners_are_listed_sorted_by_last_award_desc(client, icp, engine):
    signal_keys = _seed_three_winners(engine, icp)
    payload = _companies(client)

    items = payload["items"]
    assert len(items) == 3
    # 33885-03 (2026-08-13) > 29997-02 (2026-06-22) > 33112-02 (2026-05-19)
    assert [item["last_award_at"] for item in items] == sorted(
        (item["last_award_at"] for item in items), reverse=True
    )
    for item in items:
        assert item["awards_count"] == 1
        assert item["contact_status"] == "to_contact"
        assert item["contacted_at"] is None
        assert len(item["total_amount"]) == 1
        assert item["total_amount"][0]["currency"] == "CHF"

    signals_by_key = client.get("/signals?freshness=all").json()["items"]
    company_key_by_signal = {s["signal_id"]: s["company_key"] for s in signals_by_key}
    items_by_company_key = {item["company_key"]: item for item in items}
    for signal_key in signal_keys:
        company_key = company_key_by_signal[signal_key]
        item = items_by_company_key[company_key]
        expected_band = _match_band(engine, signal_key)
        assert item["top_fit"] == _expected_fit(expected_band)

    assert payload["page"]["scan_truncated"] is False
    assert payload["page"]["has_more"] is False
    assert payload["read_at"] == NOW.date().isoformat()
    assert payload["plan_code"] == "scale"


def test_same_winner_under_two_icps_aggregates_into_one_row(client, icp, engine):
    second_icp = client.post(
        "/target-icps",
        json={"label": "Suivi bis", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]
    with engine.begin() as connection:
        materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)
        materialize_simap(connection, SIMAP_RICH, target_icp_id=second_icp)
        run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="companies-list-two-test", limit=10
        )

    items = _companies(client)["items"]

    assert len(items) == 1
    assert items[0]["awards_count"] == 2
    assert items[0]["total_amount"] == [{"currency": "CHF", "value": "1869755.00"}]


def test_companies_aggregate_all_account_profiles_beyond_plan_feed_limit(app, engine):
    essential = TestClient(app, headers={"Origin": ORIGIN})
    response = essential.post(
        "/auth/signup",
        json={
            "email": "companies-multi-profile@kivou.eu",
            "password": PASSWORD,
            "company_name": "Companies Multi Profile",
            "locale": "fr",
        },
    )
    assert response.status_code == 201, response.text
    pin_session_cookie(essential, response)
    account_id = essential.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="essential",
            subscription_id="sub_companies_multi_profile",
            now=NOW,
        )
    first_icp = essential.post(
        "/target-icps",
        json={"label": "Premier", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]
    second_icp = essential.post(
        "/target-icps",
        json={"label": "Second", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]
    with engine.begin() as connection:
        materialize_simap(connection, "33885-03", target_icp_id=first_icp)
        materialize_simap(connection, "33885-03", target_icp_id=second_icp)

    payload = _companies(essential)

    assert len(payload["items"]) == 1
    assert payload["items"][0]["awards_count"] == 2


def test_company_projection_batches_more_than_250_signal_keys(client, icp, engine):
    with engine.begin() as connection:
        signal_key = materialize_simap(
            connection, SIMAP_RICH, target_icp_id=icp
        ).signal_key
        projected = ensure_companies_for_signal_keys(
            connection,
            signal_keys=(signal_key,) * 251,
            now=NOW,
        )

    assert projected[signal_key].startswith("cmp_")


def test_query_filters_by_name_case_and_accent_insensitively(client, icp, engine):
    _seed_three_winners(engine, icp)

    for needle in ("egli", "EGLI", "Egli"):
        items = _companies(client, q=needle)["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Egli Gartenbau AG Sursee"

    assert _companies(client, q="ne-correspond-a-rien")["items"] == []


def test_contact_status_filter_reflects_a_company_contact(client, icp, engine):
    _seed_three_winners(engine, icp)
    all_items = _companies(client)["items"]
    target_key = all_items[0]["company_key"]

    contacted = client.post(f"/companies/{target_key}/contact", json={"status": "contacted"})
    assert contacted.status_code == 200

    contacted_items = _companies(client, contact_status="contacted")["items"]
    assert [item["company_key"] for item in contacted_items] == [target_key]

    pending_items = _companies(client, contact_status="to_contact")["items"]
    assert target_key not in {item["company_key"] for item in pending_items}
    assert len(pending_items) == 2

    bad = client.get("/companies?contact_status=bogus")
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "invalid_contact_status"


def test_cursor_pagination_has_no_duplicate_and_exhausts_has_more(client, icp, engine):
    _seed_three_winners(engine, icp)

    first_page = _companies(client, limit=2)
    assert len(first_page["items"]) == 2
    assert first_page["page"]["has_more"] is True
    assert first_page["page"]["next_cursor"] is not None

    second_page = _companies(client, limit=2, cursor=first_page["page"]["next_cursor"])
    assert len(second_page["items"]) == 1
    assert second_page["page"]["has_more"] is False
    assert second_page["page"]["next_cursor"] is None

    first_keys = [item["company_key"] for item in first_page["items"]]
    second_keys = [item["company_key"] for item in second_page["items"]]
    assert set(first_keys).isdisjoint(second_keys)

    whole = _companies(client)["items"]
    assert set(first_keys) | set(second_keys) == {item["company_key"] for item in whole}


def test_invalid_cursor_is_rejected(client, icp, engine):
    response = client.get("/companies?cursor=not-a-valid-cursor!!")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_company_cursor"


def test_fresh_account_without_subscription_or_unlocked_signal_sees_an_empty_list(app):
    anonymous_client = TestClient(app, headers={"Origin": ORIGIN})
    response = anonymous_client.post(
        "/auth/signup",
        json={
            "email": "fresh-account@kivou.eu",
            "password": PASSWORD,
            "company_name": "Fresh Account",
            "locale": "fr",
        },
    )
    assert response.status_code == 201, response.text
    pin_session_cookie(anonymous_client, response)

    payload = _companies(anonymous_client)

    assert payload["items"] == []


# ─── fix round 2 (F5) — la troncature laisse tomber les PLUS ANCIENNES ───────


def test_the_scan_cap_keeps_the_most_recently_materialized_companies(
    client, icp, engine, monkeypatch
):
    """Un plafond atteint doit couper par l'âge, pas par un identifiant opaque.

    Le balayage triait par `signal_key` seul : à la troncature, les entreprises
    survivantes étaient celles dont la clé de signal était la plus petite —
    c'est-à-dire un tirage au sort. Il suit désormais l'ordre du feed
    (`materialized_at DESC, signal_key ASC`), donc ce sont les signaux les plus
    anciennement matérialisés qui tombent.

    Le plafond est relu à l'appel (`feed_query.HISTORY_SCAN_CAP`) : le lier à
    l'import rendait ce `monkeypatch` sans effet.
    """
    from signals.feed import query as feed_query

    signal_keys = _seed_three_winners(engine, icp)
    kept = signal_keys[:2]
    with engine.begin() as connection:
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key.in_(kept))
            .values(materialized_at=dt.datetime(2026, 8, 24, 10, 0, tzinfo=dt.UTC))
        )
    monkeypatch.setattr(feed_query, "HISTORY_SCAN_CAP", 2)

    payload = _companies(client)

    assert payload["page"]["scan_truncated"] is True
    company_key_by_signal = {
        item["signal_id"]: item["company_key"]
        for item in client.get("/signals?freshness=all").json()["items"]
    }
    assert {item["company_key"] for item in payload["items"]} == {
        company_key_by_signal[signal_key] for signal_key in kept
    }


def test_discovery_companies_read_all_granted_signals_beyond_scan_cap(
    app, engine, monkeypatch
) -> None:
    from signals.feed import query as feed_query

    discovery_client = TestClient(app, headers={"Origin": ORIGIN})
    response = discovery_client.post(
        "/auth/signup",
        json={
            "email": "companies-discovery@kivou.eu",
            "password": PASSWORD,
            "company_name": "Companies Discovery",
            "locale": "fr",
        },
    )
    pin_session_cookie(discovery_client, response)
    icp_id = discovery_client.post(
        "/target-icps",
        json={"label": "Suivi", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]
    signal_keys = _seed_three_winners(engine, icp_id)
    account_id = discovery_client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        opportunities = {
            row.signal_key: row.opportunity_key
            for row in connection.execute(
                sa.select(
                    materialized_signal.c.signal_key,
                    materialized_signal.c.opportunity_key,
                ).where(materialized_signal.c.signal_key.in_(signal_keys))
            )
        }
        connection.execute(
            sa.insert(discovery_signal_grant),
            [
                {
                    "account_id": account_id,
                    "signal_key": key,
                    "opportunity_key": opportunities[key],
                    "granted_at": NOW,
                    "created_at": NOW,
                }
                for key in signal_keys
            ],
        )

    monkeypatch.setattr(feed_query, "HISTORY_SCAN_CAP", 1)
    payload = _companies(discovery_client)

    assert payload["plan_code"] == "discovery"
    assert len(payload["items"]) == 3
