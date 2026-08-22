"""Bounded materialization of persisted opportunities for one active TargetICP."""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging

import sqlalchemy as sa

from signals.accounts.icp_input import TargetIcpInput, to_target_icp
from signals.accounts.schema import target_icp
from signals.feed.policy import CANDIDATE_SCAN_CAP
from signals.feed.query import is_customer_display_name
from signals.ingestion.persisted import canonical_award, canonical_event
from signals.matching import MatchingEngine
from signals.needs import NeedGraphEngine
from signals.persistence import materialize_signal
from signals.persistence.schema import (
    contract_award,
    materialized_signal,
    opportunity_representation,
    source_event,
)
from signals.recency import assess_recency
from signals.understanding import ContractUnderstandingEngine

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class BackfillResult:
    candidates_available: int = 0
    candidates_evaluated: int = 0
    signals_materialized: int = 0
    signals_invalidated: int = 0
    truncated: bool = False


def _target_state(connection: sa.Connection, target_icp_id: str):
    row = connection.execute(
        sa.select(
            target_icp.c.target_icp_id,
            target_icp.c.label,
            target_icp.c.status,
            target_icp.c.matching_revision,
            target_icp.c.plan_limit_code,
            target_icp.c.customer_input,
        ).where(target_icp.c.target_icp_id == target_icp_id)
    ).one_or_none()
    if row is None:
        return None
    profile = None
    if row.status == "active" and row.plan_limit_code is None:
        profile = to_target_icp(
            TargetIcpInput.model_validate(row.customer_input),
            target_icp_id=row.target_icp_id,
            label=row.label,
        )
    return profile, row.matching_revision


def _candidate_query(publication_floor: dt.date) -> sa.Select:
    return (
        sa.select(
            opportunity_representation.c.opportunity_key,
            sa.func.max(source_event.c.published_on).label("latest_publication"),
        )
        .select_from(
            opportunity_representation.join(
                contract_award,
                opportunity_representation.c.award_key == contract_award.c.award_key,
            ).join(source_event, contract_award.c.event_key == source_event.c.event_key)
        )
        .where(source_event.c.published_on >= publication_floor)
        .group_by(opportunity_representation.c.opportunity_key)
    )


def _has_customer_name(award) -> bool:
    for party in award.awardee_parties:
        for member in party.members:
            organization = member.organization
            identifier = organization.identifiers[0] if organization.identifiers else None
            if is_customer_display_name(
                organization.legal_name,
                identifier.value if identifier else None,
            ):
                return True
    return False


def _representatives(
    connection: sa.Connection, opportunity_keys: tuple[str, ...]
) -> tuple[tuple[object, object], ...]:
    if not opportunity_keys:
        return ()
    rows = connection.execute(
        sa.select(opportunity_representation.c.opportunity_key, source_event, contract_award)
        .select_from(
            opportunity_representation.join(
                contract_award,
                opportunity_representation.c.award_key == contract_award.c.award_key,
            ).join(source_event, contract_award.c.event_key == source_event.c.event_key)
        )
        .where(opportunity_representation.c.opportunity_key.in_(opportunity_keys))
        .order_by(opportunity_representation.c.opportunity_key, contract_award.c.award_key)
    ).all()
    grouped: dict[str, list[tuple[object, object, str]]] = {}
    for row in rows:
        event = canonical_event(row)
        award = canonical_award(row, event)
        grouped.setdefault(row.opportunity_key, []).append((event, award, row.award_key))
    selected = []
    for opportunity_key in opportunity_keys:
        choices = grouped.get(opportunity_key, [])
        if not choices:
            continue
        event, award, _ = min(
            choices,
            key=lambda item: (not _has_customer_name(item[1]), item[2]),
        )
        selected.append((event, award))
    return tuple(selected)


def _publication_date(event) -> dt.date | None:
    published = event.published_at
    return published.date() if isinstance(published, dt.datetime) else published


def materialize_existing_opportunities_for_target(
    engine: sa.Engine,
    *,
    target_icp_id: str,
    as_of: dt.date,
    materialized_at: dt.datetime,
    max_candidates: int = CANDIDATE_SCAN_CAP,
) -> BackfillResult:
    """Evaluate a bounded persisted set; only the existing `show` may materialize."""
    with engine.begin() as connection:
        return rematerialize_target_in_transaction(
            connection,
            target_icp_id=target_icp_id,
            as_of=as_of,
            materialized_at=materialized_at,
            max_candidates=max_candidates,
        )


