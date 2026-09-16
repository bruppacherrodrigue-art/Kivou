from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa

from signals.chief_of_staff.attempt_store import ChiefOfStaffAttemptStore
from signals.chief_of_staff.context import context_fingerprint
from signals.model_runtime.budget import ModelBudgetStore
from signals.model_runtime.config import ModelRoute

from .test_validation import NOW, context


def test_attempt_store_uses_model_journal_as_financial_truth(
    migrated_sqlite_engine,
) -> None:
    budget = ModelBudgetStore(migrated_sqlite_engine, clock=lambda: NOW)
    budget.reserve(
        route=ModelRoute(
            usage="chief_of_staff",
            model="fixture/model",
            daily_budget_usd=Decimal("1"),
        ),
        estimated_usd=Decimal("0.02"),
        call_id="11111111-1111-4111-8111-111111111111",
    )
    budget.succeed(
        call_id="11111111-1111-4111-8111-111111111111",
        actual_usd=Decimal("0.007"),
        input_tokens=10,
        output_tokens=5,
    )
    value = context()
    store = ChiefOfStaffAttemptStore(migrated_sqlite_engine)
    stored = store.append(
        attempt_id="22222222-2222-4222-8222-222222222222",
        context_fingerprint=context_fingerprint(value),
        cadence=value.cadence,
        period_start=value.period_start,
        period_end=value.period_end,
        started_at=NOW,
        completed_at=NOW + dt.timedelta(seconds=1),
        model_route="untrusted/caller-value",
        model_call_id="11111111-1111-4111-8111-111111111111",
        status="RESPONSE_REJECTED",
        stage="STRUCTURED_RESPONSE",
        result_code="INVALID_JSON",
        profile_version=value.profile_version,
        context_version=value.context_version,
        expected_report_version="chief-of-staff-report-v1",
        hermes_version="0.20.4",
    )
    assert stored.model_route == "fixture/model"
    assert stored.reserved_usd == Decimal("0.02")
    assert stored.actual_usd == Decimal("0.007")
    assert stored.status == "RESPONSE_REJECTED"
    assert store.history(limit=10) == (stored,)


def test_attempt_store_without_model_call_keeps_sanitized_metadata_only(
    migrated_sqlite_engine,
) -> None:
    value = context()
    store = ChiefOfStaffAttemptStore(migrated_sqlite_engine)
    stored = store.append(
        attempt_id="33333333-3333-4333-8333-333333333333",
        context_fingerprint=context_fingerprint(value),
        cadence=value.cadence,
        period_start=value.period_start,
        period_end=value.period_end,
        started_at=NOW,
        completed_at=NOW,
        model_route="fixture/offline",
        model_call_id=None,
        status="VALIDATED_NOT_PERSISTED",
        stage="COMPLETE",
        result_code="DRY_RUN_VALIDATED",
        profile_version=value.profile_version,
        context_version=value.context_version,
        expected_report_version="chief-of-staff-report-v1",
        hermes_version="0.20.4",
    )
    assert stored.model_call_id is None
    assert stored.reserved_usd == Decimal("0")
    assert stored.actual_usd is None
    columns = {
        item["name"]
        for item in sa.inspect(migrated_sqlite_engine).get_columns(
            "chief_of_staff_attempt"
        )
    }
    assert not {
        "prompt",
        "raw_prompt",
        "response",
        "raw_response",
        "narrative",
        "email",
        "secret",
    }.intersection(columns)
    serialized = repr(stored)
    for forbidden in ("prompt", "response", "narrative", "email", "secret"):
        assert forbidden not in serialized.lower()


def test_attempt_store_is_append_only_and_bounded(migrated_sqlite_engine) -> None:
    value = context()
    store = ChiefOfStaffAttemptStore(migrated_sqlite_engine)
    values = {
        "attempt_id": "44444444-4444-4444-8444-444444444444",
        "context_fingerprint": context_fingerprint(value),
        "cadence": value.cadence,
        "period_start": value.period_start,
        "period_end": value.period_end,
        "started_at": NOW,
        "completed_at": NOW,
        "model_route": "fixture/offline",
        "model_call_id": None,
        "status": "PROVIDER_FAILED",
        "stage": "PROVIDER_CALL",
        "result_code": "TIMEOUT",
        "profile_version": value.profile_version,
        "context_version": value.context_version,
        "expected_report_version": "chief-of-staff-report-v1",
        "hermes_version": "0.20.4",
    }
    store.append(**values)
    with pytest.raises(sa.exc.IntegrityError):
        store.append(**values)
    for limit in (0, 101):
        with pytest.raises(ValueError, match="between"):
            store.history(limit=limit)
