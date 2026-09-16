from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from signals.chief_of_staff.attempt_store import ChiefOfStaffAttemptStore
from signals.chief_of_staff.hermes import (
    ChiefOfStaffHermesResult,
    ChiefOfStaffResponseRejected,
)
from signals.chief_of_staff.service import ChiefOfStaffService, reporting_period
from signals.chief_of_staff.store import ChiefOfStaffReportStore
from signals.supervisor.runtime import SupervisorTimeout

from .test_context import overview
from .test_validation import NOW, report


@dataclass
class OverviewReader:
    calls: int = 0

    def overview(self, *, now: dt.datetime, **_: object):
        self.calls += 1
        return overview()


@dataclass
class Generator:
    calls: int = 0
    model: str = "fixture/offline"

    def generate(self, context, *, call_id: str | None = None):
        self.calls += 1
        return ChiefOfStaffHermesResult(
            report=report(
                context,
                report_ref="report:fixture:daily",
                created_at=context.generated_at,
                executive_status="WATCH",
                executive_summary="La situation demande une revue humaine.",
                reason_codes=("HUMAN_REVIEW_REQUIRED",),
                observations=(),
                priorities=(),
                decision_requests=(),
                unknowns=(),
                source_refs=(),
            ),
            model="fixture/offline",
            usage={"input_tokens": 10, "output_tokens": 5},
            call_id=None,
            reserved_usd=Decimal("0.01"),
            actual_usd=Decimal("0.005"),
            input_tokens=10,
            output_tokens=5,
        )


def test_reporting_period_uses_completed_zurich_day_and_week() -> None:
    zurich = ZoneInfo("Europe/Zurich")
    at = dt.datetime(2026, 9, 15, 5, 30, tzinfo=dt.UTC)
    daily = reporting_period("DAILY", at=at)
    weekly = reporting_period("WEEKLY", at=at)
    assert daily == (
        dt.datetime(2026, 9, 14, tzinfo=zurich),
        dt.datetime(2026, 9, 15, tzinfo=zurich),
    )
    assert weekly == (
        dt.datetime(2026, 9, 7, tzinfo=zurich),
        dt.datetime(2026, 9, 14, tzinfo=zurich),
    )


def test_service_dry_run_collects_validates_and_never_persists(
    migrated_sqlite_engine,
) -> None:
    reader = OverviewReader()
    generator = Generator()
    store = ChiefOfStaffReportStore(migrated_sqlite_engine)
    attempts = ChiefOfStaffAttemptStore(migrated_sqlite_engine)
    outcome = ChiefOfStaffService(
        overview_reader=reader,
        generator=generator,
        store=store,
        attempt_store=attempts,
        clock=lambda: NOW,
    ).generate(cadence="DAILY")
    assert outcome.persisted is False
    assert outcome.inserted is False
    assert outcome.report.report_ref == "report:fixture:daily"
    assert reader.calls == generator.calls == 1
    assert store.latest() is None
    assert attempts.history()[0].status == "VALIDATED_NOT_PERSISTED"


def test_service_persists_only_after_semantic_validation(migrated_sqlite_engine) -> None:
    store = ChiefOfStaffReportStore(migrated_sqlite_engine)
    service = ChiefOfStaffService(
        overview_reader=OverviewReader(),
        generator=Generator(),
        store=store,
        attempt_store=ChiefOfStaffAttemptStore(migrated_sqlite_engine),
        clock=lambda: NOW,
    )
    first = service.generate(cadence="DAILY", persist=True)
    replay = service.generate(cadence="DAILY", persist=True)
    assert first.persisted is True and first.inserted is True
    assert replay.persisted is True and replay.inserted is False
    assert store.latest().report == first.report
    assert sorted(
        item.status
        for item in ChiefOfStaffAttemptStore(migrated_sqlite_engine).history()
    ) == ["IDEMPOTENT_EXISTING", "VALIDATED_PERSISTED"]


