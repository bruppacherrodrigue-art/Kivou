from __future__ import annotations

import sqlalchemy as sa
from alembic import command

from signals.persistence.database import alembic_config, create_database_engine, current_revision


def test_supplier_directory_migration_has_dated_business_and_contact_fields(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'directory-migration.db'}")
    config = alembic_config(engine)
    command.upgrade(config, "0047_contact_waterfall")
    command.upgrade(config, "0049_supplier_contact_form")

    columns = {column["name"] for column in sa.inspect(engine).get_columns("supplier_directory")}
    assert {
        "siren",
        "legal_name",
        "legal_name_observed_at",
        "naf_code",
        "naf_observed_at",
        "family_keys",
        "families_observed_at",
        "department",
        "department_observed_at",
        "city",
        "city_observed_at",
        "employees",
        "employees_observed_at",
        "domain",
        "domain_observed_at",
        "directors",
        "directors_observed_at",
        "professional_email",
        "email_source",
        "email_verification_status",
        "email_observed_at",
        "contact_form_url",
        "contact_form_observed_at",
        "suppressed_at",
    } <= columns
    assert current_revision(engine) == "0049_supplier_contact_form"
