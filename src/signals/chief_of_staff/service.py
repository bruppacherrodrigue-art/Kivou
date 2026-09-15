"""Read-only Chief of Staff generation pipeline."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from signals.chief_of_staff.business_memory import load_business_memory
from signals.chief_of_staff.context import build_context
from signals.chief_of_staff.contracts import Cadence, ChiefOfStaffContext, ChiefOfStaffReport
from signals.chief_of_staff.facts import collect_founder_facts
from signals.chief_of_staff.hermes import ChiefOfStaffHermesResult
from signals.chief_of_staff.store import ChiefOfStaffReportStore, StoredChiefOfStaffReport
from signals.chief_of_staff.validation import validate_report

_ZURICH = ZoneInfo("Europe/Zurich")


class OverviewReader(Protocol):
    def overview(self, *, now: dt.datetime, **kwargs: object) -> object: ...


class ReportGenerator(Protocol):
    def generate(self, context: ChiefOfStaffContext) -> ChiefOfStaffHermesResult: ...


@dataclass(frozen=True)
class ChiefOfStaffGeneration:
    context: ChiefOfStaffContext
    report: ChiefOfStaffReport
    model: str
    persisted: bool
    inserted: bool
    stored: StoredChiefOfStaffReport | None
    usage: dict[str, object]
    estimated_cost: Decimal
    actual_cost: Decimal | None


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Chief of Staff clock must be timezone-aware")
    return value


def reporting_period(cadence: Cadence, *, at: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """Return the last completed Zurich business period."""

    at = _aware(at)
    local = at.astimezone(_ZURICH)
    if cadence == "ON_DEMAND":
        return at - dt.timedelta(days=1), at
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if cadence == "DAILY":
        return today - dt.timedelta(days=1), today
    current_monday = today - dt.timedelta(days=today.weekday())
    return current_monday - dt.timedelta(days=7), current_monday


class ChiefOfStaffService:
    """Orchestrate deterministic reads before and validation after Hermes."""

    def __init__(
        self,
        *,
        overview_reader: OverviewReader,
        generator: ReportGenerator,
        store: ChiefOfStaffReportStore,
        clock=lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self.overview_reader = overview_reader
        self.generator = generator
        self.store = store
        self.clock = clock

    def generate(
        self,
        *,
        cadence: Cadence,
        at: dt.datetime | None = None,
        persist: bool = False,
    ) -> ChiefOfStaffGeneration:
        generated_at = _aware(at or self.clock())
        period_start, period_end = reporting_period(cadence, at=generated_at)
        overview = self.overview_reader.overview(now=generated_at)
        context = build_context(
            overview=overview,
            facts=collect_founder_facts(overview),
            memory=load_business_memory(),
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
            generated_at=generated_at,
        )
        generated = self.generator.generate(context)
        report = validate_report(generated.report, context=context)
        usage = dict(generated.usage or {})
        estimated_cost = generated.reserved_usd or Decimal("0")
        stored: StoredChiefOfStaffReport | None = None
        inserted = False
        if persist:
            stored, inserted = self.store.append(
                report=report,
                context=context,
                captured_at=generated_at,
                model_route=generated.model,
                usage_metadata=usage,
                estimated_cost=estimated_cost,
                actual_cost=generated.actual_usd,
                model_call_id=generated.call_id,
            )
        return ChiefOfStaffGeneration(
            context=context,
            report=report,
            model=generated.model,
            persisted=persist,
            inserted=inserted,
            stored=stored,
            usage=usage,
            estimated_cost=estimated_cost,
            actual_cost=generated.actual_usd,
        )


__all__ = ["ChiefOfStaffGeneration", "ChiefOfStaffService", "reporting_period"]
