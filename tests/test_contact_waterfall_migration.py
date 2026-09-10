from __future__ import annotations

import sqlalchemy as sa
from alembic import command

from signals.persistence.database import alembic_config, create_database_engine, current_revision


def test_contact_waterfall_migration_adds_domain_journal_and_two_contact_sources(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'waterfall.db'}")
    config = alembic_config(engine)
    command.upgrade(config, "0046_sirene_apollo_binding")
    command.upgrade(config, "0047_contact_waterfall")

    inspector = sa.inspect(engine)
    binding_columns = {column["name"] for column in inspector.get_columns("sirene_apollo_binding")}
    assert {
        "domain",
        "website_url",
        "domain_source",
        "domain_query",
        "domain_observed_at",
    } <= binding_columns
    checks = " ".join(
        str(item["sqltext"]) for item in inspector.get_check_constraints("acquisition_contact")
    )
    assert "company_website" in checks
    assert "DELIVERABILITY_VERIFIED" in checks
    assert "mx_smtp" in checks
    assert current_revision(engine) == "0047_contact_waterfall"