def test_invalid_context_fails_before_model_invocation(migrated_sqlite_engine) -> None:
    generator = Generator()

    class BrokenReader:
        def overview(self, *, now: dt.datetime, **_: object):
            raise ValueError("invalid deterministic read model")

    with pytest.raises(ValueError, match="invalid deterministic"):
        ChiefOfStaffService(
            overview_reader=BrokenReader(),
            generator=generator,
            store=ChiefOfStaffReportStore(migrated_sqlite_engine),
            attempt_store=ChiefOfStaffAttemptStore(migrated_sqlite_engine),
            clock=lambda: NOW,
        ).generate(cadence="DAILY")
    assert generator.calls == 0


def test_clock_must_be_timezone_aware(migrated_sqlite_engine) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ChiefOfStaffService(
            overview_reader=OverviewReader(),
            generator=Generator(),
            store=ChiefOfStaffReportStore(migrated_sqlite_engine),
            attempt_store=ChiefOfStaffAttemptStore(migrated_sqlite_engine),
            clock=lambda: dt.datetime(2026, 9, 15),  # noqa: DTZ001 - deliberately invalid
        ).generate(cadence="DAILY")


@pytest.mark.parametrize(
    ("error", "status", "stage", "code"),
    (
        (
            SupervisorTimeout("safe timeout"),
            "PROVIDER_FAILED",
            "PROVIDER_CALL",
            "TIMEOUT",
        ),
        (
            ChiefOfStaffResponseRejected("Hermes response is not JSON", code="INVALID_JSON"),
            "RESPONSE_REJECTED",
            "STRUCTURED_RESPONSE",
            "INVALID_JSON",
        ),
        (
            ChiefOfStaffResponseRejected("Hermes schema is invalid", code="SCHEMA_INVALID"),
            "RESPONSE_REJECTED",
            "STRUCTURED_RESPONSE",
            "SCHEMA_INVALID",
        ),
    ),
)
def test_service_audits_provider_and_response_failures(
    migrated_sqlite_engine, error, status, stage, code
) -> None:
    class FailingGenerator:
        model = "fixture/offline"

        def generate(self, context, *, call_id=None):
            raise error

    attempts = ChiefOfStaffAttemptStore(migrated_sqlite_engine)
    service = ChiefOfStaffService(
        overview_reader=OverviewReader(),
        generator=FailingGenerator(),
        store=ChiefOfStaffReportStore(migrated_sqlite_engine),
        attempt_store=attempts,
        clock=lambda: NOW,
    )
    with pytest.raises(type(error)):
        service.generate(cadence="DAILY")
    attempt = attempts.history()[0]
    assert (attempt.status, attempt.stage, attempt.result_code) == (status, stage, code)


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        ({"source_refs": ("fact:invented",)}, "UNKNOWN_SOURCE_REF"),
        ({"executive_summary": "La valeur exacte est 42"}, "NUMERIC_HALLUCINATION"),
        ({"executive_summary": "Active la campagne"}, "FORBIDDEN_COMMAND"),
    ),
)
def test_service_audits_semantic_rejections(
    migrated_sqlite_engine, mutation, code
) -> None:
    class InvalidGenerator(Generator):
        def generate(self, context, *, call_id=None):
            generated = super().generate(context, call_id=call_id)
            return generated.__class__(
                **{
                    **generated.__dict__,
                    "report": generated.report.model_copy(update=mutation),
                }
            )

    attempts = ChiefOfStaffAttemptStore(migrated_sqlite_engine)
    service = ChiefOfStaffService(
        overview_reader=OverviewReader(),
        generator=InvalidGenerator(),
        store=ChiefOfStaffReportStore(migrated_sqlite_engine),
        attempt_store=attempts,
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError):
        service.generate(cadence="DAILY")
    attempt = attempts.history()[0]
    assert attempt.status == "SEMANTICALLY_REJECTED"
    assert attempt.stage == "SEMANTIC_VALIDATION"
    assert attempt.result_code == code
    assert "Active la campagne" not in repr(attempt)
