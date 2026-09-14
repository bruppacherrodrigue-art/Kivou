"""Durable explicit company enrichment independent of winner signal age."""

import sqlalchemy as sa
from alembic import op

revision = "0062_company_enrichment_requests"
down_revision = "0061_company_live_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_directory_enrichment_job",
        sa.Column("siren", sa.String(9), primary_key=True),
        sa.Column("job_id", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("claimed_by", sa.String(64)),
        sa.Column("lease_id", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_after", sa.DateTime(timezone=True)),
        sa.Column("previous_observed_at", sa.DateTime(timezone=True)),
        sa.Column("baseline_fields", sa.JSON, nullable=False),
        sa.Column("added_fields", sa.JSON, nullable=False),
        sa.Column("outcome", sa.String(16)),
        sa.Column("error_code", sa.String(64)),
        sa.CheckConstraint("length(siren) = 9", name="ck_company_enrichment_siren"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'ready', 'partial', 'failed', 'budget_wait')",
            name="ck_company_enrichment_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3", name="ck_company_enrichment_attempts"
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('enriched', 'no_change')",
            name="ck_company_enrichment_outcome",
        ),
        sa.CheckConstraint(
            "status <> 'running' OR (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND started_at IS NOT NULL AND claimed_by IS NOT NULL AND attempt_count > 0)",
            name="ck_company_enrichment_lease",
        ),
    )
    op.create_index(
        "ix_company_enrichment_due",
        "company_directory_enrichment_job",
        ["status", "retry_after", "queued_at"],
    )


def downgrade() -> None:
    raise RuntimeError("restore previous application without downgrading company data")
