"""Freeze the B0 organization sample and retain private contact evidence in census DB."""

import sqlalchemy as sa
from alembic import op

revision = "0075_milomail_b0_contact_yield"
down_revision = "0074_milomail_a1_sample_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("acquisition_census_permit") as batch:
        batch.drop_constraint("ck_census_permit_phase", type_="check")
        batch.drop_constraint("ck_census_permit_caps", type_="check")
        batch.create_check_constraint("ck_census_permit_phase",
            "phase IN ('COVERAGE','COVERAGE_A0','COVERAGE_A1_SAMPLE','CONTACT_YIELD_B0','ENRICHMENT')")
        batch.create_check_constraint("ck_census_permit_caps",
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
            "AND sample_plan_hash IS NOT NULL))))")
    op.create_table(
        "acquisition_census_b0_plan",
        sa.Column("plan_id", sa.String(64), primary_key=True),
        sa.Column("census_id", sa.String(64), sa.ForeignKey(
            "acquisition_census_run.census_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("baseline_hash", sa.String(64), nullable=False),
        sa.Column("seed", sa.String(64), nullable=False),
        sa.Column("pool_before", sa.Integer),
        sa.Column("pool_after", sa.Integer),
        sa.Column("credit_cap", sa.Integer, nullable=False),
        sa.Column("minimum_pool_balance", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("credit_cap BETWEEN 1 AND 1500 AND minimum_pool_balance >= 500",
                           name="ck_census_b0_budget"),
        sa.CheckConstraint("status IN ('PLANNED','ACTIVE','PAUSED','COMPLETE','REVIEW_REQUIRED')",
                           name="ck_census_b0_status"),
    )
    op.create_index("ix_census_b0_plan_run", "acquisition_census_b0_plan", ["census_id"])
    op.create_table(
        "acquisition_census_b0_entry",
        sa.Column("plan_id", sa.String(64), sa.ForeignKey(
            "acquisition_census_b0_plan.plan_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("candidate_id", sa.String(64), sa.ForeignKey(
            "acquisition_census_candidate.candidate_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("selection_rank", sa.Integer, nullable=False),
        sa.Column("stratum", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.JSON),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("selection_rank BETWEEN 1 AND 200", name="ck_census_b0_rank"),
        sa.CheckConstraint("status IN ('PLANNED','COMPLETE','REVIEW_REQUIRED')",
                           name="ck_census_b0_entry_status"),
        sa.UniqueConstraint("plan_id", "selection_rank", name="uq_census_b0_rank"),
    )
    op.create_index("ix_census_b0_entry_progress", "acquisition_census_b0_entry",
                    ["plan_id", "status", "selection_rank"])
    op.create_table(
        "acquisition_census_legal_page_cache",
        sa.Column("domain_hash", sa.String(64), primary_key=True),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("acquisition_census_legal_page_cache")
    op.drop_index("ix_census_b0_entry_progress", table_name="acquisition_census_b0_entry")
    op.drop_table("acquisition_census_b0_entry")
    op.drop_index("ix_census_b0_plan_run", table_name="acquisition_census_b0_plan")
    op.drop_table("acquisition_census_b0_plan")
    with op.batch_alter_table("acquisition_census_permit") as batch:
        batch.drop_constraint("ck_census_permit_caps", type_="check")
        batch.drop_constraint("ck_census_permit_phase", type_="check")
        batch.create_check_constraint("ck_census_permit_phase",
            "phase IN ('COVERAGE','COVERAGE_A0','COVERAGE_A1_SAMPLE','ENRICHMENT')")
        batch.create_check_constraint("ck_census_permit_caps",
            "max_pages >= 0 AND max_candidates >= 0 AND max_enrichments >= 0 "
            "AND max_credits > 0 AND ((billing_basis = 'PRICED' AND max_cost_chf > 0 "
            "AND price_chf_per_credit > 0) OR (billing_basis = 'PREPAID_SHARED_POOL' "
            "AND max_cost_chf = 0 AND price_chf_per_credit IS NULL AND max_enrichments = 0 "
            "AND ((phase = 'COVERAGE_A0' AND max_pages = 9 AND max_credits = 9 "
            "AND sample_plan_hash IS NULL) OR (phase = 'COVERAGE_A1_SAMPLE' "
            "AND max_pages BETWEEN 1 AND 81 AND max_credits BETWEEN 1 AND 81 "
            "AND sample_plan_hash IS NOT NULL))))")
