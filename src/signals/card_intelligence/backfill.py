"""One bounded, tenant-scoped page of deterministic factual publications.

The backfill reuses the feed's deterministic candidate window and its scan
cap.  It never follows ``next_offset`` itself and never constructs a provider,
model, prompt, generator, or QA implementation.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

import sqlalchemy as sa

from signals.accounts.schema import account
from signals.card_intelligence.contracts import (
    PresentationInput,
    PresentationVariant,
    PublishedCardPresentation,
)
from signals.card_intelligence.input import build_presentation_input
from signals.card_intelligence.service import publish_factual_fallback
from signals.card_intelligence.store import (
    lock_publication_source,
    published_for_signals,
)
from signals.feed import policy as feed_policy
from signals.feed.query import feed_page

MAX_BACKFILL_ITEMS = 50
_INVALID_ARGUMENTS = "invalid backfill arguments"


class _InvalidFactualPublication(RuntimeError):
    """Force the enclosing item savepoint to roll back an unsafe result."""


@dataclass(frozen=True)
class BackfillResult:
    """Opaque progress for exactly one explicit page."""

    scanned: int
    published: int
    unchanged: int
    failed: int
    next_offset: int | None
    scan_truncated: bool


def _invalid() -> None:
    raise ValueError(_INVALID_ARGUMENTS)


def _validate_arguments(
    *,
    account_id: object,
    as_of: object,
    language: object,
    limit: object,
    offset: object,
    now: object,
) -> Literal["fr", "en"]:
    if (
        not isinstance(account_id, str)
        or re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z_-]{0,63}", account_id) is None
    ):
        _invalid()
    if type(as_of) is not dt.date:
        _invalid()
    if language not in ("fr", "en"):
        _invalid()
    if type(limit) is not int or not 1 <= limit <= MAX_BACKFILL_ITEMS:
        _invalid()
    if (
        type(offset) is not int
        or not 0 <= offset <= feed_policy.CANDIDATE_SCAN_CAP
    ):
        _invalid()
    if (
        not isinstance(now, dt.datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        _invalid()
    return cast(Literal["fr", "en"], language)


def _current_factual(
    presentation: PublishedCardPresentation | None,
) -> bool:
    """Accept only the recursively parsed public factual envelope.

    ``published_for_signals`` also reconstructs the current source and rejects
    a row whose persisted input fingerprint is stale.  A malformed active row
    is therefore absent here and is republished instead of counted unchanged.
    """

    return (
        presentation is not None
        and presentation.status == "FALLBACK"
        and presentation.content.variant is PresentationVariant.FACTUAL_FALLBACK
    )


def _was_published_factual(
    stored: object,
    *,
    source: PresentationInput,
) -> bool:
    if not isinstance(stored, Mapping):
        return False
    values = dict(stored)
    return (
        values.get("account_id") == source.account_id
        and values.get("signal_key") == source.signal_key
        and values.get("language") == source.language
        and values.get("input_fingerprint") == source.fingerprint()
        and values.get("qa_status") == "FALLBACK"
        and values.get("payload_variant") == "FACTUAL_FALLBACK"
        and values.get("published_at") is not None
    )


def _publication_lock_order(
    source: PresentationInput,
) -> tuple[str, str, str, str, str, str]:
    """Order shared authority rows before tenant-specific publication rows."""

    return (
        source.facts.source_event_binding,
        source.facts.source_award_binding,
        source.account_id,
        source.target_icp_id,
        source.signal_key,
        source.language,
    )


def backfill_factual_presentations(
    engine: sa.Engine,
    *,
    account_id: str,
    as_of: dt.date,
    language: Literal["fr", "en"],
    limit: int,
    offset: int,
    now: dt.datetime,
) -> BackfillResult:
    """Process one explicit feed page and return bounded opaque progress.

    The caller decides whether to invoke a later offset.  This function makes
    one candidate-window call only and cannot advance beyond the feed scan cap.
    Every item is assembled and mutated inside a savepoint so one unsafe row
    does not roll back publications already proven safe on the same page.
    """

    checked_language = _validate_arguments(
        account_id=account_id,
        as_of=as_of,
        language=language,
        limit=limit,
        offset=offset,
        now=now,
    )
    published = 0
    unchanged = 0
    failed = 0

    with engine.begin() as connection:
        owned_account = connection.scalar(
            sa.select(account.c.account_id).where(account.c.account_id == account_id)
        )
        if owned_account is None:
            raise ValueError(_INVALID_ARGUMENTS)

        page = feed_page(
            connection,
            account_id=account_id,
            as_of=as_of,
            freshness="all",
            limit=limit,
            offset=offset,
            scan_cap=feed_policy.CANDIDATE_SCAN_CAP,
        )

        sources: list[PresentationInput] = []
        for item in page.items:
            try:
                with connection.begin_nested():
                    source = build_presentation_input(
                        connection,
                        account_id=account_id,
                        signal_key=item.signal.signal_key,
                        language=checked_language,
                    )
            except Exception:  # noqa: BLE001 - one opaque, savepointed item failure
                failed += 1
                continue
            sources.append(source)

        locked_sources: list[PresentationInput] = []
        for source in sorted(
            sources,
            key=_publication_lock_order,
        ):
            try:
                with connection.begin_nested():
                    locked_source = lock_publication_source(
                        connection,
                        source=source,
                    )
            except Exception:  # noqa: BLE001 - one opaque, savepointed lock failure
                failed += 1
                continue
            locked_sources.append(locked_source)

        bindings = {
            source.signal_key: (
                source.signal_revision,
                source.target_icp_revision,
            )
            for source in locked_sources
        }
        current = published_for_signals(
            connection,
            account_id=account_id,
            bindings=bindings,
            language=checked_language,
        )

        for source in locked_sources:
            if _current_factual(current.get(source.signal_key)):
                unchanged += 1
                continue
            try:
                with connection.begin_nested():
                    stored = publish_factual_fallback(
                        connection,
                        source=source,
                        now=now,
                    )
                    if not _was_published_factual(stored, source=source):
                        raise _InvalidFactualPublication
            except Exception:  # noqa: BLE001 - one opaque, savepointed item failure
                failed += 1
                continue
            published += 1

        next_candidate = offset + len(page.items)
        next_offset = (
            next_candidate
            if (
                failed == 0
                and page.has_more
                and next_candidate < feed_policy.CANDIDATE_SCAN_CAP
            )
            else None
        )

    return BackfillResult(
        scanned=len(page.items),
        published=published,
        unchanged=unchanged,
        failed=failed,
        next_offset=next_offset,
        scan_truncated=page.scan_truncated,
    )


__all__ = [
    "MAX_BACKFILL_ITEMS",
    "BackfillResult",
    "backfill_factual_presentations",
]
