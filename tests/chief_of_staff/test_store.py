from __future__ import annotations

import datetime as dt
from decimal import Decimal

from signals.chief_of_staff.store import ChiefOfStaffReportStore

from .test_validation import NOW, context, report


def test_store_is_append_only_idempotent_by_semantic_context(migrated_sqlite_engine) -> None:
    store = ChiefOfStaffReportStore(migrated_sqlite_engine)
    ctx = context()
    value = report(ctx)
    first, inserted = store.append(
        report=value,
        context=ctx,
        captured_at=NOW,
        model_route="openrouter/anthropic/claude-sonnet-4.6",
        usage_metadata={"input_tokens": 900, "output_tokens": 150},
        estimated_cost=Decimal("0.01"),
        actual_cost=Decimal("0.0045"),
        model_call_id=None,
    )
    replay, replay_inserted = store.append(
        report=value.model_copy(update={"report_ref": "report:duplicate-provider-ref"}),
        context=ctx,
        captured_at=NOW + dt.timedelta(minutes=1),
        model_route="openrouter/anthropic/claude-sonnet-4.6",
        usage_metadata={"input_tokens": 901},
        estimated_cost=Decimal("0.02"),
        actual_cost=Decimal("0.005"),
        model_call_id=None,
    )
    assert inserted is True
    assert replay_inserted is False
    assert replay.report.report_ref == first.report.report_ref
    assert store.history(limit=20) == (first,)


def test_store_reads_latest_and_bounded_history_by_cadence(migrated_sqlite_engine) -> None:
    store = ChiefOfStaffReportStore(migrated_sqlite_engine)
    first_context = context()
    store.append(
        report=report(first_context),
        context=first_context,
        captured_at=NOW,
        model_route="openrouter/model",
        usage_metadata={},
        estimated_cost=Decimal("0"),
        actual_cost=None,
        model_call_id=None,
    )
    second_context = first_context.model_copy(
        update={
            "generated_at": NOW + dt.timedelta(days=1),
            "period_start": NOW,
            "period_end": NOW + dt.timedelta(days=1),
        }
    )
    second_report = report(
        second_context,
        report_ref="report:daily:next",
        period_start=second_context.period_start,
        period_end=second_context.period_end,
        created_at=NOW + dt.timedelta(days=1),
    )
    store.append(
        report=second_report,
        context=second_context,
        captured_at=NOW + dt.timedelta(days=1),
        model_route="openrouter/model",
        usage_metadata={},
        estimated_cost=Decimal("0"),
        actual_cost=None,
        model_call_id=None,
    )
    assert store.latest(cadence="DAILY").report.report_ref == "report:daily:next"
    assert len(store.history(cadence="DAILY", limit=1)) == 1
    assert store.latest(cadence="WEEKLY") is None


def test_history_limit_is_bounded(migrated_sqlite_engine) -> None:
    store = ChiefOfStaffReportStore(migrated_sqlite_engine)
    for invalid in (0, 51):
        try:
            store.history(limit=invalid)
        except ValueError as error:
            assert "between 1 and 50" in str(error)
        else:  # pragma: no cover - assertion clarity
            raise AssertionError("invalid history limit accepted")

