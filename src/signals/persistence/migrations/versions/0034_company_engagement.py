"""Contact et note par entreprise, dernière visite du compte.

Revision ID: 0034_company_engagement
Revises: 0033_requeue_unresolved_siret
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_company_engagement"
down_revision = "0033_requeue_unresolved_siret"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_contact",
        sa.Column(
            "account_id",
            sa.String(64),
            sa.ForeignKey("account.account_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("company_key", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('to_contact', 'contacted', 'replied')",
            name="ck_company_contact_status",
        ),
    )
    op.create_index(
        "ix_company_contact_status",
        "company_contact",
        ["status"],
    )

    op.create_table(
        "company_note",
        sa.Column(
            "account_id",
            sa.String(64),
            sa.ForeignKey("account.account_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("company_key", sa.String(64), primary_key=True),
        sa.Column("body", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    with op.batch_alter_table("account") as batch:
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("account") as batch:
        batch.drop_column("last_seen_at")

    op.drop_table("company_note")
    op.drop_table("company_contact")
