from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from signals.persistence.database import (
    alembic_config,
    create_database_engine,
)
from signals.persistence.schema import (
    METADATA,
    acquisition_conversion_event,
    acquisition_conversion_journey,
)

HEAD = "0019_conversion_tracking"
CURRENT_HEAD = "0038_landing_journey"
SPEC028_TABLES = {
    "acquisition_conversion_journey",
    "acquisition_conversion_event",
}


def test_linear_head_and_exactly_two_spec028_tables(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'conversion.db'}")
    config = alembic_config(engine)
    command.upgrade(config, "head")

    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()).issuperset(SPEC028_TABLES)
    with engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
            == CURRENT_HEAD
        )
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [CURRENT_HEAD]
    assert scripts.get_revision(HEAD).down_revision == "0018_response_intelligence"

    assert {column.name for column in acquisition_conversion_journey.c} == {
        "journey_ref",
        "account_id",
        "source_click_event_ref",
        "campaign_ref",
        "member_ref",
        "acquisition_opportunity_id",
        "token_fingerprint",
        "token_version",
        "token_key_version",
        "country",
        "sector_ref",
        "sector_version",
        "need_ref",
        "need_version",
        "wedge",
        "wedge_version",
        "attribution_policy_version",
        "source_fingerprint",
        "clicked_at",
        "attribution_expires_at",
        "signed_up_at",
        "created_at",
    }
    forbidden_fragments = {"email", "user_agent", "stripe", "payload", "raw_token"}
    approved_token_columns = {"token_fingerprint", "token_version", "token_key_version"}
    for table in (acquisition_conversion_journey, acquisition_conversion_event):
        for column in table.c:
            lowered = column.name.casefold()
            assert lowered in approved_token_columns or not any(
                item in lowered for item in forbidden_fragments
            )


def test_0018_upgrade_downgrade_and_reupgrade(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'linear.db'}")
    alembic = alembic_config(engine)
    command.upgrade(alembic, "0018_response_intelligence")
    assert not SPEC028_TABLES.intersection(sa.inspect(engine).get_table_names())

    command.upgrade(alembic, HEAD)
    assert SPEC028_TABLES.issubset(sa.inspect(engine).get_table_names())

    command.downgrade(alembic, "0018_response_intelligence")
    assert not SPEC028_TABLES.intersection(sa.inspect(engine).get_table_names())
    assert "acquisition_response_evaluation" in sa.inspect(engine).get_table_names()

    command.upgrade(alembic, HEAD)
    assert SPEC028_TABLES.issubset(sa.inspect(engine).get_table_names())


def test_core_schema_matches_migration(tmp_path) -> None:
    migrated = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'migrated.db'}")
    core = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    command.upgrade(alembic_config(migrated), HEAD)
    METADATA.create_all(core)

    for table in SPEC028_TABLES:
        assert {item["name"] for item in sa.inspect(migrated).get_columns(table)} == {
            item["name"] for item in sa.inspect(core).get_columns(table)
        }


def test_source_click_is_indexed_but_not_unique_per_account_journey(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'forwarded.db'}")
    command.upgrade(alembic_config(engine), HEAD)
    inspector = sa.inspect(engine)

    unique_columns = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("acquisition_conversion_journey")
    }
    indexes = {
        tuple(item["column_names"]): item["unique"]
        for item in inspector.get_indexes("acquisition_conversion_journey")
    }
    assert ("account_id",) in unique_columns
    assert ("source_click_event_ref",) not in unique_columns
    assert indexes[("source_click_event_ref",)] == 0


def test_money_and_milestone_constraints(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'constraints.db'}")
    command.upgrade(alembic_config(engine), HEAD)
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            sa.insert(acquisition_conversion_event).values(
                conversion_event_ref="x" * 64,
                milestone="PAGE_VIEW",
                event_version="conversion-event-v1",
                event_fingerprint="y" * 64,
                mrr_known=None,
                occurred_at=dt.datetime(2026, 8, 22, 9, tzinfo=dt.UTC),
                observed_at=dt.datetime(2026, 8, 22, 9, tzinfo=dt.UTC),
                recorded_at=dt.datetime(2026, 8, 22, 9, tzinfo=dt.UTC),
            )
        )


def test_postgresql_offline_sql_contains_one_linear_revision(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")
    command.upgrade(config, f"0018_response_intelligence:{HEAD}", sql=True)
    sql = capsys.readouterr().out

    assert 'CREATE TABLE acquisition_conversion_journey' in sql
    assert 'CREATE TABLE acquisition_conversion_event' in sql
    assert "0019_conversion_tracking" in sql
