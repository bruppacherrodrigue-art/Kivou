"""Value-aware ordering and retention for the asynchronous For You queue."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.persistence.schema import (
    contract_award,
    for_you_sentence,
    materialized_signal,
    opportunity_representation,
)


@dataclass(frozen=True)
class ForYouProspectionScope:
    vertical: str
    subdivision_codes: tuple[str, ...]


@dataclass(frozen=True)
class ForYouQueueAudit:
    before: int
    older_than_30_days: int
    inactive_profile: int
    overlap: int
    deleted: int
    after: int

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


def _latest_decision_date() -> sa.ColumnElement:
    representations = opportunity_representation.alias("for_you_opportunity_representation")
    awards = contract_award.alias("for_you_contract_award")
    return (
        sa.select(
            sa.func.max(sa.func.coalesce(awards.c.award_date, awards.c.contract_notification_date))
        )
        .select_from(
            representations.join(awards, representations.c.award_key == awards.c.award_key)
        )
        .where(representations.c.opportunity_key == materialized_signal.c.opportunity_key)
        .correlate(materialized_signal)
        .scalar_subquery()
    )


def _queue_source() -> sa.FromClause:
    return for_you_sentence.outerjoin(
        materialized_signal,
        for_you_sentence.c.signal_key == materialized_signal.c.signal_key,
    ).outerjoin(
        target_icp,
        for_you_sentence.c.target_icp_id == target_icp.c.target_icp_id,
    )


def _reclaimable(now: dt.datetime) -> sa.ColumnElement:
    return sa.or_(
        for_you_sentence.c.state == "pending",
        sa.and_(
            for_you_sentence.c.state == "running",
            for_you_sentence.c.lease_expires_at <= now,
        ),
    )


def _active() -> sa.ColumnElement:
    return sa.and_(
        materialized_signal.c.signal_key.isnot(None),
        materialized_signal.c.invalidated_at.is_(None),
        materialized_signal.c.target_icp_revision == target_icp.c.matching_revision,
        target_icp.c.status == "active",
    )


def audit_and_purge_queue(
    connection: sa.Connection,
    *,
    now: dt.datetime,
    apply: bool,
) -> ForYouQueueAudit:
    """Audit and optionally delete non-client-visible executable backlog."""

    cutoff = now.astimezone(dt.UTC).date() - dt.timedelta(days=30)
    decision_date = _latest_decision_date()
    old = sa.or_(decision_date.is_(None), decision_date < cutoff)
    inactive = sa.not_(_active())
    base = (
        sa.select(for_you_sentence.c.for_you_id)
        .select_from(_queue_source())
        .where(_reclaimable(now))
    )

    def count(extra: sa.ColumnElement | None = None) -> int:
        statement = base if extra is None else base.where(extra)
        return int(
            connection.scalar(sa.select(sa.func.count()).select_from(statement.subquery())) or 0
        )

    before = count()
    old_count = count(old)
    inactive_count = count(inactive)
    overlap = count(sa.and_(old, inactive))
    doomed = base.where(sa.or_(old, inactive))
    deleted = 0
    if apply:
        result = connection.execute(
            sa.delete(for_you_sentence).where(
                for_you_sentence.c.for_you_id.in_(doomed.scalar_subquery())
            )
        )
        deleted = int(result.rowcount or 0)
    after = before - deleted
    return ForYouQueueAudit(before, old_count, inactive_count, overlap, deleted, after)


def prioritized_claim_query(
    *,
    now: dt.datetime,
    limit: int,
    scope: ForYouProspectionScope | None,
    for_you_ids: tuple[str, ...] | None,
) -> sa.Select:
    cutoff = now.astimezone(dt.UTC).date() - dt.timedelta(days=30)
    decision_date = _latest_decision_date()
    horizon = now.astimezone(dt.UTC).date()
    recent = sa.and_(decision_date >= cutoff, decision_date <= horizon)
    active_recent = sa.and_(_active(), recent)
    active_pair = active_recent
    if scope is not None:
        active_pair = sa.and_(
            active_pair,
            materialized_signal.c.inferred_trade_domain == scope.vertical,
            sa.exists(
                sa.select(sa.literal(1))
                .select_from(
                    opportunity_representation.join(
                        contract_award,
                        opportunity_representation.c.award_key == contract_award.c.award_key,
                    )
                )
                .where(
                    opportunity_representation.c.opportunity_key
                    == materialized_signal.c.opportunity_key,
                    contract_award.c.place_of_performance["subdivision_code"]
                    .as_string()
                    .in_(scope.subdivision_codes),
                )
                .correlate(materialized_signal)
            ),
        )
    else:
        active_pair = sa.false()
    priority = sa.case((active_pair, 0), (active_recent, 1), else_=2)
    query = (
        sa.select(for_you_sentence.c.for_you_id, for_you_sentence.c.input_snapshot)
        .select_from(_queue_source())
        .where(_reclaimable(now))
        .order_by(
            priority,
            decision_date.desc(),
            for_you_sentence.c.created_at,
            for_you_sentence.c.for_you_id,
        )
        .limit(limit)
    )
    if for_you_ids is not None:
        query = query.where(for_you_sentence.c.for_you_id.in_(for_you_ids))
    return query


__all__ = [
    "ForYouProspectionScope",
    "ForYouQueueAudit",
    "audit_and_purge_queue",
    "prioritized_claim_query",
]
