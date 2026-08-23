from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import acquisition_personalization_artifact

PREVIOUS = "0012_decision_engine"
HEAD = "0013_personalization"
CURRENT_HEAD = "0022_saas_company_profile"


def test_personalization_migration_is_linear_and_adds_one_artifact_table(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'personalization.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    assert set(sa.inspect(engine).get_table_names()) - before == {
        "acquisition_personalization_artifact"
    }
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [CURRENT_HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS
    assert len(HEAD) <= 32


def test_personalization_schema_contains_no_separate_contact_or_model_pii_columns() -> None:
    columns = {column.name for column in acquisition_personalization_artifact.columns}

    assert {"first_name", "last_name", "display_name", "business_email", "phone", "linkedin"}.isdisjoint(columns)
    assert {"provider", "model", "raw_provider_response"}.isdisjoint(columns)
    assert {"policy_evaluation_id", "language", "subject", "greeting", "body", "cta"} <= columns


def test_personalization_upgrade_downgrade_and_schema_parity(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'roundtrip.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    command.upgrade(config, HEAD)
    inspector = sa.inspect(engine)
    assert {
        column["name"] for column in inspector.get_columns(acquisition_personalization_artifact.name)
    } == {column.name for column in acquisition_personalization_artifact.columns}
    assert current_revision(engine) == HEAD

    command.downgrade(config, PREVIOUS)
    assert acquisition_personalization_artifact.name not in sa.inspect(engine).get_table_names()
    assert current_revision(engine) == PREVIOUS

    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD


def test_personalization_postgresql_offline_sql_is_one_table(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option(
        "sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou"
    )
    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    sql = capsys.readouterr().out

    assert sql.count("CREATE TABLE acquisition_personalization_artifact") == 1
    assert "proposal_fingerprint" in sql
    assert "first_name" not in sql
    assert "business_email" not in sql