def rematerialize_target_in_transaction(
    connection: sa.Connection,
    *,
    target_icp_id: str,
    as_of: dt.date,
    materialized_at: dt.datetime,
    max_candidates: int = CANDIDATE_SCAN_CAP,
) -> BackfillResult:
    """Réconcilie une révision ICP dans la transaction de son appelant.

    Les opportunités déjà liées au profil sont toujours réévaluées, même si
    elles sortent de la fenêtre bornée des nouveaux candidats. Cela permet de
    décider explicitement si leur ancienne correspondance reste valable.
    """
    if not 1 <= max_candidates <= CANDIDATE_SCAN_CAP:
        raise ValueError(f"max_candidates must be between 1 and {CANDIDATE_SCAN_CAP}")
    state = _target_state(connection, target_icp_id)
    if state is None:
        return BackfillResult()
    profile, matching_revision = state
    if profile is None:
        invalidated = connection.execute(
            sa.update(materialized_signal)
            .where(
                materialized_signal.c.target_icp_id == target_icp_id,
                materialized_signal.c.invalidated_at.is_(None),
            )
            .values(
                invalidated_at=materialized_at,
                invalidation_reason="target_icp_not_usable",
            )
        ).rowcount
        return BackfillResult(signals_invalidated=invalidated)

    publication_floor = as_of - dt.timedelta(days=profile.maximum_signal_age_days)
    candidates = _candidate_query(publication_floor).subquery()
    available = connection.execute(sa.select(sa.func.count()).select_from(candidates)).scalar_one()
    recent_keys = tuple(
        connection.execute(
            sa.select(candidates.c.opportunity_key)
            .order_by(
                candidates.c.latest_publication.desc(),
                candidates.c.opportunity_key,
            )
            .limit(max_candidates)
        ).scalars()
    )
    existing_keys = tuple(
        connection.execute(
            sa.select(materialized_signal.c.opportunity_key).where(
                materialized_signal.c.target_icp_id == target_icp_id
            )
        ).scalars()
    )
    keys = tuple(dict.fromkeys((*recent_keys, *existing_keys)))
    representatives = _representatives(connection, keys)

    truncated = available > max_candidates
    if truncated:
        logger.warning(
            "target opportunity backfill truncated",
            extra={
                "target_icp_id": target_icp_id,
                "candidates_available": available,
                "candidate_limit": max_candidates,
            },
        )

    understanding_engine = ContractUnderstandingEngine()
    need_engine = NeedGraphEngine()
    matching_engine = MatchingEngine()
    materialized = 0
    for event, award in representatives:
        understanding = understanding_engine.understand(award, event)
        needs = need_engine.derive(understanding)
        match = matching_engine.match(understanding, needs, profile, as_of=as_of)
        if match.decision != "show":
            continue
        recency = assess_recency(
            award_date=award.award_date,
            contract_notification_date=award.contract_notification_date,
            publication_date=_publication_date(event),
            discovered_at=(
                event.provenance.retrieved_at.date() if event.provenance.retrieved_at else None
            ),
            as_of=as_of,
        )
        result = materialize_signal(
            connection,
            event=event,
            award=award,
            understanding=understanding,
            needs=needs,
            match=match,
            recency=recency,
            as_of=as_of,
            materialized_at=materialized_at,
            target_icp_revision=matching_revision,
        )
        materialized += result.created or result.updated
    invalidated = connection.execute(
        sa.update(materialized_signal)
        .where(
            materialized_signal.c.target_icp_id == target_icp_id,
            materialized_signal.c.target_icp_revision != matching_revision,
            materialized_signal.c.invalidated_at.is_(None),
        )
        .values(
            invalidated_at=materialized_at,
            invalidation_reason="target_icp_criteria_changed",
        )
    ).rowcount
    return BackfillResult(
        candidates_available=available,
        candidates_evaluated=len(representatives),
        signals_materialized=materialized,
        signals_invalidated=invalidated,
        truncated=truncated,
    )
