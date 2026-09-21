"""Persist an immutable A1 page plan and independent page checkpoints."""

import sqlalchemy as sa
from alembic import op

revision = "0074_milomail_a1_sample_plan"
down_revision = "0073_milomail_a0_prepaid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("acquisition_census_permit") as batch:
        batch.drop_constraint("ck_census_permit_phase", type_="check")
        batch.drop_constraint("ck_census_permit_caps", type_="check")
        batch.alter_column("phase", existing_type=sa.String(16), type_=sa.String(24))
        batch.add_column(sa.Column("sample_plan_hash", sa.String(64)))
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
    op.create_table(
        "acquisition_census_sample_plan",
        sa.Column("plan_id", sa.String(64), primary_key=True),
        sa.Column("census_id", sa.String(64), sa.ForeignKey(
            "acquisition_census_run.census_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("seed", sa.String(64), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("a0_baseline_hash", sa.String(64), nullable=False),
        sa.Column("requested_new_pages", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("requested_new_pages BETWEEN 1 AND 81",
                           name="ck_census_sample_plan_page_cap"),
    )
    op.create_index("ix_census_sample_plan_run", "acquisition_census_sample_plan", ["census_id"])
    op.create_table(
        "acquisition_census_sample_page",
        sa.Column("plan_id", sa.String(64), sa.ForeignKey(
            "acquisition_census_sample_plan.plan_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("partition_id", sa.String(64), sa.ForeignKey(
            "acquisition_census_partition.partition_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("page", sa.Integer, primary_key=True),
        sa.Column("block_start", sa.Integer, nullable=False),
        sa.Column("block_end", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("call_id", sa.String(64), sa.ForeignKey(
            "acquisition_census_call.call_id", ondelete="RESTRICT")),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "page BETWEEN 2 AND 500 AND block_start >= 2 AND block_start <= page "
            "AND page <= block_end AND block_end <= 500", name="ck_census_sample_page_bounds"),
        sa.CheckConstraint("status IN ('PLANNED','COMPLETED','REVIEW_REQUIRED')",
                           name="ck_census_sample_page_status"),
    )
    op.create_index("ix_census_sample_page_progress", "acquisition_census_sample_page",
                    ["plan_id", "status", "partition_id"])


def downgrade() -> None:
    op.drop_index("ix_census_sample_page_progress", table_name="acquisition_census_sample_page")
    op.drop_table("acquisition_census_sample_page")
    op.drop_index("ix_census_sample_plan_run", table_name="acquisition_census_sample_plan")
    op.drop_table("acquisition_census_sample_plan")
    with op.batch_alter_table("acquisition_census_permit") as batch:
        batch.drop_constraint("ck_census_permit_caps", type_="check")
        batch.drop_constraint("ck_census_permit_phase", type_="check")
        batch.drop_column("sample_plan_hash")
        batch.alter_column("phase", existing_type=sa.String(24), type_=sa.String(16))
        batch.create_check_constraint("ck_census_permit_phase",
                                      "phase IN ('COVERAGE','COVERAGE_A0','ENRICHMENT')")
        batch.create_check_constraint("ck_census_permit_caps",
            "max_pages >= 0 AND max_candidates >= 0 AND max_enrichments >= 0 "
            "AND max_credits > 0 AND ((billing_basis = 'PRICED' AND max_cost_chf > 0 "
            "AND price_chf_per_credit > 0) OR (billing_basis = 'PREPAID_SHARED_POOL' "
            "AND phase = 'COVERAGE_A0' AND max_cost_chf = 0 "
            "AND price_chf_per_credit IS NULL AND max_pages = 9 AND max_credits = 9 "
            "AND max_enrichments = 0))")
