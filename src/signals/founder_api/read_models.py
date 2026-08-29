"""Deterministic production read models for the Founder Console."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from decimal import Decimal
from typing import Literal, Protocol

import sqlalchemy as sa
from pydantic import Field, field_validator
from sqlalchemy.engine import Engine

from signals.cockpit.contracts import WeeklyCommercialCockpit, completed_week
from signals.cockpit.service import WeeklyCommercialCockpitService
from signals.engagement.schema import signal_feedback
from signals.founder_api.contracts import FounderContract
from signals.operations.contracts import (
    AcquisitionOperationalHealth,
    AutonomousReadiness,
    HealthStatus,
)
from signals.operations.service import OperationsReadService
from signals.policy.contracts import AutonomyMode

FOUNDER_OVERVIEW_VERSION = "founder-console-overview-v1"
FOUNDER_QUALITY_VERSION = "founder-quality-summary-v1"
FOUNDER_QUALITY_WINDOW = dt.timedelta(days=30)
QUALITY_SEMANTICS = "CURRENT_FEEDBACK_UPDATED_IN_WINDOW_V1"


class CommercialReader(Protocol):
    def generate(self, *, week: object) -> WeeklyCommercialCockpit: ...


class OperationsReader(Protocol):
    def health(self, *, observed_at: dt.datetime) -> AcquisitionOperationalHealth: ...

    def readiness(self, *, evaluated_at: dt.datetime) -> AutonomousReadiness: ...

    def incidents(self, *, limit: int = 100) -> tuple[dict[str, object], ...]: ...

    def dead_letters(self, *, limit: int = 100) -> tuple[dict[str, object], ...]: ...


class FounderReasonCount(FounderContract):
    reason_code: str
    count: int = Field(ge=0)


class FounderQualitySummary(FounderContract):
    version: Literal["founder-quality-summary-v1"] = FOUNDER_QUALITY_VERSION
    semantics: Literal["CURRENT_FEEDBACK_UPDATED_IN_WINDOW_V1"] = QUALITY_SEMANTICS
    window_start: dt.datetime
    window_end: dt.datetime
    feedback_updated_in_window_count: int = Field(ge=0)
    relevant_feedback_updated_in_window_count: int = Field(ge=0)
    not_relevant_feedback_updated_in_window_count: int = Field(ge=0)
    contacted_in_window_count: int = Field(ge=0)
    negative_feedback_rate_bps: int | None = Field(default=None, ge=0, le=10_000)
    negative_reason_counts: tuple[FounderReasonCount, ...]
    unresolved_sector_count: int = Field(ge=0)
    unknown_mrr_journey_count: int = Field(ge=0)

    _times = field_validator("window_start", "window_end")(
        lambda value: _aware(value)
    )


class FounderAttentionItem(FounderContract):
    kind: Literal["INCIDENT", "DEAD_LETTER"]
    item_ref: str
    severity: Literal["WARNING", "HIGH", "CRITICAL"]
    status: str
    occurred_at: dt.datetime
    title_code: str
    reason_codes: tuple[str, ...]
    scope_type: str
    scope_ref: str
    source_component: str | None = None
    attempt_count: int | None = Field(default=None, ge=1)
    human_review_required: bool
    pause_required: bool

    _occurred_at = field_validator("occurred_at")(lambda value: _aware(value))


class FounderAgentStatus(FounderContract):
    name: Literal["Hermes Acquisition Supervisor"] = "Hermes Acquisition Supervisor"
    status: HealthStatus
    highest_safe_mode: AutonomyMode
    observed_at: dt.datetime
    reason_codes: tuple[str, ...]

    _observed_at = field_validator("observed_at")(lambda value: _aware(value))


class FounderTodaySummary(FounderContract):
    generated_at: dt.datetime
    open_attention_count: int = Field(ge=0)
    critical_attention_count: int = Field(ge=0)
    positive_replies_last_completed_week: int = Field(ge=0)
    paid_accounts_last_completed_week: int = Field(ge=0)
    business_period_start: dt.datetime
    business_period_end: dt.datetime
    system_status: HealthStatus
    hermes_status: HealthStatus
    highest_safe_mode: AutonomyMode

    _times = field_validator(
        "generated_at", "business_period_start", "business_period_end"
    )(lambda value: _aware(value))


class FounderSystemSummary(FounderContract):
    health: AcquisitionOperationalHealth
    readiness: AutonomousReadiness
    hermes: FounderAgentStatus
    database_access: Literal["READ_ONLY"] = "READ_ONLY"


class FounderConsoleOverview(FounderContract):
    version: Literal["founder-console-overview-v1"] = FOUNDER_OVERVIEW_VERSION
    environment: Literal["PRODUCTION"] = "PRODUCTION"
    read_only: Literal[True] = True
    generated_at: dt.datetime
    today: FounderTodaySummary
    attention: tuple[FounderAttentionItem, ...]
    business: WeeklyCommercialCockpit
    quality: FounderQualitySummary
    system: FounderSystemSummary

    _generated_at = field_validator("generated_at")(lambda value: _aware(value))


class FounderReadService:
    """Compose existing authoritative read models without creating new truth."""

    def __init__(
        self,
        engine: Engine,
        *,
        commercial: CommercialReader | None = None,
        operations: OperationsReader | None = None,
    ) -> None:
        self._engine = engine
        self._commercial = commercial or WeeklyCommercialCockpitService(engine)
        self._operations = operations or OperationsReadService(engine)

    def overview(
        self,
        *,
        now: dt.datetime,
        week_offset: int = 0,
        attention_limit: int = 20,
    ) -> FounderConsoleOverview:
        now = _aware(now)
        if not 1 <= attention_limit <= 50:
            raise ValueError("attention_limit must be between 1 and 50")
        week = completed_week(now, week_offset=week_offset)
        business = self._commercial.generate(week=week)
        health = self._operations.health(observed_at=now)
        readiness = self._operations.readiness(evaluated_at=now)
        attention = self._attention(limit=attention_limit)
        quality = self._quality(now=now, business=business)
        hermes = FounderAgentStatus(
            status=health.hermes_runtime,
            highest_safe_mode=readiness.highest_safe_mode,
            observed_at=health.observed_at,
            reason_codes=_hermes_reason_codes(health.reason_codes, readiness.blockers),
        )
        system = FounderSystemSummary(
            health=health,
            readiness=readiness,
            hermes=hermes,
        )
        today = FounderTodaySummary(
            generated_at=now,
            open_attention_count=len(attention),
            critical_attention_count=sum(
                item.severity == "CRITICAL" for item in attention
            ),
            positive_replies_last_completed_week=(
                business.funnel.positive_reply_count
            ),
            paid_accounts_last_completed_week=business.funnel.paid_account_count,
            business_period_start=business.week_start,
            business_period_end=business.week_end,
            system_status=health.status,
            hermes_status=health.hermes_runtime,
            highest_safe_mode=readiness.highest_safe_mode,
        )
        return FounderConsoleOverview(
            generated_at=now,
            today=today,
            attention=attention,
            business=business,
            quality=quality,
            system=system,
        )

    def _attention(self, *, limit: int) -> tuple[FounderAttentionItem, ...]:
        fetch_limit = min(100, max(limit * 4, limit))
        items: list[FounderAttentionItem] = []
        for row in self._operations.incidents(limit=fetch_limit):
            if str(row.get("state")) == "RESOLVED":
                continue
            items.append(_incident_attention(row))
        for row in self._operations.dead_letters(limit=fetch_limit):
            if str(row.get("status")) != "OPEN":
                continue
            items.append(_dead_letter_attention(row))
        items.sort(key=_attention_sort_key)
        return tuple(items[:limit])

    def _quality(
        self,
        *,
        now: dt.datetime,
        business: WeeklyCommercialCockpit,
    ) -> FounderQualitySummary:
        start = now - FOUNDER_QUALITY_WINDOW
        within_feedback = sa.and_(
            signal_feedback.c.updated_at >= start,
            signal_feedback.c.updated_at < now,
        )
        statement = sa.select(
            sa.func.count().filter(within_feedback).label("feedback_total"),
            sa.func.count()
            .filter(
                within_feedback,
                signal_feedback.c.relevance == "relevant",
            )
            .label("relevant_total"),
            sa.func.count()
            .filter(
                within_feedback,
                signal_feedback.c.relevance == "not_relevant",
            )
            .label("not_relevant_total"),
            sa.func.count()
            .filter(
                signal_feedback.c.contacted_at >= start,
                signal_feedback.c.contacted_at < now,
            )
            .label("contacted_total"),
        )
        reason_statement = (
            sa.select(
                signal_feedback.c.reason_code,
                sa.func.count().label("reason_count"),
            )
            .where(
                within_feedback,
                signal_feedback.c.relevance == "not_relevant",
                signal_feedback.c.reason_code.is_not(None),
            )
            .group_by(signal_feedback.c.reason_code)
            .order_by(sa.func.count().desc(), signal_feedback.c.reason_code)
        )
        with self._engine.connect() as connection:
            totals = connection.execute(statement).mappings().one()
            reasons = connection.execute(reason_statement).mappings().all()
        feedback_total = int(totals["feedback_total"] or 0)
        not_relevant_total = int(totals["not_relevant_total"] or 0)
        negative_rate = (
            int(
                (
                    Decimal(not_relevant_total)
                    / Decimal(feedback_total)
                    * Decimal(10_000)
                ).quantize(Decimal("1"))
            )
            if feedback_total
            else None
        )
        return FounderQualitySummary(
            window_start=start,
            window_end=now,
            feedback_updated_in_window_count=feedback_total,
            relevant_feedback_updated_in_window_count=int(
                totals["relevant_total"] or 0
            ),
            not_relevant_feedback_updated_in_window_count=not_relevant_total,
            contacted_in_window_count=int(totals["contacted_total"] or 0),
            negative_feedback_rate_bps=negative_rate,
            negative_reason_counts=tuple(
                FounderReasonCount(
                    reason_code=str(row["reason_code"]),
                    count=int(row["reason_count"] or 0),
                )
                for row in reasons
            ),
            unresolved_sector_count=business.data_quality.unresolved_sector_count,
            unknown_mrr_journey_count=(
                business.data_quality.unknown_mrr_journey_count
            ),
        )


def _incident_attention(row: Mapping[str, object]) -> FounderAttentionItem:
    severity = str(row.get("severity") or "WARNING")
    if severity not in {"WARNING", "HIGH", "CRITICAL"}:
        severity = "WARNING"
    return FounderAttentionItem(
        kind="INCIDENT",
        item_ref=str(row.get("incident_ref") or "incident-unavailable"),
        severity=severity,  # type: ignore[arg-type]
        status=str(row.get("state") or "UNKNOWN"),
        occurred_at=_row_time(row, "triggered_at"),
        title_code=str(row.get("incident_type") or "INCIDENT"),
        reason_codes=_string_tuple(row.get("reason_codes")),
        scope_type=str(row.get("scope_type") or "UNKNOWN"),
        scope_ref=str(row.get("scope_ref") or "unknown"),
        human_review_required=bool(row.get("human_review_required")),
        pause_required=bool(row.get("pause_required")),
    )


def _dead_letter_attention(row: Mapping[str, object]) -> FounderAttentionItem:
    return FounderAttentionItem(
        kind="DEAD_LETTER",
        item_ref=str(row.get("dead_letter_ref") or "dead-letter-unavailable"),
        severity="HIGH",
        status=str(row.get("status") or "UNKNOWN"),
        occurred_at=_row_time(row, "last_failed_at"),
        title_code=str(row.get("failure_code") or "DEAD_LETTER"),
        reason_codes=(str(row.get("failure_code") or "DEAD_LETTER"),),
        scope_type=str(row.get("scope_type") or "UNKNOWN"),
        scope_ref=str(row.get("scope_ref") or "unknown"),
        source_component=(
            str(row["source_component"])
            if row.get("source_component") is not None
            else None
        ),
        attempt_count=(
            int(row["attempt_count"])
            if row.get("attempt_count") is not None
            else None
        ),
        human_review_required=True,
        pause_required=False,
    )


def _attention_sort_key(item: FounderAttentionItem) -> tuple[int, float, str]:
    order = {"CRITICAL": 0, "HIGH": 1, "WARNING": 2}
    return (
        order[item.severity],
        -item.occurred_at.timestamp(),
        item.item_ref,
    )


def _row_time(row: Mapping[str, object], key: str) -> dt.datetime:
    value = row.get(key)
    if not isinstance(value, dt.datetime):
        raise TypeError(f"operational row is missing {key}")
    return _aware(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(sorted({str(item) for item in value if item is not None}))
    if value is None:
        return ()
    return (str(value),)


def _hermes_reason_codes(
    health_reasons: tuple[str, ...],
    readiness_blockers: tuple[str, ...],
) -> tuple[str, ...]:
    prefixes = ("HERMES", "RUNTIME", "SUPERVISOR", "QA_SHADOW")
    return tuple(
        sorted(
            {
                code
                for code in (*health_reasons, *readiness_blockers)
                if code.startswith(prefixes)
            }
        )
    )


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


__all__ = [
    "FOUNDER_OVERVIEW_VERSION",
    "FOUNDER_QUALITY_VERSION",
    "FOUNDER_QUALITY_WINDOW",
    "QUALITY_SEMANTICS",
    "FounderAgentStatus",
    "FounderAttentionItem",
    "FounderConsoleOverview",
    "FounderQualitySummary",
    "FounderReadService",
    "FounderReasonCount",
    "FounderSystemSummary",
    "FounderTodaySummary",
]
