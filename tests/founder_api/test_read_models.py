from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from signals.accounts.schema import account
from signals.engagement.schema import signal_feedback
from signals.founder_api.access import (
    FOUNDER_USER_HEADER,
    ORIGIN_SECRET_HEADER,
)
from signals.founder_api.acquisition_status import FounderAcquisitionActivity
from signals.founder_api.app import create_founder_app
from signals.founder_api.commercial_tunnel import FounderTunnelPeriod
from signals.founder_api.config import FounderApiConfig
from signals.founder_api.database import (
    FOUNDER_DATABASE_URL_ENV,
    FOUNDER_WRITE_DATABASE_URL_ENV,
    _verify_founder_writer_connection,
    create_founder_database_engine,
    create_founder_write_database_engine,
    resolve_founder_database_url,
    resolve_founder_write_database_url,
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
from signals.persistence.schema import METADATA, procedure_documents

ALLOWED_EMAIL = "rodrigue.bruppacher@gmail.com"
ALLOWED_USER = "rodrigue"
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
        FOUNDER_USER_HEADER: ALLOWED_USER,
        ORIGIN_SECRET_HEADER: ORIGIN_SECRET,
    }


def _stopped_timer(_: dt.datetime) -> FounderAcquisitionActivity:
    return FounderAcquisitionActivity(
        activity="STOPPED",
        activity_since=NOW - dt.timedelta(hours=2),
    )


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

    overview = FounderReadService(engine, timer_reader=_stopped_timer).overview(now=NOW)

    assert overview.environment == "PRODUCTION"
    assert overview.read_only is True
    assert overview.acquisition_status.activity == "STOPPED"
    assert overview.acquisition_status.activity_since == NOW - dt.timedelta(hours=2)
    assert overview.today.open_attention_count == 2
    assert overview.today.critical_attention_count == 1
    assert {
        "system_status",
        "hermes_status",
        "highest_safe_mode",
    }.isdisjoint(overview.today.model_dump())
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
    assert overview.commercial_tunnel.period_kind == FounderTunnelPeriod.LAST_7_DAYS
    assert overview.commercial_tunnel.period.end_at == NOW
    assert overview.commercial_tunnel.cohort_week_offset == 0
    assert overview.system.database_access == "READ_ONLY"
    assert {"health", "readiness", "hermes"} <= set(overview.system.model_dump())


def test_system_summary_exposes_today_persisted_model_budgets(monkeypatch) -> None:
    from decimal import Decimal

    from signals.model_runtime.budget import ModelBudgetStore
    from signals.model_runtime.config import routes_from_environment

    engine = _engine()
    monkeypatch.setenv("KIVOU_MODEL_BUDGET_ENRICHMENT_JUDGE_USD", "2.50")
    route = routes_from_environment(batch_id="founder-seed").route("enrichment_judge")
    store = ModelBudgetStore(engine, clock=lambda: NOW)
    store.reserve(route=route, estimated_usd=Decimal("0.10"), call_id="seed")
    store.succeed(
        call_id="seed",
        actual_usd=Decimal("0.04"),
        input_tokens=900,
        output_tokens=80,
    )

    overview = FounderReadService(engine, timer_reader=_stopped_timer).overview(now=NOW)

    budget = next(
        item for item in overview.system.model_budgets if item.usage == "enrichment_judge"
    )
    assert budget.model == "mistralai/mistral-small"
    assert budget.timezone == "Europe/Zurich"
    assert budget.cap_usd == Decimal("2.50")
    assert budget.actual_usd == Decimal("0.04000000")
    assert budget.reserved_usd == Decimal("0E-8")
    assert budget.remaining_usd == Decimal("2.46000000")
    assert budget.call_count == 1
    assert budget.succeeded_call_count == 1
    assert budget.failed_call_count == 0
    assert budget.rejected_call_count == 0
    assert budget.input_tokens == 900
    assert budget.output_tokens == 80


def test_overview_and_prospection_share_the_acquisition_status_read_model() -> None:
    engine = _engine()
    service = FounderReadService(engine, timer_reader=_stopped_timer)

    overview = service.overview(now=NOW)
    prospection = service.prospection(now=NOW)

    assert overview.acquisition_status == prospection.acquisition_status
    assert overview.acquisition_status.model_dump() == {
        "mode": None,
        "activity": "STOPPED",
        "activity_since": NOW - dt.timedelta(hours=2),
        "last_cycle_ref": None,
        "last_cycle_at": None,
        "last_cycle_status": None,
        "last_cycle_reason_code": None,
    }


