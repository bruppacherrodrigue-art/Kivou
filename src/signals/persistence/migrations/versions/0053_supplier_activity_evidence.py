"""Persist supplier activity evidence used by family membership.

Revision ID: 0053_supplier_activity
Revises: 0052_assisted_observation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0053_supplier_activity"
down_revision = "0052_assisted_observation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("supplier_directory") as batch:
        batch.add_column(sa.Column("naf_label", sa.Text))
        batch.add_column(sa.Column("naf_label_observed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("website_title", sa.Text))
        batch.add_column(sa.Column("website_title_observed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("supplier_directory") as batch:
        batch.drop_column("website_title_observed_at")
        batch.drop_column("website_title")
        batch.drop_column("naf_label_observed_at")
        batch.drop_column("naf_label")
