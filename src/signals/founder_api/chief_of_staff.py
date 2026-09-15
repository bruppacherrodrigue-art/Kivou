"""Sanitized Founder projections of validated Chief of Staff reports."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator

from signals.chief_of_staff.contracts import ChiefOfStaffFact, ChiefOfStaffReport
from signals.chief_of_staff.store import StoredChiefOfStaffReport
from signals.founder_api.contracts import FounderContract

LATEST_VERSION = "founder-chief-of-staff-latest-v1"
HISTORY_VERSION = "founder-chief-of-staff-history-v1"


class FounderChiefOfStaffItem(FounderContract):
    report: ChiefOfStaffReport
    facts: tuple[ChiefOfStaffFact, ...]
    captured_at: dt.datetime
    stale: bool
    model_route: str
    usage_metadata: dict[str, Any]
    estimated_cost: Decimal
    actual_cost: Decimal | None

    _captured_at = field_validator("captured_at")(
        lambda value: value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
    )


class FounderChiefOfStaffLatest(FounderContract):
    version: Literal["founder-chief-of-staff-latest-v1"] = LATEST_VERSION
    state: Literal["AVAILABLE", "EMPTY"]
    stale: bool
    report: ChiefOfStaffReport | None
    facts: tuple[ChiefOfStaffFact, ...]
    captured_at: dt.datetime | None
    model_route: str | None
    usage_metadata: dict[str, Any]
    estimated_cost: Decimal | None
    actual_cost: Decimal | None


class FounderChiefOfStaffHistory(FounderContract):
    version: Literal["founder-chief-of-staff-history-v1"] = HISTORY_VERSION
    count: int = Field(ge=0, le=50)
    items: tuple[FounderChiefOfStaffItem, ...] = Field(max_length=50)


def _stale(record: StoredChiefOfStaffReport, *, now: dt.datetime) -> bool:
    thresholds = {
        "DAILY": dt.timedelta(hours=36),
        "WEEKLY": dt.timedelta(days=9),
        "ON_DEMAND": dt.timedelta(hours=36),
    }
    return now - record.captured_at > thresholds[record.report.cadence]


def project_item(
    record: StoredChiefOfStaffReport, *, now: dt.datetime
) -> FounderChiefOfStaffItem:
    return FounderChiefOfStaffItem(
        report=record.report,
        facts=record.evidence_facts,
        captured_at=record.captured_at,
        stale=_stale(record, now=now),
        model_route=record.model_route,
        usage_metadata=record.usage_metadata,
        estimated_cost=record.estimated_cost,
        actual_cost=record.actual_cost,
    )


def project_latest(
    record: StoredChiefOfStaffReport | None, *, now: dt.datetime
) -> FounderChiefOfStaffLatest:
    if record is None:
        return FounderChiefOfStaffLatest(
            state="EMPTY",
            stale=False,
            report=None,
            facts=(),
            captured_at=None,
            model_route=None,
            usage_metadata={},
            estimated_cost=None,
            actual_cost=None,
        )
    item = project_item(record, now=now)
    return FounderChiefOfStaffLatest(
        state="AVAILABLE",
        stale=item.stale,
        report=item.report,
        facts=item.facts,
        captured_at=item.captured_at,
        model_route=item.model_route,
        usage_metadata=item.usage_metadata,
        estimated_cost=item.estimated_cost,
        actual_cost=item.actual_cost,
    )


def project_history(
    records: tuple[StoredChiefOfStaffReport, ...], *, now: dt.datetime
) -> FounderChiefOfStaffHistory:
    items = tuple(project_item(record, now=now) for record in records)
    return FounderChiefOfStaffHistory(count=len(items), items=items)


__all__ = [
    "FounderChiefOfStaffHistory",
    "FounderChiefOfStaffItem",
    "FounderChiefOfStaffLatest",
    "project_history",
    "project_latest",
]
