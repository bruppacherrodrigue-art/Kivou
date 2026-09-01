from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import (
    acquisition_compliance_assessment,
    acquisition_contact_suppression,
)

PREVIOUS = "0013_personalization"
#: La migration que CE fichier décrit, distincte de la tête de chaîne courante.
COMPLIANCE = "0014_compliance"
CURRENT_HEAD = "0029_production_observation"


def test_compliance_migration_is_linear_and_adds_exactly_two_tables(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'compliance.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, COMPLIANCE)

    assert set(sa.inspect(engine).get_table_names()) - before == {
        "acquisition_contact_suppression",
        "acquisition_compliance_assessment",
    }
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [CURRENT_HEAD]
    assert scripts.get_revision(COMPLIANCE).down_revision == PREVIOUS


def test_compliance_schema_is_pii_and_provider_minimized() -> None:
    forbidden = {
        "business_email",
        "first_name",
        "last_name",
        "display_name",
        "subject",
        "greeting",
        "body",
        "cta",
        "raw_apollo_payload",
        "provider",
        "model",
    }
    for table in (acquisition_contact_suppression, acquisition_compliance_assessment):
        assert forbidden.isdisjoint(column.name for column in table.columns)

    assert {
        "identity_hmac",
        "identity_key_version",
        "scope",
        "minimum_retention_until",
    } <= {column.name for column in acquisition_contact_suppression.columns}
    assert {
        "personalization_artifact_id",
        "input_fingerprint",
        "proposal_fingerprint",
        "policy_action_fingerprint",
        "state",
        "disposition",
        "next_action",
    } <= {column.name for column in acquisition_compliance_assessment.columns}


def test_compliance_upgrade_downgrade_and_schema_parity(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'roundtrip.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    command.upgrade(config, CURRENT_HEAD)

    inspector = sa.inspect(engine)
    for table in (acquisition_contact_suppression, acquisition_compliance_assessment):
        assert {column["name"] for column in inspector.get_columns(table.name)} == {
            column.name for column in table.columns
        }
    assert current_revision(engine) == CURRENT_HEAD
    assert {
        item["name"]
        for item in inspector.get_check_constraints(acquisition_contact_suppression.name)
    } == {
        "ck_suppression_retention_order",
        "ck_suppression_scope",
        "ck_suppression_source",
    }
    assert {
        item["name"]
        for item in inspector.get_check_constraints(acquisition_compliance_assessment.name)
    } == {
        "ck_compliance_assessment_disposition",
        "ck_compliance_assessment_expected_version",
        "ck_compliance_assessment_next_action",
        "ck_compliance_assessment_recorded_event",
        "ck_compliance_assessment_state",
        "ck_compliance_assessment_validity",
    }
    assert {
        item["name"] for item in inspector.get_indexes(acquisition_contact_suppression.name)
    } == {"ix_contact_suppression_identity"}
    assert {
        item["name"]
        for item in inspector.get_indexes(acquisition_compliance_assessment.name)
    } == {"ix_compliance_assessment_opportunity_time"}
    assert {
        index.name for index in acquisition_compliance_assessment.indexes
    } == {"ix_compliance_assessment_opportunity_time"}

    command.downgrade(config, PREVIOUS)
    names = set(sa.inspect(engine).get_table_names())
    assert acquisition_contact_suppression.name not in names
    assert acquisition_compliance_assessment.name not in names
    assert current_revision(engine) == PREVIOUS

    command.upgrade(config, CURRENT_HEAD)
    assert current_revision(engine) == CURRENT_HEAD


def test_compliance_postgresql_offline_sql_has_exactly_two_tables_and_index(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")
    command.upgrade(config, f"{PREVIOUS}:{CURRENT_HEAD}", sql=True)
    sql = capsys.readouterr().out

    assert sql.count("CREATE TABLE acquisition_contact_suppression") == 1
    assert sql.count("CREATE TABLE acquisition_compliance_assessment") == 1
    assert "ix_contact_suppression_identity" in sql
    assert "business_email" not in sql
    assert "CREATE TABLE acquisition_" in sql
