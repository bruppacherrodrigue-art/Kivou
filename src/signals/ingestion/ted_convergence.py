from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from signals.ingestion.sources import SourceWindow

TED_CURSOR_VERSION = 1


def _positive_integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"TED cursor {field} must be a positive integer")
    return value


def _date(value: Any, *, field: str) -> dt.date:
    if not isinstance(value, str):
        raise TypeError(f"TED cursor {field} must be an ISO date")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"TED cursor {field} must be an ISO date") from error


@dataclasses.dataclass(frozen=True)
class TedCycleCursor:
    cycle_since: dt.date
    cycle_until: dt.date
    page: int
    page_size: int
    pending_publication_numbers: tuple[str, ...] = ()
    next_index: int = 0
    more_pages: bool = True
    complete: bool = False
    version: int = dataclasses.field(default=TED_CURSOR_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.cycle_until < self.cycle_since:
            raise ValueError("TED cursor cycle ends before it starts")
        _positive_integer(self.page, field="page")
        _positive_integer(self.page_size, field="page_size")
        if isinstance(self.next_index, bool) or not isinstance(self.next_index, int):
            raise TypeError("TED cursor next_index must be an integer")
        if self.next_index < 0:
            raise ValueError("TED cursor next_index cannot be negative")
        if len(self.pending_publication_numbers) > self.page_size:
            raise ValueError("TED cursor pending page exceeds page_size")
        if any(
            not isinstance(number, str) or not number.strip()
            for number in self.pending_publication_numbers
        ):
            raise ValueError("TED cursor publication numbers must be non-empty strings")
        if len(set(self.pending_publication_numbers)) != len(
            self.pending_publication_numbers
        ):
            raise ValueError("TED cursor publication numbers must be unique")
        if self.pending_publication_numbers:
            if self.next_index >= len(self.pending_publication_numbers):
                raise ValueError("TED cursor next_index exceeds the pending page")
        elif self.next_index != 0:
            raise ValueError("TED cursor without pending notices must start at index zero")
        if self.complete and (
            self.pending_publication_numbers or self.next_index or self.more_pages
        ):
            raise ValueError("TED completed cursor cannot retain pending work")
        if not self.complete and not self.pending_publication_numbers and not self.more_pages:
            raise ValueError("TED incomplete cursor must retain searchable work")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TedCycleCursor:
        expected = {
            "version",
            "cycle_since",
            "cycle_until",
            "page",
            "page_size",
            "pending_publication_numbers",
            "next_index",
            "more_pages",
            "complete",
        }
        if set(value) != expected:
            raise ValueError("TED cursor fields are incomplete or unsupported")
        if value.get("version") != TED_CURSOR_VERSION:
            raise ValueError("unsupported TED cursor version")
        pending = value.get("pending_publication_numbers")
        if not isinstance(pending, list):
            raise TypeError("TED cursor pending notices must be a list")
        more_pages = value.get("more_pages")
        complete = value.get("complete")
        if not isinstance(more_pages, bool) or not isinstance(complete, bool):
            raise TypeError("TED cursor completion flags must be boolean")
        return cls(
            cycle_since=_date(value.get("cycle_since"), field="cycle_since"),
            cycle_until=_date(value.get("cycle_until"), field="cycle_until"),
            page=_positive_integer(value.get("page"), field="page"),
            page_size=_positive_integer(value.get("page_size"), field="page_size"),
            pending_publication_numbers=tuple(pending),
            next_index=value.get("next_index"),
            more_pages=more_pages,
            complete=complete,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "cycle_since": self.cycle_since.isoformat(),
            "cycle_until": self.cycle_until.isoformat(),
            "page": self.page,
            "page_size": self.page_size,
            "pending_publication_numbers": list(self.pending_publication_numbers),
            "next_index": self.next_index,
            "more_pages": self.more_pages,
            "complete": self.complete,
        }


def _fresh(window: SourceWindow, *, page_size: int) -> TedCycleCursor:
    return TedCycleCursor(
        cycle_since=window.since,
        cycle_until=window.until,
        page=1,
        page_size=_positive_integer(page_size, field="page_size"),
    )


def plan_ted_cycle(
    *,
    cursor: Mapping[str, Any] | None,
    window: SourceWindow,
    page_size: int,
) -> TedCycleCursor:
    if cursor is None:
        return _fresh(window, page_size=page_size)
    if "version" not in cursor:
        if set(cursor) != {"window_end"} or not isinstance(cursor.get("window_end"), str):
            raise ValueError("unsupported legacy TED cursor")
        return _fresh(window, page_size=page_size)
    if cursor.get("version") != TED_CURSOR_VERSION:
        raise ValueError("unsupported TED cursor version")
    stored = TedCycleCursor.from_dict(cursor)
    return _fresh(window, page_size=page_size) if stored.complete else stored


def record_ted_search_page(
    cursor: TedCycleCursor,
    *,
    publication_numbers: Sequence[str],
    total: int,
) -> TedCycleCursor:
    if cursor.complete or cursor.pending_publication_numbers:
        raise ValueError("TED cursor is not ready for a search page")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError("TED search total must be a non-negative integer")
    numbers = tuple(dict.fromkeys(publication_numbers))
    if not numbers:
        return dataclasses.replace(cursor, more_pages=False, complete=True)
    consumed_through_page = cursor.page * cursor.page_size
    return dataclasses.replace(
        cursor,
        pending_publication_numbers=numbers,
        next_index=0,
        more_pages=consumed_through_page < total,
    )


def current_ted_publication_number(cursor: TedCycleCursor) -> str | None:
    if not cursor.pending_publication_numbers:
        return None
    return cursor.pending_publication_numbers[cursor.next_index]


def advance_ted_notice(cursor: TedCycleCursor) -> TedCycleCursor:
    if current_ted_publication_number(cursor) is None:
        raise ValueError("TED cursor has no notice to advance")
    next_index = cursor.next_index + 1
    if next_index < len(cursor.pending_publication_numbers):
        return dataclasses.replace(cursor, next_index=next_index)
    if cursor.more_pages:
        return dataclasses.replace(
            cursor,
            page=cursor.page + 1,
            pending_publication_numbers=(),
            next_index=0,
        )
    return dataclasses.replace(
        cursor,
        pending_publication_numbers=(),
        next_index=0,
        more_pages=False,
        complete=True,
    )
