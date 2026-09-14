"""Allow the v2 prospect mail body contract up to 110 words."""

from __future__ import annotations

from alembic import op

revision = "0056_prospect_mail_word_limit_v2"
down_revision = "0055_company_enrichment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("prospect_target") as batch:
        batch.drop_constraint("ck_prospect_target_words", type_="check")
        batch.create_check_constraint(
            "ck_prospect_target_words",
            "mail_word_count BETWEEN 1 AND 110",
        )


def downgrade() -> None:
    with op.batch_alter_table("prospect_target") as batch:
        batch.drop_constraint("ck_prospect_target_words", type_="check")
        batch.create_check_constraint(
            "ck_prospect_target_words",
            "mail_word_count BETWEEN 1 AND 90",
        )
