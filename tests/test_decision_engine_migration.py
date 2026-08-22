from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import acquisition_decision_evaluation

PREVIOUS = "0011_company_research"
HEAD = "0012_decision_engine"
CURRENT_HEAD = "0017_target_icp_revision"


def test_decision_engine_migration_is_linear_and_adds_exactly_one_table(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'decision.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) - before == {
        "acquisition_decision_evaluation"
    }
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(HEAD).down_revision == PREVIOUS
    assert len(HEAD) <= 32
    assert current_revision(engine) == HEAD


def test_decision_audit_constraints_and_foreign_keys_are_durable(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'constraints.db'}")
    command.upgrade(alembic_config(engine), "head")
    inspector = sa.inspect(engine)

    uniques = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("acquisition_decision_evaluation")
    }
    assert ("policy_evaluation_id",) in uniques
    assert ("recorded_event_id",) in uniques
    fks = {
        tuple(item["constrained_columns"]): (item["referred_table"], item["options"])
        for item in inspector.get_foreign_keys("acquisition_decision_evaluation")
    }
    assert fks[("acquisition_opportunity_id",)][0] == "acquisition_opportunity"
    assert fks[("policy_evaluation_id",)][0] == "policy_evaluation"
    assert fks[("recorded_event_id",)][0] == "acquisition_event"
    assert all(options.get("ondelete") == "RESTRICT" for _, options in fks.values())


def test_migrated_table_matches_core_schema_and_excludes_pii(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    command.upgrade(alembic_config(engine), "head")
    columns = {
        column["name"]
        for column in sa.inspect(engine).get_columns("acquisition_decision_evaluation")
    }

    assert columns == {column.name for column in acquisition_decision_evaluation.columns}
    assert not {
        "business_email",
        "contact_name",
        "first_name",
        "last_name",
        "phone",
        "score",
        "confidence",
        "raw_provider_response",
    } & columns


def test_postgresql_offline_migration_contains_only_decision_audit(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")
    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)

    sql = capsys.readouterr().out
    assert "CREATE TABLE acquisition_decision_evaluation" in sql
    assert sql.count("CREATE TABLE") == 1
    assert "UNIQUE (policy_evaluation_id)" in sql
    assert "ON DELETE RESTRICT" in sql


def test_decision_engine_migration_downgrades_to_previous_head(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'downgrade.db'}")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)

    command.downgrade(config, PREVIOUS)

    assert current_revision(engine) == PREVIOUS
    assert "acquisition_decision_evaluation" not in sa.inspect(engine).get_table_names()
