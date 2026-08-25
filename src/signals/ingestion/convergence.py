from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Mapping
from typing import Any

from signals.ingestion.sources import SourceWindow

DECP_CYCLE_CURSOR_VERSION = 1


@dataclasses.dataclass(frozen=True)
class DecpCycleCursor:
    cycle_end: dt.date
    next_window_start: dt.date

    def __post_init__(self) -> None:
        if self.next_window_start > self.cycle_end + dt.timedelta(days=1):
            raise ValueError("DECP cursor advanced beyond its cycle")

    @property
    def complete(self) -> bool:
        return self.next_window_start > self.cycle_end

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": DECP_CYCLE_CURSOR_VERSION,
            "cycle_end": self.cycle_end.isoformat(),
            "next_window_start": self.next_window_start.isoformat(),
        }


def _stored_decp_cursor(value: Mapping[str, Any] | None) -> DecpCycleCursor | None:
    if value is None or "version" not in value:
        return None
    if value.get("version") != DECP_CYCLE_CURSOR_VERSION:
        raise ValueError("unsupported DECP convergence cursor version")
    try:
        cycle_end = dt.date.fromisoformat(str(value["cycle_end"]))
        next_window_start = dt.date.fromisoformat(str(value["next_window_start"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid DECP convergence cursor") from error
    return DecpCycleCursor(
        cycle_end=cycle_end,
        next_window_start=next_window_start,
    )


def plan_decp_cycle(
    *,
    cursor: Mapping[str, Any] | None,
    checkpoint_end: dt.datetime | None,
    until: dt.datetime,
    overlap_days: int,
    explicit_since: dt.date | None = None,
) -> DecpCycleCursor:
    if overlap_days < 1:
        raise ValueError("DECP overlap must be positive")
    cycle_end = until.date()
    stored = _stored_decp_cursor(cursor)
    if stored is not None and (not stored.complete or cycle_end <= stored.cycle_end):
        return stored

    if explicit_since is not None:
        next_window_start = explicit_since
    elif checkpoint_end is not None:
        next_window_start = checkpoint_end.date() - dt.timedelta(days=overlap_days)
    else:
        next_window_start = cycle_end - dt.timedelta(days=overlap_days)
    if next_window_start > cycle_end:
        raise ValueError("DECP cycle starts after its end")
    return DecpCycleCursor(
        cycle_end=cycle_end,
        next_window_start=next_window_start,
    )


def next_decp_window(cursor: DecpCycleCursor) -> SourceWindow | None:
    if cursor.complete:
        return None
    return SourceWindow(since=cursor.next_window_start, until=cursor.next_window_start)


def advance_decp_cycle(
    cursor: DecpCycleCursor,
    completed_window: SourceWindow,
) -> DecpCycleCursor:
    if completed_window.since != completed_window.until:
        raise ValueError("DECP convergence units must be one calendar day")
    if completed_window.since != cursor.next_window_start:
        raise ValueError("DECP convergence window does not match its cursor")
    return dataclasses.replace(
        cursor,
        next_window_start=cursor.next_window_start + dt.timedelta(days=1),
    )


def decp_checkpoint_high_water(
    *,
    previous: dt.datetime | None,
    completed_window: SourceWindow,
    requested_until: dt.datetime,
) -> dt.datetime:
    if completed_window.until > requested_until.date():
        raise ValueError("completed DECP window exceeds the requested end")
    candidate = (
        requested_until
        if completed_window.until == requested_until.date()
        else dt.datetime.combine(completed_window.until, dt.time.min, tzinfo=dt.UTC)
    )
    if previous is None:
        return candidate
    normalized = previous if previous.tzinfo else previous.replace(tzinfo=dt.UTC)
    return max(normalized, candidate)
