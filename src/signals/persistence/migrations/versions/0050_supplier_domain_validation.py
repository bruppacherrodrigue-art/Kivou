"""Persist supplier-domain validation and re-verification state.

Revision ID: 0050_supplier_domain_validation
Revises: 0049_supplier_contact_form
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0050_supplier_domain_validation"
down_revision = "0049_supplier_contact_form"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("supplier_directory") as batch:
        batch.add_column(sa.Column("domain_validation_method", sa.String(32)))
        batch.add_column(sa.Column("domain_validation_evidence_url", sa.Text))
        batch.add_column(sa.Column("reverification_required_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("reverification_reason", sa.String(128)))
        batch.create_check_constraint(
            "ck_supplier_directory_domain_validation_method",
            "domain_validation_method IS NULL OR "
            "domain_validation_method IN ('name_word', 'registration_number')",
        )


def downgrade() -> None:
    with op.batch_alter_table("supplier_directory") as batch:
        batch.drop_constraint("ck_supplier_directory_domain_validation_method", type_="check")
        batch.drop_column("reverification_reason")
        batch.drop_column("reverification_required_at")
        batch.drop_column("domain_validation_evidence_url")
        batch.drop_column("domain_validation_method")
