"""Complete the cold-mail landing journal.

Revision ID: 0038_landing_journey
Revises: 0037_portal_capture_runtime
"""

import sqlalchemy as sa
from alembic import op

revision = "0038_landing_journey"
down_revision = "0037_portal_capture_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("account_landing_signal") as batch:
        batch.add_column(sa.Column("token_fingerprint", sa.String(64)))
        batch.add_column(sa.Column("signal_opened_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("confirmation_started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("profile_confirmed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("dashboard_ready_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("account_landing_signal") as batch:
        batch.drop_column("dashboard_ready_at")
        batch.drop_column("profile_confirmed_at")
        batch.drop_column("confirmation_started_at")
        batch.drop_column("signal_opened_at")
        batch.drop_column("token_fingerprint")
