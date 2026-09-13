"""Shared Europe/Zurich day boundaries for assisted prospection."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

PROSPECTION_TIMEZONE = "Europe/Zurich"
_ZONE = ZoneInfo(PROSPECTION_TIMEZONE)


def prospection_day_bounds(value: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("prospection clock must be timezone-aware")
    local_start = dt.datetime.combine(
        value.astimezone(_ZONE).date(),
        dt.time(),
        tzinfo=_ZONE,
    )
    return (
        local_start.astimezone(dt.UTC),
        (local_start + dt.timedelta(days=1)).astimezone(dt.UTC),
    )


def prospection_day(value: dt.datetime) -> dt.date:
    return prospection_day_bounds(value)[0].astimezone(_ZONE).date()


__all__ = ["PROSPECTION_TIMEZONE", "prospection_day", "prospection_day_bounds"]
