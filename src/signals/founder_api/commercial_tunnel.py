"""Read-only period, cohort, and current commercial tunnel projections."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from pydantic import Field, field_validator, model_validator
from sqlalchemy.engine import Connection, Engine

from signals.accounts.schema import account_landing_signal
from signals.cockpit.contracts import completed_week
from signals.founder_api.contracts import FounderContract
from signals.persistence.schema import (
    acquisition_campaign_member,
    acquisition_conversion_event,
    acquisition_conversion_journey,
    acquisition_provider_event,
    prospect_delivery_event,
    prospect_target,
)

_ZURICH = ZoneInfo("Europe/Zurich")
_CURRENT_TRANSITIONS = ("PAID", "CHURNED")


def _aware_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(dt.UTC)


class FounderTunnelPeriod(StrEnum):
    TODAY = "today"
    LAST_7_DAYS = "last_7_days"


class FounderMoneyTotal(FounderContract):
    currency: Literal["CHF", "EUR"]
    minor_units: int = Field(ge=0)


class FounderTunnelCounts(FounderContract):
    sent_count: int = Field(ge=0)
    opened_count: int = Field(ge=0)
    click_count: int = Field(ge=0)
    landing_count: int = Field(ge=0)
    confirmed_profile_count: int = Field(ge=0)
    paid_count: int = Field(ge=0)


class FounderTunnelSlice(FounderTunnelCounts):
    start_at: dt.datetime
    end_at: dt.datetime

    _times = field_validator("start_at", "end_at")(_aware_utc)

    @model_validator(mode="after")
    def validate_bounds(self) -> FounderTunnelSlice:
        if self.end_at < self.start_at:
            raise ValueError("tunnel end must not precede its start")
        return self


class FounderTunnelCurrent(FounderContract):
    observed_at: dt.datetime
    mrr_by_currency: tuple[FounderMoneyTotal, ...] = Field(max_length=2)
    churn_count: int = Field(ge=0)

    _observed_at = field_validator("observed_at")(_aware_utc)

    @field_validator("mrr_by_currency")
    @classmethod
    def unique_sorted_money(
        cls, value: tuple[FounderMoneyTotal, ...]
    ) -> tuple[FounderMoneyTotal, ...]:
        currencies = tuple(item.currency for item in value)
        if currencies != tuple(sorted(set(currencies))):
            raise ValueError("money totals must have unique sorted currencies")
        return value


class FounderCommercialTunnel(FounderContract):
    period_kind: FounderTunnelPeriod
    period: FounderTunnelSlice
    cohort_week_offset: int = Field(ge=0, le=51)
    cohort: FounderTunnelSlice
    current: FounderTunnelCurrent


@dataclass(frozen=True)
class _TunnelBounds:
    start: dt.datetime
    end: dt.datetime


def period_bounds(
    now: dt.datetime,
    period: FounderTunnelPeriod,
) -> _TunnelBounds:
    """Resolve an inclusive observation window from local Zurich midnight."""

    observed_at = _aware_utc(now)
    period = FounderTunnelPeriod(period)
    local_date = observed_at.astimezone(_ZURICH).date()
    if period is FounderTunnelPeriod.LAST_7_DAYS:
        local_date -= dt.timedelta(days=6)
    local_start = dt.datetime.combine(local_date, dt.time.min, tzinfo=_ZURICH)
    return _TunnelBounds(start=local_start.astimezone(dt.UTC), end=observed_at)


class FounderCommercialTunnelReadService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def read(
        self,
        *,
        now: dt.datetime,
        period: FounderTunnelPeriod,
        week_offset: int,
    ) -> FounderCommercialTunnel:
        observed_at = _aware_utc(now)
        period = FounderTunnelPeriod(period)
        bounds = period_bounds(observed_at, period)
        week = completed_week(observed_at, week_offset=week_offset)
        cohort_bounds = _TunnelBounds(
            start=week.week_start.astimezone(dt.UTC),
            end=week.week_end.astimezone(dt.UTC),
        )
        with self._engine.connect() as connection:
            period_counts = _period_counts(connection, bounds=bounds)
            cohort_counts = _cohort_counts(
                connection,
                bounds=cohort_bounds,
                observed_at=observed_at,
            )
            current = _current(connection, observed_at=observed_at)
        return FounderCommercialTunnel(
            period_kind=period,
            period=FounderTunnelSlice(
                start_at=bounds.start,
                end_at=bounds.end,
                **period_counts,
            ),
            cohort_week_offset=week_offset,
            cohort=FounderTunnelSlice(
                start_at=cohort_bounds.start,
                end_at=cohort_bounds.end,
                **cohort_counts,
            ),
            current=current,
        )


def _period_counts(
    connection: Connection,
    *,
    bounds: _TunnelBounds,
) -> dict[str, int]:
    return {
        "sent_count": (
            _distinct_between(
                connection,
                acquisition_campaign_member.c.member_ref,
                acquisition_campaign_member.c.step_1_sent_at,
                bounds,
            )
            + _distinct_between(
                connection,
                prospect_target.c.target_id,
                prospect_target.c.sent_at,
                bounds,
            )
        ),
        "opened_count": (
            _distinct_between(
                connection,
                acquisition_provider_event.c.member_ref,
                acquisition_provider_event.c.occurred_at,
                bounds,
                acquisition_provider_event.c.provider_event_type == "email_opened",
                acquisition_provider_event.c.resolution_state.in_(("ACCEPTED", "PROCESSED")),
            )
            + _distinct_between(
                connection,
                prospect_delivery_event.c.target_id,
                prospect_delivery_event.c.occurred_at,
                bounds,
                prospect_delivery_event.c.provider_event_type == "email_opened",
            )
        ),
        "click_count": _distinct_between(
            connection,
            acquisition_conversion_event.c.conversion_event_ref,
            acquisition_conversion_event.c.occurred_at,
            bounds,
            acquisition_conversion_event.c.milestone == "CLICK",
        ),
        "landing_count": _distinct_between(
            connection,
            account_landing_signal.c.account_id,
            account_landing_signal.c.created_at,
            bounds,
            account_landing_signal.c.qa.is_(False),
        ),
        "confirmed_profile_count": _distinct_between(
            connection,
            account_landing_signal.c.account_id,
            account_landing_signal.c.profile_confirmed_at,
            bounds,
            account_landing_signal.c.qa.is_(False),
        ),
        "paid_count": _distinct_between(
            connection,
            acquisition_conversion_event.c.account_id,
            acquisition_conversion_event.c.occurred_at,
            bounds,
            acquisition_conversion_event.c.milestone == "PAID",
            acquisition_conversion_event.c.account_id.is_not(None),
        ),
    }


def _cohort_counts(
    connection: Connection,
    *,
    bounds: _TunnelBounds,
    observed_at: dt.datetime,
) -> dict[str, int]:
    cohort = (
        sa.select(
            acquisition_campaign_member.c.member_ref.label("member_ref"),
            acquisition_campaign_member.c.step_1_sent_at.label("sent_at"),
        )
        .where(
            acquisition_campaign_member.c.step_1_sent_at >= bounds.start,
            acquisition_campaign_member.c.step_1_sent_at < bounds.end,
        )
        .subquery("founder_tunnel_cohort")
    )
    sent_count = _count(
        connection,
        sa.select(sa.func.count(sa.distinct(cohort.c.member_ref))).select_from(cohort),
    )
    opened_count = _count(
        connection,
        sa.select(sa.func.count(sa.distinct(acquisition_provider_event.c.member_ref)))
        .select_from(
            cohort.join(
                acquisition_provider_event,
                acquisition_provider_event.c.member_ref == cohort.c.member_ref,
            )
        )
        .where(
            acquisition_provider_event.c.provider_event_type == "email_opened",
            acquisition_provider_event.c.resolution_state.in_(("ACCEPTED", "PROCESSED")),
            acquisition_provider_event.c.occurred_at >= cohort.c.sent_at,
            acquisition_provider_event.c.occurred_at <= observed_at,
        ),
    )
    click_count = _count(
        connection,
        sa.select(sa.func.count(sa.distinct(acquisition_conversion_event.c.conversion_event_ref)))
        .select_from(
            cohort.join(
                acquisition_conversion_event,
                acquisition_conversion_event.c.member_ref == cohort.c.member_ref,
            )
        )
        .where(
            acquisition_conversion_event.c.milestone == "CLICK",
            acquisition_conversion_event.c.occurred_at >= cohort.c.sent_at,
            acquisition_conversion_event.c.occurred_at <= observed_at,
        ),
    )
    cohort_journeys = cohort.join(
        acquisition_conversion_journey,
        acquisition_conversion_journey.c.member_ref == cohort.c.member_ref,
    )
    landing_count = _cohort_account_count(
        connection,
        cohort_journeys=cohort_journeys,
        cohort=cohort,
        timestamp=account_landing_signal.c.created_at,
        observed_at=observed_at,
    )
    confirmed_profile_count = _cohort_account_count(
        connection,
        cohort_journeys=cohort_journeys,
        cohort=cohort,
        timestamp=account_landing_signal.c.profile_confirmed_at,
        observed_at=observed_at,
    )
    paid_count = _count(
        connection,
        sa.select(sa.func.count(sa.distinct(acquisition_conversion_journey.c.account_id)))
        .select_from(
            cohort_journeys.join(
                acquisition_conversion_event,
                acquisition_conversion_event.c.journey_ref
                == acquisition_conversion_journey.c.journey_ref,
            )
        )
        .where(
            acquisition_conversion_event.c.milestone == "PAID",
            acquisition_conversion_event.c.occurred_at >= cohort.c.sent_at,
            acquisition_conversion_event.c.occurred_at <= observed_at,
        ),
    )
    assisted = _assisted_cohort_counts(
        connection,
        bounds=bounds,
        observed_at=observed_at,
    )
    return {
        "sent_count": sent_count + assisted["sent_count"],
        "opened_count": opened_count + assisted["opened_count"],
        "click_count": click_count + assisted["click_count"],
        "landing_count": landing_count + assisted["landing_count"],
        "confirmed_profile_count": (
            confirmed_profile_count + assisted["confirmed_profile_count"]
        ),
        "paid_count": paid_count + assisted["paid_count"],
    }


def _assisted_cohort_counts(
    connection: Connection,
    *,
    bounds: _TunnelBounds,
    observed_at: dt.datetime,
) -> dict[str, int]:
    cohort = (
        sa.select(
            prospect_target.c.target_id.label("target_id"),
            prospect_target.c.sent_at.label("sent_at"),
        )
        .where(
            prospect_target.c.sent_at >= bounds.start,
            prospect_target.c.sent_at < bounds.end,
        )
        .subquery("founder_tunnel_assisted_cohort")
    )
    sent_count = _count(
        connection,
        sa.select(sa.func.count(sa.distinct(cohort.c.target_id))).select_from(cohort),
    )
    opened_count = _count(
        connection,
        sa.select(sa.func.count(sa.distinct(prospect_delivery_event.c.target_id)))
        .select_from(
            cohort.join(
                prospect_delivery_event,
                prospect_delivery_event.c.target_id == cohort.c.target_id,
            )
        )
        .where(
            prospect_delivery_event.c.provider_event_type == "email_opened",
            prospect_delivery_event.c.occurred_at >= cohort.c.sent_at,
            prospect_delivery_event.c.occurred_at <= observed_at,
        ),
    )
    click_count = _count(
        connection,
        sa.select(sa.func.count(sa.distinct(acquisition_conversion_event.c.conversion_event_ref)))
        .select_from(
            cohort.join(
                acquisition_conversion_event,
                acquisition_conversion_event.c.prospect_target_id == cohort.c.target_id,
            )
        )
        .where(
            acquisition_conversion_event.c.milestone == "CLICK",
            acquisition_conversion_event.c.occurred_at >= cohort.c.sent_at,
            acquisition_conversion_event.c.occurred_at <= observed_at,
        ),
    )
    cohort_journeys = cohort.join(
        acquisition_conversion_journey,
        acquisition_conversion_journey.c.prospect_target_id == cohort.c.target_id,
    )
    landing_count = _cohort_account_count(
        connection,
        cohort_journeys=cohort_journeys,
        cohort=cohort,
        timestamp=account_landing_signal.c.created_at,
        observed_at=observed_at,
    )
    confirmed_profile_count = _cohort_account_count(
        connection,
        cohort_journeys=cohort_journeys,
        cohort=cohort,
        timestamp=account_landing_signal.c.profile_confirmed_at,
        observed_at=observed_at,
    )
    paid_count = _count(
        connection,
        sa.select(sa.func.count(sa.distinct(acquisition_conversion_journey.c.account_id)))
        .select_from(
            cohort_journeys.join(
                acquisition_conversion_event,
                acquisition_conversion_event.c.journey_ref
                == acquisition_conversion_journey.c.journey_ref,
            )
        )
        .where(
            acquisition_conversion_event.c.milestone == "PAID",
            acquisition_conversion_event.c.occurred_at >= cohort.c.sent_at,
            acquisition_conversion_event.c.occurred_at <= observed_at,
        ),
    )
    return {
        "sent_count": sent_count,
        "opened_count": opened_count,
        "click_count": click_count,
        "landing_count": landing_count,
        "confirmed_profile_count": confirmed_profile_count,
        "paid_count": paid_count,
    }


def _cohort_account_count(
    connection: Connection,
    *,
    cohort_journeys: sa.FromClause,
    cohort: sa.Subquery,
    timestamp: sa.Column,
    observed_at: dt.datetime,
) -> int:
    return _count(
        connection,
        sa.select(sa.func.count(sa.distinct(account_landing_signal.c.account_id)))
        .select_from(
            cohort_journeys.join(
                account_landing_signal,
                account_landing_signal.c.account_id == acquisition_conversion_journey.c.account_id,
            )
        )
        .where(
            account_landing_signal.c.qa.is_(False),
            timestamp >= cohort.c.sent_at,
            timestamp <= observed_at,
        ),
    )


def _current(
    connection: Connection,
    *,
    observed_at: dt.datetime,
) -> FounderTunnelCurrent:
    rows = tuple(
        connection.execute(_current_projection_statement(observed_at=observed_at)).mappings()
    )
    totals: Counter[str] = Counter()
    churn_count = sum(row["current_milestone"] == "CHURNED" for row in rows)
    for row in rows:
        if row["current_milestone"] != "PAID" or row["mrr_known"] is not True:
            continue
        currency = str(row["currency"] or "").upper()
        if row["mrr_minor_units"] is None or currency not in {"CHF", "EUR"}:
            continue
        totals[currency] += int(row["mrr_minor_units"])
    return FounderTunnelCurrent(
        observed_at=observed_at,
        mrr_by_currency=tuple(
            FounderMoneyTotal(currency=currency, minor_units=totals[currency])
            for currency in sorted(totals)
        ),
        churn_count=churn_count,
    )


def _current_projection_statement(
    *,
    observed_at: dt.datetime,
) -> sa.Select[tuple[object, ...]]:
    events = acquisition_conversion_event
    transition_ranked = (
        sa.select(
            events.c.journey_ref,
            events.c.milestone,
            events.c.occurred_at,
            sa.func.row_number()
            .over(
                partition_by=events.c.journey_ref,
                order_by=(
                    events.c.occurred_at.desc(),
                    events.c.observed_at.desc(),
                    events.c.recorded_at.desc(),
                    sa.case((events.c.milestone == "CHURNED", 1), else_=0).desc(),
                    events.c.conversion_event_ref.desc(),
                ),
            )
            .label("transition_rank"),
        )
        .where(
            events.c.journey_ref.is_not(None),
            events.c.milestone.in_(_CURRENT_TRANSITIONS),
            events.c.occurred_at <= observed_at,
        )
        .cte("founder_current_transition_ranked")
    )
    current_transition = (
        sa.select(
            transition_ranked.c.journey_ref,
            transition_ranked.c.milestone,
            transition_ranked.c.occurred_at,
        )
        .where(transition_ranked.c.transition_rank == 1)
        .cte("founder_current_transition")
    )
    mrr_ranked = (
        sa.select(
            events.c.journey_ref,
            events.c.mrr_known,
            events.c.mrr_minor_units,
            events.c.currency,
            sa.func.row_number()
            .over(
                partition_by=events.c.journey_ref,
                order_by=(
                    events.c.occurred_at.desc(),
                    events.c.observed_at.desc(),
                    events.c.recorded_at.desc(),
                    events.c.conversion_event_ref.desc(),
                ),
            )
            .label("mrr_rank"),
        )
        .select_from(
            events.join(
                current_transition,
                events.c.journey_ref == current_transition.c.journey_ref,
            )
        )
        .where(
            current_transition.c.milestone == "PAID",
            events.c.milestone == "MRR_CHANGED",
            events.c.mrr_known.is_(True),
            events.c.mrr_minor_units.is_not(None),
            events.c.currency.is_not(None),
            events.c.occurred_at <= observed_at,
            events.c.occurred_at >= current_transition.c.occurred_at,
        )
        .cte("founder_current_mrr_ranked")
    )
    current_mrr = (
        sa.select(
            mrr_ranked.c.journey_ref,
            mrr_ranked.c.mrr_known,
            mrr_ranked.c.mrr_minor_units,
            mrr_ranked.c.currency,
        )
        .where(mrr_ranked.c.mrr_rank == 1)
        .cte("founder_current_mrr")
    )
    return sa.select(
        current_transition.c.journey_ref,
        current_transition.c.milestone.label("current_milestone"),
        current_mrr.c.mrr_known,
        current_mrr.c.mrr_minor_units,
        current_mrr.c.currency,
    ).select_from(
        current_transition.outerjoin(
            current_mrr,
            current_mrr.c.journey_ref == current_transition.c.journey_ref,
        )
    )


def _distinct_between(
    connection: Connection,
    identity: sa.Column,
    timestamp: sa.Column,
    bounds: _TunnelBounds,
    *conditions: sa.ColumnElement[bool],
) -> int:
    return _count(
        connection,
        sa.select(sa.func.count(sa.distinct(identity))).where(
            timestamp >= bounds.start,
            timestamp <= bounds.end,
            *conditions,
        ),
    )


def _count(connection: Connection, statement: sa.Select[tuple[int]]) -> int:
    return int(connection.scalar(statement) or 0)


__all__ = [
    "FounderCommercialTunnel",
    "FounderCommercialTunnelReadService",
    "FounderMoneyTotal",
    "FounderTunnelCounts",
    "FounderTunnelCurrent",
    "FounderTunnelPeriod",
    "FounderTunnelSlice",
    "period_bounds",
]
