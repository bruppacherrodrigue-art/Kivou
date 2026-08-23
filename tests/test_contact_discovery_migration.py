from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import acquisition_contact, contact_discovery_run

PREVIOUS = "0009_supplier_discovery"
HEAD = "0010_contact_discovery"
CURRENT_HEAD = "0023_transactional_email_runtime"


def test_contact_discovery_migration_is_linear_and_adds_exactly_two_tables(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'contact-migration.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) - before == {
        "acquisition_contact",
        "contact_discovery_run",
    }
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(HEAD).down_revision == PREVIOUS
    assert len(HEAD) <= 32
    assert current_revision(engine) == HEAD


def test_contact_identity_and_run_ownership_constraints_are_durable(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'contact-schema.db'}")
    command.upgrade(alembic_config(engine), "head")
    inspector = sa.inspect(engine)

    contact_uniques = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("acquisition_contact")
    }
    assert ("provider", "provider_person_id", "supplier_ref") in contact_uniques

    run_uniques = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("contact_discovery_run")
    }
    assert ("policy_evaluation_id",) in run_uniques
    foreign_keys = inspector.get_foreign_keys("contact_discovery_run")
    referred = {
        tuple(item["constrained_columns"]): (item["referred_table"], item["options"])
        for item in foreign_keys
    }
    assert referred[("policy_evaluation_id",)][0] == "policy_evaluation"
    assert referred[("acquisition_opportunity_id",)][0] == "acquisition_opportunity"
    assert referred[("supplier_ref",)][0] == "acquisition_supplier"
    assert all(options.get("ondelete") == "RESTRICT" for _, options in referred.values())
    contact_columns = {column["name"] for column in inspector.get_columns("acquisition_contact")}
    assert (
        not {
            "phone",
            "personal_email",
            "personal_address",
            "photo",
            "biography",
            "linkedin_person_url",
            "raw_provider_response",
        }
        & contact_columns
    )


def test_migrated_contact_tables_match_core_schema(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'contact-core.db'}")
    command.upgrade(alembic_config(engine), "head")
    inspector = sa.inspect(engine)

    for table in (acquisition_contact, contact_discovery_run):
        assert {column["name"] for column in inspector.get_columns(table.name)} == {
            column.name for column in table.columns
        }


def test_postgresql_offline_migration_contains_only_contact_tables(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")
    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)

    sql = capsys.readouterr().out
    assert "CREATE TABLE acquisition_contact" in sql
    assert "CREATE TABLE contact_discovery_run" in sql
    assert sql.count("CREATE TABLE") == 2
    assert "UNIQUE (policy_evaluation_id)" in sql
    assert "ON DELETE RESTRICT" in sql
