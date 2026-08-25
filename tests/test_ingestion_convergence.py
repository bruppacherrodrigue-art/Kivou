from __future__ import annotations

import datetime as dt

from signals.ingestion.convergence import (
    DecpCycleCursor,
    advance_decp_cycle,
    decp_checkpoint_high_water,
    next_decp_window,
    plan_decp_cycle,
)
from signals.ingestion.sources import SourceWindow

UTC = dt.UTC


def test_decp_cycle_cursor_is_versioned_and_resumes_the_next_daily_window() -> None:
    requested_until = dt.datetime(2026, 8, 25, 10, 30, tzinfo=UTC)

    cursor = plan_decp_cycle(
        cursor=None,
        checkpoint_end=None,
        until=requested_until,
        overlap_days=2,
    )

    assert cursor.as_dict() == {
        "version": 1,
        "cycle_end": "2026-08-25",
        "next_window_start": "2026-08-23",
    }
    assert next_decp_window(cursor) == SourceWindow(
        since=dt.date(2026, 8, 23),
        until=dt.date(2026, 8, 23),
    )

    resumed = plan_decp_cycle(
        cursor=advance_decp_cycle(
            cursor,
            SourceWindow(dt.date(2026, 8, 23), dt.date(2026, 8, 23)),
        ).as_dict(),
        checkpoint_end=None,
        until=requested_until + dt.timedelta(days=3),
        overlap_days=2,
    )

    assert resumed.cycle_end == dt.date(2026, 8, 25)
    assert next_decp_window(resumed) == SourceWindow(
        since=dt.date(2026, 8, 24),
        until=dt.date(2026, 8, 24),
    )


def test_checkpoint_high_water_never_regresses_during_overlap() -> None:
    previous = dt.datetime(2026, 8, 24, 12, tzinfo=UTC)
    requested_until = dt.datetime(2026, 8, 25, 10, 30, tzinfo=UTC)

    overlapping = decp_checkpoint_high_water(
        previous=previous,
        completed_window=SourceWindow(dt.date(2026, 8, 23), dt.date(2026, 8, 23)),
        requested_until=requested_until,
    )
    completed = decp_checkpoint_high_water(
        previous=overlapping,
        completed_window=SourceWindow(dt.date(2026, 8, 25), dt.date(2026, 8, 25)),
        requested_until=requested_until,
    )

    assert overlapping == previous
    assert completed == requested_until


def test_completed_cycle_waits_for_a_new_high_water_then_starts_a_new_overlap() -> None:
    completed = DecpCycleCursor(
        cycle_end=dt.date(2026, 8, 25),
        next_window_start=dt.date(2026, 8, 26),
    )
    checkpoint_end = dt.datetime(2026, 8, 25, 10, 30, tzinfo=UTC)

    unchanged = plan_decp_cycle(
        cursor=completed.as_dict(),
        checkpoint_end=checkpoint_end,
        until=checkpoint_end,
        overlap_days=2,
    )
    restarted = plan_decp_cycle(
        cursor=completed.as_dict(),
        checkpoint_end=checkpoint_end,
        until=checkpoint_end + dt.timedelta(days=1),
        overlap_days=2,
    )

    assert next_decp_window(unchanged) is None
    assert restarted.as_dict() == {
        "version": 1,
        "cycle_end": "2026-08-26",
        "next_window_start": "2026-08-23",
    }
