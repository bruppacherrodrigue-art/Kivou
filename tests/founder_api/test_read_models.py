from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from signals.accounts.schema import account
from signals.engagement.schema import signal_feedback
from signals.founder_api.access import (
    ACCESS_ASSERTION_HEADER,
    ACCESS_EMAIL_HEADER,
    ORIGIN_SECRET_HEADER,
)
from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig
from signals.founder_api.database import (
    FOUNDER_DATABASE_URL_ENV,
    create_founder_database_engine,
    resolve_founder_database_url,
)
from signals.founder_api.read_models import FounderReadService
from signals.operations.contracts import (
    DEFAULT_RETRY_POLICY,
    BreakerScope,
    DeadLetterExhaustion,
    IncidentSeverity,
    IncidentTrigger,
    IncidentType,
    ScopeType,
    WorkType,
)
from signals.operations.store import OperationsStore
from signals.persistence.schema import METADATA

ALLOWED_EMAIL = "rodrigue.bruppacher@gmail.com"
ORIGIN_SECRET = "s" * 40
NOW = dt.datetime(2026, 8, 29, 18, 30, tzinfo=dt.UTC)


def _engine() -> sa.Engine:
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    METADATA.create_all(engine)
    return engine


def _headers() -> dict[str, str]:
    return {
        ACCESS_EMAIL_HEADER: ALLOWED_EMAIL,
        ACCESS_ASSERTION_HEADER: "signed-by-cloudflare-access",
        ORIGIN_SECRET_HEADER: ORIGIN_SECRET,
    }


def _seed_quality(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.insert(account),
            {
                "account_id": "account-quality",
                "display_name": "Quality Account",
                "locale": "fr",
                "onboarding_status": "ready_for_signals",
                "created_at": NOW - dt.timedelta(days=60),
                "updated_at": NOW - dt.timedelta(days=1),
            },
        )
        connection.execute(
            sa.insert(signal_feedback),
            [
                {
                    "account_id": "account-quality",
                    "signal_key": "signal-relevant",
                    "relevance": "relevant",
                    "reason_code": None,
                    "note": None,
                    "contacted_at": NOW - dt.timedelta(days=1),
                    "event_status_at_feedback": "recent_award",
                    "event_age_days_at_feedback": 5,
                    "signal_revision_at_feedback": 1,
                    "opportunity_key": "opportunity-relevant",
                    "target_icp_id": None,
                    "created_at": NOW - dt.timedelta(days=2),
                    "updated_at": NOW - dt.timedelta(days=1),
                },
                {
                    "account_id": "account-quality",
                    "signal_key": "signal-negative",
                    "relevance": "not_relevant",
                    "reason_code": "wrong_need",
                    "note": None,
                    "contacted_at": None,
                    "event_status_at_feedback": "recent_award",
                    "event_age_days_at_feedback": 7,
                    "signal_revision_at_feedback": 1,
                    "opportunity_key": "opportunity-negative",
                    "target_icp_id": None,
                    "created_at": NOW - dt.timedelta(days=3),
                    "updated_at": NOW - dt.timedelta(days=2),
                },
                {
                    "account_id": "account-quality",
                    "signal_key": "signal-old",
                    "relevance": "not_relevant",
                    "reason_code": "too_late",
                    "note": None,
                    "contacted_at": None,
                    "event_status_at_feedback": "aging_award",
                    "event_age_days_at_feedback": 90,
                    "signal_revision_at_feedback": 1,
                    "opportunity_key": "opportunity-old",
                    "target_icp_id": None,
                    "created_at": NOW - dt.timedelta(days=45),
                    "updated_at": NOW - dt.timedelta(days=40),
                },
            ],
        )


def _seed_attention(engine: sa.Engine) -> None:
    store = OperationsStore(engine)
    scope = BreakerScope(scope_type=ScopeType.GLOBAL, scope_ref="acquisition")
    store.open_incident(
        IncidentTrigger(
            incident_type=IncidentType.PROVIDER_FAILURE,
            severity=IncidentSeverity.CRITICAL,
            scope=scope,
            source_state_ref="provider-state",
            triggered_at=NOW - dt.timedelta(minutes=10),
            reason_codes=("PROVIDER_UNAVAILABLE",),
            human_review_required=True,
            pause_required=True,
        )
    )
    store.enqueue_dead_letter(
        DeadLetterExhaustion(
            work_type=WorkType.SUPERVISOR_CYCLE,
            work_ref="supervisor-cycle",
            scope=scope,
            attempt_count=5,
            first_failed_at=NOW - dt.timedelta(hours=1),
            last_failed_at=NOW - dt.timedelta(minutes=20),
            failure_code="MAXIMUM_ATTEMPTS",
            retry_policy_version=DEFAULT_RETRY_POLICY.version,
            source_component="supervisor",
            source_state_ref="supervisor-state",
        ),
        created_at=NOW - dt.timedelta(minutes=20),
    )


def test_overview_composes_only_authoritative_read_models() -> None:
    engine = _engine()
    _seed_quality(engine)
    _seed_attention(engine)

    overview = FounderReadService(engine).overview(now=NOW)

    assert overview.environment == "PRODUCTION"
    assert overview.read_only is True
    assert overview.today.open_attention_count == 2
    assert overview.today.critical_attention_count == 1
    assert overview.today.system_status.value == "NOT_READY"
    assert [item.kind for item in overview.attention] == ["INCIDENT", "DEAD_LETTER"]
    assert overview.attention[0].title_code == "PROVIDER_FAILURE"
    assert overview.attention[0].pause_required is True
    assert overview.quality.feedback_updated_in_window_count == 2
    assert overview.quality.relevant_feedback_updated_in_window_count == 1
    assert overview.quality.not_relevant_feedback_updated_in_window_count == 1
    assert overview.quality.contacted_in_window_count == 1
    assert overview.quality.negative_feedback_rate_bps == 5_000
    assert overview.quality.negative_reason_counts[0].reason_code == "wrong_need"
    assert overview.business.delivery_semantics == "PROXY_SENT_MINUS_BOUNCE_V1"
    assert overview.system.database_access == "READ_ONLY"


def test_overview_route_is_authenticated_bounded_and_read_only() -> None:
    engine = _engine()
    read_service = FounderReadService(engine)
    app = create_founder_app(
        FounderApiConfig(
            allowed_email=ALLOWED_EMAIL,
            origin_secret=ORIGIN_SECRET,
        ),
        now_override=lambda: NOW,
        read_service=read_service,
    )

    with TestClient(app) as client:
        response = client.get("/api/founder/overview", headers=_headers())
        invalid = client.get(
            "/api/founder/overview?week_offset=52",
            headers=_headers(),
        )
        unauthenticated = client.get("/api/founder/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["environment"] == "PRODUCTION"
    assert payload["read_only"] is True
    assert invalid.status_code == 422
    assert unauthenticated.status_code == 403


def test_overview_fails_closed_when_read_models_are_absent() -> None:
    app = create_founder_app(
        FounderApiConfig(
            allowed_email=ALLOWED_EMAIL,
            origin_secret=ORIGIN_SECRET,
        ),
        now_override=lambda: NOW,
    )
    with TestClient(app) as client:
        response = client.get("/api/founder/overview", headers=_headers())

    assert response.status_code == 503


def test_founder_database_never_guesses_or_accepts_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FOUNDER_DATABASE_URL_ENV, raising=False)
    with pytest.raises(RuntimeError, match=FOUNDER_DATABASE_URL_ENV):
        resolve_founder_database_url()
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_founder_database_engine("sqlite+pysqlite:///:memory:")
