"""Identify recipe landings without rewriting commercial history."""

import sqlalchemy as sa
from alembic import op

revision = "0043_qa_landing"
down_revision = "0042_account_deletion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("account_landing_signal", sa.Column(
        "qa", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))


def downgrade() -> None:
    with op.batch_alter_table("account_landing_signal") as batch:
        batch.drop_column("qa")
