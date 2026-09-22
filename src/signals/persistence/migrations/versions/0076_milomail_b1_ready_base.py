"""Add frozen B1 plan, versioned decisions, private lead view and HTTP ledger."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0076_milomail_b1_ready_base"
down_revision = "0075_milomail_b0_contact_yield"
branch_labels = None
depends_on = None


def _permit_constraints(*, include_b1: bool) -> None:
    phase = "'FRANCE_B1_READY_BASE'," if include_b1 else ""
    b1 = (
        " OR (phase = 'FRANCE_B1_READY_BASE' AND max_pages BETWEEN 0 AND 220 "
        "AND max_candidates BETWEEN 184 AND 7000 AND max_enrichments BETWEEN 1 AND 900 "
        "AND max_credits BETWEEN 1 AND 900 AND sample_plan_hash IS NOT NULL)"
        if include_b1 else ""
    )
    with op.batch_alter_table("acquisition_census_permit") as batch:
        batch.drop_constraint("ck_census_permit_caps", type_="check")
        batch.drop_constraint("ck_census_permit_phase", type_="check")
        batch.create_check_constraint(
            "ck_census_permit_phase",
            "phase IN ('COVERAGE','COVERAGE_A0','COVERAGE_A1_SAMPLE',"
            f"'CONTACT_YIELD_B0',{phase}'ENRICHMENT')",
        )
        batch.create_check_constraint(
            "ck_census_permit_caps",
            "max_pages >= 0 AND max_candidates >= 0 AND max_enrichments >= 0 "
            "AND max_credits > 0 AND ((billing_basis = 'PRICED' AND max_cost_chf > 0 "
            "AND price_chf_per_credit > 0) OR (billing_basis = 'PREPAID_SHARED_POOL' "
            "AND max_cost_chf = 0 AND price_chf_per_credit IS NULL AND ((max_enrichments = 0 "
            "AND ((phase = 'COVERAGE_A0' AND max_pages = 9 AND max_credits = 9 "
            "AND sample_plan_hash IS NULL) OR (phase = 'COVERAGE_A1_SAMPLE' "
            "AND max_pages BETWEEN 1 AND 81 AND max_credits BETWEEN 1 AND 81 "
            "AND sample_plan_hash IS NOT NULL))) OR (phase = 'CONTACT_YIELD_B0' "
            "AND max_pages = 0 AND max_candidates BETWEEN 5 AND 200 "
            "AND max_enrichments BETWEEN 1 AND 400 AND max_credits BETWEEN 1 AND 1500 "
            f"AND sample_plan_hash IS NOT NULL){b1})))",
        )


def upgrade() -> None:
    _permit_constraints(include_b1=True)
    op.create_table(
        "acquisition_census_b1_plan",
        sa.Column("plan_id", sa.String(64), primary_key=True),
        sa.Column("census_id", sa.String(64), sa.ForeignKey("acquisition_census_run.census_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("seed", sa.String(64), nullable=False),
        sa.Column("caps", sa.JSON, nullable=False),
        sa.Column("cumulative_limits", sa.JSON, nullable=False),
        sa.Column("pool_before", sa.Integer, nullable=False),
        sa.Column("pool_after", sa.Integer),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pool_before >= 1000", name="ck_census_b1_pool"),
        sa.CheckConstraint("status IN ('PLANNED','ACTIVE','PAUSED','COMPLETE','REVIEW_REQUIRED')", name="ck_census_b1_plan_status"),
    )
    op.create_index("ix_census_b1_plan_run", "acquisition_census_b1_plan", ["census_id"])
    op.create_table(
        "acquisition_census_b1_page",
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("acquisition_census_b1_plan.plan_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("partition_id", sa.String(64), sa.ForeignKey("acquisition_census_partition.partition_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("page", sa.Integer, primary_key=True),
        sa.Column("allocation_reason", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("call_id", sa.String(64), sa.ForeignKey("acquisition_census_call.call_id", ondelete="RESTRICT")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("page BETWEEN 2 AND 500", name="ck_census_b1_page_bounds"),
        sa.CheckConstraint("status IN ('PLANNED','COMPLETED','REVIEW_REQUIRED')", name="ck_census_b1_page_status"),
    )
    op.create_index("ix_census_b1_page_progress", "acquisition_census_b1_page", ["plan_id", "status"])
    op.create_table(
        "acquisition_census_b1_entry",
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("acquisition_census_b1_plan.plan_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("candidate_id", sa.String(64), sa.ForeignKey("acquisition_census_candidate.candidate_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("selection_rank", sa.Integer, nullable=False),
        sa.Column("stratum", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.JSON),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("selection_rank BETWEEN 1 AND 1200", name="ck_census_b1_rank"),
        sa.CheckConstraint("status IN ('PLANNED','COMPLETE','REVIEW_REQUIRED')", name="ck_census_b1_entry_status"),
        sa.UniqueConstraint("plan_id", "selection_rank", name="uq_census_b1_rank"),
    )
    op.create_index("ix_census_b1_entry_progress", "acquisition_census_b1_entry", ["plan_id", "status", "selection_rank"])
    op.create_table(
        "acquisition_census_b1_decision",
        sa.Column("decision_id", sa.String(64), primary_key=True),
        sa.Column("candidate_id", sa.String(64), sa.ForeignKey("acquisition_census_candidate.candidate_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ruleset_version", sa.String(64), nullable=False),
        sa.Column("prior_decision", sa.String(24)),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("activity_status", sa.String(32), nullable=False),
        sa.Column("reason_codes", sa.JSON, nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("decision IN ('SEND_THEORETICAL','HOLD','NO_SEND')", name="ck_census_b1_decision"),
    )
    op.create_index("ix_census_b1_decision_status", "acquisition_census_b1_decision", ["ruleset_version", "decision"])
    op.create_index("ix_census_b1_decision_history", "acquisition_census_b1_decision", ["candidate_id", "decided_at"])
    op.create_table(
        "acquisition_census_b1_ready_lead",
        sa.Column("candidate_id", sa.String(64), sa.ForeignKey("acquisition_census_candidate.candidate_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("program_key", sa.String(32), nullable=False),
        sa.Column("first_name", sa.String(128)),
        sa.Column("role", sa.String(128)),
        sa.Column("company_name", sa.String(512)),
        sa.Column("company_domain", sa.String(253), nullable=False),
        sa.Column("professional_email", sa.String(320), nullable=False),
        sa.Column("sector", sa.String(64), nullable=False),
        sa.Column("size_band", sa.String(16), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("segment", sa.String(64), nullable=False),
        sa.Column("provider_evidence", sa.JSON, nullable=False),
        sa.Column("ruleset_version", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("primary_reason", sa.String(128)),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("suppressed", sa.Boolean, nullable=False),
        sa.UniqueConstraint("program_key", "professional_email", name="uq_census_b1_program_email"),
        sa.CheckConstraint("decision IN ('READY_THEORETICAL','HOLD','NO_SEND')", name="ck_census_b1_lead_status"),
    )
    op.create_index("ix_census_b1_lead_segment", "acquisition_census_b1_ready_lead", ["decision", "segment"])
    op.create_table(
        "acquisition_census_legal_http_attempt",
        sa.Column("attempt_id", sa.String(64), primary_key=True),
        sa.Column("census_id", sa.String(64), sa.ForeignKey("acquisition_census_run.census_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("candidate_id", sa.String(64), sa.ForeignKey("acquisition_census_candidate.candidate_id", ondelete="RESTRICT")),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("request_type", sa.String(32), nullable=False),
        sa.Column("proof_type", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer),
        sa.Column("cache_hit", sa.Boolean, nullable=False),
    )
    op.create_index("ix_census_legal_http_run", "acquisition_census_legal_http_attempt", ["census_id", "request_type", "outcome"])


def downgrade() -> None:
    op.drop_index("ix_census_legal_http_run", table_name="acquisition_census_legal_http_attempt")
    op.drop_table("acquisition_census_legal_http_attempt")
    op.drop_index("ix_census_b1_lead_segment", table_name="acquisition_census_b1_ready_lead")
    op.drop_table("acquisition_census_b1_ready_lead")
    op.drop_index("ix_census_b1_decision_history", table_name="acquisition_census_b1_decision")
    op.drop_index("ix_census_b1_decision_status", table_name="acquisition_census_b1_decision")
    op.drop_table("acquisition_census_b1_decision")
    op.drop_index("ix_census_b1_entry_progress", table_name="acquisition_census_b1_entry")
    op.drop_table("acquisition_census_b1_entry")
    op.drop_index("ix_census_b1_page_progress", table_name="acquisition_census_b1_page")
    op.drop_table("acquisition_census_b1_page")
    op.drop_index("ix_census_b1_plan_run", table_name="acquisition_census_b1_plan")
    op.drop_table("acquisition_census_b1_plan")
    _permit_constraints(include_b1=False)
