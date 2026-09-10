"""Persist supplier domains and allow website-verified contacts.

Revision ID: 0047_contact_waterfall
Revises: 0046_sirene_apollo_binding
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0047_contact_waterfall"
down_revision = "0046_sirene_apollo_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sirene_apollo_binding", sa.Column("domain", sa.String(253)))
    op.add_column("sirene_apollo_binding", sa.Column("website_url", sa.Text))
    op.add_column("sirene_apollo_binding", sa.Column("domain_source", sa.String(32)))
    op.add_column("sirene_apollo_binding", sa.Column("domain_query", sa.String(1024)))
    op.add_column(
        "sirene_apollo_binding", sa.Column("domain_observed_at", sa.DateTime(timezone=True))
    )
    with op.batch_alter_table("acquisition_contact") as batch:
        batch.drop_constraint("ck_acquisition_contact_provider", type_="check")
        batch.drop_constraint("ck_acquisition_contact_verification_state", type_="check")
        batch.drop_constraint("ck_acquisition_contact_verification_source", type_="check")
        batch.create_check_constraint(
            "ck_acquisition_contact_provider",
            "provider IN ('apollo', 'company_website')",
        )
        batch.create_check_constraint(
            "ck_acquisition_contact_verification_state",
            "verification_state IN ('PROVIDER_VERIFIED', 'DELIVERABILITY_VERIFIED')",
        )
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


def downgrade() -> None:
    with op.batch_alter_table("acquisition_contact") as batch:
        batch.drop_constraint("ck_acquisition_contact_provider", type_="check")
        batch.drop_constraint("ck_acquisition_contact_verification_state", type_="check")
        batch.drop_constraint("ck_acquisition_contact_verification_source", type_="check")
        batch.create_check_constraint("ck_acquisition_contact_provider", "provider = 'apollo'")
        batch.create_check_constraint(
            "ck_acquisition_contact_verification_state",
            "verification_state = 'PROVIDER_VERIFIED'",
        )
        batch.create_check_constraint(
            "ck_acquisition_contact_verification_source",
            "verification_provider = 'apollo' AND provider_email_status = 'verified'",
        )
    op.drop_column("sirene_apollo_binding", "domain_observed_at")
    op.drop_column("sirene_apollo_binding", "domain_query")
    op.drop_column("sirene_apollo_binding", "domain_source")
    op.drop_column("sirene_apollo_binding", "website_url")
    op.drop_column("sirene_apollo_binding", "domain")
