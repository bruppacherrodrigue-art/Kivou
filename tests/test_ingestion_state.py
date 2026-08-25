from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from signals.ingestion.model import IngestionCounters
from signals.ingestion.state import (
    advance_checkpoint,
    fail_checkpoint,
    finish_run,
    load_checkpoint,
    load_run,
    reconcile_stale_runs,
    start_run,
)
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import ingestion_run, source_event

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


def test_stale_running_rows_are_terminalized_without_deleting_audit_or_business_rows(
    tmp_path,
):
    engine = _engine(tmp_path)
    now = dt.datetime(2026, 8, 25, 9, tzinfo=UTC)
    stale_started = now - dt.timedelta(hours=2)
    recent_started = now - dt.timedelta(minutes=5)
    completed_started = now - dt.timedelta(days=1)

    with engine.begin() as connection:
        connection.execute(
            source_event.insert().values(
                event_key="decp:retained-business-row:v1",
                source_system="decp",
                source_notice_id="retained-business-row",
                notice_version="v1",
                source_country="FR",
                source_procedure_id=None,
                source_url=None,
                event_type="award",
                published_at_raw="2026-08-24",
                published_on=dt.date(2026, 8, 24),
                published_precision="day",
                discovered_at=completed_started,
                procedure_buyers=[],
                created_at=completed_started,
            )
        )
        stale_id = start_run(
            connection,
            source="decp",
            started_at=stale_started,
            dry_run=False,
            run_id="stale-decp",
        )
        recent_id = start_run(
            connection,
            source="decp",
            started_at=recent_started,
            dry_run=False,
            run_id="recent-decp",
        )
        completed_id = start_run(
            connection,
            source="decp",
            started_at=completed_started,
            dry_run=False,
            run_id="completed-decp",
        )
        finish_run(
            connection,
            run_id=completed_id,
            finished_at=completed_started + dt.timedelta(minutes=1),
            status="success",
            counters=IngestionCounters(records_fetched=3),
        )

        reconciled = reconcile_stale_runs(
            connection,
            source="decp",
            stale_before=now - dt.timedelta(hours=1),
            reconciled_at=now,
        )

    with engine.connect() as connection:
        stale = load_run(connection, run_id=stale_id)
        recent = load_run(connection, run_id=recent_id)
        completed = load_run(connection, run_id=completed_id)
        run_count = connection.execute(
            sa.select(sa.func.count()).select_from(ingestion_run)
        ).scalar_one()
        event_count = connection.execute(
            sa.select(sa.func.count()).select_from(source_event)
        ).scalar_one()

    assert reconciled == 1
    assert stale.status == "failed"
    assert stale.finished_at == now
    assert stale.error_category == "stale_run_reconciled"
    assert stale.error_message is None
    assert recent.status == "running"
    assert recent.finished_at is None
    assert completed.status == "success"
    assert completed.records_fetched == 3
    assert run_count == 3
    assert event_count == 1
