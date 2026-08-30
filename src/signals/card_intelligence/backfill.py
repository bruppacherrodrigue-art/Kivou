"""Bounded, offline-safe backfill for factual presentation fallbacks."""

from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy.engine import Engine

from signals.card_intelligence.input import build_presentation_input
from signals.card_intelligence.service import publish_factual_fallback
from signals.card_intelligence.store import current_publication_row
from signals.feed.query import feed_page

MAX_BACKFILL_ITEMS = 50


@dataclasses.dataclass(frozen=True)
class BackfillResult:
    scanned: int
    published: int
    unchanged: int


def backfill_factual_presentations(
    engine: Engine,
    *,
    account_id: str,
    as_of: dt.date,
    language: str,
    limit: int,
    now: dt.datetime,
) -> BackfillResult:
    """Publish at most 50 safe fallbacks; this function never calls a provider."""
    if language not in ("fr", "en"):
        raise ValueError("language must be fr or en")
    if not 1 <= limit <= MAX_BACKFILL_ITEMS:
        raise ValueError(f"limit must be between 1 and {MAX_BACKFILL_ITEMS}")

    published = 0
    unchanged = 0
    with engine.begin() as connection:
        page = feed_page(
            connection,
            account_id=account_id,
            as_of=as_of,
            freshness="all",
            limit=limit,
            scan_cap=limit,
        )
        for item in page.items:
            source = build_presentation_input(
                connection,
                item=item,
                account_id=account_id,
                language=language,
            )
            current = current_publication_row(connection, source=source)
            if current is not None and current["input_fingerprint"] == source.fingerprint():
                unchanged += 1
                continue
            row = publish_factual_fallback(connection, source=source, now=now)
            if row["qa_status"] == "FALLBACK" and row["published_at"] is not None:
                published += 1

    return BackfillResult(scanned=len(page.items), published=published, unchanged=unchanged)
