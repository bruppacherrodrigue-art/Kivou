from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa

from signals.ingestion.model import (
    Checkpoint,
    IngestionCounters,
    IngestionRun,
    RunStatus,
    SourceName,
)
from signals.persistence.schema import ingestion_checkpoint, ingestion_run


def _aware(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _checkpoint(row: sa.Row | None) -> Checkpoint | None:
    if row is None:
        return None
    return Checkpoint(
        source=row.source,
        cursor=row.cursor,
        window_end=_aware(row.window_end),
        last_started_at=_aware(row.last_started_at),
        last_completed_at=_aware(row.last_completed_at),
        status=row.status,
        updated_at=_aware(row.updated_at),
    )


def _checkpoint_payload(value: Checkpoint | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "cursor": value.cursor,
        "window_end": value.window_end.isoformat() if value.window_end else None,
        "status": value.status,
    }


def load_checkpoint(connection: sa.Connection, *, source: SourceName) -> Checkpoint | None:
    row = connection.execute(
        sa.select(ingestion_checkpoint).where(ingestion_checkpoint.c.source == source)
    ).one_or_none()
    return _checkpoint(row)


def start_run(
    connection: sa.Connection,
    *,
    source: SourceName,
    started_at: dt.datetime,
    dry_run: bool,
    run_id: str | None = None,
) -> str:
    previous = load_checkpoint(connection, source=source)
    identifier = run_id or f"ing_{uuid.uuid4().hex}"
    connection.execute(
        sa.insert(ingestion_run).values(
            run_id=identifier,
            source=source,
            started_at=started_at,
            finished_at=None,
            status="running",
            **dataclasses.asdict(IngestionCounters()),
            error_category=None,
            error_message=None,
            checkpoint_before=_checkpoint_payload(previous),
            checkpoint_after=None,
            dry_run=dry_run,
        )
    )
    values = {
        "last_started_at": started_at,
        "status": "running",
        "updated_at": started_at,
    }
    if previous is None:
        connection.execute(
            sa.insert(ingestion_checkpoint).values(
                source=source,
                cursor=None,
                window_end=None,
                last_completed_at=None,
                **values,
            )
        )
    else:
        connection.execute(
            sa.update(ingestion_checkpoint)
            .where(ingestion_checkpoint.c.source == source)
            .values(**values)
        )
    return identifier


def advance_checkpoint(
    connection: sa.Connection,
    *,
    source: SourceName,
    cursor: dict[str, Any] | None,
    window_end: dt.datetime,
    completed_at: dt.datetime,
) -> Checkpoint:
    connection.execute(
        sa.update(ingestion_checkpoint)
        .where(ingestion_checkpoint.c.source == source)
        .values(
            cursor=cursor,
            window_end=window_end,
            last_completed_at=completed_at,
            status="success",
            updated_at=completed_at,
        )
    )
    result = load_checkpoint(connection, source=source)
    assert result is not None
    return result


def fail_checkpoint(
    connection: sa.Connection, *, source: SourceName, failed_at: dt.datetime
) -> Checkpoint:
    connection.execute(
        sa.update(ingestion_checkpoint)
        .where(ingestion_checkpoint.c.source == source)
        .values(status="failed", updated_at=failed_at)
    )
    result = load_checkpoint(connection, source=source)
    assert result is not None
    return result


def _safe_message(message: str | None) -> str | None:
    if message is None:
        return None
    return " ".join(message.split())[:500]


def finish_run(
    connection: sa.Connection,
    *,
    run_id: str,
    finished_at: dt.datetime,
    status: RunStatus,
    counters: IngestionCounters,
    checkpoint_after: Checkpoint | None = None,
    error_category: str | None = None,
    error_message: str | None = None,
) -> None:
    connection.execute(
        sa.update(ingestion_run)
        .where(ingestion_run.c.run_id == run_id)
        .values(
            finished_at=finished_at,
            status=status,
            **dataclasses.asdict(counters),
            error_category=error_category,
            error_message=_safe_message(error_message),
            checkpoint_after=_checkpoint_payload(checkpoint_after),
        )
    )


def load_run(connection: sa.Connection, *, run_id: str) -> IngestionRun:
    row = connection.execute(
        sa.select(ingestion_run).where(ingestion_run.c.run_id == run_id)
    ).one()
    return IngestionRun(
        run_id=row.run_id,
        source=row.source,
        started_at=_aware(row.started_at),
        finished_at=_aware(row.finished_at),
        status=row.status,
        records_fetched=row.records_fetched,
        records_accepted=row.records_accepted,
        records_rejected=row.records_rejected,
        records_persisted=row.records_persisted,
        representations_linked=row.representations_linked,
        opportunity_conflicts=row.opportunity_conflicts,
        signals_materialized=row.signals_materialized,
        rate_limited_count=row.rate_limited_count,
        error_category=row.error_category,
        error_message=row.error_message,
        checkpoint_before=row.checkpoint_before,
        checkpoint_after=row.checkpoint_after,
        dry_run=bool(row.dry_run),
    )
