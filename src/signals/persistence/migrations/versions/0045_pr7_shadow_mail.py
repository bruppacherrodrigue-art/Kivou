"""Persist PR7 shadow messages for human review.

Revision ID: 0045_pr7_shadow_mail
Revises: 0044_email_verification
"""

import sqlalchemy as sa
from alembic import op

revision = "0045_pr7_shadow_mail"
down_revision = "0044_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_shadow_mail",
        sa.Column("shadow_mail_id", sa.String(64), primary_key=True),
        sa.Column("cycle_ref", sa.String(64), sa.ForeignKey("acquisition_runtime_cycle.cycle_ref", ondelete="CASCADE"), nullable=False),
        sa.Column("opportunity_key", sa.String(256), nullable=False, index=True),
        sa.Column("procedure_award_key", sa.String(64), nullable=False),
        sa.Column("supplier_ref", sa.String(64)),
        sa.Column("contact_ref", sa.String(64)),
        sa.Column("company_name", sa.Text, nullable=False),
        sa.Column("contact_role", sa.String(128), nullable=False),
        sa.Column("masked_email", sa.String(320), nullable=False),
        sa.Column("signal_snapshot", sa.JSON, nullable=False),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("apollo_query", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_day", sa.Date, nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("procedure_award_key", "created_day", name="uq_shadow_mail_procedure_day"),
        sa.CheckConstraint("status = 'SHADOW'", name="ck_shadow_mail_status"),
    )


def downgrade() -> None:
    op.drop_table("acquisition_shadow_mail")
