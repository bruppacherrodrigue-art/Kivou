"""Join the deployed model-budget and V11 histories without altering data."""

revision = "0061_company_live_merge"
down_revision = ("0058_model_call_budget", "0060_boamp_notice_facts")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
