from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import METADATA, acquisition_event, acquisition_opportunity

PREVIOUS_REVISION = "0006_award_text_capacity"
ACQUISITION_REVISION = "0007_acquisition_event_store"
CURRENT_HEAD = "0027_signal_notes"


def test_upgrade_from_0006_adds_only_acquisition_memory_tables(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'upgrade.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS_REVISION)
    with engine.connect() as connection:
        before = set(sa.inspect(connection).get_table_names())

    command.upgrade(config, ACQUISITION_REVISION)

    with engine.connect() as connection:
        after = set(sa.inspect(connection).get_table_names())
    assert after - before == {"acquisition_opportunity", "acquisition_event"}
    assert before <= after
    assert current_revision(engine) == ACQUISITION_REVISION


def test_fresh_database_reaches_one_linear_acquisition_head(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'fresh.db'}")
    config = alembic_config(engine)
    command.upgrade(config, "head")
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(ACQUISITION_REVISION).down_revision == PREVIOUS_REVISION
    assert all(len(revision.revision) <= 32 for revision in script.walk_revisions())
    assert current_revision(engine) == CURRENT_HEAD


def test_migrated_acquisition_tables_match_declared_core_schema(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'schema.db'}")
    command.upgrade(alembic_config(engine), "head")

    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        for table in (acquisition_opportunity, acquisition_event):
            migrated = {column["name"] for column in inspector.get_columns(table.name)}
            assert migrated == {column.name for column in table.columns}
            assert table.metadata is METADATA


def test_event_constraints_scope_sequence_and_idempotency_to_the_opportunity(
    tmp_path,
) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'constraints.db'}")
    command.upgrade(alembic_config(engine), "head")

    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        uniques = {
            (item["name"], tuple(item["column_names"]))
            for item in inspector.get_unique_constraints("acquisition_event")
        }
        foreign_keys = inspector.get_foreign_keys("acquisition_event")

    assert (
        "uq_acquisition_event_stream_sequence",
        ("acquisition_opportunity_id", "stream_sequence"),
    ) in uniques
    assert (
        "uq_acquisition_event_idempotency",
        ("acquisition_opportunity_id", "idempotency_key"),
    ) in uniques
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["referred_table"] == "acquisition_opportunity"
    assert foreign_keys[0]["options"].get("ondelete") == "RESTRICT"


def test_projection_has_only_operationally_justified_indexes(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'indexes.db'}")
    command.upgrade(alembic_config(engine), "head")

    with engine.connect() as connection:
        indexes = {
            (item["name"], tuple(item["column_names"]))
            for item in sa.inspect(connection).get_indexes("acquisition_opportunity")
        }

    assert indexes == {
        ("ix_acquisition_opportunity_next_review_at", ("next_review_at",)),
        ("ix_acquisition_opportunity_retry_at", ("retry_at",)),
        ("ix_acquisition_opportunity_state", ("state",)),
    }


def test_postgresql_offline_migration_creates_only_the_two_acquisition_tables(
    capsys,
) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option(
        "sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou"
    )

    command.upgrade(config, f"{PREVIOUS_REVISION}:{ACQUISITION_REVISION}", sql=True)

    sql = capsys.readouterr().out
    assert "CREATE TABLE acquisition_opportunity" in sql
    assert "CREATE TABLE acquisition_event" in sql
    assert sql.count("CREATE TABLE") == 2
    assert "NUMERIC(18, 6)" in sql
    assert "ON DELETE RESTRICT" in sql
