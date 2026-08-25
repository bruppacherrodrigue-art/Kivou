from __future__ import annotations

import datetime as dt

import pytest

from signals.ingestion.sources import SourceWindow
from signals.ingestion.ted_convergence import (
    TedCycleCursor,
    advance_ted_notice,
    current_ted_publication_number,
    plan_ted_cycle,
    record_ted_search_page,
)

WINDOW = SourceWindow(dt.date(2026, 8, 22), dt.date(2026, 8, 25))


def test_fresh_ted_cycle_cursor_is_versioned_and_ready_for_page_one() -> None:
    cursor = plan_ted_cycle(cursor=None, window=WINDOW, page_size=50)

    assert cursor.as_dict() == {
        "version": 1,
        "cycle_since": "2026-08-22",
        "cycle_until": "2026-08-25",
        "page": 1,
        "page_size": 50,
        "pending_publication_numbers": [],
        "next_index": 0,
        "more_pages": True,
        "complete": False,
    }
    assert current_ted_publication_number(cursor) is None


def test_incomplete_stored_cycle_resumes_exactly_when_newer_data_exists() -> None:
    stored = {
        "version": 1,
        "cycle_since": "2026-08-22",
        "cycle_until": "2026-08-25",
        "page": 4,
        "page_size": 25,
        "pending_publication_numbers": ["one", "two", "three"],
        "next_index": 1,
        "more_pages": True,
        "complete": False,
    }

    cursor = plan_ted_cycle(
        cursor=stored,
        window=SourceWindow(dt.date(2026, 8, 23), dt.date(2026, 8, 26)),
        page_size=50,
    )

    assert cursor.as_dict() == stored
    assert current_ted_publication_number(cursor) == "two"


def test_search_page_is_deduplicated_and_checkpointed_before_any_download() -> None:
    fresh = plan_ted_cycle(cursor=None, window=WINDOW, page_size=3)

    searched = record_ted_search_page(
        fresh,
        publication_numbers=("three", "two", "two", "one"),
        total=8,
    )

    assert searched.pending_publication_numbers == ("three", "two", "one")
    assert searched.next_index == 0
    assert searched.more_pages is True
    assert searched.complete is False
    assert current_ted_publication_number(searched) == "three"


def test_notice_progress_advances_within_page_then_moves_to_next_page() -> None:
    searched = record_ted_search_page(
        plan_ted_cycle(cursor=None, window=WINDOW, page_size=2),
        publication_numbers=("two", "one"),
        total=3,
    )

    after_one = advance_ted_notice(searched)
    after_page = advance_ted_notice(after_one)

    assert current_ted_publication_number(after_one) == "one"
    assert after_one.next_index == 1
    assert after_page.as_dict() == {
        "version": 1,
        "cycle_since": "2026-08-22",
        "cycle_until": "2026-08-25",
        "page": 2,
        "page_size": 2,
        "pending_publication_numbers": [],
        "next_index": 0,
        "more_pages": True,
        "complete": False,
    }


def test_last_notice_terminalizes_the_cycle() -> None:
    searched = record_ted_search_page(
        plan_ted_cycle(cursor=None, window=WINDOW, page_size=50),
        publication_numbers=("only",),
        total=1,
    )

    completed = advance_ted_notice(searched)

    assert completed.complete is True
    assert completed.more_pages is False
    assert completed.pending_publication_numbers == ()
    assert completed.next_index == 0
    assert current_ted_publication_number(completed) is None


def test_empty_search_page_terminalizes_the_cycle() -> None:
    cursor = record_ted_search_page(
        plan_ted_cycle(cursor=None, window=WINDOW, page_size=50),
        publication_numbers=(),
        total=0,
    )

    assert cursor.complete is True


def test_completed_or_legacy_cursor_starts_the_requested_overlap_cycle() -> None:
    completed = TedCycleCursor(
        cycle_since=WINDOW.since,
        cycle_until=WINDOW.until,
        page=2,
        page_size=2,
        complete=True,
        more_pages=False,
    )
    next_window = SourceWindow(dt.date(2026, 8, 23), dt.date(2026, 8, 26))

    from_completed = plan_ted_cycle(
        cursor=completed.as_dict(), window=next_window, page_size=25
    )
    from_legacy = plan_ted_cycle(
        cursor={"window_end": "2026-08-25"}, window=next_window, page_size=25
    )

    assert from_completed == from_legacy
    assert from_completed.cycle_since == next_window.since
    assert from_completed.cycle_until == next_window.until
    assert from_completed.page == 1
    assert from_completed.page_size == 25


def test_unrecognized_unversioned_cursor_is_rejected_instead_of_reset() -> None:
    with pytest.raises(ValueError, match="legacy TED"):
        plan_ted_cycle(cursor={"page": 4}, window=WINDOW, page_size=50)


@pytest.mark.parametrize(
    "stored",
    (
        {
            "version": 2,
            "cycle_since": "2026-08-22",
            "cycle_until": "2026-08-25",
            "page": 1,
            "page_size": 50,
            "pending_publication_numbers": [],
            "next_index": 0,
            "more_pages": True,
            "complete": False,
        },
        {
            "version": 1,
            "cycle_since": "2026-08-25",
            "cycle_until": "2026-08-22",
            "page": 1,
            "page_size": 50,
            "pending_publication_numbers": [],
            "next_index": 0,
            "more_pages": True,
            "complete": False,
        },
        {
            "version": 1,
            "cycle_since": "2026-08-22",
            "cycle_until": "2026-08-25",
            "page": 1,
            "page_size": 50,
            "pending_publication_numbers": ["one"],
            "next_index": 2,
            "more_pages": False,
            "complete": False,
        },
        {
            "version": 1,
            "cycle_since": "2026-08-22",
            "cycle_until": "2026-08-25",
            "page": 1,
            "page_size": 50,
            "pending_publication_numbers": ["one"],
            "next_index": 0,
            "more_pages": False,
            "complete": True,
        },
    ),
)
def test_ted_cursor_rejects_unknown_or_incoherent_state(stored) -> None:
    with pytest.raises(ValueError, match="TED"):
        plan_ted_cycle(cursor=stored, window=WINDOW, page_size=50)
