"""Census execution permits and bounded official company evidence cache."""

import sqlalchemy as sa
from alembic import op

revision = "0072_milomail_census_readiness"
down_revision = "0071_milomail_shadow_census"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("acquisition_census_run") as batch:
        batch.add_column(sa.Column("official_requests_reserved", sa.Integer, nullable=False,
                                   server_default="0"))
        batch.create_check_constraint("ck_census_official_request_count",
                                      "official_requests_reserved >= 0")
    op.create_table(
        "acquisition_census_permit",
        sa.Column("permit_id", sa.String(64), primary_key=True),
        sa.Column("census_id", sa.String(64), sa.ForeignKey("acquisition_census_run.census_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("program_key", sa.String(32), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("database_id", sa.String(128), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("allowed_partitions", sa.JSON, nullable=False),
        sa.Column("max_pages", sa.Integer, nullable=False),
        sa.Column("max_candidates", sa.Integer, nullable=False),
        sa.Column("max_enrichments", sa.Integer, nullable=False),
        sa.Column("max_credits", sa.Integer, nullable=False),
        sa.Column("max_cost_chf", sa.Numeric(12, 4), nullable=False),
        sa.Column("price_chf_per_credit", sa.Numeric(12, 6), nullable=False),
        sa.Column("pricing_reference", sa.String(256), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("issued_by_reference", sa.String(128), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.CheckConstraint("phase IN ('COVERAGE','ENRICHMENT')", name="ck_census_permit_phase"),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED')", name="ck_census_permit_status"),
        sa.CheckConstraint("max_pages >= 0 AND max_candidates >= 0 AND max_enrichments >= 0 AND max_credits > 0 AND max_cost_chf > 0 AND price_chf_per_credit > 0", name="ck_census_permit_caps"),
    )
    op.create_index("ix_census_permit_run_phase", "acquisition_census_permit", ["census_id", "phase"])
    with op.batch_alter_table("acquisition_census_call") as batch:
        batch.add_column(sa.Column("permit_id", sa.String(64)))
        batch.create_foreign_key("fk_census_call_permit", "acquisition_census_permit", ["permit_id"], ["permit_id"], ondelete="RESTRICT")
    op.create_index("ix_census_call_permit", "acquisition_census_call", ["permit_id"])
    op.create_table(
        "acquisition_census_official_cache",
        sa.Column("query_hash", sa.String(64), primary_key=True),
        sa.Column("source_name", sa.String(64), nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "acquisition_census_company_match",
        sa.Column("census_id", sa.String(64), sa.ForeignKey("acquisition_census_run.census_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("provider_organization_id", sa.String(128), primary_key=True),
        sa.Column("match_evidence", sa.JSON, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_census_company_match_status", "acquisition_census_company_match", ["census_id", "observed_at"])


def downgrade() -> None:
    op.drop_index("ix_census_company_match_status", table_name="acquisition_census_company_match")
    op.drop_table("acquisition_census_company_match")
    op.drop_table("acquisition_census_official_cache")
    op.drop_index("ix_census_call_permit", table_name="acquisition_census_call")
    with op.batch_alter_table("acquisition_census_call") as batch:
        batch.drop_constraint("fk_census_call_permit", type_="foreignkey")
        batch.drop_column("permit_id")
    op.drop_index("ix_census_permit_run_phase", table_name="acquisition_census_permit")
    op.drop_table("acquisition_census_permit")
    with op.batch_alter_table("acquisition_census_run") as batch:
        batch.drop_constraint("ck_census_official_request_count", type_="check")
        batch.drop_column("official_requests_reserved")
