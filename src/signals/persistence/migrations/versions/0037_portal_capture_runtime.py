"""État de discipline et motif d'accès des portails.

Revision ID: 0037_portal_capture_runtime
Revises: 0036_procedure_documents
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_portal_capture_runtime"
down_revision = "0036_procedure_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("procedure_documents") as batch:
        batch.add_column(sa.Column("access_detail", sa.String(128)))
        batch.add_column(
            sa.Column(
                "classified_requirements_count",
                sa.Integer,
                nullable=False,
                server_default="0",
            )
        )
    op.create_table(
        "portal_capture_runtime",
        sa.Column("host", sa.String(255), primary_key=True),
        sa.Column("consecutive_errors", sa.Integer, nullable=False),
        sa.Column("last_request_at", sa.DateTime(timezone=True)),
        sa.Column("blocked_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_portal_capture_runtime_blocked_until",
        "portal_capture_runtime",
        ["blocked_until"],
    )


def downgrade() -> None:
    op.drop_table("portal_capture_runtime")
    with op.batch_alter_table("procedure_documents") as batch:
        batch.drop_column("classified_requirements_count")
        batch.drop_column("access_detail")
