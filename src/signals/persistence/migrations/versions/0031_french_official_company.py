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
    op.add_column(
        "saas_company",
        sa.Column(
            "official_source",
            sa.String(32),
            nullable=False,
            server_default="public_notice",
        ),
    )
    op.create_check_constraint(
        "ck_saas_company_official_source",
        "saas_company",
        "official_source IN ('public_notice', 'official_register')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_saas_company_official_source",
        "saas_company",
        type_="check",
    )
    op.drop_column("saas_company", "official_source")
