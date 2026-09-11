"""Bounded counters for the assisted Founder workflow."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.accounts.schema import account_landing_signal
from signals.persistence.schema import (
    acquisition_conversion_journey,
    acquisition_runtime_cycle,
    prospect_target,
)


@dataclass(frozen=True)
class AssistedStats:
    cycles: int
    prepared: int
    approved: int
    rejected_by_reason: dict[str, int]
    sent: int
    opened: int
    clicks: int
    landings: int
    profiles_confirmed: int
    instantly_credit_units: int
    instantly_request_count: int


def assisted_stats(engine: Engine, *, since: dt.datetime) -> AssistedStats:
    if since.tzinfo is None or since.utcoffset() is None:
        raise ValueError("stats boundary must be timezone-aware")
    with engine.connect() as connection:
        count = lambda query: int(connection.scalar(query) or 0)
        rejection_rows = connection.execute(
            sa.select(prospect_target.c.rejection_reason, sa.func.count())
            .where(prospect_target.c.rejected_at >= since)
            .group_by(prospect_target.c.rejection_reason)
        ).all()
        landings = sa.select(
            sa.func.count(sa.distinct(acquisition_conversion_journey.c.account_id))
        ).where(
            acquisition_conversion_journey.c.prospect_target_id.is_not(None),
            acquisition_conversion_journey.c.signed_up_at >= since,
        )
        confirmed = (
            sa.select(sa.func.count(sa.distinct(account_landing_signal.c.account_id)))
            .select_from(
                acquisition_conversion_journey.join(
                    account_landing_signal,
                    account_landing_signal.c.account_id
                    == acquisition_conversion_journey.c.account_id,
                )
            )
            .where(
                acquisition_conversion_journey.c.prospect_target_id.is_not(None),
                account_landing_signal.c.profile_confirmed_at >= since,
            )
        )
        return AssistedStats(
            cycles=count(
                sa.select(sa.func.count())
                .select_from(acquisition_runtime_cycle)
                .where(acquisition_runtime_cycle.c.started_at >= since)
            ),
            prepared=count(
                sa.select(sa.func.count())
                .select_from(prospect_target)
                .where(prospect_target.c.created_at >= since)
            ),
            approved=count(
                sa.select(sa.func.count())
                .select_from(prospect_target)
                .where(prospect_target.c.approved_at >= since)
            ),
            rejected_by_reason={str(reason): int(total) for reason, total in rejection_rows},
            sent=count(
                sa.select(sa.func.count())
                .select_from(prospect_target)
                .where(prospect_target.c.sent_at >= since)
            ),
            opened=count(
                sa.select(sa.func.count())
                .select_from(prospect_target)
                .where(prospect_target.c.opened_at >= since)
            ),
            clicks=count(
                sa.select(sa.func.count())
                .select_from(prospect_target)
                .where(prospect_target.c.clicked_at >= since)
            ),
            landings=count(landings),
            profiles_confirmed=count(confirmed),
            instantly_credit_units=count(
                sa.select(sa.func.coalesce(sa.func.sum(prospect_target.c.instantly_credit_units), 0))
                .where(prospect_target.c.sent_at >= since)
            ),
            instantly_request_count=count(
                sa.select(sa.func.coalesce(sa.func.sum(prospect_target.c.instantly_request_count), 0))
                .where(prospect_target.c.sent_at >= since)
            ),
        )


__all__ = ["AssistedStats", "assisted_stats"]
