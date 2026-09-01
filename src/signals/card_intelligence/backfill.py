"""One bounded, tenant-scoped page of deterministic factual publications.

The backfill reuses the feed's deterministic candidate query with a dedicated
offline scan cap.  It never follows ``next_offset`` itself and never constructs
a provider, model, prompt, generator, or QA implementation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
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
from signals.feed.query import feed_page
from signals.persistence.schema import card_presentation_artifact

MAX_BACKFILL_ITEMS = 50
OFFLINE_CANDIDATE_SCAN_CAP = 1000
_INVALID_ARGUMENTS = "invalid backfill arguments"
_ACCOUNT_BACKFILL_LOCK_NAMESPACE = (
    b"kivou:card-intelligence:factual-backfill:account:v1\x00"
)
_GUARDED_AUTHORITY_LOCK_SQL = (
    "LOCK TABLE target_icp IN SHARE MODE NOWAIT",
    "LOCK TABLE materialized_signal IN SHARE MODE NOWAIT",
    "LOCK TABLE contract_award IN SHARE MODE NOWAIT",
    "LOCK TABLE source_event IN SHARE MODE NOWAIT",
    "LOCK TABLE opportunity_representation IN SHARE MODE NOWAIT",
    "LOCK TABLE evidence IN SHARE MODE NOWAIT",
)
_GUARDED_ARTIFACT_LOCK_SQL = (
    "LOCK TABLE card_presentation_artifact IN SHARE ROW EXCLUSIVE MODE NOWAIT"
)
_GUARDED_READ_COMMITTED_SQL = (
    "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
)
_GUARDED_LOCK_TIMEOUT_SQL = "SET LOCAL lock_timeout = '8s'"


class _InvalidFactualPublication(RuntimeError):
    """Reject a stored result that cannot prove a factual publication."""


class _BackfillPreconditionFailed(RuntimeError):
    """Abort a guarded transaction without reflecting drift details."""


@dataclass(frozen=True)
class BackfillResult:
    """Opaque progress for exactly one explicit page."""

    scanned: int
    published: int
    unchanged: int
    failed: int
    next_offset: int | None
    scan_truncated: bool


@dataclass(frozen=True)
class BackfillPrecondition:
    """All-or-none recovery expectations checked before any publication."""

    expected_candidate_count: int
    expected_active_publication_count: int
    expected_current_factual_artifact_digest: str
    protected_language: Literal["fr", "en"] | None = None
    expected_protected_active_publication_count: int | None = None
    expected_protected_current_factual_artifact_digest: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.expected_candidate_count) is not int
            or not 0 <= self.expected_candidate_count <= MAX_BACKFILL_ITEMS
            or type(self.expected_active_publication_count) is not int
            or not 0
            <= self.expected_active_publication_count
            <= MAX_BACKFILL_ITEMS
            or not isinstance(
                self.expected_current_factual_artifact_digest,
                str,
            )
            or re.fullmatch(
                r"[0-9a-f]{64}",
                self.expected_current_factual_artifact_digest,
            )
            is None
        ):
            _invalid()
        protected_values = (
            self.protected_language,
            self.expected_protected_active_publication_count,
            self.expected_protected_current_factual_artifact_digest,
        )
        if any(value is not None for value in protected_values) and not all(
            value is not None for value in protected_values
        ):
            _invalid()
        if all(value is not None for value in protected_values) and (
            self.protected_language not in ("fr", "en")
            or type(self.expected_protected_active_publication_count) is not int
            or not 0
            <= self.expected_protected_active_publication_count
            <= MAX_BACKFILL_ITEMS
            or not isinstance(
                self.expected_protected_current_factual_artifact_digest,
                str,
            )
            or re.fullmatch(
                r"[0-9a-f]{64}",
                self.expected_protected_current_factual_artifact_digest,
            )
            is None
        ):
            _invalid()


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
    precondition: object,
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
        or not 0 <= offset <= OFFLINE_CANDIDATE_SCAN_CAP
    ):
        _invalid()
    if (
        not isinstance(now, dt.datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        _invalid()
    if precondition is not None and not isinstance(
        precondition,
        BackfillPrecondition,
    ):
        _invalid()
    if (
        isinstance(precondition, BackfillPrecondition)
        and precondition.expected_candidate_count > limit
    ):
        _invalid()
    if (
        isinstance(precondition, BackfillPrecondition)
        and precondition.protected_language == language
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


def _current_factual_artifact_digest(
    current: Mapping[str, PublishedCardPresentation],
) -> str:
    artifact_ids = sorted(
        presentation.artifact_id
        for presentation in current.values()
        if _current_factual(presentation)
    )
    canonical = json.dumps(artifact_ids, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _active_publication_count(
    connection: sa.Connection,
    *,
    account_id: str,
    language: Literal["fr", "en"],
) -> int:
    count = connection.scalar(
        sa.select(sa.func.count())
        .select_from(card_presentation_artifact)
        .where(
            card_presentation_artifact.c.account_id == account_id,
            card_presentation_artifact.c.language == language,
            card_presentation_artifact.c.published_at.is_not(None),
            card_presentation_artifact.c.superseded_at.is_(None),
        )
    )
    if type(count) is not int:
        raise _BackfillPreconditionFailed
    return count


def _stop_guarded() -> None:
    raise _BackfillPreconditionFailed from None


def _prepare_guarded_transaction(connection: sa.Connection) -> None:
    dialect = connection.dialect.name
    try:
        if dialect == "sqlite":
            # Python's sqlite legacy transaction mode does not BEGIN for reads;
            # without this, RELEASE of the store savepoint commits too early.
            connection.exec_driver_sql("BEGIN")
            return
        if dialect != "postgresql":
            _stop_guarded()
        connection.exec_driver_sql(_GUARDED_READ_COMMITTED_SQL)
        connection.exec_driver_sql(_GUARDED_LOCK_TIMEOUT_SQL)
    except _BackfillPreconditionFailed:
        raise
    except Exception:  # noqa: BLE001 - guarded lock setup stays opaque
        _stop_guarded()


def _lock_guarded_authorities(connection: sa.Connection) -> None:
    if connection.dialect.name == "sqlite":
        return
    if connection.dialect.name != "postgresql":
        _stop_guarded()
    try:
        for statement in _GUARDED_AUTHORITY_LOCK_SQL:
            connection.exec_driver_sql(statement)
    except Exception:  # noqa: BLE001 - guarded lock failure stays opaque
        _stop_guarded()


def _lock_guarded_artifact_table(connection: sa.Connection) -> None:
    if connection.dialect.name == "sqlite":
        return
    if connection.dialect.name != "postgresql":
        _stop_guarded()
    try:
        connection.exec_driver_sql(_GUARDED_ARTIFACT_LOCK_SQL)
    except Exception:  # noqa: BLE001 - guarded lock failure stays opaque
        _stop_guarded()


def _owned_account_statement(
    account_id: str,
    *,
    guarded: bool,
) -> sa.Select:
    statement = sa.select(account.c.account_id).where(
        account.c.account_id == account_id
    )
    return (
        statement.with_for_update(read=True, key_share=True)
        if guarded
        else statement
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


def _account_backfill_lock_key(account_id: str) -> int:
    """Return one namespaced signed bigint; collisions only over-serialize."""

    digest = hashlib.sha256(
        _ACCOUNT_BACKFILL_LOCK_NAMESPACE + account_id.encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _lock_account_backfill_transaction(
    connection: sa.Connection,
    *,
    account_id: str,
) -> None:
    """Serialize one account's pages without locking business-table rows."""

    dialect = connection.dialect.name
    if dialect == "sqlite":
        return
    if dialect != "postgresql":
        raise RuntimeError("unsupported database dialect for factual backfill")
    connection.execute(
        sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _account_backfill_lock_key(account_id)},
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
    precondition: BackfillPrecondition | None = None,
) -> BackfillResult:
    """Process one explicit feed page and return bounded opaque progress.

    The caller decides whether to invoke a later offset and this function never
    advances beyond the offline cap. Normal mode reads one candidate window and
    keeps item failures savepoint-scoped. Guarded mode rereads the same window
    under static authority locks and makes every publication all-or-none in the
    enclosing transaction.
    """

    checked_language = _validate_arguments(
        account_id=account_id,
        as_of=as_of,
        language=language,
        limit=limit,
        offset=offset,
        now=now,
        precondition=precondition,
    )
    published = 0
    unchanged = 0
    failed = 0

    with engine.begin() as connection:
        if precondition is not None:
            _prepare_guarded_transaction(connection)
        _lock_account_backfill_transaction(
            connection,
            account_id=account_id,
        )
        try:
            owned_account = connection.scalar(
                _owned_account_statement(
                    account_id,
                    guarded=precondition is not None,
                )
            )
        except Exception:
            if precondition is not None:
                _stop_guarded()
            raise
        if owned_account is None:
            raise ValueError(_INVALID_ARGUMENTS)

        page = feed_page(
            connection,
            account_id=account_id,
            as_of=as_of,
            freshness="all",
            limit=limit,
            offset=offset,
            scan_cap=OFFLINE_CANDIDATE_SCAN_CAP,
        )
        if precondition is not None and (
            len(page.items) != precondition.expected_candidate_count
            or page.has_more
            or page.scan_truncated
        ):
            _stop_guarded()
        if precondition is not None:
            _lock_guarded_authorities(connection)
            locked_page = feed_page(
                connection,
                account_id=account_id,
                as_of=as_of,
                freshness="all",
                limit=limit,
                offset=offset,
                scan_cap=OFFLINE_CANDIDATE_SCAN_CAP,
            )
            if (
                locked_page != page
                or len(locked_page.items)
                != precondition.expected_candidate_count
                or locked_page.has_more
                or locked_page.scan_truncated
            ):
                _stop_guarded()
            page = locked_page
        if page.scan_truncated:
            return BackfillResult(
                scanned=len(page.items),
                published=0,
                unchanged=0,
                failed=0,
                next_offset=None,
                scan_truncated=True,
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
                if precondition is not None:
                    _stop_guarded()
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
                if precondition is not None:
                    _stop_guarded()
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
        if precondition is not None:
            _lock_guarded_artifact_table(connection)
        current = published_for_signals(
            connection,
            account_id=account_id,
            bindings=bindings,
            language=checked_language,
        )
        if precondition is not None:
            active_count = _active_publication_count(
                connection,
                account_id=account_id,
                language=checked_language,
            )
            actual_digest = _current_factual_artifact_digest(current)
            if (
                active_count
                != precondition.expected_active_publication_count
                or not hmac.compare_digest(
                    actual_digest,
                    precondition.expected_current_factual_artifact_digest,
                )
            ):
                _stop_guarded()
            if precondition.protected_language is not None:
                try:
                    protected_current = published_for_signals(
                        connection,
                        account_id=account_id,
                        bindings=bindings,
                        language=precondition.protected_language,
                    )
                    protected_active_count = _active_publication_count(
                        connection,
                        account_id=account_id,
                        language=precondition.protected_language,
                    )
                    protected_digest = _current_factual_artifact_digest(
                        protected_current
                    )
                except Exception:  # noqa: BLE001 - guarded proof stays opaque
                    _stop_guarded()
                if (
                    len(protected_current)
                    != precondition.expected_protected_active_publication_count
                    or protected_active_count
                    != precondition.expected_protected_active_publication_count
                    or not hmac.compare_digest(
                        protected_digest,
                        precondition.expected_protected_current_factual_artifact_digest,
                    )
                ):
                    _stop_guarded()

        for source in locked_sources:
            if _current_factual(current.get(source.signal_key)):
                unchanged += 1
                continue
            try:
                if precondition is not None:
                    stored = publish_factual_fallback(
                        connection,
                        source=source,
                        now=now,
                    )
                    if not _was_published_factual(stored, source=source):
                        raise _InvalidFactualPublication
                else:
                    with connection.begin_nested():
                        stored = publish_factual_fallback(
                            connection,
                            source=source,
                            now=now,
                        )
                        if not _was_published_factual(stored, source=source):
                            raise _InvalidFactualPublication
            except Exception:  # noqa: BLE001 - one opaque publication failure
                if precondition is not None:
                    _stop_guarded()
                failed += 1
                continue
            published += 1

        next_candidate = offset + len(page.items)
        next_offset = (
            next_candidate
            if (
                failed == 0
                and page.has_more
                and next_candidate < OFFLINE_CANDIDATE_SCAN_CAP
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
    "OFFLINE_CANDIDATE_SCAN_CAP",
    "BackfillPrecondition",
    "BackfillResult",
    "backfill_factual_presentations",
]
