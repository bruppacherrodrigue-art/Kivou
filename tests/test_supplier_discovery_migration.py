from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision

PREVIOUS = "0008_policy_gateway"
HEAD = "0009_supplier_discovery"
CURRENT_HEAD = "0027_signal_notes"


def test_supplier_discovery_migration_is_linear_and_adds_exactly_two_tables(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'supplier-migration.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) - before == {
        "acquisition_supplier",
        "supplier_discovery_run",
    }
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(HEAD).down_revision == PREVIOUS
    assert len(HEAD) <= 32
    assert current_revision(engine) == HEAD


def test_supplier_discovery_run_has_one_to_one_policy_evaluation_constraint(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'supplier-schema.db'}")
    command.upgrade(alembic_config(engine), "head")
    inspector = sa.inspect(engine)
    unique_columns = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("supplier_discovery_run")
    }
    assert ("policy_evaluation_id",) in unique_columns
    foreign_keys = inspector.get_foreign_keys("supplier_discovery_run")
    policy_fk = next(
        item for item in foreign_keys if item["constrained_columns"] == ["policy_evaluation_id"]
    )
    assert policy_fk["referred_table"] == "policy_evaluation"
    assert policy_fk["options"]["ondelete"] == "RESTRICT"
    checks = {
        item["name"] for item in inspector.get_check_constraints("supplier_discovery_run")
    }
    assert "ck_supplier_discovery_run_provider_total" in checks


def test_postgresql_offline_migration_contains_only_supplier_tables(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option(
        "sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou"
    )
    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    sql = capsys.readouterr().out
    assert "CREATE TABLE acquisition_supplier" in sql
    assert "CREATE TABLE supplier_discovery_run" in sql
    assert sql.count("CREATE TABLE") == 2
    assert "UNIQUE (policy_evaluation_id)" in sql
    assert "ON DELETE RESTRICT" in sql
