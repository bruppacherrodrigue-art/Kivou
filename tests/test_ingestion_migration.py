from __future__ import annotations

import sqlalchemy as sa
from alembic import command

from signals.persistence.database import alembic_config, create_database_engine, current_revision

PREVIOUS_REVISION = "0004_alerts_feedback_analytics"
INGESTION_REVISION = "0005_ingestion_runtime"


def test_ingestion_migration_is_additive_after_the_current_main_head(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'upgrade.db'}")
    config = alembic_config(engine)

    command.upgrade(config, PREVIOUS_REVISION)
    with engine.connect() as connection:
        before = set(sa.inspect(connection).get_table_names())
        assert "ingestion_checkpoint" not in before
        assert "ingestion_run" not in before

    command.upgrade(config, INGESTION_REVISION)
    with engine.connect() as connection:
        after = set(sa.inspect(connection).get_table_names())

    assert current_revision(engine) == INGESTION_REVISION
    assert after - before == {"ingestion_checkpoint", "ingestion_run"}
    assert before <= after


def test_ingestion_tables_expose_only_narrow_operational_state(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'schema.db'}")
    command.upgrade(alembic_config(engine), "head")

    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        checkpoint = {column["name"] for column in inspector.get_columns("ingestion_checkpoint")}
        run = {column["name"] for column in inspector.get_columns("ingestion_run")}

    assert checkpoint == {
        "source",
        "cursor",
        "window_end",
        "last_started_at",
        "last_completed_at",
        "status",
        "updated_at",
    }
    assert run == {
        "run_id",
        "source",
        "started_at",
        "finished_at",
        "status",
        "records_fetched",
        "records_accepted",
        "records_rejected",
        "records_persisted",
        "representations_linked",
        "opportunity_conflicts",
        "signals_materialized",
        "rate_limited_count",
        "error_category",
        "error_message",
        "checkpoint_before",
        "checkpoint_after",
        "dry_run",
    }
