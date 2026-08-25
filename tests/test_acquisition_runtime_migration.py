from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    current_revision,
)
from signals.persistence.schema import (
    METADATA,
    acquisition_campaign_member,
    acquisition_runtime_approval,
    acquisition_runtime_cycle,
    acquisition_runtime_lease,
    acquisition_runtime_observation,
    acquisition_runtime_stage,
    acquisition_runtime_stage_attempt,
)

PREVIOUS = "0024_scheduled_plan_change"
HEAD = "0026_acquisition_runtime"
RUNTIME_TABLES = {
    acquisition_runtime_approval.name,
    acquisition_runtime_lease.name,
    acquisition_runtime_observation.name,
    acquisition_runtime_cycle.name,
    acquisition_runtime_stage.name,
    acquisition_runtime_stage_attempt.name,
}


def _engine(tmp_path: pathlib.Path, name: str) -> sa.Engine:
    return create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")


def test_acquisition_runtime_migration_is_one_additive_revision(tmp_path) -> None:
    engine = _engine(tmp_path, "runtime-revision.db")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    scripts = ScriptDirectory.from_config(config)
    assert set(sa.inspect(engine).get_table_names()) - before == RUNTIME_TABLES
    assert scripts.get_heads() == [HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS
    assert (pathlib.Path(scripts.versions) / "0026_acquisition_runtime.py").is_file()


def test_acquisition_runtime_migration_matches_declared_schema(tmp_path) -> None:
    migrated = _engine(tmp_path, "runtime-migrated.db")
    declared = _engine(tmp_path, "runtime-declared.db")
    command.upgrade(alembic_config(migrated), HEAD)
    METADATA.create_all(declared)

    for table_name in (*sorted(RUNTIME_TABLES), acquisition_campaign_member.name):
        migrated_columns = {
            column["name"]
            for column in sa.inspect(migrated).get_columns(table_name)
        }
        declared_columns = {
            column["name"]
            for column in sa.inspect(declared).get_columns(table_name)
        }
        assert migrated_columns == declared_columns

    checks = {
        check["name"]
        for check in sa.inspect(migrated).get_check_constraints(
            acquisition_campaign_member.name
        )
    }
    assert "ck_campaign_member_transport_identity" in checks


def test_acquisition_runtime_migration_roundtrip(tmp_path) -> None:
    engine = _engine(tmp_path, "runtime-roundtrip.db")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)

    command.downgrade(config, PREVIOUS)

    assert current_revision(engine) == PREVIOUS
    assert not RUNTIME_TABLES & set(sa.inspect(engine).get_table_names())
    member_columns = {
        column["name"]
        for column in sa.inspect(engine).get_columns(acquisition_campaign_member.name)
    }
    assert "transport_recipient_identity" not in member_columns
    assert "transport_recipient_key_version" not in member_columns

    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD
    assert RUNTIME_TABLES <= set(sa.inspect(engine).get_table_names())


def test_acquisition_runtime_postgresql_sql_is_bounded_and_secret_free(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql://kivou:placeholder@localhost/kivou",
    )

    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    upgrade_sql = capsys.readouterr().out.lower()
    command.downgrade(config, f"{HEAD}:{PREVIOUS}", sql=True)
    downgrade_sql = capsys.readouterr().out.lower()

    for table_name in RUNTIME_TABLES:
        assert upgrade_sql.count(f"create table {table_name} (") == 1
        assert f"drop table {table_name}" in downgrade_sql
    assert "add column transport_recipient_identity" in upgrade_sql
    assert "add column transport_recipient_key_version" in upgrade_sql
    assert "create index ix_campaign_member_transport_identity" in upgrade_sql
    assert "drop index ix_campaign_member_transport_identity" in downgrade_sql
    assert "drop column transport_recipient_identity" in downgrade_sql
    for forbidden in (
        "raw_payload",
        "provider_payload",
        "message_content",
        "business_email",
        "api_key",
        "secret_key",
        "phone",
    ):
        assert forbidden not in upgrade_sql
