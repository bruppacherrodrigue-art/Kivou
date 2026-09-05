"""Retain bounded rejected provider output for diagnostics.

Revision ID: 0040_for_you_raw_diagnostics
Revises: 0039_for_you_sentence
"""

import sqlalchemy as sa
from alembic import op

revision = "0040_for_you_raw_diagnostics"
down_revision = "0039_for_you_sentence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("for_you_sentence") as batch:
        batch.drop_constraint("ck_for_you_validation_reason", type_="check")
        batch.add_column(sa.Column("raw_provider_response", sa.Text))
        batch.add_column(sa.Column("raw_response_expires_at", sa.DateTime(timezone=True)))
        batch.create_index(
            "ix_for_you_sentence_raw_response_expires_at",
            ["raw_response_expires_at"],
        )
        batch.create_check_constraint(
            "ck_for_you_validation_reason",
            "validation_reason IS NULL OR validation_reason IN ('provider_unavailable', 'invalid_shape', 'invalid_content', 'too_many_words', 'exclamation', 'superlative', 'invented_number', 'invented_date', 'invented_name_or_place')",
        )


def downgrade() -> None:
    with op.batch_alter_table("for_you_sentence") as batch:
        batch.drop_constraint("ck_for_you_validation_reason", type_="check")
        batch.drop_index("ix_for_you_sentence_raw_response_expires_at")
        batch.drop_column("raw_response_expires_at")
        batch.drop_column("raw_provider_response")
        batch.create_check_constraint(
            "ck_for_you_validation_reason",
            "validation_reason IS NULL OR validation_reason IN ('provider_unavailable', 'invalid_shape', 'too_many_words', 'exclamation', 'superlative', 'invented_number', 'invented_date', 'invented_name_or_place')",
        )
