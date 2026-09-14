"""Ownership metadata for the staging-only public company mirror."""

import sqlalchemy as sa
from alembic import op

revision = "0063_catalogue_mirror"
down_revision = "0062_company_enrichment_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalogue_mirror_entry",
        sa.Column("siren", sa.String(9), primary_key=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_fact_hashes", sa.JSON(), nullable=False),
        sa.Column("mirrored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "catalogue_mirror_state",
        sa.Column("source", sa.String(16), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("mirrored_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source = 'production'", name="ck_catalogue_mirror_source"),
    )


def downgrade() -> None:
    raise RuntimeError("restore previous application without downgrading company data")
