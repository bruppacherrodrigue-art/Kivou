"""Durable, program-scoped SHADOW census checkpoints and credit reservations."""

import sqlalchemy as sa
from alembic import op

revision = "0071_milomail_shadow_census"
down_revision = "0070_program_conversion_receipt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_census_run",
        sa.Column("census_id", sa.String(64), primary_key=True),
        sa.Column("program_id", sa.String(64), sa.ForeignKey("acquisition_program.program_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("filter_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("limits_snapshot", sa.JSON),
        sa.Column("pages_reserved", sa.Integer, nullable=False),
        sa.Column("candidate_slots_reserved", sa.Integer, nullable=False),
        sa.Column("enrichments_reserved", sa.Integer, nullable=False),
        sa.Column("credits_reserved", sa.Integer, nullable=False),
        sa.Column("actual_apollo_credits", sa.Integer),
        sa.Column("actual_cost_chf", sa.Numeric(12, 4)),
        sa.Column("usage_evidence_ref", sa.String(128)),
        sa.Column("usage_reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('PLANNED','ACTIVE','PAUSED','COMPLETE','REVIEW_REQUIRED')", name="ck_census_run_status"),
        sa.CheckConstraint("pages_reserved >= 0 AND candidate_slots_reserved >= 0 AND enrichments_reserved >= 0 AND credits_reserved >= 0", name="ck_census_run_reservations"),
        sa.CheckConstraint("actual_apollo_credits IS NULL OR actual_apollo_credits >= 0", name="ck_census_actual_credits"),
        sa.CheckConstraint("actual_cost_chf IS NULL OR actual_cost_chf >= 0", name="ck_census_actual_cost"),
    )
    op.create_index("ix_census_run_program", "acquisition_census_run", ["program_id", "created_at"])
    op.create_table(
        "acquisition_census_partition",
        sa.Column("partition_id", sa.String(64), primary_key=True),
        sa.Column("census_id", sa.String(64), sa.ForeignKey("acquisition_census_run.census_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("filter_signature", sa.String(64), nullable=False),
        sa.Column("parent_partition_id", sa.String(64), sa.ForeignKey("acquisition_census_partition.partition_id", ondelete="RESTRICT")),
        sa.Column("filters", sa.JSON, nullable=False),
        sa.Column("sector", sa.String(64), nullable=False),
        sa.Column("size_min", sa.Integer, nullable=False),
        sa.Column("size_max", sa.Integer, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("cursor_page", sa.Integer, nullable=False),
        sa.Column("estimated_result_count", sa.Integer),
        sa.Column("processed_count", sa.Integer, nullable=False),
        sa.Column("unique_count", sa.Integer, nullable=False),
        sa.Column("duplicate_count", sa.Integer, nullable=False),
        sa.Column("credit_count", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(64)),
        sa.UniqueConstraint("census_id", "filter_signature", name="uq_census_filter_signature"),
        sa.CheckConstraint("size_min > 0 AND size_max >= size_min AND cursor_page > 0", name="ck_census_partition_bounds"),
        sa.CheckConstraint("status IN ('PLANNED','ACTIVE','COMPLETE','INCOMPLETE','REVIEW_REQUIRED')", name="ck_census_partition_status"),
    )
    op.create_index("ix_census_partition_progress", "acquisition_census_partition", ["census_id", "status", "partition_id"])
    op.create_table(
        "acquisition_census_candidate",
        sa.Column("candidate_id", sa.String(64), primary_key=True),
        sa.Column("census_id", sa.String(64), sa.ForeignKey("acquisition_census_run.census_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider_organization_id", sa.String(128), nullable=False),
        sa.Column("primary_domain", sa.String(253)),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("sector", sa.String(64)),
        sa.Column("location", sa.String(512)),
        sa.Column("company_size", sa.Integer),
        sa.Column("role", sa.String(64)),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_confidence", sa.String(16), nullable=False),
        sa.Column("provider_evidence", sa.JSON),
        sa.Column("recipient_provider", sa.String(32)),
        sa.Column("recipient_provider_confidence", sa.String(16)),
        sa.Column("contact_found", sa.Boolean, nullable=False),
        sa.Column("leader_identified", sa.Boolean, nullable=False),
        sa.Column("email_verified", sa.Boolean, nullable=False),
        sa.Column("opportunity_id", sa.String(64), sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT")),
        sa.Column("contact_ref", sa.String(64), sa.ForeignKey("acquisition_contact.contact_ref", ondelete="RESTRICT")),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("decision", sa.String(16)),
        sa.Column("reason_codes", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('PENDING','DECIDED','REVIEW_REQUIRED')", name="ck_census_candidate_status"),
        sa.CheckConstraint("decision IS NULL OR decision IN ('SEND','HOLD','NO_SEND')", name="ck_census_candidate_decision"),
    )
    op.create_index("ix_census_candidate_status", "acquisition_census_candidate", ["census_id", "status"])
    op.create_table(
        "acquisition_census_identity",
        sa.Column("census_id", sa.String(64), sa.ForeignKey("acquisition_census_run.census_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("identity_kind", sa.String(16), primary_key=True),
        sa.Column("identity_hash", sa.String(64), primary_key=True),
        sa.Column("candidate_id", sa.String(64), sa.ForeignKey("acquisition_census_candidate.candidate_id", ondelete="RESTRICT"), nullable=False),
    )
    op.create_index("ix_census_identity_candidate", "acquisition_census_identity", ["candidate_id"])
    op.create_table(
        "acquisition_census_occurrence",
        sa.Column("partition_id", sa.String(64), sa.ForeignKey("acquisition_census_partition.partition_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("candidate_id", sa.String(64), sa.ForeignKey("acquisition_census_candidate.candidate_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("first_page", sa.Integer, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "acquisition_census_call",
        sa.Column("call_id", sa.String(64), primary_key=True),
        sa.Column("census_id", sa.String(64), sa.ForeignKey("acquisition_census_run.census_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("partition_id", sa.String(64), sa.ForeignKey("acquisition_census_partition.partition_id", ondelete="RESTRICT")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reserved_credits", sa.Integer, nullable=False),
        sa.Column("candidate_slots", sa.Integer, nullable=False),
        sa.Column("result_snapshot", sa.JSON),
        sa.Column("result_count", sa.Integer),
        sa.Column("error_category", sa.String(64)),
        sa.Column("retry_after", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("census_id", "kind", "subject_hash", "attempt", name="uq_census_call_attempt"),
        sa.CheckConstraint("status IN ('RESERVED','COMPLETED','RATE_LIMITED','REVIEW_REQUIRED')", name="ck_census_call_status"),
        sa.CheckConstraint("reserved_credits >= 0 AND candidate_slots >= 0 AND attempt > 0", name="ck_census_call_budget"),
        sa.CheckConstraint("result_count IS NULL OR result_count >= 0", name="ck_census_result_count"),
    )
    op.create_index("ix_census_call_run_status", "acquisition_census_call", ["census_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_census_call_run_status", table_name="acquisition_census_call")
    op.drop_table("acquisition_census_call")
    op.drop_table("acquisition_census_occurrence")
    op.drop_index("ix_census_identity_candidate", table_name="acquisition_census_identity")
    op.drop_table("acquisition_census_identity")
    op.drop_index("ix_census_candidate_status", table_name="acquisition_census_candidate")
    op.drop_table("acquisition_census_candidate")
    op.drop_index("ix_census_partition_progress", table_name="acquisition_census_partition")
    op.drop_table("acquisition_census_partition")
    op.drop_index("ix_census_run_program", table_name="acquisition_census_run")
    op.drop_table("acquisition_census_run")
