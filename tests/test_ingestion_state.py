from __future__ import annotations

import datetime as dt

from signals.ingestion.model import IngestionCounters
from signals.ingestion.state import (
    advance_checkpoint,
    fail_checkpoint,
    finish_run,
    load_checkpoint,
    load_run,
    start_run,
)
from signals.persistence.database import create_database_engine, migrate_to_latest

UTC = dt.UTC


def _engine(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'state.db'}")
    migrate_to_latest(engine)
    return engine


def test_success_advances_checkpoint_and_persists_audit_counters(tmp_path):
    engine = _engine(tmp_path)
    started = dt.datetime(2026, 8, 19, 8, tzinfo=UTC)
    completed = started + dt.timedelta(minutes=3)

    with engine.begin() as connection:
        run_id = start_run(connection, source="boamp", started_at=started, dry_run=False)
    with engine.begin() as connection:
        before = load_checkpoint(connection, source="boamp")
        assert before is not None
        assert before.status == "running"
        assert before.cursor is None

        after = advance_checkpoint(
            connection,
            source="boamp",
            cursor={"offset": 300},
            window_end=completed,
            completed_at=completed,
        )
        finish_run(
            connection,
            run_id=run_id,
            finished_at=completed,
            status="success",
            counters=IngestionCounters(
                records_fetched=12,
                records_accepted=10,
                records_rejected=2,
                records_persisted=10,
                representations_linked=1,
                signals_materialized=3,
            ),
            checkpoint_after=after,
        )

    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="boamp")
        run = load_run(connection, run_id=run_id)

    assert checkpoint is not None
    assert checkpoint.cursor == {"offset": 300}
    assert checkpoint.window_end == completed
    assert checkpoint.last_completed_at == completed
    assert checkpoint.status == "success"
    assert run.status == "success"
    assert run.records_fetched == 12
    assert run.signals_materialized == 3
    assert run.checkpoint_after["cursor"] == {"offset": 300}


def test_failed_source_retains_previous_checkpoint_for_restart(tmp_path):
    engine = _engine(tmp_path)
    old_end = dt.datetime(2026, 8, 18, 20, tzinfo=UTC)
    started = dt.datetime(2026, 8, 19, 8, tzinfo=UTC)

    with engine.begin() as connection:
        seed_run = start_run(
            connection, source="ted", started_at=old_end, dry_run=False, run_id="seed"
        )
        checkpoint = advance_checkpoint(
            connection,
            source="ted",
            cursor={"page": 7},
            window_end=old_end,
            completed_at=old_end,
        )
        finish_run(
            connection,
            run_id=seed_run,
            finished_at=old_end,
            status="success",
            counters=IngestionCounters(),
            checkpoint_after=checkpoint,
        )

    with engine.begin() as connection:
        run_id = start_run(connection, source="ted", started_at=started, dry_run=False)
        fail_checkpoint(connection, source="ted", failed_at=started + dt.timedelta(minutes=1))
        finish_run(
            connection,
            run_id=run_id,
            finished_at=started + dt.timedelta(minutes=1),
            status="rate_limited",
            counters=IngestionCounters(rate_limited_count=1),
            error_category="rate_limited",
            error_message="HTTP 429\nraw response omitted",
        )

    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="ted")
        run = load_run(connection, run_id=run_id)

    assert checkpoint is not None
    assert checkpoint.cursor == {"page": 7}
    assert checkpoint.window_end == old_end
    assert checkpoint.last_completed_at == old_end
    assert checkpoint.status == "failed"
    assert run.status == "rate_limited"
    assert run.rate_limited_count == 1
    assert run.checkpoint_after is None
    assert run.error_message == "HTTP 429 raw response omitted"


def test_starting_again_reads_the_durable_success_window(tmp_path):
    engine = _engine(tmp_path)
    completed = dt.datetime(2026, 8, 19, 6, tzinfo=UTC)
    with engine.begin() as connection:
        start_run(connection, source="simap", started_at=completed, dry_run=False, run_id="first")
        advance_checkpoint(
            connection,
            source="simap",
            cursor={"last_item": "abc"},
            window_end=completed,
            completed_at=completed,
        )

    with engine.begin() as connection:
        start_run(
            connection,
            source="simap",
            started_at=completed + dt.timedelta(hours=1),
            dry_run=False,
            run_id="second",
        )
        restarted = load_checkpoint(connection, source="simap")

    assert restarted is not None
    assert restarted.cursor == {"last_item": "abc"}
    assert restarted.window_end == completed
    assert restarted.last_started_at == completed + dt.timedelta(hours=1)
    assert restarted.status == "running"
