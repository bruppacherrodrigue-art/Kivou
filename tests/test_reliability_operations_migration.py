from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import (
    METADATA,
    acquisition_dead_letter,
    acquisition_operational_incident,
)

PREVIOUS = "0020_hermes_learning_loop"
HEAD = "0021_reliability_operations"
CURRENT_HEAD = "0023_transactional_email_runtime"
TABLES = (acquisition_operational_incident, acquisition_dead_letter)


def test_reliability_migration_is_single_linear_head_and_adds_two_tables(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'ops.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    assert set(sa.inspect(engine).get_table_names()) - before == {table.name for table in TABLES}
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [CURRENT_HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS
    versions = pathlib.Path(scripts.versions)
    assert (versions / "0021_reliability_operations.py").is_file()
    assert (versions / "0022_saas_company_profile.py").is_file()
    assert (versions / "0023_transactional_email_runtime.py").is_file()


def test_reliability_roundtrip_and_core_schema_parity(tmp_path) -> None:
    migrated = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'migrated.db'}")
    core = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    config = alembic_config(migrated)
    command.upgrade(config, HEAD)
    METADATA.create_all(core)

    for table in TABLES:
        assert {column["name"] for column in sa.inspect(migrated).get_columns(table.name)} == {
            column["name"] for column in sa.inspect(core).get_columns(table.name)
        }

    command.downgrade(config, PREVIOUS)
    assert {table.name for table in TABLES}.isdisjoint(sa.inspect(migrated).get_table_names())
    assert current_revision(migrated) == PREVIOUS
    command.upgrade(config, HEAD)
    assert current_revision(migrated) == HEAD


def test_reliability_postgresql_offline_sql_has_two_pii_minimal_tables(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")
    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    sql = capsys.readouterr().out.lower()

    assert sql.count("create table acquisition_operational_incident (") == 1
    assert sql.count("create table acquisition_dead_letter (") == 1
    for forbidden in (
        "email",
        "response_body",
        "raw_payload",
        "api_key",
        "webhook_secret",
        "session_cookie",
    ):
        assert forbidden not in sql


def test_reliability_core_tables_exclude_raw_payload_and_pii_columns() -> None:
    forbidden = {
        "email",
        "lead_email",
        "customer_email",
        "name",
        "company_name",
        "response_body",
        "raw_payload",
        "raw_exception",
        "api_key",
        "webhook_secret",
        "session_cookie",
    }
    for table in TABLES:
        assert forbidden.isdisjoint(column.name for column in table.columns)
