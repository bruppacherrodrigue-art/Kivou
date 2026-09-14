"""Bounded administrative BOAMP backfill; dry-run by default, no request-time fetching."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol

import sqlalchemy as sa
from pydantic import Field, model_validator

from signals.client_value.notice_facts import (
    DEFAULT_SNAPSHOT_POLICY,
    FactModel,
    NoticeSourceSnapshot,
    SnapshotPolicy,
    decode_notice_snapshot,
    store_notice_facts,
)
from signals.connectors.boamp import BoampClient, BoampUnsupportedPayload, parse_award_notice
from signals.connectors.boamp.errors import BoampError
from signals.connectors.boamp.facts import (
    BOAMP_FACTS_EXTRACTOR_VERSION,
    extract_boamp_notice_facts,
    prepare_related_notice_snapshot,
)
from signals.persistence.database import create_database_engine
from signals.persistence.identity import award_key
from signals.persistence.notice_schema import notice_award_facts, notice_source_snapshot
from signals.persistence.schema import contract_award, source_event


class NoticeReader(Protocol):
    def fetch_record(self, notice_id: str) -> dict | None: ...


_SAFE_FAILURE_REASONS = frozenset(
    {
        "notice_identity_mismatch",
        "event_identity_mismatch",
        "stored_award_alignment_mismatch",
        "source_facts_alignment_rejected",
        "notice_reader_required",
        "notice_not_found",
        "related_notice_limit",
        "related_notice_not_found",
    }
)


class NoticeBackfillAttempt(FactModel):
    event_key: str = Field(min_length=1, max_length=256)
    attempts: int = Field(ge=1, le=3)
    reason: str | None = Field(default=None, max_length=128)


class NoticeBackfillCursor(FactModel):
    selection_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    after_event_key: str = Field(default="", max_length=256)
    pending: tuple[NoticeBackfillAttempt, ...] = Field(default=(), max_length=100)
    terminal: tuple[NoticeBackfillAttempt, ...] = Field(default=(), max_length=100)
    terminal_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def distinct_pending(self):
        if len({item.event_key for item in self.pending}) != len(self.pending):
            raise ValueError("pending notice identities must be unique")
        return self


class NoticeBackfillItem(FactModel):
    event_key: str
    status: Literal[
        "would_process", "stored", "already_complete", "failed", "unsupported", "exhausted"
    ]
    attempts: int = 0
    reason: str | None = None


class NoticeBackfillResult(FactModel):
    dry_run: bool
    selected: int
    facts_created: int = 0
    snapshots_created: int = 0
    cache_hits: int = 0
    cursor: NoticeBackfillCursor
    items: tuple[NoticeBackfillItem, ...] = ()


def _needs_facts():
    latest_pending = (
        sa.select(notice_award_facts.c.needs_related_enrichment)
        .where(
            notice_award_facts.c.award_key == contract_award.c.award_key,
            notice_award_facts.c.extractor_version == BOAMP_FACTS_EXTRACTOR_VERSION,
        )
        .order_by(
            notice_award_facts.c.collected_at.desc(),
            notice_award_facts.c.created_at.desc(),
            notice_award_facts.c.needs_related_enrichment.asc(),
            notice_award_facts.c.facts_key.desc(),
        )
        .limit(1)
        .correlate(contract_award)
        .scalar_subquery()
    )
    return sa.exists(
        sa.select(contract_award.c.award_key).where(
            contract_award.c.event_key == source_event.c.event_key,
            sa.func.coalesce(latest_pending, sa.true()).is_(True),
        )
    )


def _bind_selection(
    engine: sa.Engine, cursor: NoticeBackfillCursor, event_keys: tuple[str, ...] | None
) -> tuple[NoticeBackfillCursor, tuple[str, ...] | None]:
    selection_hash = None
    if event_keys is not None:
        if (
            not isinstance(event_keys, tuple)
            or not 1 <= len(event_keys) <= 100
            or any(type(key) is not str or not 1 <= len(key) <= 256 for key in event_keys)
            or len(set(event_keys)) != len(event_keys)
        ):
            raise ValueError("event_keys must contain 1 to 100 distinct exact event keys")
        event_keys = tuple(sorted(event_keys))
        with engine.connect() as connection:
            found = set(
                connection.execute(
                    sa.select(source_event.c.event_key).where(
                        source_event.c.source_system == "boamp",
                        source_event.c.event_key.in_(event_keys),
                    )
                ).scalars()
            )
        if found != set(event_keys):
            raise ValueError("event_keys must name existing BOAMP events")
        selection_hash = hashlib.sha256(
            json.dumps(event_keys, separators=(",", ":")).encode()
        ).hexdigest()
    if cursor.selection_hash != selection_hash:
        pristine = (
            cursor.selection_hash is None
            and not cursor.after_event_key
            and not cursor.pending
            and not cursor.terminal
            and cursor.terminal_count == 0
        )
        if not pristine:
            raise ValueError("cursor selection differs; use a separate cursor file")
        cursor = cursor.model_copy(update={"selection_hash": selection_hash})
    if event_keys is not None:
        cursor_keys = {item.event_key for item in (*cursor.pending, *cursor.terminal)}
        if cursor.after_event_key:
            cursor_keys.add(cursor.after_event_key)
        if not cursor_keys.issubset(event_keys):
            raise ValueError("cursor contains identities outside its selection")
    return cursor, event_keys


def _selected(
    engine: sa.Engine,
    cursor: NoticeBackfillCursor,
    limit: int,
    event_keys: tuple[str, ...] | None = None,
) -> list[dict]:
    selection = source_event.c.event_key.in_(event_keys) if event_keys is not None else sa.true()
    with engine.connect() as connection:
        # Retry pending identities before advancing the source-event cursor.
        pending_keys = [item.event_key for item in cursor.pending][:limit]
        pending = (
            connection.execute(
                sa.select(source_event)
                .where(
                    source_event.c.event_key.in_(pending_keys),
                    source_event.c.source_system == "boamp",
                    selection,
                )
                .order_by(source_event.c.event_key)
            )
            .mappings()
            .all()
            if pending_keys
            else []
        )
        room = min(limit - len(pending), 100 - len(cursor.pending))
        fresh = (
            connection.execute(
                sa.select(source_event)
                .where(
                    source_event.c.source_system == "boamp",
                    selection,
                    source_event.c.event_key > cursor.after_event_key,
                    source_event.c.event_key.not_in(pending_keys),
                    _needs_facts(),
                )
                .order_by(source_event.c.event_key)
                .limit(room)
            )
            .mappings()
            .all()
            if room
            else []
        )
    return [dict(row) for row in [*pending, *fresh]]


def _utc(value: dt.datetime) -> dt.datetime:
    # SQLite serializes DateTime(timezone=True) without its offset. All writes
    # entering this module are validated and normalized to UTC first.
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def _cached_source(engine: sa.Engine, row: dict, now: dt.datetime) -> NoticeSourceSnapshot | None:
    query = sa.select(notice_source_snapshot).where(
        notice_source_snapshot.c.source_system == "boamp",
        notice_source_snapshot.c.source_notice_id == row["source_notice_id"],
        notice_source_snapshot.c.payload_compressed.is_not(None),
        notice_source_snapshot.c.expires_at > now,
    )
    if row["notice_version"] is not None:
        query = query.where(notice_source_snapshot.c.notice_version == row["notice_version"])
    with engine.connect() as connection:
        stored = (
            connection.execute(
                query.order_by(
                    notice_source_snapshot.c.collected_at.desc(),
                    notice_source_snapshot.c.snapshot_key,
                ).limit(1)
            )
            .mappings()
            .first()
        )
    if stored is None:
        return None
    return NoticeSourceSnapshot(
        **{
            field.name: stored[field.name]
            for field in dataclasses.fields(NoticeSourceSnapshot)
            if field.name not in {"collected_at", "expires_at", "notice_version"}
        },
        notice_version=stored["notice_version"] or None,
        collected_at=_utc(stored["collected_at"]),
        expires_at=_utc(stored["expires_at"]),
    )


def _extract_existing(
    engine: sa.Engine,
    row: dict,
    raw: dict,
    *,
    collected_at: dt.datetime,
    policy: SnapshotPolicy,
    related_records: tuple[dict, ...] = (),
    related_source_snapshots: tuple[NoticeSourceSnapshot, ...] = (),
):
    if raw.get("idweb") != row["source_notice_id"]:
        raise ValueError("notice_identity_mismatch")
    event, awards = parse_award_notice(raw, retrieved_at=collected_at)
    if row["notice_version"] is not None:
        event = event.model_copy(
            update={
                "provenance": event.provenance.model_copy(
                    update={"notice_version": row["notice_version"]}
                )
            }
        )
        awards = tuple(award.model_copy(update={"event_ref": event.ref()}) for award in awards)
    if event.ref().key() != row["event_key"]:
        raise ValueError("event_identity_mismatch")
    with engine.connect() as connection:
        stored_keys = set(
            connection.execute(
                sa.select(contract_award.c.award_key).where(
                    contract_award.c.event_key == row["event_key"]
                )
            ).scalars()
        )
    exact_awards = tuple(award for award in awards if award_key(award) in stored_keys)
    if not exact_awards or {award_key(award) for award in exact_awards} != stored_keys:
        raise ValueError("stored_award_alignment_mismatch")
    extracted = extract_boamp_notice_facts(
        raw,
        event=event,
        awards=exact_awards,
        collected_at=collected_at,
        policy=policy,
        related_records=related_records,
        related_source_snapshots=related_source_snapshots,
    )
    if extracted.rejections or len(extracted.awards) != len(exact_awards):
        raise ValueError("source_facts_alignment_rejected")
    return extracted


def backfill_notice_facts(
    engine: sa.Engine,
    *,
    now: dt.datetime,
    client: NoticeReader | None = None,
    limit: int = 100,
    dry_run: bool = True,
    cursor: NoticeBackfillCursor | None = None,
    event_keys: tuple[str, ...] | None = None,
    checkpoint: Callable[[NoticeBackfillCursor], None] | None = None,
    policy: SnapshotPolicy = DEFAULT_SNAPSHOT_POLICY,
) -> NoticeBackfillResult:
    """Process at most 100 notices, one attempt each, with a resumable three-attempt cap.

    The CLI persists checkpoints before each external lookup and after each
    committed notice transaction. The cursor retains the last 100 terminal
    outcomes plus a cumulative count; the full batch report contains no raw facts.
    An exact optional event selection is bound to its own durable cursor and
    never widens to other sources on retry. Existing global cursors still work.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100 notices")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(dt.UTC)
    cursor, event_keys = _bind_selection(engine, cursor or NoticeBackfillCursor(), event_keys)
    rows = _selected(engine, cursor, limit, event_keys)
    if dry_run:
        return NoticeBackfillResult(
            dry_run=True,
            selected=len(rows),
            cursor=cursor,
            items=tuple(
                NoticeBackfillItem(event_key=row["event_key"], status="would_process")
                for row in rows
            ),
        )
    items = []
    related_cache: dict[str, tuple[dict, NoticeSourceSnapshot]] = {}
    facts_created = snapshots_created = cache_hits = 0
    for row in rows:
        key = row["event_key"]
        pending = {item.event_key: item for item in cursor.pending}
        old = pending.get(key)
        attempts = old.attempts if old else 0
        if attempts >= 3:
            # A process can die after its third pre-fetch checkpoint.
            item = NoticeBackfillAttempt(event_key=key, attempts=3, reason="attempt_limit")
            pending.pop(key, None)
            cursor = cursor.model_copy(
                update={
                    "pending": tuple(pending.values()),
                    "terminal": (*cursor.terminal, item)[-100:],
                    "terminal_count": cursor.terminal_count + 1,
                }
            )
            if checkpoint:
                checkpoint(cursor)
            items.append(
                NoticeBackfillItem(
                    event_key=key, status="exhausted", attempts=3, reason="attempt_limit"
                )
            )
            continue
        attempts += 1
        pending[key] = NoticeBackfillAttempt(event_key=key, attempts=attempts)
        cursor = cursor.model_copy(
            update={
                "after_event_key": max(cursor.after_event_key, key),
                "pending": tuple(pending.values()),
            }
        )
        if checkpoint:
            checkpoint(cursor)
        status, reason = "stored", None
        try:
            cached = _cached_source(engine, row, now)
            if cached is not None:
                raw = decode_notice_snapshot(cached, policy=policy)
                collected_at = cached.collected_at
                cache_hits += 1
            else:
                if client is None:
                    raise ValueError("notice_reader_required")
                raw = client.fetch_record(row["source_notice_id"])
                if raw is None:
                    raise ValueError("notice_not_found")
                collected_at = now
            extracted = _extract_existing(
                engine, row, raw, collected_at=collected_at, policy=policy
            )
            linked_ids = tuple(dict.fromkeys(parse_award_notice(raw)[0].source_notice_links))
            if len(linked_ids) > 3:
                raise ValueError("related_notice_limit")
            if linked_ids and any(fact.duration is None for fact in extracted.awards):
                related = []
                related_snapshots = []
                for related_id in linked_ids:
                    if related_id == row["source_notice_id"]:
                        continue
                    if related_id not in related_cache:
                        if len(related_cache) >= 3:
                            related_cache.pop(next(iter(related_cache)))
                        archived = _cached_source(
                            engine, {"source_notice_id": related_id, "notice_version": None}, now
                        )
                        if archived is not None:
                            related_cache[related_id] = (
                                decode_notice_snapshot(archived, policy=policy),
                                archived,
                            )
                            cache_hits += 1
                        else:
                            if client is None:
                                raise ValueError("notice_reader_required")
                            payload = client.fetch_record(related_id)
                            if payload is None or payload.get("idweb") != related_id:
                                raise ValueError("related_notice_not_found")
                            related_cache[related_id] = (
                                payload,
                                prepare_related_notice_snapshot(
                                    payload,
                                    collected_at=now,
                                    policy=policy,
                                ),
                            )
                    related.append(related_cache[related_id][0])
                    related_snapshots.append(related_cache[related_id][1])
                extracted = _extract_existing(
                    engine,
                    row,
                    raw,
                    collected_at=collected_at,
                    policy=policy,
                    related_records=tuple(related),
                    related_source_snapshots=tuple(related_snapshots),
                )
            if cached is not None:
                extracted = dataclasses.replace(extracted, snapshot=cached)
            with engine.begin() as connection:
                stored = store_notice_facts(connection, extracted)
            facts_created += stored.facts_created
            snapshots_created += stored.snapshot_created + stored.related_snapshots_created
            pending.pop(key, None)
        except BoampUnsupportedPayload:
            status, reason = "unsupported", "unsupported_notice_family"
            pending.pop(key, None)
        except (BoampError, ValueError, TypeError, sa.exc.SQLAlchemyError) as error:
            status = "exhausted" if attempts >= 3 else "failed"
            reason = getattr(error, "category", None) or (
                str(error) if str(error) in _SAFE_FAILURE_REASONS else type(error).__name__
            )
            if attempts >= 3:
                pending.pop(key, None)
            else:
                pending[key] = NoticeBackfillAttempt(
                    event_key=key, attempts=attempts, reason=reason
                )
        terminal = status in {"unsupported", "exhausted"}
        cursor = cursor.model_copy(
            update={
                "pending": tuple(pending.values()),
                "terminal": (
                    *cursor.terminal,
                    NoticeBackfillAttempt(event_key=key, attempts=attempts, reason=reason),
                )[-100:]
                if terminal
                else cursor.terminal,
                "terminal_count": cursor.terminal_count + int(terminal),
            }
        )
        if checkpoint:
            checkpoint(cursor)
        items.append(
            NoticeBackfillItem(event_key=key, status=status, attempts=attempts, reason=reason)
        )
    return NoticeBackfillResult(
        dry_run=False,
        selected=len(rows),
        facts_created=facts_created,
        snapshots_created=snapshots_created,
        cache_hits=cache_hits,
        cursor=cursor,
        items=tuple(items),
    )


