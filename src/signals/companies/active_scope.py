"""Shared database predicate for current signals owned by active accounts."""

from __future__ import annotations

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.persistence.schema import materialized_signal


def active_account_signal_exists(signal_key) -> sa.ColumnElement[bool]:
    return sa.exists(
        sa.select(sa.literal(1))
        .select_from(
            materialized_signal.join(
                target_icp,
                materialized_signal.c.target_icp_id == target_icp.c.target_icp_id,
            )
        )
        .where(
            materialized_signal.c.signal_key == signal_key,
            materialized_signal.c.invalidated_at.is_(None),
            materialized_signal.c.target_icp_revision == target_icp.c.matching_revision,
            target_icp.c.status == "active",
        )
    )


__all__ = ["active_account_signal_exists"]
