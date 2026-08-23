from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from signals.cockpit.contracts import (
    COCKPIT_TIMEZONE,
    COCKPIT_WEEK_VERSION,
    DELIVERY_SEMANTICS,
    REPORT_VERSION,
    AnalyticalRow,
    CockpitDataQuality,
    FunnelMetrics,
    MoneyTotal,
    WedgeM2Efficiency,
    WeeklyCommercialCockpit,
    completed_week,
)


def test_completed_week_is_monday_bounded_dst_aware_and_offset_is_bounded() -> None:
    now = dt.datetime(2026, 3, 30, 10, tzinfo=dt.UTC)

    latest = completed_week(now, week_offset=0)
    previous = completed_week(now, week_offset=1)

    assert latest.version == COCKPIT_WEEK_VERSION
    assert latest.timezone == COCKPIT_TIMEZONE
    assert latest.week_start == dt.datetime.fromisoformat("2026-03-23T00:00:00+01:00")
    assert latest.week_end == dt.datetime.fromisoformat("2026-03-30T00:00:00+02:00")
    assert previous.week_start == dt.datetime.fromisoformat("2026-03-16T00:00:00+01:00")
    with pytest.raises(ValueError):
        completed_week(now, week_offset=52)
    with pytest.raises(ValueError):
        completed_week(now.replace(tzinfo=None), week_offset=0)


def test_report_contract_is_strict_immutable_decimal_and_currency_separated() -> None:
    week = completed_week(dt.datetime(2026, 8, 19, 10, tzinfo=dt.UTC), week_offset=0)
    report = WeeklyCommercialCockpit(
        report_ref="a" * 64,
        week_start=week.week_start,
        week_end=week.week_end,
        captured_at=week.week_end,
        funnel=FunnelMetrics(
            delivered_proxy_count=1,
            positive_reply_count=1,
            click_count=1,
            activated_account_count=2,
            paid_account_count=2,
            mrr_by_currency=(MoneyTotal(currency="CHF", minor_units=9900),),
            churn_count=0,
        ),
        analytical_rows=(
            AnalyticalRow(
                country="CH",
                sector_ref="sector",
                need_ref="need",
                campaign_ref="campaign",
                delivered_proxy_count=1,
                positive_reply_count=1,
                click_count=1,
                activated_account_count=2,
                paid_account_count=2,
                mrr_by_currency=(MoneyTotal(currency="CHF", minor_units=9900),),
                churn_count=0,
                positive_reply_rate=Decimal("1"),
                click_rate=Decimal("1"),
                activation_rate=Decimal("2"),
                paid_rate=Decimal("2"),
            ),
        ),
        wedge_m2_efficiency=(
            WedgeM2Efficiency(
                wedge="construction",
                currency="CHF",
                m2_eligible_delivered_proxy_count=1,
                retained_m2_accounts=1,
                retained_m2_mrr_minor_units=9900,
                retained_m2_mrr_per_1000_delivered=Decimal("9900000"),
                data_status="READY",
            ),
        ),
        data_quality=CockpitDataQuality(
            unresolved_sector_count=0,
            unknown_mrr_journey_count=0,
            m2_insufficient_wedges=(),
            captured_at=week.week_end,
        ),
    )

    assert report.report_version == REPORT_VERSION
    assert report.timezone == COCKPIT_TIMEZONE
    assert report.delivery_semantics == DELIVERY_SEMANTICS
    assert report.funnel.activated_account_count > report.funnel.delivered_proxy_count
    assert report.funnel.mrr_by_currency[0].minor_units == 9900
    with pytest.raises(ValidationError):
        report.model_copy(update={"unknown": "field"}, deep=True).model_validate(
            {**report.model_dump(), "unknown": "field"}
        )
    with pytest.raises(ValidationError):
        MoneyTotal(currency="USD", minor_units=1)
