from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Mapping
from typing import Any

from signals.ingestion.sources import SourceWindow

DECP_CYCLE_CURSOR_VERSION = 2
DECP_LEGACY_CYCLE_CURSOR_VERSION = 1


@dataclasses.dataclass(frozen=True)
class DecpCycleCursor:
    cycle_end: dt.date
    next_window_start: dt.date
    offset: int = 0
    window_total: int | None = None

    def __post_init__(self) -> None:
        if self.next_window_start > self.cycle_end + dt.timedelta(days=1):
            raise ValueError("DECP cursor advanced beyond its cycle")
        if not isinstance(self.offset, int) or isinstance(self.offset, bool) or self.offset < 0:
            raise ValueError("DECP cursor offset must be non-negative")
        if self.window_total is not None and (
            not isinstance(self.window_total, int)
            or isinstance(self.window_total, bool)
            or self.window_total < 0
        ):
            raise ValueError("DECP cursor window total must be non-negative")
        if self.offset and self.window_total is None:
            raise ValueError("DECP cursor offset requires a window total")
        if self.window_total is not None and self.offset > self.window_total:
            raise ValueError("DECP cursor offset exceeds its window total")
        if self.complete and (self.offset != 0 or self.window_total is not None):
            raise ValueError("completed DECP cursor cannot retain intra-day progress")

    @property
    def complete(self) -> bool:
        return self.next_window_start > self.cycle_end

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": DECP_CYCLE_CURSOR_VERSION,
            "cycle_end": self.cycle_end.isoformat(),
            "next_window_start": self.next_window_start.isoformat(),
            "offset": self.offset,
            "window_total": self.window_total,
        }


def _stored_decp_cursor(value: Mapping[str, Any] | None) -> DecpCycleCursor | None:
    if value is None or "version" not in value:
        return None
    version = value.get("version")
    if version not in {DECP_LEGACY_CYCLE_CURSOR_VERSION, DECP_CYCLE_CURSOR_VERSION}:
        raise ValueError("unsupported DECP convergence cursor version")
    try:
        cycle_end = dt.date.fromisoformat(str(value["cycle_end"]))
        next_window_start = dt.date.fromisoformat(str(value["next_window_start"]))
        offset = 0 if version == DECP_LEGACY_CYCLE_CURSOR_VERSION else value["offset"]
        window_total = (
            None if version == DECP_LEGACY_CYCLE_CURSOR_VERSION else value["window_total"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid DECP convergence cursor") from error
    try:
        return DecpCycleCursor(
            cycle_end=cycle_end,
            next_window_start=next_window_start,
            offset=offset,
            window_total=window_total,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("invalid DECP convergence cursor") from error


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
        offset=0,
        window_total=None,
    )


def advance_decp_batch(
    cursor: DecpCycleCursor,
    completed_window: SourceWindow,
    *,
    next_offset: int,
    window_total: int,
    day_complete: bool,
) -> DecpCycleCursor:
    if completed_window.since != completed_window.until:
        raise ValueError("DECP convergence units must stay inside one calendar day")
    if completed_window.since != cursor.next_window_start:
        raise ValueError("DECP convergence batch does not match its cursor")
    if not isinstance(next_offset, int) or isinstance(next_offset, bool) or next_offset < 0:
        raise ValueError("DECP next offset must be non-negative")
    if (
        not isinstance(window_total, int)
        or isinstance(window_total, bool)
        or window_total < 0
    ):
        raise ValueError("DECP window total must be non-negative")
    if next_offset > window_total:
        raise ValueError("DECP next offset exceeds its window total")
    if day_complete:
        if next_offset != window_total:
            raise ValueError("complete DECP day must exhaust its window total")
        return advance_decp_cycle(cursor, completed_window)
    if next_offset == 0 or next_offset == window_total:
        raise ValueError("partial DECP day must retain positive remaining progress")
    if cursor.window_total == window_total and next_offset <= cursor.offset:
        raise ValueError("DECP batch did not advance its cursor")
    return dataclasses.replace(
        cursor,
        offset=next_offset,
        window_total=window_total,
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
