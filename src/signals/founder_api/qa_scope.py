"""Shared exclusion boundary for Founder conversion metrics."""

from __future__ import annotations

import sqlalchemy as sa

from signals.accounts.schema import account_landing_signal
from signals.persistence.schema import acquisition_conversion_event


def non_qa_conversion_event(
    events: sa.Table = acquisition_conversion_event,
) -> sa.ColumnElement[bool]:
    """Reject an event once either its token or account is durably marked QA."""

    return ~sa.exists(
        sa.select(sa.literal(1))
        .select_from(account_landing_signal)
        .where(
            account_landing_signal.c.qa.is_(True),
            sa.or_(
                sa.and_(
                    events.c.token_fingerprint.is_not(None),
                    account_landing_signal.c.token_fingerprint == events.c.token_fingerprint,
                ),
                sa.and_(
                    events.c.account_id.is_not(None),
                    account_landing_signal.c.account_id == events.c.account_id,
                ),
            ),
        )
        .correlate(events)
    )


__all__ = ["non_qa_conversion_event"]
