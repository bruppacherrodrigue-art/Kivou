from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from signals.chief_of_staff.hermes import ChiefOfStaffHermesResult
from signals.chief_of_staff.service import ChiefOfStaffService, reporting_period
from signals.chief_of_staff.store import ChiefOfStaffReportStore

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

    def generate(self, context):
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
    outcome = ChiefOfStaffService(
        overview_reader=reader,
        generator=generator,
        store=store,
        clock=lambda: NOW,
    ).generate(cadence="DAILY")
    assert outcome.persisted is False
    assert outcome.inserted is False
    assert outcome.report.report_ref == "report:fixture:daily"
    assert reader.calls == generator.calls == 1
    assert store.latest() is None


def test_service_persists_only_after_semantic_validation(migrated_sqlite_engine) -> None:
    store = ChiefOfStaffReportStore(migrated_sqlite_engine)
    service = ChiefOfStaffService(
        overview_reader=OverviewReader(),
        generator=Generator(),
        store=store,
        clock=lambda: NOW,
    )
    first = service.generate(cadence="DAILY", persist=True)
    replay = service.generate(cadence="DAILY", persist=True)
    assert first.persisted is True and first.inserted is True
    assert replay.persisted is True and replay.inserted is False
    assert store.latest().report == first.report


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
            clock=lambda: NOW,
        ).generate(cadence="DAILY")
    assert generator.calls == 0


def test_clock_must_be_timezone_aware(migrated_sqlite_engine) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ChiefOfStaffService(
            overview_reader=OverviewReader(),
            generator=Generator(),
            store=ChiefOfStaffReportStore(migrated_sqlite_engine),
            clock=lambda: dt.datetime(2026, 9, 15),  # noqa: DTZ001 - deliberately invalid
        ).generate(cadence="DAILY")
