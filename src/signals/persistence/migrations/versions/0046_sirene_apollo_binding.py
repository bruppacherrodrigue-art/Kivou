"""Bind SIREN identities to resolved Apollo organisations.

Revision ID: 0046_sirene_apollo_binding
Revises: 0045_pr7_shadow_mail
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0046_sirene_apollo_binding"
down_revision = "0045_pr7_shadow_mail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "supplier_discovery_run",
        sa.Column("family_result_counts", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "supplier_discovery_run",
        sa.Column("family_target_counts", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "sirene_apollo_binding",
        sa.Column("siren", sa.String(9), primary_key=True),
        sa.Column("apollo_organization_id", sa.String(128)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_method", sa.String(64), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 4)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('resolved', 'unresolved', 'legacy')",
            name="ck_sirene_apollo_binding_status",
        ),
        sa.CheckConstraint(
            "confidence_score IS NULL OR "
            "(confidence_score >= 0 AND confidence_score <= 1)",
            name="ck_sirene_apollo_binding_confidence",
        ),
    )
    # Apollo-first supplier records have no trustworthy SIREN and are retained
    # as explicit legacy history. They are never copied into the binding table.
    with op.batch_alter_table("acquisition_supplier") as batch:
        batch.drop_constraint("ck_acquisition_supplier_identity_status", type_="check")
        batch.create_check_constraint(
            "ck_acquisition_supplier_identity_status",
            "identity_status IN ('PROVIDER_IDENTIFIED', 'SIRENE_IDENTIFIED', "
            "'LEGACY_APOLLO', 'DOMAIN_CONFLICT')",
        )
    with op.batch_alter_table("acquisition_company_profile") as batch:
        batch.drop_constraint("ck_company_profile_supplier_identity", type_="check")
        batch.create_check_constraint(
            "ck_company_profile_supplier_identity",
            "supplier_identity_status IN ('PROVIDER_IDENTIFIED', 'SIRENE_IDENTIFIED', "
            "'LEGACY_APOLLO', 'DOMAIN_CONFLICT')",
        )
    op.execute(
        sa.text(
            "UPDATE acquisition_supplier SET identity_status = 'LEGACY_APOLLO' "
            "WHERE provider = 'apollo'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE acquisition_supplier SET identity_status = 'PROVIDER_IDENTIFIED' "
            "WHERE identity_status = 'LEGACY_APOLLO'"
        )
    )
    with op.batch_alter_table("acquisition_supplier") as batch:
        batch.drop_constraint("ck_acquisition_supplier_identity_status", type_="check")
        batch.create_check_constraint(
            "ck_acquisition_supplier_identity_status",
            "identity_status IN ('PROVIDER_IDENTIFIED', 'DOMAIN_CONFLICT')",
        )
    with op.batch_alter_table("acquisition_company_profile") as batch:
        batch.drop_constraint("ck_company_profile_supplier_identity", type_="check")
        batch.create_check_constraint(
            "ck_company_profile_supplier_identity",
            "supplier_identity_status IN ('PROVIDER_IDENTIFIED', 'DOMAIN_CONFLICT')",
        )
    op.drop_table("sirene_apollo_binding")
    op.drop_column("supplier_discovery_run", "family_target_counts")
    op.drop_column("supplier_discovery_run", "family_result_counts")
