"""Add private account-scoped signal notes.

Revision ID: 0027_signal_notes
Revises: 0026_acquisition_runtime
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_signal_notes"
down_revision = "0026_acquisition_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_note",
        sa.Column(
            "account_id",
            sa.String(64),
            sa.ForeignKey("account.account_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("signal_key", sa.String(64), primary_key=True),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("signal_note")
