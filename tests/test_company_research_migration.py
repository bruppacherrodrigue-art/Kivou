from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import acquisition_company_profile, company_research_run

PREVIOUS = "0010_contact_discovery"
HEAD = "0011_company_research"
CURRENT_HEAD = "0033_requeue_unresolved_siret"


def test_company_research_migration_is_linear_and_adds_exactly_two_tables(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'company.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) - before == {
        "acquisition_company_profile",
        "company_research_run",
    }
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(HEAD).down_revision == PREVIOUS
    assert len(HEAD) <= 32
    assert current_revision(engine) == HEAD


def test_company_profile_and_run_constraints_are_durable(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'constraints.db'}")
    command.upgrade(alembic_config(engine), "head")
    inspector = sa.inspect(engine)

    profile_fks = {
        tuple(item["constrained_columns"]): (item["referred_table"], item["options"])
        for item in inspector.get_foreign_keys("acquisition_company_profile")
    }
    assert profile_fks[("acquisition_opportunity_id",)][0] == "acquisition_opportunity"
    assert profile_fks[("supplier_ref",)][0] == "acquisition_supplier"
    assert profile_fks[("contact_ref",)][0] == "acquisition_contact"
    assert all(options.get("ondelete") == "RESTRICT" for _, options in profile_fks.values())

    run_uniques = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("company_research_run")
    }
    assert ("policy_evaluation_id",) in run_uniques
    run_fks = {
        tuple(item["constrained_columns"]): (item["referred_table"], item["options"])
        for item in inspector.get_foreign_keys("company_research_run")
    }
    assert run_fks[("policy_evaluation_id",)][0] == "policy_evaluation"
    assert run_fks[("acquisition_opportunity_id",)][0] == "acquisition_opportunity"
    assert run_fks[("supplier_ref",)][0] == "acquisition_supplier"
    assert run_fks[("contact_ref",)][0] == "acquisition_contact"
    assert all(options.get("ondelete") == "RESTRICT" for _, options in run_fks.values())


def test_migrated_company_tables_match_core_schema_and_exclude_pii(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    command.upgrade(alembic_config(engine), "head")
    inspector = sa.inspect(engine)

    for table in (acquisition_company_profile, company_research_run):
        assert {column["name"] for column in inspector.get_columns(table.name)} == {
            column.name for column in table.columns
        }
    columns = {column["name"] for column in inspector.get_columns("acquisition_company_profile")}
    assert (
        not {
            "business_email",
            "contact_name",
            "phone",
            "annual_revenue",
            "raw_provider_response",
        }
        & columns
    )


def test_postgresql_offline_migration_contains_only_company_research_tables(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")
    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)

    sql = capsys.readouterr().out
    assert "CREATE TABLE acquisition_company_profile" in sql
    assert "CREATE TABLE company_research_run" in sql
    assert sql.count("CREATE TABLE") == 2
    assert "UNIQUE (policy_evaluation_id)" in sql
    assert "ON DELETE RESTRICT" in sql
