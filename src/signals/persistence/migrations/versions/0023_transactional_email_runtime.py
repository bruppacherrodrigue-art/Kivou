"""Add durable transactional alert delivery runtime state.

Revision ID: 0023_transactional_email_runtime
Revises: 0022_saas_company_profile
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_transactional_email_runtime"
down_revision = "0022_saas_company_profile"
branch_labels = None
depends_on = None

DELIVERY_TABLE = "signal_alert_delivery"
LEASE_TABLE = "signal_alert_job_lease"


def upgrade() -> None:
    op.add_column(DELIVERY_TABLE, sa.Column("batch_key", sa.String(64)))
    op.add_column(DELIVERY_TABLE, sa.Column("delivery_message_id", sa.String(255)))
    op.add_column(DELIVERY_TABLE, sa.Column("retryable", sa.Boolean()))
    op.add_column(
        DELIVERY_TABLE,
        sa.Column("attempt_started_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        DELIVERY_TABLE,
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        DELIVERY_TABLE,
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        DELIVERY_TABLE,
        sa.Column("suppressed_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        DELIVERY_TABLE,
        sa.Column("suppression_reason_code", sa.String(64)),
    )

    delivery = sa.table(
        DELIVERY_TABLE,
        sa.column("status", sa.String(32)),
        sa.column("retryable", sa.Boolean()),
        sa.column("next_attempt_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        sa.update(delivery)
        .where(delivery.c.status.in_(("failed", "unknown_delivery_state")))
        .values(retryable=False, next_attempt_at=None)
    )

    op.create_index(
        "ix_signal_alert_delivery_batch_key",
        DELIVERY_TABLE,
        ["batch_key"],
    )
    op.create_index(
        "ix_signal_alert_delivery_lease_expires_at",
        DELIVERY_TABLE,
        ["lease_expires_at"],
    )
    op.create_index(
        "ix_signal_alert_delivery_next_attempt_at",
        DELIVERY_TABLE,
        ["next_attempt_at"],
    )
    with op.batch_alter_table(DELIVERY_TABLE) as batch_op:
        batch_op.create_check_constraint(
            "ck_alert_delivery_status",
            "status IN ('queued', 'sending', 'sent', 'failed', "
            "'unknown_delivery_state', 'suppressed')",
        )

    op.create_table(
        LEASE_TABLE,
        sa.Column("job_name", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_signal_alert_job_lease_lease_expires_at",
        LEASE_TABLE,
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_signal_alert_job_lease_lease_expires_at",
        table_name=LEASE_TABLE,
    )
    op.drop_table(LEASE_TABLE)

    with op.batch_alter_table(DELIVERY_TABLE) as batch_op:
        batch_op.drop_constraint("ck_alert_delivery_status", type_="check")
    op.drop_index(
        "ix_signal_alert_delivery_next_attempt_at",
        table_name=DELIVERY_TABLE,
    )
    op.drop_index(
        "ix_signal_alert_delivery_lease_expires_at",
        table_name=DELIVERY_TABLE,
    )
    op.drop_index(
        "ix_signal_alert_delivery_batch_key",
        table_name=DELIVERY_TABLE,
    )
    with op.batch_alter_table(DELIVERY_TABLE) as batch_op:
        batch_op.drop_column("suppression_reason_code")
        batch_op.drop_column("suppressed_at")
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("attempt_started_at")
        batch_op.drop_column("retryable")
        batch_op.drop_column("delivery_message_id")
        batch_op.drop_column("batch_key")
