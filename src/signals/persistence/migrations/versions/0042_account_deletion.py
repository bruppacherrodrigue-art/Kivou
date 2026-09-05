"""Add the durable account deletion request.

Revision ID: 0042_account_deletion
Revises: 0041_for_you_model_fit
"""

import sqlalchemy as sa
from alembic import op

revision = "0042_account_deletion"
down_revision = "0041_for_you_model_fit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_deletion_request",
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("account_id", name="uq_account_deletion_account"),
    )
    op.create_index(
        "ix_account_deletion_request_account_id",
        "account_deletion_request",
        ["account_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_account_deletion_request_account_id", table_name="account_deletion_request")
    op.drop_table("account_deletion_request")
