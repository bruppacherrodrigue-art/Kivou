"""Add Kivou supplier identity and bounded discovery-run audit."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_supplier_discovery"
down_revision = "0008_policy_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_supplier",
        sa.Column("supplier_ref", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_organization_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("primary_domain", sa.String(253)),
        sa.Column("website_url", sa.Text()),
        sa.Column("linkedin_company_url", sa.Text()),
        sa.Column("country_code", sa.String(2)),
        sa.Column("location", sa.Text()),
        sa.Column("industry", sa.Text()),
        sa.Column("identity_status", sa.String(32), nullable=False),
        sa.Column("identity_conflict_fingerprint", sa.String(64)),
        sa.Column("provider_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "provider_organization_id",
            name="uq_acquisition_supplier_provider_identity",
        ),
        sa.CheckConstraint(
            "identity_status IN ('PROVIDER_IDENTIFIED', 'DOMAIN_CONFLICT')",
            name="ck_acquisition_supplier_identity_status",
        ),
    )
    op.create_index(
        "ix_acquisition_supplier_primary_domain",
        "acquisition_supplier",
        ["primary_domain"],
    )
    op.create_index(
        "ix_acquisition_supplier_identity_conflict_fingerprint",
        "acquisition_supplier",
        ["identity_conflict_fingerprint"],
    )
    op.create_table(
        "supplier_discovery_run",
        sa.Column("discovery_run_id", sa.String(64), primary_key=True),
        sa.Column("signal_ref", sa.String(256), nullable=False),
        sa.Column("policy_evaluation_id", sa.String(64), nullable=False, unique=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("search_profile_version", sa.String(64), nullable=False),
        sa.Column("search_profile_fingerprint", sa.String(64), nullable=False),
        sa.Column("search_profile", sa.JSON(), nullable=False),
        sa.Column("provider_request_fingerprint", sa.String(64), nullable=False),
        sa.Column("requested_max_pages", sa.Integer(), nullable=False),
        sa.Column("per_page", sa.Integer(), nullable=False),
        sa.Column("candidate_cap", sa.Integer(), nullable=False),
        sa.Column("planned_provider_credit_units", sa.Integer(), nullable=False),
        sa.Column("pages_requested", sa.Integer(), nullable=False),
        sa.Column("provider_credit_units_observed", sa.Integer()),
        sa.Column("provider_total_entries", sa.Integer()),
        sa.Column("partial_results_only", sa.Boolean()),
        sa.Column("records_returned", sa.Integer(), nullable=False),
        sa.Column("records_accepted", sa.Integer(), nullable=False),
        sa.Column("records_rejected", sa.Integer(), nullable=False),
        sa.Column("rejection_reason_counts", sa.JSON(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("opportunities_created", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_category", sa.String(64)),
        sa.Column("error_detail", sa.String(512)),
        sa.Column("retry_after", sa.DateTime(timezone=True)),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_evaluation_id"],
            ["policy_evaluation.evaluation_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('STARTED', 'SUCCESS', 'PARTIAL', 'FAILED', 'SEARCH_TOO_BROAD')",
            name="ck_supplier_discovery_run_status",
        ),
        sa.CheckConstraint(
            "requested_max_pages >= 1 AND requested_max_pages <= 5",
            name="ck_supplier_discovery_run_pages",
        ),
        sa.CheckConstraint(
            "per_page >= 1 AND per_page <= 100",
            name="ck_supplier_discovery_run_per_page",
        ),
        sa.CheckConstraint(
            "candidate_cap >= 1 AND candidate_cap <= 500",
            name="ck_supplier_discovery_run_candidate_cap",
        ),
        sa.CheckConstraint(
            "planned_provider_credit_units >= 0 AND pages_requested >= 0",
            name="ck_supplier_discovery_run_credit_counts",
        ),
        sa.CheckConstraint(
            "provider_credit_units_observed IS NULL OR provider_credit_units_observed >= 0",
            name="ck_supplier_discovery_run_observed_credits",
        ),
        sa.CheckConstraint(
            "provider_total_entries IS NULL OR provider_total_entries >= 0",
            name="ck_supplier_discovery_run_provider_total",
        ),
        sa.CheckConstraint(
            "records_returned >= 0 AND records_accepted >= 0 "
            "AND records_rejected >= 0 AND duplicates >= 0 "
            "AND opportunities_created >= 0",
            name="ck_supplier_discovery_run_record_counts",
        ),
    )
    op.create_index("ix_supplier_discovery_run_status", "supplier_discovery_run", ["status"])
    op.create_index(
        "ix_supplier_discovery_run_signal_time",
        "supplier_discovery_run",
        ["signal_ref", "started_at"],
    )
    op.create_index(
        "ix_supplier_discovery_run_status_time",
        "supplier_discovery_run",
        ["status", "started_at"],
    )


def downgrade() -> None:
    op.drop_table("supplier_discovery_run")
    op.drop_table("acquisition_supplier")
