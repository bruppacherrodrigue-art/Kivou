"""Bounded, offline-safe backfill for factual presentation fallbacks."""

from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy.engine import Engine

from signals.card_intelligence.input import build_presentation_input
from signals.card_intelligence.service import publish_factual_fallback
from signals.card_intelligence.store import current_publication_row
from signals.feed import policy
from signals.feed.query import feed_page

MAX_BACKFILL_ITEMS = 50


@dataclasses.dataclass(frozen=True)
class BackfillResult:
    scanned: int
    published: int
    unchanged: int
    failed: int
    next_offset: int | None
    failures: tuple[str, ...] = ()


def backfill_factual_presentations(
    engine: Engine,
    *,
    account_id: str,
    as_of: dt.date,
    language: str,
    limit: int,
    offset: int = 0,
    now: dt.datetime,
) -> BackfillResult:
    """Publish at most 50 safe fallbacks; this function never calls a provider."""
    if language not in ("fr", "en"):
        raise ValueError("language must be fr or en")
    if not 1 <= limit <= MAX_BACKFILL_ITEMS:
        raise ValueError(f"limit must be between 1 and {MAX_BACKFILL_ITEMS}")
    if not 0 <= offset < policy.CANDIDATE_SCAN_CAP:
        raise ValueError(
            f"offset must be between 0 and {policy.CANDIDATE_SCAN_CAP - 1}"
        )

    published = 0
    unchanged = 0
    failures: list[str] = []
    with engine.begin() as connection:
        page = feed_page(
            connection,
            account_id=account_id,
            as_of=as_of,
            freshness="all",
            limit=limit,
            offset=offset,
            # ``feed_page.offset`` is applied after identity/freshness filters.
            # Scan the whole bounded candidate window on every page, otherwise
            # excluded raw rows can make offset=0 loop forever.
            scan_cap=policy.CANDIDATE_SCAN_CAP,
        )
        for item in page.items:
            try:
                outcome: str
                # One malformed source cannot roll back the safe publications
                # completed earlier in this bounded page.
                with connection.begin_nested():
                    source = build_presentation_input(
                        connection,
                        item=item,
                        account_id=account_id,
                        language=language,
                    )
                    current = current_publication_row(connection, source=source)
                    if (
                        current is not None
                        and current["input_fingerprint"] == source.fingerprint()
                    ):
                        outcome = "unchanged"
                    else:
                        row = publish_factual_fallback(connection, source=source, now=now)
                        if row["qa_status"] != "FALLBACK" or row["published_at"] is None:
                            raise ValueError("fallback_not_publishable")
                        outcome = "published"
                if outcome == "unchanged":
                    unchanged += 1
                else:
                    published += 1
            except Exception as error:  # noqa: BLE001 - per-item offline boundary
                signal_key = getattr(getattr(item, "signal", None), "signal_key", "unknown")
                failures.append(f"{signal_key}:{type(error).__name__}")

    consumed = offset + len(page.items)
    next_offset = None
    if page.items and consumed < policy.CANDIDATE_SCAN_CAP and (
        len(page.items) == limit or page.has_more
    ):
        next_offset = consumed
    return BackfillResult(
        scanned=len(page.items),
        published=published,
        unchanged=unchanged,
        failed=len(failures),
        next_offset=next_offset,
        failures=tuple(failures),
    )