def _write_cursor(path: Path, cursor: NoticeBackfillCursor) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=".notice-backfill-", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(cursor.model_dump_json())
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m signals.client_value.notice_backfill")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--cursor-file", type=Path)
    parser.add_argument(
        "--event-key", action="append", help="exact BOAMP event key; repeat up to 100 times"
    )
    arguments = parser.parse_args()
    if arguments.execute and arguments.cursor_file is None:
        parser.error("--execute requires --cursor-file for durable attempt checkpoints")
    engine = create_database_engine()
    try:
        with contextlib.ExitStack() as stack:
            if arguments.execute:
                lock = stack.enter_context(arguments.cursor_file.with_suffix(".lock").open("a"))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            cursor = NoticeBackfillCursor()
            if arguments.cursor_file and arguments.cursor_file.exists():
                if arguments.cursor_file.stat().st_size > 256 * 1024:
                    raise ValueError("cursor file exceeds 256 KiB")
                cursor = NoticeBackfillCursor.model_validate_json(arguments.cursor_file.read_text())
            client = stack.enter_context(BoampClient()) if arguments.execute else None
            result = backfill_notice_facts(
                engine,
                now=dt.datetime.now(dt.UTC),
                limit=arguments.limit,
                dry_run=not arguments.execute,
                cursor=cursor,
                event_keys=tuple(arguments.event_key) if arguments.event_key is not None else None,
                client=client,
                checkpoint=(lambda state: _write_cursor(arguments.cursor_file, state))
                if arguments.execute
                else None,
            )
            print(result.model_dump_json())
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
