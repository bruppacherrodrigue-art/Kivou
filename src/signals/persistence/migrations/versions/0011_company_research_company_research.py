"""Add opportunity-scoped company research profile and provider run audit."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_company_research"
down_revision = "0010_contact_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_company_profile",
        sa.Column("acquisition_opportunity_id", sa.String(64), primary_key=True),
        sa.Column("supplier_ref", sa.String(64), nullable=False),
        sa.Column("contact_ref", sa.String(64), nullable=False),
        sa.Column("signal_ref", sa.String(256), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_organization_id", sa.String(128), nullable=False),
        sa.Column("provider_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_source_fingerprint", sa.String(64), nullable=False),
        sa.Column("provider_company_name", sa.Text(), nullable=False),
        sa.Column("provider_primary_domain", sa.String(253)),
        sa.Column("provider_website_url", sa.Text()),
        sa.Column("provider_country", sa.String(128)),
        sa.Column("provider_industry", sa.String(256)),
        sa.Column("provider_employee_count", sa.Integer()),
        sa.Column("provider_founded_year", sa.Integer()),
        sa.Column("provider_short_description", sa.Text()),
        sa.Column("provider_keywords", sa.JSON(), nullable=False),
        sa.Column("supplier_identity_status", sa.String(32), nullable=False),
        sa.Column("contact_role_profile_version", sa.String(64), nullable=False),
        sa.Column("contact_role_tier", sa.Integer(), nullable=False),
        sa.Column("provider_research_status", sa.String(32), nullable=False),
        sa.Column("research_completeness", sa.String(16), nullable=False),
        sa.Column("research_gaps", sa.JSON(), nullable=False),
        sa.Column("size_band", sa.String(16), nullable=False),
        sa.Column("size_band_version", sa.String(64), nullable=False),
        sa.Column("prebuild_version", sa.String(64), nullable=False),
        sa.Column("prebuild_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["acquisition_opportunity_id"],
            ["acquisition_opportunity.acquisition_opportunity_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_ref"], ["acquisition_supplier.supplier_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["contact_ref"], ["acquisition_contact.contact_ref"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("provider = 'apollo'", name="ck_company_profile_provider"),
        sa.CheckConstraint(
            "supplier_identity_status IN ('PROVIDER_IDENTIFIED', 'DOMAIN_CONFLICT')",
            name="ck_company_profile_supplier_identity",
        ),
        sa.CheckConstraint(
            "provider_research_status = 'CURRENT_PROVIDER_RECORD'",
            name="ck_company_profile_provider_status",
        ),
        sa.CheckConstraint(
            "research_completeness IN ('COMPLETE', 'LIMITED')",
            name="ck_company_profile_completeness",
        ),
        sa.CheckConstraint(
            "size_band IN ('UNKNOWN', 'MICRO', 'SMB', 'MID_MARKET', 'ENTERPRISE')",
            name="ck_company_profile_size_band",
        ),
        sa.CheckConstraint(
            "provider_employee_count IS NULL OR "
            "(provider_employee_count >= 0 AND provider_employee_count <= 10000000)",
            name="ck_company_profile_employee_count",
        ),
        sa.CheckConstraint(
            "provider_founded_year IS NULL OR "
            "(provider_founded_year >= 1000 AND provider_founded_year <= 9999)",
            name="ck_company_profile_founded_year",
        ),
        sa.CheckConstraint(
            "contact_role_tier >= 1 AND contact_role_tier <= 4",
            name="ck_company_profile_role_tier",
        ),
    )
    op.create_index(
        "ix_acquisition_company_profile_supplier_ref",
        "acquisition_company_profile",
        ["supplier_ref"],
    )
    op.create_index(
        "ix_acquisition_company_profile_research_completeness",
        "acquisition_company_profile",
        ["research_completeness"],
    )
    op.create_index(
        "ix_company_profile_completeness_updated",
        "acquisition_company_profile",
        ["research_completeness", "updated_at"],
    )
    op.create_table(
        "company_research_run",
        sa.Column("company_research_run_id", sa.String(64), primary_key=True),
        sa.Column("acquisition_opportunity_id", sa.String(64), nullable=False),
        sa.Column("supplier_ref", sa.String(64), nullable=False),
        sa.Column("contact_ref", sa.String(64), nullable=False),
        sa.Column("policy_evaluation_id", sa.String(64), nullable=False, unique=True),
        sa.Column("research_profile_version", sa.String(64), nullable=False),
        sa.Column("research_profile_fingerprint", sa.String(64), nullable=False),
        sa.Column("research_profile", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_endpoint_kind", sa.String(32), nullable=False),
        sa.Column("provider_request_fingerprint", sa.String(64), nullable=False),
        sa.Column("expected_post_policy_version", sa.Integer(), nullable=False),
        sa.Column("planned_provider_credit_units", sa.Integer(), nullable=False),
        sa.Column("observed_provider_credit_units", sa.Integer()),
        sa.Column("provider_calls", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False),
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
            ["contact_ref"], ["acquisition_contact.contact_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["policy_evaluation_id"],
            ["policy_evaluation.evaluation_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("provider = 'apollo'", name="ck_company_run_provider"),
        sa.CheckConstraint(
            "provider_endpoint_kind = 'exact_organization_id'",
            name="ck_company_run_endpoint",
        ),
        sa.CheckConstraint(
            "status IN ('STARTED', 'SUCCESS', 'LIMITED', 'FAILED')",
            name="ck_company_run_status",
        ),
        sa.CheckConstraint(
            "expected_post_policy_version >= 2", name="ck_company_run_expected_version"
        ),
        sa.CheckConstraint(
            "planned_provider_credit_units = 1 AND provider_calls >= 0 AND provider_calls <= 1",
            name="ck_company_run_call_bound",
        ),
        sa.CheckConstraint(
            "observed_provider_credit_units IS NULL OR observed_provider_credit_units >= 0",
            name="ck_company_run_observed_credits",
        ),
    )
    op.create_index("ix_company_research_run_status", "company_research_run", ["status"])
    op.create_index(
        "ix_company_research_run_opportunity_time",
        "company_research_run",
        ["acquisition_opportunity_id", "started_at"],
    )
    op.create_index(
        "ix_company_research_run_status_time",
        "company_research_run",
        ["status", "started_at"],
    )


def downgrade() -> None:
    op.drop_table("company_research_run")
    op.drop_table("acquisition_company_profile")
