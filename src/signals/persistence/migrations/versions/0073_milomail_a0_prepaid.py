"""Allow the narrow prepaid staging A0 permit without inventing a CHF unit price."""

import sqlalchemy as sa
from alembic import op

revision = "0073_milomail_a0_prepaid"
down_revision = "0072_milomail_census_readiness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("acquisition_census_permit") as batch:
        batch.drop_constraint("ck_census_permit_phase", type_="check")
        batch.drop_constraint("ck_census_permit_caps", type_="check")
        batch.alter_column("price_chf_per_credit", existing_type=sa.Numeric(12, 6),
                           nullable=True)
        batch.add_column(sa.Column("billing_basis", sa.String(32), nullable=False,
                                   server_default="PRICED"))
        batch.add_column(sa.Column("apollo_secret_ref", sa.String(80)))
        batch.create_check_constraint("ck_census_permit_phase",
                                      "phase IN ('COVERAGE','COVERAGE_A0','ENRICHMENT')")
        batch.create_check_constraint("ck_census_permit_caps",
            "max_pages >= 0 AND max_candidates >= 0 AND max_enrichments >= 0 "
            "AND max_credits > 0 AND ((billing_basis = 'PRICED' AND "
            "max_cost_chf > 0 AND price_chf_per_credit > 0) OR "
            "(billing_basis = 'PREPAID_SHARED_POOL' AND phase = 'COVERAGE_A0' "
            "AND max_cost_chf = 0 AND price_chf_per_credit IS NULL "
            "AND max_pages = 9 AND max_credits = 9 AND max_enrichments = 0))")


def downgrade() -> None:
    with op.batch_alter_table("acquisition_census_permit") as batch:
        batch.drop_constraint("ck_census_permit_caps", type_="check")
        batch.drop_constraint("ck_census_permit_phase", type_="check")
        batch.drop_column("apollo_secret_ref")
        batch.drop_column("billing_basis")
        batch.alter_column("price_chf_per_credit", existing_type=sa.Numeric(12, 6),
                           nullable=False)
        batch.create_check_constraint("ck_census_permit_phase",
                                      "phase IN ('COVERAGE','ENRICHMENT')")
        batch.create_check_constraint("ck_census_permit_caps",
            "max_pages >= 0 AND max_candidates >= 0 AND max_enrichments >= 0 "
            "AND max_credits > 0 AND max_cost_chf > 0 AND price_chf_per_credit > 0")
