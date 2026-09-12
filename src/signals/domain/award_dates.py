"""The single acquisition/customer date: award, then contract notification."""

from __future__ import annotations

import datetime as dt
from typing import Protocol


class DatedAward(Protocol):
    award_date: dt.date | None
    contract_notification_date: dt.date | None


def attribution_date(award: DatedAward) -> dt.date | None:
    return award.award_date or award.contract_notification_date


__all__ = ["attribution_date"]
