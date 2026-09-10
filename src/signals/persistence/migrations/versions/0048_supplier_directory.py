"""Persist reusable SIREN-first supplier directory.

Revision ID: 0048_supplier_directory
Revises: 0047_contact_waterfall
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0048_supplier_directory"
down_revision = "0047_contact_waterfall"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supplier_directory",
        sa.Column("siren", sa.String(9), primary_key=True),
        sa.Column("legal_name", sa.Text, nullable=False),
        sa.Column("legal_name_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("naf_code", sa.String(8)),
        sa.Column("naf_observed_at", sa.DateTime(timezone=True)),
        sa.Column("family_keys", sa.JSON, nullable=False),
        sa.Column("families_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("department", sa.String(3)),
        sa.Column("department_observed_at", sa.DateTime(timezone=True)),
        sa.Column("city", sa.Text),
        sa.Column("city_observed_at", sa.DateTime(timezone=True)),
        sa.Column("employees", sa.Integer),
        sa.Column("employees_observed_at", sa.DateTime(timezone=True)),
        sa.Column("domain", sa.String(253)),
        sa.Column("website_url", sa.Text),
        sa.Column("domain_source", sa.String(32)),
        sa.Column("domain_observed_at", sa.DateTime(timezone=True)),
        sa.Column("apollo_organization_id", sa.String(128)),
        sa.Column("apollo_status", sa.String(16)),
        sa.Column("apollo_observed_at", sa.DateTime(timezone=True)),
        sa.Column("directors", sa.JSON, nullable=False),
        sa.Column("directors_observed_at", sa.DateTime(timezone=True)),
        sa.Column("professional_email", sa.String(320)),
        sa.Column("email_source", sa.String(16)),
        sa.Column("email_verification_status", sa.String(32)),
        sa.Column("email_contact_name", sa.Text),
        sa.Column("email_contact_title", sa.Text),
        sa.Column("email_observed_at", sa.DateTime(timezone=True)),
        sa.Column("suppressed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(siren) = 9", name="ck_supplier_directory_siren"),
        sa.CheckConstraint(
            "employees IS NULL OR employees >= 0", name="ck_supplier_directory_employees"
        ),
        sa.CheckConstraint(
            "email_source IS NULL OR email_source IN ('apollo', 'site', 'manual')",
            name="ck_supplier_directory_email_source",
        ),
        sa.CheckConstraint(
            "apollo_status IS NULL OR apollo_status IN ('resolved', 'unresolved')",
            name="ck_supplier_directory_apollo_status",
        ),
    )
    op.create_index("ix_supplier_directory_domain", "supplier_directory", ["domain"])
    with op.batch_alter_table("acquisition_contact") as batch:
        batch.drop_constraint("ck_acquisition_contact_verification_source", type_="check")
        batch.create_check_constraint(
            "ck_acquisition_contact_verification_source",
            "(provider = 'apollo' AND verification_provider = 'apollo' "
            "AND provider_email_status = 'verified' "
            "AND verification_state = 'PROVIDER_VERIFIED') OR "
            "(provider = 'company_website' AND verification_provider = 'dns_mx' "
            "AND provider_email_status = 'mx_accepted' "
            "AND verification_state = 'DELIVERABILITY_VERIFIED' "
            "AND display_name IS NOT NULL)",
        )
    with op.batch_alter_table("acquisition_company_profile") as batch:
        batch.drop_constraint("ck_company_profile_provider", type_="check")
        batch.create_check_constraint(
            "ck_company_profile_provider", "provider IN ('apollo', 'sirene')"
        )


def downgrade() -> None:
    with op.batch_alter_table("acquisition_company_profile") as batch:
        batch.drop_constraint("ck_company_profile_provider", type_="check")
        batch.create_check_constraint("ck_company_profile_provider", "provider = 'apollo'")
    with op.batch_alter_table("acquisition_contact") as batch:
        batch.drop_constraint("ck_acquisition_contact_verification_source", type_="check")
        batch.create_check_constraint(
            "ck_acquisition_contact_verification_source",
            "(provider = 'apollo' AND verification_provider = 'apollo' "
            "AND provider_email_status = 'verified' "
            "AND verification_state = 'PROVIDER_VERIFIED') OR "
            "(provider = 'company_website' AND verification_provider = 'mx_smtp' "
            "AND provider_email_status = 'smtp_accepted' "
            "AND verification_state = 'DELIVERABILITY_VERIFIED' "
            "AND display_name IS NOT NULL)",
        )
    op.drop_index("ix_supplier_directory_domain", table_name="supplier_directory")
    op.drop_table("supplier_directory")
