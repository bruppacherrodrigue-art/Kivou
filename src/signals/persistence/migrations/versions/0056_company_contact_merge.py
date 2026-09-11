"""Join the company-enrichment and company-contact migration branches.

Revision ID: 0056_company_contact_merge
Revises: 0055_company_enrichment, 0054_company_contact_lookup
"""

from __future__ import annotations

revision = "0056_company_contact_merge"
down_revision = ("0055_company_enrichment", "0054_company_contact_lookup")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
