"""Persist dated supplier contact-form channels.

Revision ID: 0049_supplier_contact_form
Revises: 0048_supplier_directory
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0049_supplier_contact_form"
down_revision = "0048_supplier_directory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("supplier_directory") as batch:
        batch.add_column(sa.Column("contact_form_url", sa.Text))
        batch.add_column(sa.Column("contact_form_observed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("supplier_directory") as batch:
        batch.drop_column("contact_form_observed_at")
        batch.drop_column("contact_form_url")
