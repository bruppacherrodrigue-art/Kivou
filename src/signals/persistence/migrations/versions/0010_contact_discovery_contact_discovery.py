"""Add selected contact identity and bounded contact discovery audit."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_contact_discovery"
down_revision = "0009_supplier_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_contact",
        sa.Column("contact_ref", sa.String(64), primary_key=True),
        sa.Column("supplier_ref", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_person_id", sa.String(128), nullable=False),
        sa.Column("provider_organization_id", sa.String(128), nullable=False),
        sa.Column("first_name", sa.Text()),
        sa.Column("last_name", sa.Text()),
        sa.Column("display_name", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("role_profile_version", sa.String(64), nullable=False),
        sa.Column("role_tier", sa.Integer(), nullable=False),
        sa.Column("business_email", sa.String(320), nullable=False),
        sa.Column("provider_email_status", sa.String(64), nullable=False),
        sa.Column("verification_state", sa.String(32), nullable=False),
        sa.Column("verification_provider", sa.String(32), nullable=False),
        sa.Column("provider_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["supplier_ref"], ["acquisition_supplier.supplier_ref"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_person_id",
            "supplier_ref",
            name="uq_acquisition_contact_provider_employment",
        ),
        sa.CheckConstraint("provider = 'apollo'", name="ck_acquisition_contact_provider"),
        sa.CheckConstraint(
            "verification_state = 'PROVIDER_VERIFIED'",
            name="ck_acquisition_contact_verification_state",
        ),
        sa.CheckConstraint(
            "verification_provider = 'apollo' AND provider_email_status = 'verified'",
            name="ck_acquisition_contact_verification_source",
        ),
        sa.CheckConstraint(
            "role_tier >= 1 AND role_tier <= 4",
            name="ck_acquisition_contact_role_tier",
        ),
    )
    op.create_index(
        "ix_acquisition_contact_supplier_ref",
        "acquisition_contact",
        ["supplier_ref"],
    )
    op.create_index(
        "ix_acquisition_contact_supplier_verification",
        "acquisition_contact",
        ["supplier_ref", "verification_state"],
    )
    op.create_table(
        "contact_discovery_run",
        sa.Column("contact_discovery_run_id", sa.String(64), primary_key=True),
        sa.Column("acquisition_opportunity_id", sa.String(64), nullable=False),
        sa.Column("supplier_ref", sa.String(64), nullable=False),
        sa.Column("policy_evaluation_id", sa.String(64), nullable=False, unique=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("search_profile_version", sa.String(64), nullable=False),
        sa.Column("search_profile_fingerprint", sa.String(64), nullable=False),
        sa.Column("search_profile", sa.JSON(), nullable=False),
        sa.Column("provider_request_fingerprint", sa.String(64), nullable=False),
        sa.Column("expected_post_policy_version", sa.Integer(), nullable=False),
        sa.Column("requested_max_pages", sa.Integer(), nullable=False),
        sa.Column("per_page", sa.Integer(), nullable=False),
        sa.Column("max_enrichment_attempts", sa.Integer(), nullable=False),
        sa.Column("people_search_requests", sa.Integer(), nullable=False),
        sa.Column("provider_total_entries", sa.Integer()),
        sa.Column("search_results_returned", sa.Integer(), nullable=False),
        sa.Column("search_results_truncated", sa.Boolean(), nullable=False),
        sa.Column("candidates_eligible", sa.Integer(), nullable=False),
        sa.Column("candidates_rejected", sa.Integer(), nullable=False),
        sa.Column("enrichment_attempts", sa.Integer(), nullable=False),
        sa.Column("planned_provider_credit_units", sa.Integer(), nullable=False),
        sa.Column("observed_provider_credit_units", sa.Integer()),
        sa.Column("attempted_contact_refs", sa.JSON(), nullable=False),
        sa.Column("selected_contact_ref", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_category", sa.String(64)),
        sa.Column("error_detail", sa.String(512)),
        sa.Column("retry_after", sa.DateTime(timezone=True)),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["acquisition_opportunity_id"],
            ["acquisition_opportunity.acquisition_opportunity_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_ref"], ["acquisition_supplier.supplier_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["policy_evaluation_id"],
            ["policy_evaluation.evaluation_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_contact_ref"],
            ["acquisition_contact.contact_ref"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("provider = 'apollo'", name="ck_contact_run_provider"),
        sa.CheckConstraint(
            "status IN ('STARTED', 'SUCCESS', 'NO_CANDIDATE', "
            "'NO_VERIFIED_CONTACT', 'CONTACT_SEARCH_TOO_BROAD', 'FAILED')",
            name="ck_contact_run_status",
        ),
        sa.CheckConstraint(
            "expected_post_policy_version >= 2", name="ck_contact_run_expected_version"
        ),
        sa.CheckConstraint(
            "requested_max_pages = 1 AND per_page >= 1 AND per_page <= 25 "
            "AND max_enrichment_attempts >= 1 AND max_enrichment_attempts <= 3",
            name="ck_contact_run_bounds",
        ),
        sa.CheckConstraint(
            "people_search_requests >= 0 AND search_results_returned >= 0 "
            "AND candidates_eligible >= 0 AND candidates_rejected >= 0 "
            "AND enrichment_attempts >= 0",
            name="ck_contact_run_counters",
        ),
        sa.CheckConstraint(
            "provider_total_entries IS NULL OR provider_total_entries >= 0",
            name="ck_contact_run_provider_total",
        ),
        sa.CheckConstraint(
            "planned_provider_credit_units >= 0 AND "
            "(observed_provider_credit_units IS NULL OR observed_provider_credit_units >= 0)",
            name="ck_contact_run_credits",
        ),
    )
    op.create_index("ix_contact_discovery_run_status", "contact_discovery_run", ["status"])
    op.create_index(
        "ix_contact_discovery_run_opportunity_time",
        "contact_discovery_run",
        ["acquisition_opportunity_id", "started_at"],
    )
    op.create_index(
        "ix_contact_discovery_run_status_time",
        "contact_discovery_run",
        ["status", "started_at"],
    )


def downgrade() -> None:
    op.drop_table("contact_discovery_run")
    op.drop_table("acquisition_contact")
