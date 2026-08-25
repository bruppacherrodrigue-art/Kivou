from __future__ import annotations

import datetime as dt

import pytest

from signals.ingestion.convergence import (
    DecpCycleCursor,
    advance_decp_batch,
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
        "version": 2,
        "cycle_end": "2026-08-25",
        "next_window_start": "2026-08-23",
        "offset": 0,
        "window_total": None,
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
        "version": 2,
        "cycle_end": "2026-08-26",
        "next_window_start": "2026-08-23",
        "offset": 0,
        "window_total": None,
    }


def test_decp_cursor_resumes_inside_a_day_and_accepts_the_legacy_version() -> None:
    requested_until = dt.datetime(2026, 8, 25, 10, 30, tzinfo=UTC)
    legacy = {
        "version": 1,
        "cycle_end": "2026-08-25",
        "next_window_start": "2026-08-24",
    }

    cursor = plan_decp_cycle(
        cursor=legacy,
        checkpoint_end=None,
        until=requested_until,
        overlap_days=2,
    )
    partial = advance_decp_batch(
        cursor,
        SourceWindow(dt.date(2026, 8, 24), dt.date(2026, 8, 24)),
        next_offset=2,
        window_total=5,
        day_complete=False,
    )

    assert partial.as_dict() == {
        "version": 2,
        "cycle_end": "2026-08-25",
        "next_window_start": "2026-08-24",
        "offset": 2,
        "window_total": 5,
    }
    assert plan_decp_cycle(
        cursor=partial.as_dict(),
        checkpoint_end=None,
        until=requested_until + dt.timedelta(days=1),
        overlap_days=2,
    ) == partial

    completed = advance_decp_batch(
        partial,
        SourceWindow(dt.date(2026, 8, 24), dt.date(2026, 8, 24)),
        next_offset=5,
        window_total=5,
        day_complete=True,
    )

    assert completed.next_window_start == dt.date(2026, 8, 25)
    assert completed.offset == 0
    assert completed.window_total is None


def test_decp_cursor_rejects_incoherent_intra_day_offsets() -> None:
    requested_until = dt.datetime(2026, 8, 25, 10, 30, tzinfo=UTC)

    for stored in (
        {
            "version": 2,
            "cycle_end": "2026-08-25",
            "next_window_start": "2026-08-24",
            "offset": -1,
            "window_total": 5,
        },
        {
            "version": 2,
            "cycle_end": "2026-08-25",
            "next_window_start": "2026-08-24",
            "offset": 3,
            "window_total": 2,
        },
        {
            "version": 2,
            "cycle_end": "2026-08-25",
            "next_window_start": "2026-08-24",
            "offset": 1,
            "window_total": None,
        },
        {
            "version": 2,
            "cycle_end": "2026-08-25",
            "next_window_start": "2026-08-24",
            "offset": 1.5,
            "window_total": 5,
        },
        {
            "version": 2,
            "cycle_end": "2026-08-25",
            "next_window_start": "2026-08-24",
            "offset": 1,
            "window_total": 5.5,
        },
    ):
        with pytest.raises(ValueError, match="DECP"):
            plan_decp_cycle(
                cursor=stored,
                checkpoint_end=None,
                until=requested_until,
                overlap_days=2,
            )
