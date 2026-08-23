"""Add the client-safe SaaS company profile identity table.

Revision ID: 0022_saas_company_profile
Revises: 0021_reliability_operations
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

revision = "0022_saas_company_profile"
down_revision = "0021_reliability_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "materialized_signal",
        sa.Column("company_identity_fingerprint", sa.String(64)),
    )
    op.create_table(
        "saas_company",
        sa.Column("company_key", sa.String(64), primary_key=True),
        sa.Column("identity_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("identity_method", sa.String(32), nullable=False),
        sa.Column("identity_validation", sa.JSON, nullable=False),
        sa.Column("source_award_key", sa.String(64), nullable=False),
        sa.Column("origin_signal_key", sa.String(64), nullable=False),
        sa.Column("official_name", sa.Text, nullable=False),
        sa.Column("official_country", sa.String(2)),
        sa.Column("official_address", sa.Text),
        sa.Column("official_identifiers", sa.JSON, nullable=False),
        sa.Column("official_website_url", sa.Text),
        sa.Column("official_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_award_key"], ["contract_award.award_key"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["origin_signal_key"], ["materialized_signal.signal_key"], ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_saas_company_source_award_key", "saas_company", ["source_award_key"])
    op.create_index("ix_saas_company_origin_signal_key", "saas_company", ["origin_signal_key"])
    if not context.is_offline_mode():
        from signals.companies.indexing import backfill_signal_company_identities

        backfill_signal_company_identities(op.get_bind())
    op.create_index(
        "ix_materialized_signal_company_identity_fingerprint",
        "materialized_signal",
        ["company_identity_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_materialized_signal_company_identity_fingerprint",
        table_name="materialized_signal",
    )
    op.drop_column("materialized_signal", "company_identity_fingerprint")
    op.drop_table("saas_company")
