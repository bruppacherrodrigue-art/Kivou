"""Make the Founder prospect-mail contract persistent and fail closed.

Revision ID: 0054_prospect_mail_contract
Revises: 0053_supplier_activity
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0054_prospect_mail_contract"
down_revision = "0053_supplier_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("prospect_target") as batch:
        batch.add_column(sa.Column("signal_department", sa.Text))
        batch.add_column(
            sa.Column(
                "mail_contract_status",
                sa.String(16),
                nullable=False,
                server_default="failed",
            )
        )
        batch.add_column(
            sa.Column(
                "mail_contract_failure",
                sa.String(128),
                server_default="legacy_template",
            )
        )
    op.execute(
        sa.text(
            "UPDATE prospect_target SET signal_department = signal_location "
            "WHERE signal_department IS NULL"
        )
    )
    with op.batch_alter_table("prospect_target") as batch:
        batch.drop_constraint("ck_prospect_target_words", type_="check")
        batch.create_check_constraint(
            "ck_prospect_target_words",
            "mail_word_count BETWEEN 1 AND 90",
        )
        batch.create_check_constraint(
            "ck_prospect_target_mail_contract",
            "(mail_contract_status = 'passed' AND mail_contract_failure IS NULL) OR "
            "(mail_contract_status = 'failed' AND mail_contract_failure IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("prospect_target") as batch:
        batch.drop_constraint("ck_prospect_target_mail_contract", type_="check")
        batch.drop_constraint("ck_prospect_target_words", type_="check")
        batch.create_check_constraint(
            "ck_prospect_target_words",
            "mail_word_count BETWEEN 1 AND 120",
        )
        batch.drop_column("mail_contract_failure")
        batch.drop_column("mail_contract_status")
        batch.drop_column("signal_department")
