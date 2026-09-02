"""Record whether company identity facts came from a notice or official register.

Revision ID: 0031_french_official_company
Revises: 0030_winner_enrichment
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_french_official_company"
down_revision = "0030_winner_enrichment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("saas_company") as batch:
        batch.add_column(
            sa.Column(
                "official_source",
                sa.String(32),
                nullable=False,
                server_default="public_notice",
            )
        )
        batch.create_check_constraint(
            "ck_saas_company_official_source",
            "official_source IN ('public_notice', 'official_register')",
        )


def downgrade() -> None:
    with op.batch_alter_table("saas_company") as batch:
        batch.drop_constraint("ck_saas_company_official_source", type_="check")
        batch.drop_column("official_source")
