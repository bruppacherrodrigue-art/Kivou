"""PR1 §5 — `GET /dashboard` : nouveautés depuis la dernière visite, relances.

Les fixtures et l'aveu (« un `company_key` n'apparaît qu'après
`run_winner_enrichment_batch` ») sont copiés de `test_companies_list.py`.

`NOW = 2026-08-20` est choisi pour que TROIS faits tiennent ensemble sans se
contredire :
  - `33885-03` (avis SIMAP à trois lots, trois titulaires distincts — APEXA
    GmbH, Detecon (Schweiz) AG, Digizone GmbH) a une date d'attribution du
    2026-08-13 : sept jours avant `NOW`, donc `recent_award` — le SEUL des
    quatre avis dont le statut appartient aux « nouveautés » (§5).
  - `29997-02` (attribué 2026-06-22), `33112-02` (2026-05-19) et `34794-02`
    (2026-07-09) sont tous trop anciens pour être `recent_award` à cette date,
    mais restent des signaux accessibles ordinaires — utiles au suivi
    commercial (`to_follow_up`) sans polluer les nouveautés.
  - Les quatre avis sont publiés entre le 2026-08-13 et le 2026-08-15, donc
    TOUS dans la fenêtre `[NOW - 7 j, NOW] = [2026-08-13, 2026-08-20]` — ce qui
    rend `week.new` calculable directement depuis les avis choisis.
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
    materialize_simap,
    pin_session_cookie,
)

from signals.api import ApiConfig, create_app
from signals.companies.enrichment import run_winner_enrichment_batch
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import materialized_signal

NOW = dt.datetime(2026, 8, 20, 9, 0, tzinfo=dt.UTC)


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
            "email": "dashboard@kivou.eu",
            "password": PASSWORD,
            "company_name": "Dashboard",
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
            subscription_id="sub_dashboard",
            now=NOW,
        )
    return client


@pytest.fixture
def icp(client: TestClient) -> str:
    return client.post(
        "/target-icps",
        json={"label": "Suivi", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]


def _seed_new_signals(client: TestClient, engine) -> list[str]:
    """Trois ICP actifs, un seul avis `recent_award` — trois signaux distincts.

    `signal_key` se dérive de `(opportunity_key, target_icp_id)` (PR1 §5,
    `signals.persistence.identity.signal_key`) : matérialiser les trois lots de
    `33885-03` sous le MÊME icp ne ferait qu'un seul signal, la dernière
    écriture l'emportant sur les précédentes. Trois ICP distincts, en revanche,
    produisent trois signaux bel et bien séparés à partir du MÊME lot — donc
    de la MÊME date d'attribution, ce qui les rend tous `recent_award`.
    """
    icps = [
        client.post(
            "/target-icps",
            json={"label": f"Suivi {n}", "customer_input": COMPLETE_ICP_INPUT},
        ).json()["target_icp_id"]
        for n in range(3)
    ]
    keys = []
    with engine.begin() as connection:
        for target_icp_id in icps:
            keys.append(
                materialize_simap(connection, "33885-03", target_icp_id=target_icp_id).signal_key
            )
        run_winner_enrichment_batch(connection, now=NOW, worker_ref="dashboard-test", limit=10)
    return keys


def _set_band_and_score(engine, signal_key: str, *, band: str, score: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == signal_key)
            .values(icp_match_band=band, icp_match_normalized_score=score)
        )


def _company_key_for(client: TestClient, signal_key: str) -> str:
    items = client.get("/signals?freshness=all").json()["items"]
    return next(item["company_key"] for item in items if item["signal_id"] == signal_key)


def _dashboard(client: TestClient) -> dict:
    response = client.get("/dashboard")
    assert response.status_code == 200, response.text
    return response.json()


def test_fresh_account_counts_new_signals_then_resets_after_the_first_visit(client, engine):
    _seed_new_signals(client, engine)

    first = _dashboard(client)
    assert first["last_seen_at"] is None
    assert first["as_of"] == NOW.date().isoformat()
    assert first["new_since_last_visit"] == 3

    second = _dashboard(client)
    assert dt.datetime.fromisoformat(second["last_seen_at"]) == NOW
    assert second["new_since_last_visit"] == 0


def test_strong_matches_counts_only_new_signals_with_a_strong_band(client, engine):
    keys = _seed_new_signals(client, engine)
    _set_band_and_score(engine, keys[0], band="strong", score=80)

    payload = _dashboard(client)

    assert payload["new_since_last_visit"] == 3
    assert payload["strong_matches"] == 1
    assert payload["strong_matches"] <= payload["new_since_last_visit"]


def test_top3_is_ordered_by_band_then_score_and_carries_a_company_key(client, engine):
    keys = _seed_new_signals(client, engine)
    _set_band_and_score(engine, keys[0], band="weak", score=10)
    _set_band_and_score(engine, keys[1], band="strong", score=50)
    _set_band_and_score(engine, keys[2], band="promising", score=90)

    payload = _dashboard(client)
    top3 = payload["top3"]

    assert len(top3) == 3
    assert [item["signal_id"] for item in top3] == [keys[1], keys[2], keys[0]]
    for item in top3:
        assert item["status"] == "new"
        assert item["company_key"]


def test_to_follow_up_lists_companies_contacted_a_week_or_more_ago(client, icp, engine, clock):
    with engine.begin() as connection:
        key_a = materialize_simap(connection, "29997-02", target_icp_id=icp).signal_key
        key_b = materialize_simap(connection, "33112-02", target_icp_id=icp).signal_key
        run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="dashboard-follow-up", limit=10
        )

    company_a = _company_key_for(client, key_a)
    company_b = _company_key_for(client, key_b)

    contacted_a = client.post(f"/companies/{company_a}/contact", json={"status": "contacted"})
    assert contacted_a.status_code == 200

    clock.advance(dt.timedelta(days=7))
    contacted_b = client.post(f"/companies/{company_b}/contact", json={"status": "contacted"})
    assert contacted_b.status_code == 200

    clock.advance(dt.timedelta(days=1))
    payload = _dashboard(client)

    follow_up = {item["company_key"]: item for item in payload["to_follow_up"]}
    assert company_a in follow_up
    assert follow_up[company_a]["days_since_contact"] == 8
    assert follow_up[company_a]["last_signal"]["company_key"] == company_a
    assert follow_up[company_a]["last_signal"]["signal_id"] == key_a
    assert company_b not in follow_up


def test_week_counts_relevant_contacted_and_replied_within_the_window(client, icp, engine):
    new_keys = _seed_new_signals(client, engine)
    with engine.begin() as connection:
        key_a = materialize_simap(connection, "29997-02", target_icp_id=icp).signal_key
        key_b = materialize_simap(connection, "33112-02", target_icp_id=icp).signal_key
        key_c = materialize_simap(connection, "34794-02", target_icp_id=icp).signal_key
        run_winner_enrichment_batch(connection, now=NOW, worker_ref="dashboard-week", limit=10)

    relevant = client.put(f"/signals/{key_a}/feedback", json={"relevance": "relevant"})
    assert relevant.status_code == 200

    # §6 — contacter un signal sans avis préalable enregistre AUSSI `relevant`
    # (`engagement/feedback.py::mark_contacted`) : ce signal compte donc à la
    # fois dans `saved` et dans `contacted`.
    contacted = client.post(f"/signals/{key_b}/contacted")
    assert contacted.status_code == 200

    company_c = _company_key_for(client, key_c)
    replied = client.post(f"/companies/{company_c}/contact", json={"status": "replied"})
    assert replied.status_code == 200

    payload = _dashboard(client)

    # Les quatre avis (`33885-03` × 3 ICP, `29997-02`, `33112-02`, `34794-02`)
    # sont tous publiés entre le 2026-08-13 et le 2026-08-15 — dans la fenêtre
    # `[2026-08-13, 2026-08-20]` — donc les six signaux comptent dans `new`.
    assert payload["week"] == {
        "new": len(new_keys) + 3,
        "saved": 2,
        "contacted": 1,
        "replied": 1,
    }


def test_fresh_account_without_any_signal_sees_an_empty_dashboard(app):
    anonymous_client = TestClient(app, headers={"Origin": ORIGIN})
    response = anonymous_client.post(
        "/auth/signup",
        json={
            "email": "fresh-dashboard@kivou.eu",
            "password": PASSWORD,
            "company_name": "Fresh Dashboard",
            "locale": "fr",
        },
    )
    assert response.status_code == 201, response.text
    pin_session_cookie(anonymous_client, response)

    payload = _dashboard(anonymous_client)

    assert payload["last_seen_at"] is None
    assert payload["new_since_last_visit"] == 0
    assert payload["strong_matches"] == 0
    assert payload["top3"] == []
    assert payload["to_follow_up"] == []
    assert payload["week"] == {"new": 0, "saved": 0, "contacted": 0, "replied": 0}
    assert payload["scan_truncated"] is False
