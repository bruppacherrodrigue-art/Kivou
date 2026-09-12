"""Persist the customer-facing location projection.

Revision ID: 0058_client_location
Revises: 0057_directory_contact_keys
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0058_client_location"
down_revision = "0057_directory_contact_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("contract_award") as batch:
        batch.add_column(sa.Column("client_location", sa.JSON))
        batch.add_column(sa.Column("client_location_basis", sa.String(32)))


def downgrade() -> None:
    with op.batch_alter_table("contract_award") as batch:
        batch.drop_column("client_location_basis")
        batch.drop_column("client_location")
