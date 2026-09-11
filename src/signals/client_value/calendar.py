"""Calendrier commercial dérivé des seules dates publiées du contrat."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import TypedDict

DEFAULT_START_DELAY_MONTHS = 2


class CommercialCalendar(TypedDict, total=False):
    start_month: str
    duration_months: int
    source: str


def _add_months(value: dt.date, months: int) -> dt.date:
    """Ajoute des mois calendaires et ramène le résultat au premier du mois."""
    absolute_month = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(absolute_month, 12)
    return dt.date(year, zero_based_month + 1, 1)


def _delay_for_cpv(cpv_code: str | None, configured: Mapping[str, int]) -> int:
    normalized = "".join(character for character in (cpv_code or "") if character.isdigit())[:8]
    matches = [
        (prefix, months)
        for raw_prefix, months in configured.items()
        if (prefix := "".join(character for character in raw_prefix if character.isdigit()))
        and normalized.startswith(prefix)
        and months >= 0
    ]
    return max(matches, key=lambda item: len(item[0]))[1] if matches else DEFAULT_START_DELAY_MONTHS


def _duration_months(value: int | None, unit: str | None) -> int | None:
    if value is None or value <= 0:
        return None
    normalized = (unit or "").casefold()
    if normalized in {"month", "months"}:
        return value
    if normalized in {"year", "years"}:
        return value * 12
    return None


def commercial_calendar(
    *,
    notification_date: dt.date | None,
    cpv_code: str | None,
    duration_value: int | None,
    duration_unit: str | None,
    delay_months_by_cpv_prefix: Mapping[str, int] | None = None,
) -> CommercialCalendar | None:
    """Rend le calendrier probable, ou rien quand la notification manque."""
    if notification_date is None:
        return None
    start = _add_months(
        notification_date,
        _delay_for_cpv(cpv_code, delay_months_by_cpv_prefix or {}),
    )
    result: CommercialCalendar = {
        "start_month": start.strftime("%Y-%m"),
        "source": "public_notice",
    }
    months = _duration_months(duration_value, duration_unit)
    if months is not None:
        result["duration_months"] = months
    return result


__all__ = ["DEFAULT_START_DELAY_MONTHS", "CommercialCalendar", "commercial_calendar"]