def test_overview_route_is_authenticated_bounded_and_read_only() -> None:
    engine = _engine()
    read_service = FounderReadService(engine, timer_reader=_stopped_timer)
    app = create_founder_app(
        FounderApiConfig(
            allowed_email=ALLOWED_EMAIL,
            allowed_user=ALLOWED_USER,
            origin_secret=ORIGIN_SECRET,
        ),
        now_override=lambda: NOW,
        read_service=read_service,
    )

    with TestClient(app) as client:
        response = client.get("/api/founder/overview", headers=_headers())
        today_response = client.get(
            "/api/founder/overview?period=today&week_offset=1",
            headers=_headers(),
        )
        invalid = client.get(
            "/api/founder/overview?week_offset=52",
            headers=_headers(),
        )
        invalid_period = client.get(
            "/api/founder/overview?period=this_month",
            headers=_headers(),
        )
        unauthenticated = client.get("/api/founder/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["environment"] == "PRODUCTION"
    assert payload["read_only"] is True
    assert payload["acquisition_status"]["activity"] == "STOPPED"
    assert {
        "system_status",
        "hermes_status",
        "highest_safe_mode",
    }.isdisjoint(payload["today"])
    assert {"health", "readiness", "hermes"} <= set(payload["system"])
    assert payload["business"]["delivery_semantics"] == "PROXY_SENT_MINUS_BOUNCE_V1"
    assert payload["commercial_tunnel"]["period_kind"] == "last_7_days"
    assert payload["commercial_tunnel"]["cohort_week_offset"] == 0
    assert today_response.status_code == 200
    assert today_response.json()["commercial_tunnel"]["period_kind"] == "today"
    assert today_response.json()["commercial_tunnel"]["cohort_week_offset"] == 1
    assert invalid.status_code == 422
    assert invalid_period.status_code == 422
    assert unauthenticated.status_code == 403


def test_overview_fails_closed_when_read_models_are_absent() -> None:
    app = create_founder_app(
        FounderApiConfig(
            allowed_email=ALLOWED_EMAIL,
            allowed_user=ALLOWED_USER,
            origin_secret=ORIGIN_SECRET,
        ),
        now_override=lambda: NOW,
    )
    with TestClient(app) as client:
        response = client.get("/api/founder/overview", headers=_headers())

    assert response.status_code == 503


def test_review_required_document_blocks_are_only_exposed_by_authenticated_founder_api() -> None:
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(
            sa.insert(procedure_documents).values(
                procedure_document_key="review-1",
                source_system="boamp",
                source_notice_id="tender-1",
                source_url="https://example.test/dce.txt",
                host="example.test",
                access_status="available",
                byte_size=12,
                blocks=[{"locator": "page 1", "text": "Exigence", "method": "pdf_text"}],
                join_status="review_required",
                linked_award_key="award-1",
                captured_at=NOW,
                created_at=NOW,
            )
        )
    app = create_founder_app(
        FounderApiConfig(
            allowed_email=ALLOWED_EMAIL,
            allowed_user=ALLOWED_USER,
            origin_secret=ORIGIN_SECRET,
        ),
        read_service=FounderReadService(engine),
    )

    with TestClient(app) as client:
        response = client.get("/api/founder/procedure-document-reviews", headers=_headers())
        unauthenticated = client.get("/api/founder/procedure-document-reviews")

    assert response.status_code == 200
    assert response.json()[0]["blocks"][0]["text"] == "Exigence"
    assert unauthenticated.status_code == 403


def test_founder_database_never_guesses_or_accepts_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FOUNDER_DATABASE_URL_ENV, raising=False)
    with pytest.raises(RuntimeError, match=FOUNDER_DATABASE_URL_ENV):
        resolve_founder_database_url()
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_founder_database_engine("sqlite+pysqlite:///:memory:")


def test_founder_writer_requires_explicit_dedicated_postgres_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FOUNDER_WRITE_DATABASE_URL_ENV, raising=False)
    with pytest.raises(RuntimeError, match=FOUNDER_WRITE_DATABASE_URL_ENV):
        resolve_founder_write_database_url()
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_founder_write_database_engine("sqlite+pysqlite:///:memory:")
    with pytest.raises(RuntimeError, match="kivou_founder_rw"):
        create_founder_write_database_engine(
            "postgresql+psycopg://wrong_role:secret@127.0.0.1/kivou"
        )


def test_founder_writer_role_probe_closes_its_implicit_transaction() -> None:
    class ScalarResult:
        def __init__(self, value: str) -> None:
            self._value = value

        def scalar_one(self) -> str:
            return self._value

    class Connection:
        def __init__(self) -> None:
            self.values = iter(("kivou_founder_rw", "off"))
            self.rollback_count = 0

        def exec_driver_sql(self, statement: str) -> ScalarResult:
            del statement
            return ScalarResult(next(self.values))

        def rollback(self) -> None:
            self.rollback_count += 1

    connection = Connection()

    _verify_founder_writer_connection(connection)  # type: ignore[arg-type]

    assert connection.rollback_count == 1
