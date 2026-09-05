"""Persist the provider fit verdict for each for-you pair.

Revision ID: 0041_for_you_model_fit
Revises: 0040_for_you_raw_diagnostics
"""

import sqlalchemy as sa
from alembic import op

revision = "0041_for_you_model_fit"
down_revision = "0040_for_you_raw_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("for_you_sentence") as batch:
        batch.add_column(sa.Column("model_fit", sa.String(16)))
        batch.create_check_constraint(
            "ck_for_you_model_fit",
            "model_fit IS NULL OR model_fit IN ('strong', 'weak', 'none')",
        )


def downgrade() -> None:
    with op.batch_alter_table("for_you_sentence") as batch:
        batch.drop_constraint("ck_for_you_model_fit", type_="check")
        batch.drop_column("model_fit")
