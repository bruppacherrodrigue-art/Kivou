"""Remove a stale verification marker after provider acceptance.

Revision ID: 0067_acceptance_error_cleanup
Revises: 0066_async_chief_merge
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0067_acceptance_error_cleanup"
down_revision = "0066_async_chief_merge"
branch_labels = None
depends_on = None

_TRANSIENT_VERIFICATION_ERROR = "instantly_email_verification_pending"


def upgrade() -> None:
    """Restore the accepted-target invariant without touching real failures."""
    target = sa.table(
        "prospect_target",
        sa.column("status", sa.String(16)),
        sa.column("instantly_accepted_at", sa.DateTime(timezone=True)),
        sa.column("delivery_error", sa.Text),
    )
    op.execute(
        sa.update(target)
        .where(
            target.c.status == "sent",
            target.c.instantly_accepted_at.is_not(None),
            target.c.delivery_error == _TRANSIENT_VERIFICATION_ERROR,
        )
        .values(delivery_error=None)
    )


def downgrade() -> None:
    """The stale marker is invalid state and must not be recreated."""
