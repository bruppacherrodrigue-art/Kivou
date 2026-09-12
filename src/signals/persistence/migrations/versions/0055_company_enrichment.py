"""Persist one-pass model company enrichment.

Revision ID: 0055_company_enrichment
Revises: 0054_prospect_mail_contract
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0055_company_enrichment"
down_revision = "0054_prospect_mail_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("supplier_directory") as batch:
        batch.drop_constraint("ck_supplier_directory_email_source", type_="check")
        batch.drop_constraint("ck_supplier_directory_domain_validation_method", type_="check")
        batch.add_column(sa.Column("family_source", sa.String(16)))
        batch.add_column(sa.Column("family_confidence", sa.Numeric(4, 3)))
        batch.add_column(sa.Column("family_confirmation_status", sa.String(16)))
        batch.add_column(sa.Column("domain_confidence", sa.Numeric(4, 3)))
        batch.add_column(sa.Column("director_display_name", sa.Text))
        batch.add_column(sa.Column("director_source", sa.String(16)))
        batch.add_column(sa.Column("director_observed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("email_confidence", sa.Numeric(4, 3)))
        batch.add_column(sa.Column("phone", sa.String(32)))
        batch.add_column(sa.Column("phone_source", sa.String(16)))
        batch.add_column(sa.Column("phone_observed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("enrichment_notes", sa.Text))
        batch.add_column(sa.Column("enrichment_model_id", sa.String(128)))
        batch.add_column(sa.Column("enrichment_cost_usd", sa.Numeric(12, 6)))
        batch.add_column(sa.Column("enrichment_input_tokens", sa.Integer))
        batch.add_column(sa.Column("enrichment_output_tokens", sa.Integer))
        batch.add_column(sa.Column("enrichment_evidence", sa.JSON))
        batch.add_column(sa.Column("enrichment_decision", sa.JSON))
        batch.add_column(sa.Column("enrichment_observed_at", sa.DateTime(timezone=True)))
        batch.create_check_constraint(
            "ck_supplier_directory_email_source",
            "email_source IS NULL OR email_source IN ('apollo', 'site', 'manual', 'model')",
        )
        batch.create_check_constraint(
            "ck_supplier_directory_domain_validation_method",
            "domain_validation_method IS NULL OR "
            "domain_validation_method IN ('name_word', 'registration_number', 'model')",
        )
        batch.create_check_constraint(
            "ck_supplier_directory_domain_confidence",
            "domain_confidence IS NULL OR domain_confidence BETWEEN 0 AND 1",
        )
        batch.create_check_constraint(
            "ck_supplier_directory_email_confidence",
            "email_confidence IS NULL OR email_confidence BETWEEN 0 AND 1",
        )
        batch.create_check_constraint(
            "ck_supplier_directory_family_confidence",
            "family_confidence IS NULL OR family_confidence BETWEEN 0 AND 1",
        )
        batch.create_check_constraint(
            "ck_supplier_directory_family_confirmation",
            "family_confirmation_status IS NULL OR "
            "family_confirmation_status IN ('confirmed', 'unconfirmed')",
        )
        batch.create_check_constraint(
            "ck_supplier_directory_enrichment_cost",
            "enrichment_cost_usd IS NULL OR enrichment_cost_usd >= 0",
        )

    with op.batch_alter_table("prospect_target") as batch:
        batch.drop_constraint("ck_prospect_target_email_source", type_="check")
        batch.create_check_constraint(
            "ck_prospect_target_email_source",
            "email_source IN ('apollo', 'site', 'manual', 'model')",
        )


def downgrade() -> None:
    with op.batch_alter_table("prospect_target") as batch:
        batch.drop_constraint("ck_prospect_target_email_source", type_="check")
        batch.create_check_constraint(
            "ck_prospect_target_email_source",
            "email_source IN ('apollo', 'site', 'manual')",
        )
    with op.batch_alter_table("supplier_directory") as batch:
        batch.drop_constraint("ck_supplier_directory_enrichment_cost", type_="check")
        batch.drop_constraint("ck_supplier_directory_family_confirmation", type_="check")
        batch.drop_constraint("ck_supplier_directory_family_confidence", type_="check")
        batch.drop_constraint("ck_supplier_directory_email_confidence", type_="check")
        batch.drop_constraint("ck_supplier_directory_domain_confidence", type_="check")
        batch.drop_constraint("ck_supplier_directory_domain_validation_method", type_="check")
        batch.drop_constraint("ck_supplier_directory_email_source", type_="check")
        for column in (
            "enrichment_observed_at",
            "enrichment_decision",
            "enrichment_evidence",
            "enrichment_output_tokens",
            "enrichment_input_tokens",
            "enrichment_cost_usd",
            "enrichment_model_id",
            "enrichment_notes",
            "phone_observed_at",
            "phone_source",
            "phone",
            "email_confidence",
            "director_observed_at",
            "director_source",
            "director_display_name",
            "domain_confidence",
            "family_confirmation_status",
            "family_confidence",
            "family_source",
        ):
            batch.drop_column(column)
        batch.create_check_constraint(
            "ck_supplier_directory_email_source",
            "email_source IS NULL OR email_source IN ('apollo', 'site', 'manual')",
        )
        batch.create_check_constraint(
            "ck_supplier_directory_domain_validation_method",
            "domain_validation_method IS NULL OR "
            "domain_validation_method IN ('name_word', 'registration_number')",
        )
