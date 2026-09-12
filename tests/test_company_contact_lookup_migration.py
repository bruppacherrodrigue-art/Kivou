from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from feed_helpers import make_account

from signals.companies.schema import company_contact_lookup_attempt
from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    current_revision,
)
from signals.persistence.schema import supplier_directory

PREVIOUS = "0052_assisted_observation"
HEAD = "0057_directory_contact_keys"
NOW = dt.datetime(2026, 9, 11, 9, tzinfo=dt.UTC)


def test_company_contact_lookup_is_account_scoped_and_audits_provider_attempts(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'contact-lookup.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)

    command.upgrade(config, HEAD)

    inspector = sa.inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("company_contact_lookup")}
    assert set(columns) == {
        "lookup_id",
        "account_id",
        "company_key",
        "directory_siren",
        "provider_organization_id",
        "status",
        "organization",
        "contacts",
        "requested_at",
        "researched_at",
        "refresh_after",
        "lease_id",
        "lease_expires_at",
        "error_code",
        "created_at",
        "updated_at",
    }
    attempt_columns = {
        column["name"]
        for column in inspector.get_columns("company_contact_lookup_attempt")
    }
    assert attempt_columns == {
        "attempt_id",
        "account_id",
        "company_key",
        "directory_siren",
        "provider_organization_id",
        "status",
        "requested_at",
        "completed_at",
        "lease_expires_at",
        "organization_enrichment_requests",
        "people_search_requests",
        "people_match_requests",
        "planned_credit_units",
        "attempted_credit_units",
        "observed_credit_units",
        "error_code",
    }
    assert inspector.get_pk_constraint("company_contact_lookup")["constrained_columns"] == [
        "lookup_id"
    ]
    foreign_keys = {
        key["referred_table"]: key["options"]
        for key in inspector.get_foreign_keys("company_contact_lookup")
    }
    assert foreign_keys == {
        "account": {"ondelete": "CASCADE"},
        "supplier_directory": {"ondelete": "CASCADE"},
    }
    attempt_foreign_keys = {
        key["referred_table"]: key["options"]
        for key in inspector.get_foreign_keys("company_contact_lookup_attempt")
    }
    assert attempt_foreign_keys == {
        "account": {"ondelete": "CASCADE"},
        "supplier_directory": {"ondelete": "CASCADE"},
    }
    unique = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("company_contact_lookup")
    }
    assert ("account_id", "company_key") in unique
    assert "trg_company_contact_lookup_directory_change" in {
        row[0]
        for row in engine.connect().execute(
            sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        )
    }
    assert ScriptDirectory.from_config(config).get_heads() == [HEAD]
    assert current_revision(engine) == HEAD


def test_company_contact_lookup_migration_roundtrips(tmp_path) -> None:
    engine = create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / 'contact-lookup-roundtrip.db'}"
    )
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    assert "company_contact_lookup" not in sa.inspect(engine).get_table_names()
    assert "company_contact_lookup_attempt" not in sa.inspect(engine).get_table_names()
    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD


def test_downgrade_preserves_directory_only_attempt_history(tmp_path) -> None:
    engine = create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / 'contact-lookup-directory-downgrade.db'}"
    )
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    with engine.begin() as connection:
        account_id = make_account(connection, "directory-downgrade@example.test", "Client")
        connection.execute(
            sa.insert(supplier_directory).values(
                siren="331364729",
                legal_name="Entreprise annuaire",
                legal_name_observed_at=NOW,
                family_keys=[],
                families_observed_at=NOW,
                directors=[],
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            sa.insert(company_contact_lookup_attempt).values(
                attempt_id="attempt-directory-only",
                account_id=account_id,
                company_key="cmp_directory_331364729",
                directory_siren="331364729",
                provider_organization_id="apollo-org-directory",
                status="no_contact",
                requested_at=NOW,
                completed_at=NOW,
                lease_expires_at=NOW,
                organization_enrichment_requests=1,
                people_search_requests=1,
                people_match_requests=0,
                planned_credit_units=4,
                attempted_credit_units=1,
                observed_credit_units=None,
                error_code=None,
            )
        )

    command.downgrade(config, "0056_company_contact_merge")

    assert current_revision(engine) == "0056_company_contact_merge"
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(company_contact_lookup_attempt)
        ) == 1
        assert {
            key["referred_table"]
            for key in sa.inspect(connection).get_foreign_keys(
                "company_contact_lookup_attempt"
            )
        } == {"account", "supplier_directory"}

    command.upgrade(config, HEAD)

    assert current_revision(engine) == HEAD
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(company_contact_lookup_attempt)
        ) == 1


def test_company_contact_lookup_postgresql_sql_is_scoped_and_secret_free(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")

    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)

    sql = capsys.readouterr().out
    assert len(HEAD) <= 32
    assert sql.count("CREATE TABLE") == 2
    assert "CREATE TABLE company_contact_lookup" in sql
    assert "CREATE TABLE company_contact_lookup_attempt" in sql
    assert "UNIQUE (account_id, company_key)" in sql
    assert sql.count("ON DELETE CASCADE") == 6
    assert sql.count("DROP CONSTRAINT IF EXISTS company_contact_lookup_company_key_fkey") == 1
    assert (
        sql.count(
            "DROP CONSTRAINT IF EXISTS company_contact_lookup_attempt_company_key_fkey"
        )
        == 1
    )
    assert "CREATE INDEX ix_company_contact_attempt_account_requested" in sql
    assert "CREATE TRIGGER trg_company_contact_lookup_directory_change" in sql
    assert "raw_provider_response" not in sql
