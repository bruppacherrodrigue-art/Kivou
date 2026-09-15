from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from signals.chief_of_staff.contracts import (
    BusinessDecision,
    ChiefOfStaffContext,
    ChiefOfStaffFact,
    ChiefOfStaffPriority,
    ChiefOfStaffReport,
    DataQualitySummary,
)

NOW = dt.datetime(2026, 9, 15, 5, 30, tzinfo=dt.UTC)


def fact(**changes: object) -> ChiefOfStaffFact:
    values: dict[str, object] = {
        "fact_ref": "fact:cockpit:paid:2026w37",
        "domain": "BUSINESS",
        "metric_key": "paid_account_count",
        "value": 2,
        "unit": "COUNT",
        "currency": None,
        "period_start": NOW - dt.timedelta(days=7),
        "period_end": NOW,
        "captured_at": NOW,
        "source_contract": "WeeklyCommercialCockpit",
        "source_version": "weekly-commercial-cockpit-v1",
        "data_status": "KNOWN",
    }
    values.update(changes)
    return ChiefOfStaffFact.model_validate(values)


def context(**changes: object) -> ChiefOfStaffContext:
    values: dict[str, object] = {
        "generated_at": NOW,
        "cadence": "DAILY",
        "period_start": NOW - dt.timedelta(days=1),
        "period_end": NOW,
        "business_memory_version": "business-memory-v1",
        "business_memory": (
            BusinessDecision(
                decision_key="governance.kivou_truth",
                category="GOVERNANCE",
                statement="Kivou conserve la vérité.",
                status="ACTIVE",
                effective_from=dt.date(2026, 9, 15),
                version="1.0.0",
                source_ref="docs/adr/2026-09-15-hermes-chief-of-staff.md",
            ),
        ),
        "profile_version": "1.0.0",
        "facts": (fact(period_start=NOW - dt.timedelta(days=1)),),
        "active_gates": (),
        "known_incidents": (),
        "data_quality": DataQualitySummary(reason_codes=(), fact_refs=()),
        "available_capabilities": ("STRATEGIC_SYNTHESIS",),
    }
    values.update(changes)
    return ChiefOfStaffContext.model_validate(values)


def report(**changes: object) -> ChiefOfStaffReport:
    values: dict[str, object] = {
        "report_ref": "report:daily:2026-09-15",
        "context_fingerprint": "a" * 64,
        "cadence": "DAILY",
        "period_start": NOW - dt.timedelta(days=1),
        "period_end": NOW,
        "created_at": NOW,
        "executive_status": "WATCH",
        "executive_summary": "Une attention humaine est requise.",
        "reason_codes": ("FOUNDER_REVIEW",),
        "observations": (),
        "priorities": (),
        "decision_requests": (),
        "unknowns": (),
        "source_refs": ("fact:cockpit:paid:2026w37",),
        "confidence": Decimal("0.8"),
        "supervisor_version": "hermes-agent-0.20.4",
        "profile_version": "1.0.0",
    }
    values.update(changes)
    return ChiefOfStaffReport.model_validate(values)


def test_contracts_are_strict_frozen_and_reject_unknown_fields() -> None:
    value = fact()
    with pytest.raises(ValidationError):
        ChiefOfStaffFact.model_validate({**value.model_dump(), "extra": "denied"})
    with pytest.raises(ValidationError):
        value.value = 3  # type: ignore[misc]


def test_all_context_dates_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        context(generated_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError, match="timezone-aware"):
        fact(captured_at=NOW.replace(tzinfo=None))


def test_unknown_value_is_not_converted_to_zero() -> None:
    unknown = fact(value=None, data_status="UNKNOWN")
    assert unknown.value is None
    with pytest.raises(ValidationError, match="unknown facts cannot carry a value"):
        fact(value=0, data_status="UNKNOWN")


def test_money_requires_integer_minor_units_and_explicit_currency() -> None:
    money = fact(value=1250, unit="MINOR_UNITS", currency="CHF")
    assert money.value == 1250
    with pytest.raises(ValidationError, match="money facts"):
        fact(value=Decimal("12.50"), unit="MINOR_UNITS", currency="CHF")
    with pytest.raises(ValidationError, match="currency"):
        fact(value=1250, unit="MINOR_UNITS", currency=None)


def test_context_is_shadow_and_untrusted_data_only() -> None:
    value = context()
    assert value.runtime_mode == "SHADOW"
    assert value.content_boundary == "UNTRUSTED_DATA"
    with pytest.raises(ValidationError):
        context(content_boundary="TRUSTED")


def test_report_allows_at_most_three_ranked_priorities() -> None:
    priorities = tuple(
        ChiefOfStaffPriority(
            priority=index,
            owner="FOUNDER",
            recommended_action="Examiner la preuve citée.",
            reason_codes=("FOUNDER_REVIEW",),
            fact_refs=("fact:cockpit:paid:2026w37",),
            approval_required=True,
        )
        for index in range(1, 4)
    )
    priorities += (
        ChiefOfStaffPriority.model_construct(
            priority=4,
            owner="FOUNDER",
            recommended_action="Examiner la preuve citée.",
            reason_codes=("FOUNDER_REVIEW",),
            fact_refs=("fact:cockpit:paid:2026w37",),
            approval_required=True,
        ),
    )
    with pytest.raises(ValidationError):
        report(priorities=priorities)


def test_business_decision_is_versioned_and_sourced() -> None:
    decision = BusinessDecision(
        decision_key="governance.kivou_truth",
        category="GOVERNANCE",
        statement="Kivou conserve la vérité.",
        status="ACTIVE",
        effective_from=dt.date(2026, 9, 15),
        version="1.0.0",
        source_ref="docs/adr/2026-09-15-hermes-chief-of-staff.md",
    )
    assert decision.source_ref.startswith("docs/")
