"""Read-only Chief of Staff generation pipeline."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from signals.chief_of_staff.attempt_store import (
    AttemptStage,
    AttemptStatus,
    ChiefOfStaffAttemptStore,
    StoredChiefOfStaffAttempt,
)
from signals.chief_of_staff.business_memory import load_business_memory
from signals.chief_of_staff.context import build_context, context_fingerprint
from signals.chief_of_staff.contracts import (
    REPORT_VERSION,
    Cadence,
    ChiefOfStaffContext,
    ChiefOfStaffReport,
)
from signals.chief_of_staff.facts import collect_founder_facts
from signals.chief_of_staff.hermes import (
    ChiefOfStaffHermesResult,
    ChiefOfStaffResponseRejected,
)
from signals.chief_of_staff.store import ChiefOfStaffReportStore, StoredChiefOfStaffReport
from signals.chief_of_staff.validation import ReportValidationError, validate_report
from signals.supervisor.pin import load_hermes_pin

_ZURICH = ZoneInfo("Europe/Zurich")


class OverviewReader(Protocol):
    def overview(self, *, now: dt.datetime, **kwargs: object) -> object: ...


class ReportGenerator(Protocol):
    model: str

    def generate(
        self, context: ChiefOfStaffContext, *, call_id: str | None = None
    ) -> ChiefOfStaffHermesResult: ...


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
    attempt: StoredChiefOfStaffAttempt


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
        attempt_store: ChiefOfStaffAttemptStore,
        clock=lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self.overview_reader = overview_reader
        self.generator = generator
        self.store = store
        self.attempt_store = attempt_store
        self.clock = clock

    def _append_attempt(
        self,
        *,
        attempt_id: str,
        context: ChiefOfStaffContext,
        started_at: dt.datetime,
        model_route: str,
        model_call_id: str | None,
        status: AttemptStatus,
        stage: AttemptStage,
        result_code: str,
    ) -> StoredChiefOfStaffAttempt:
        completed_at = _aware(self.clock())
        completed_at = max(completed_at, started_at)
        return self.attempt_store.append(
            attempt_id=attempt_id,
            context_fingerprint=context_fingerprint(context),
            cadence=context.cadence,
            period_start=context.period_start,
            period_end=context.period_end,
            started_at=started_at,
            completed_at=completed_at,
            model_route=model_route,
            model_call_id=model_call_id,
            status=status,
            stage=stage,
            result_code=result_code,
            profile_version=context.profile_version,
            context_version=context.context_version,
            expected_report_version=REPORT_VERSION,
            hermes_version=load_hermes_pin().version,
        )

    def generate(
        self,
        *,
        cadence: Cadence,
        at: dt.datetime | None = None,
        persist: bool = False,
    ) -> ChiefOfStaffGeneration:
        runtime_started_at = _aware(self.clock())
        generated_at = _aware(at or runtime_started_at)
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
        attempt_id = str(uuid.uuid4())
        planned_call_id = str(uuid.uuid4())
        model_route = self.generator.model
        try:
            generated = self.generator.generate(context, call_id=planned_call_id)
        except ChiefOfStaffResponseRejected as exc:
            self._append_attempt(
                attempt_id=attempt_id,
                context=context,
                started_at=runtime_started_at,
                model_route=model_route,
                model_call_id=planned_call_id,
                status="RESPONSE_REJECTED",
                stage="STRUCTURED_RESPONSE",
                result_code=exc.code,
            )
            raise
        except Exception as exc:
            category = getattr(exc, "category", "")
            code = getattr(exc, "code", "")
            result_code = (
                str(code)
                if code in {
                    "AUTH",
                    "PERMISSION",
                    "RATE_LIMITED",
                    "HERMES_PLAN_INVALID",
                    "SERVER_ERROR",
                    "TIMEOUT",
                    "NETWORK",
                    "DAILY_MODEL_BUDGET_EXHAUSTED",
                }
                else {
                    "timeout": "TIMEOUT",
                    "unavailable": "PROVIDER_UNAVAILABLE",
                    "provider": "PROVIDER_FAILED",
                }.get(str(category), "PROVIDER_FAILED")
            )
            self._append_attempt(
                attempt_id=attempt_id,
                context=context,
                started_at=runtime_started_at,
                model_route=model_route,
                model_call_id=planned_call_id,
                status="PROVIDER_FAILED",
                stage="PROVIDER_CALL",
                result_code=result_code,
            )
            raise
        try:
            report = validate_report(generated.report, context=context)
        except ReportValidationError as exc:
            self._append_attempt(
                attempt_id=attempt_id,
                context=context,
                started_at=runtime_started_at,
                model_route=generated.model,
                model_call_id=generated.call_id or planned_call_id,
                status="SEMANTICALLY_REJECTED",
                stage="SEMANTIC_VALIDATION",
                result_code=exc.code,
            )
            raise
        usage = dict(generated.usage or {})
        estimated_cost = generated.reserved_usd or Decimal("0")
        stored: StoredChiefOfStaffReport | None = None
        inserted = False
        if persist:
            try:
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
            except Exception:
                self._append_attempt(
                    attempt_id=attempt_id,
                    context=context,
                    started_at=runtime_started_at,
                    model_route=generated.model,
                    model_call_id=generated.call_id or planned_call_id,
                    status="VALIDATED_NOT_PERSISTED",
                    stage="PERSISTENCE",
                    result_code="PERSISTENCE_FAILED",
                )
                raise
        attempt = self._append_attempt(
            attempt_id=attempt_id,
            context=context,
            started_at=runtime_started_at,
            model_route=generated.model,
            model_call_id=generated.call_id or planned_call_id,
            status=(
                "VALIDATED_NOT_PERSISTED"
                if not persist
                else "VALIDATED_PERSISTED"
                if inserted
                else "IDEMPOTENT_EXISTING"
            ),
            stage="COMPLETE",
            result_code=(
                "DRY_RUN_VALIDATED"
                if not persist
                else "REPORT_PERSISTED"
                if inserted
                else "REPORT_ALREADY_EXISTS"
            ),
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
            attempt=attempt,
        )


__all__ = ["ChiefOfStaffGeneration", "ChiefOfStaffService", "reporting_period"]
