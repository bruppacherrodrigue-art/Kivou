from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic import command

from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    current_revision,
)

PREVIOUS = "0025_alert_recipient_context"
HEAD = "0026_acquisition_runtime"
TABLE = "acquisition_runtime_approval"


def _engine(tmp_path: pathlib.Path, name: str) -> sa.Engine:
    return create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")


def test_runtime_approval_migration_roundtrip_is_additive(tmp_path) -> None:
    engine = _engine(tmp_path, "approval-roundtrip.db")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)

    assert TABLE in sa.inspect(engine).get_table_names()
    columns = {item["name"] for item in sa.inspect(engine).get_columns(TABLE)}
    assert "binding_fingerprint" in columns
    assert "approved_by_actor_ref" in columns
    assert "consumed_by_ref" in columns

    command.downgrade(config, PREVIOUS)
    assert current_revision(engine) == PREVIOUS
    assert TABLE not in sa.inspect(engine).get_table_names()

    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD
    assert TABLE in sa.inspect(engine).get_table_names()


def test_runtime_approval_postgresql_offline_sql_is_closed_and_secret_free(
    capsys,
) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql://kivou:placeholder@localhost/kivou",
    )

    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    upgrade_sql = capsys.readouterr().out.lower()
    command.downgrade(config, f"{HEAD}:{PREVIOUS}", sql=True)
    downgrade_sql = capsys.readouterr().out.lower()

    assert upgrade_sql.count(f"create table {TABLE} (") == 1
    assert "ck_acquisition_runtime_approval_state" in upgrade_sql
    assert "ck_acquisition_runtime_approval_lifecycle" in upgrade_sql
    assert f"drop table {TABLE}" in downgrade_sql
    for forbidden in (
        "business_email",
        "phone",
        "raw_payload",
        "provider_payload",
        "message_content",
        "canonical_arguments",
        "api_key",
        "secret_key",
    ):
        assert forbidden not in upgrade_sql
