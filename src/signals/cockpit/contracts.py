"""Strict immutable contracts and calendar semantics for SPEC-030."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

REPORT_VERSION = "weekly-commercial-cockpit-v1"
COCKPIT_WEEK_VERSION = "cockpit-week-v1"
COCKPIT_TIMEZONE = "Europe/Zurich"
DELIVERY_SEMANTICS = "PROXY_SENT_MINUS_BOUNCE_V1"
MAXIMUM_WEEK_OFFSET = 51

StableRef = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[int, Field(ge=0)]
Rate = Annotated[Decimal, Field(ge=0)]


class CockpitContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class CockpitWeek(CockpitContract):
    version: Literal["cockpit-week-v1"] = COCKPIT_WEEK_VERSION
    timezone: Literal["Europe/Zurich"] = COCKPIT_TIMEZONE
    week_start: dt.datetime
    week_end: dt.datetime

    _times = field_validator("week_start", "week_end")(_aware)

    @model_validator(mode="after")
    def validate_bounds(self) -> CockpitWeek:
        if self.week_end <= self.week_start:
            raise ValueError("week end must follow week start")
        for value in (self.week_start, self.week_end):
            local = value.astimezone(ZoneInfo(COCKPIT_TIMEZONE))
            if local.weekday() != 0 or local.time() != dt.time(0):
                raise ValueError("cockpit week bounds must be local Monday midnight")
        return self


def completed_week(now: dt.datetime, *, week_offset: int = 0) -> CockpitWeek:
    """Resolve one of the latest 52 completed Zurich business weeks."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if week_offset < 0 or week_offset > MAXIMUM_WEEK_OFFSET:
        raise ValueError("week_offset must be between 0 and 51")
    zone = ZoneInfo(COCKPIT_TIMEZONE)
    local_now = now.astimezone(zone)
    current_start_date = local_now.date() - dt.timedelta(days=local_now.weekday())
    current_start = dt.datetime.combine(current_start_date, dt.time(0), tzinfo=zone)
    week_end = current_start - dt.timedelta(days=7 * week_offset)
    week_start = week_end - dt.timedelta(days=7)
    return CockpitWeek(week_start=week_start, week_end=week_end)


class MoneyTotal(CockpitContract):
    currency: Literal["CHF", "EUR"]
    minor_units: Count


class FunnelMetrics(CockpitContract):
    delivered_proxy_count: Count
    positive_reply_count: Count
    click_count: Count
    activated_account_count: Count
    paid_account_count: Count
    mrr_by_currency: tuple[MoneyTotal, ...] = Field(max_length=2)
    churn_count: Count

    @field_validator("mrr_by_currency")
    @classmethod
    def unique_sorted_money(cls, value: tuple[MoneyTotal, ...]) -> tuple[MoneyTotal, ...]:
        currencies = tuple(item.currency for item in value)
        if currencies != tuple(sorted(set(currencies))):
            raise ValueError("money totals must have unique sorted currencies")
        return value


class AnalyticalRow(CockpitContract):
    country: Literal["CH", "FR"]
    sector_ref: StableRef
    need_ref: StableRef
    campaign_ref: StableRef
    delivered_proxy_count: Count
    positive_reply_count: Count
    click_count: Count
    activated_account_count: Count
    paid_account_count: Count
    mrr_by_currency: tuple[MoneyTotal, ...] = Field(max_length=2)
    churn_count: Count
    positive_reply_rate: Rate | None
    click_rate: Rate | None
    activation_rate: Rate | None
    paid_rate: Rate | None

    _money = field_validator("mrr_by_currency")(FunnelMetrics.unique_sorted_money.__func__)


class WedgeM2Efficiency(CockpitContract):
    wedge: StableRef
    currency: Literal["CHF", "EUR"] | None
    m2_eligible_delivered_proxy_count: Count
    retained_m2_accounts: Count
    retained_m2_mrr_minor_units: Count | None
    retained_m2_mrr_per_1000_delivered: Rate | None
    data_status: Literal["READY", "INSUFFICIENT_M2_EVIDENCE"]

    @model_validator(mode="after")
    def validate_status(self) -> WedgeM2Efficiency:
        complete = (
            self.currency is not None
            and self.m2_eligible_delivered_proxy_count > 0
            and self.retained_m2_mrr_minor_units is not None
            and self.retained_m2_mrr_per_1000_delivered is not None
        )
        if (self.data_status == "READY") != complete:
            raise ValueError("M2 data status does not match its bounded evidence")
        return self


class CockpitDataQuality(CockpitContract):
    delivery_is_proxy: Literal[True] = True
    unresolved_sector_count: Count
    unknown_mrr_journey_count: Count
    matching_disagreement: Count = 0
    m2_insufficient_wedges: tuple[StableRef, ...]
    captured_at: dt.datetime

    _captured = field_validator("captured_at")(_aware)

    @field_validator("m2_insufficient_wedges")
    @classmethod
    def sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("insufficient wedges must be unique and sorted")
        return value


class WeeklyCommercialCockpit(CockpitContract):
    report_version: Literal["weekly-commercial-cockpit-v1"] = REPORT_VERSION
    report_ref: Fingerprint
    week_start: dt.datetime
    week_end: dt.datetime
    captured_at: dt.datetime
    timezone: Literal["Europe/Zurich"] = COCKPIT_TIMEZONE
    delivery_semantics: Literal["PROXY_SENT_MINUS_BOUNCE_V1"] = DELIVERY_SEMANTICS
    funnel: FunnelMetrics
    analytical_rows: tuple[AnalyticalRow, ...]
    wedge_m2_efficiency: tuple[WedgeM2Efficiency, ...]
    data_quality: CockpitDataQuality

    _times = field_validator("week_start", "week_end", "captured_at")(_aware)

    @model_validator(mode="after")
    def validate_cutoff(self) -> WeeklyCommercialCockpit:
        CockpitWeek(week_start=self.week_start, week_end=self.week_end)
        if self.captured_at != self.week_end or self.data_quality.captured_at != self.week_end:
            raise ValueError("completed report capture must equal its exclusive cutoff")
        row_keys = tuple(
            (row.country, row.sector_ref, row.need_ref, row.campaign_ref)
            for row in self.analytical_rows
        )
        if row_keys != tuple(sorted(set(row_keys))):
            raise ValueError("analytical rows must be uniquely and stably sorted")
        wedge_keys = tuple((row.wedge, row.currency or "") for row in self.wedge_m2_efficiency)
        if wedge_keys != tuple(sorted(set(wedge_keys))):
            raise ValueError("wedge rows must be uniquely and stably sorted")
        return self


__all__ = [
    "COCKPIT_TIMEZONE",
    "COCKPIT_WEEK_VERSION",
    "DELIVERY_SEMANTICS",
    "MAXIMUM_WEEK_OFFSET",
    "REPORT_VERSION",
    "AnalyticalRow",
    "CockpitDataQuality",
    "CockpitWeek",
    "FunnelMetrics",
    "MoneyTotal",
    "WedgeM2Efficiency",
    "WeeklyCommercialCockpit",
    "completed_week",
]
