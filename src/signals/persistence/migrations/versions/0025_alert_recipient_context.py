"""Bind alert delivery rows to a privacy-safe recipient context.

Revision ID: 0025_alert_recipient_context
Revises: 0024_scheduled_plan_change
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_alert_recipient_context"
down_revision = "0024_scheduled_plan_change"
branch_labels = None
depends_on = None

DELIVERY_TABLE = "signal_alert_delivery"
FINGERPRINT_COLUMN = "recipient_context_fingerprint"
REFUSAL_INDEX = "ix_signal_alert_delivery_recipient_context_refusal"


def upgrade() -> None:
    op.add_column(
        DELIVERY_TABLE,
        sa.Column(FINGERPRINT_COLUMN, sa.String(64)),
    )
    op.create_index(
        REFUSAL_INDEX,
        DELIVERY_TABLE,
        ["account_id", FINGERPRINT_COLUMN, "status", "last_error_code"],
    )


def downgrade() -> None:
    op.drop_index(REFUSAL_INDEX, table_name=DELIVERY_TABLE)
    op.drop_column(DELIVERY_TABLE, FINGERPRINT_COLUMN)
