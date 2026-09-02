"""PR1 §2 — le statut unifié new | saved | ignored | contacted, dérivé jamais stocké."""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
from billing_helpers import subscribe
from fastapi.testclient import TestClient
from feed_helpers import COMPLETE_ICP_INPUT, ORIGIN, PASSWORD, materialize_simap, pin_session_cookie

from signals.api import ApiConfig, create_app
from signals.persistence.database import create_database_engine, migrate_to_latest

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
            "email": "signal-status@kivou.eu",
            "password": PASSWORD,
            "company_name": "Signal Status",
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
            subscription_id="sub_signal_status",
            now=NOW,
        )
    return client


@pytest.fixture
def icp(client: TestClient) -> str:
    return client.post(
        "/target-icps",
        json={"label": "Statut", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]


def _seed(engine, icp, count=3):
    """count signaux SIMAP distincts, récents."""
    keys = []
    with engine.begin() as connection:
        for name in ("29997-02", "33112-02", "33885-03", "34794-02")[:count]:
            keys.append(materialize_simap(connection, name, target_icp_id=icp).signal_key)
    return keys


def test_status_is_new_without_any_feedback(client, icp, engine):
    keys = _seed(engine, icp)
    body = client.get("/signals?freshness=all").json()
    assert {item["status"] for item in body["items"]} == {"new"}
    assert body["counts"] == {"new": 3, "saved": 0, "ignored": 0, "contacted": 0}
    assert body["counts_truncated"] is False
    assert client.get(f"/signals/{keys[0]}").json()["status"] == "new"


def test_status_follows_feedback_then_contact_wins(client, icp, engine):
    saved, ignored, contacted = _seed(engine, icp)
    client.put(f"/signals/{saved}/feedback", json={"relevance": "relevant"})
    client.put(f"/signals/{ignored}/feedback", json={"relevance": "not_relevant", "reason": "too_late"})
    client.post(f"/signals/{contacted}/contacted")
    # Contacté puis jugé non pertinent : l'action l'emporte sur l'opinion.
    client.put(f"/signals/{contacted}/feedback", json={"relevance": "not_relevant", "reason": "other"})
    by_key = {
        item["signal_id"]: item["status"]
        for item in client.get(
            "/signals?freshness=all&status=new&status=saved&status=ignored&status=contacted"
        ).json()["items"]
    }
    assert by_key == {saved: "saved", ignored: "ignored", contacted: "contacted"}
    assert client.get(f"/signals/{contacted}").json()["status"] == "contacted"


def test_default_listing_hides_ignored_but_counts_it(client, icp, engine):
    keys = _seed(engine, icp)
    client.put(f"/signals/{keys[1]}/feedback", json={"relevance": "not_relevant", "reason": "wrong_need"})
    body = client.get("/signals?freshness=all").json()
    assert keys[1] not in {item["signal_id"] for item in body["items"]}
    assert body["counts"] == {"new": 2, "saved": 0, "ignored": 1, "contacted": 0}


def test_status_filter_is_multi_valued_and_validated(client, icp, engine):
    keys = _seed(engine, icp)
    client.put(f"/signals/{keys[0]}/feedback", json={"relevance": "relevant"})
    only_saved = client.get("/signals?freshness=all&status=saved").json()
    assert [item["signal_id"] for item in only_saved["items"]] == [keys[0]]
    assert only_saved["counts"]["new"] == 2, "les compteurs ignorent le filtre de statut"
    both = client.get("/signals?freshness=all&status=saved&status=new").json()
    assert len(both["items"]) == 3
    assert client.get("/signals?status=bogus").status_code == 422
    assert client.get("/signals?status=bogus").json()["detail"]["code"] == "invalid_status"


def test_history_view_filters_status_before_the_page(client, icp, engine):
    keys = _seed(engine, icp, count=4)
    client.put(f"/signals/{keys[3]}/feedback", json={"relevance": "not_relevant", "reason": "other"})
    page = client.get("/signals?view=history&limit=2").json()
    assert keys[3] not in {item["signal_id"] for item in page["items"]}
    assert page["counts"]["ignored"] == 1
    second = (
        client.get(f"/signals?view=history&limit=2&cursor={page['page']['next_cursor']}").json()
        if page["page"]["next_cursor"]
        else {"items": []}
    )
    assert keys[3] not in {item["signal_id"] for item in second["items"]}


def test_legacy_recency_value_in_status_is_still_understood(client, icp, engine):
    _seed(engine, icp)
    legacy = client.get("/signals?view=history&status=recent_award")
    assert legacy.status_code == 200
    explicit = client.get("/signals?view=history&recency_status=recent_award")
    assert [i["signal_id"] for i in legacy.json()["items"]] == [
        i["signal_id"] for i in explicit.json()["items"]
    ]


# ─── fix round 1 — les compteurs de l'historique ne dépendent pas de `limit` ──


def test_history_counts_do_not_depend_on_the_page_size(client, icp, engine):
    keys = _seed(engine, icp, count=4)
    client.put(f"/signals/{keys[1]}/feedback", json={"relevance": "not_relevant", "reason": "wrong_need"})
    expected_counts = {"new": 3, "saved": 0, "ignored": 1, "contacted": 0}

    small = client.get("/signals?view=history&limit=1").json()
    medium = client.get("/signals?view=history&limit=2").json()
    large = client.get("/signals?view=history&limit=50").json()
    for body in (small, medium, large):
        assert body["counts"] == expected_counts
        assert body["counts_truncated"] is False

    assert small["page"]["has_more"] is True
    assert large["page"]["has_more"] is False

    non_ignored = sorted(key for key in keys if key != keys[1])
    seen: list[str] = []
    cursor = None
    while True:
        params = "view=history&limit=1"
        if cursor:
            params += f"&cursor={cursor}"
        page = client.get(f"/signals?{params}").json()
        seen.extend(item["signal_id"] for item in page["items"])
        if not page["page"]["has_more"]:
            break
        cursor = page["page"]["next_cursor"]
    assert sorted(seen) == non_ignored
    assert len(seen) == len(set(seen)), "aucun signal ne doit revenir deux fois"


def test_excluded_by_status_reports_the_default_ignored_exclusion(client, icp, engine):
    keys = _seed(engine, icp)
    client.put(f"/signals/{keys[0]}/feedback", json={"relevance": "not_relevant", "reason": "too_late"})
    recent = client.get("/signals?freshness=all").json()
    assert recent["excluded"]["by_status"] == 1
    history = client.get("/signals?view=history").json()
    assert history["excluded"]["by_status"] == 1


def test_history_counts_truncated_when_the_scan_cap_is_hit(client, icp, engine, monkeypatch):
    from signals.feed import query

    _seed(engine, icp, count=4)
    monkeypatch.setattr(query, "HISTORY_SCAN_CAP", 2)
    body = client.get("/signals?view=history&limit=50").json()
    assert body["counts_truncated"] is True


def _walk_history(client, params: str, first_page: dict) -> list[str]:
    """Épuise `view=history` en suivant `next_cursor`, borné pour ne jamais boucler."""
    seen = [item["signal_id"] for item in first_page["items"]]
    cursor = first_page["page"]["next_cursor"]
    has_more = first_page["page"]["has_more"]
    for _ in range(10):
        if not has_more:
            return seen
        page = client.get(f"/signals?{params}&cursor={cursor}").json()
        seen.extend(item["signal_id"] for item in page["items"])
        has_more = page["page"]["has_more"]
        cursor = page["page"]["next_cursor"]
    pytest.fail("l'historique ne s'est jamais terminé (has_more toujours vrai)")


def test_history_stays_walkable_when_the_scan_cap_hits_before_the_page_is_full(
    client, icp, engine, monkeypatch
):
    from signals.feed import query

    keys = _seed(engine, icp, count=4)
    monkeypatch.setattr(query, "HISTORY_SCAN_CAP", 2)

    first = client.get("/signals?view=history&limit=50").json()
    assert len(first["items"]) == 2
    assert first["page"]["has_more"] is True
    assert first["page"]["next_cursor"] is not None
    assert first["counts_truncated"] is True

    seen = _walk_history(client, "view=history&limit=50", first)
    assert sorted(seen) == sorted(keys)
    assert len(seen) == len(set(seen))


def test_history_full_page_then_cap_hit_still_reports_more(client, icp, engine, monkeypatch):
    from signals.feed import query

    keys = _seed(engine, icp, count=4)
    monkeypatch.setattr(query, "HISTORY_SCAN_CAP", 3)

    first = client.get("/signals?view=history&limit=2").json()
    assert len(first["items"]) == 2
    assert first["page"]["has_more"] is True

    seen = _walk_history(client, "view=history&limit=2", first)
    assert sorted(seen) == sorted(keys)
    assert len(seen) == len(set(seen))
