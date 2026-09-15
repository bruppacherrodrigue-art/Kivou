from __future__ import annotations

import datetime as dt
from decimal import Decimal

from chief_of_staff.test_validation import NOW, context, report
from fastapi.testclient import TestClient

from signals.chief_of_staff.store import ChiefOfStaffReportStore
from signals.founder_api.access import FOUNDER_USER_HEADER, ORIGIN_SECRET_HEADER
from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig

_CONFIG = FounderApiConfig(
    allowed_email="rodrigue.bruppacher@gmail.com",
    allowed_user="rodrigue",
    origin_secret="s" * 40,
)
_HEADERS = {FOUNDER_USER_HEADER: "rodrigue", ORIGIN_SECRET_HEADER: "s" * 40}


def _store(engine, *, captured_at: dt.datetime = NOW) -> ChiefOfStaffReportStore:
    store = ChiefOfStaffReportStore(engine)
    ctx = context()
    store.append(
        report=report(ctx),
        context=ctx,
        captured_at=captured_at,
        model_route="openrouter/fixture",
        usage_metadata={"input_tokens": 10, "output_tokens": 5},
        estimated_cost=Decimal("0.01"),
        actual_cost=Decimal("0.004"),
        model_call_id=None,
    )
    return store


def test_latest_is_authenticated_versioned_and_contains_no_raw_provider_data(
    migrated_sqlite_engine,
) -> None:
    app = create_founder_app(
        _CONFIG,
        now_override=lambda: NOW,
        chief_of_staff_store=_store(migrated_sqlite_engine),
    )
    with TestClient(app) as client:
        response = client.get("/api/founder/chief-of-staff/latest", headers=_HEADERS)
        unauthenticated = client.get("/api/founder/chief-of-staff/latest")
        mutation = client.post("/api/founder/chief-of-staff/latest", headers=_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "founder-chief-of-staff-latest-v1"
    assert payload["state"] == "AVAILABLE"
    assert payload["report"]["report_ref"] == "report:daily:2026-09-15"
    assert payload["model_route"] == "openrouter/fixture"
    assert payload["usage_metadata"] == {"input_tokens": 10, "output_tokens": 5}
    assert "prompt" not in response.text.lower()
    assert "provider_response" not in response.text.lower()
    assert unauthenticated.status_code == 403
    assert mutation.status_code == 405


def test_latest_without_report_is_a_normal_empty_state(migrated_sqlite_engine) -> None:
    app = create_founder_app(
        _CONFIG,
        now_override=lambda: NOW,
        chief_of_staff_store=ChiefOfStaffReportStore(migrated_sqlite_engine),
    )
    with TestClient(app) as client:
        response = client.get("/api/founder/chief-of-staff/latest", headers=_HEADERS)
    assert response.status_code == 200
    assert response.json() == {
        "version": "founder-chief-of-staff-latest-v1",
        "state": "EMPTY",
        "stale": False,
        "report": None,
        "captured_at": None,
        "model_route": None,
        "usage_metadata": {},
        "estimated_cost": None,
        "actual_cost": None,
    }


def test_chief_routes_return_explicit_503_when_store_is_unavailable() -> None:
    app = create_founder_app(_CONFIG, now_override=lambda: NOW)
    with TestClient(app) as client:
        latest = client.get("/api/founder/chief-of-staff/latest", headers=_HEADERS)
        history = client.get("/api/founder/chief-of-staff/history", headers=_HEADERS)
    assert latest.status_code == history.status_code == 503


def test_history_is_bounded_and_cadence_filtered(migrated_sqlite_engine) -> None:
    app = create_founder_app(
        _CONFIG,
        now_override=lambda: NOW + dt.timedelta(days=2),
        chief_of_staff_store=_store(migrated_sqlite_engine),
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/founder/chief-of-staff/history?cadence=DAILY&limit=1",
            headers=_HEADERS,
        )
        too_many = client.get(
            "/api/founder/chief-of-staff/history?limit=51", headers=_HEADERS
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "founder-chief-of-staff-history-v1"
    assert payload["count"] == 1
    assert payload["items"][0]["stale"] is True
    assert too_many.status_code == 422
