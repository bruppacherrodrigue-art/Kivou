from __future__ import annotations

import datetime as dt

from signals.client_value.calendar import commercial_calendar


def test_notification_uses_the_default_two_month_delay() -> None:
    assert commercial_calendar(
        notification_date=dt.date(2026, 11, 30),
        cpv_code="45233120",
        duration_value=18,
        duration_unit="month",
    ) == {
        "start_month": "2027-01",
        "duration_months": 18,
        "source": "public_notice",
    }


def test_the_longest_configured_cpv_prefix_wins() -> None:
    assert commercial_calendar(
        notification_date=dt.date(2026, 8, 31),
        cpv_code="45233120-6",
        duration_value=2,
        duration_unit="year",
        delay_months_by_cpv_prefix={"45": 3, "452331": 5},
    ) == {
        "start_month": "2027-01",
        "duration_months": 24,
        "source": "public_notice",
    }


def test_an_unconvertible_or_missing_duration_is_omitted() -> None:
    assert commercial_calendar(
        notification_date=dt.date(2026, 9, 10),
        cpv_code=None,
        duration_value=45,
        duration_unit="day",
    ) == {"start_month": "2026-11", "source": "public_notice"}


def test_calendar_is_absent_without_notification_date() -> None:
    assert commercial_calendar(
        notification_date=None,
        cpv_code="45233120",
        duration_value=12,
        duration_unit="month",
    ) is None
