"""Merge the asynchronous prospect-send and Chief of Staff branches.

Revision ID: 0066_async_chief_merge
Revises: 0065_async_prospect_send, 0065_chief_of_staff
"""

from __future__ import annotations

revision = "0066_async_chief_merge"
down_revision = ("0065_async_prospect_send", "0065_chief_of_staff")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join the two independently additive schema histories."""


def downgrade() -> None:
    """Split back to the two independent migration heads."""
