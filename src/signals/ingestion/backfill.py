"""Bounded materialization of persisted opportunities for one active TargetICP."""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging

import sqlalchemy as sa

from signals.accounts.icp_input import TargetIcpInput, to_target_icp
from signals.accounts.schema import target_icp
from signals.companies.official_cache import official_holders_for_opportunities
from signals.domain.french_departments import NUTS3_DEPARTMENTS, location_subdivision
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


def _prepare_landing_opportunity(
    connection: sa.Connection,
    *,
    target_icp_id: str,
    opportunity_key: str,
    as_of: dt.date,
    materialized_at: dt.datetime,
) -> dict[str, object] | None:
    """Materialize the decision-engine bait for one account-owned profile.

    The acquisition decision already selected this opportunity for the target.
    We still run the ordinary understanding, needs, matching, recency and
    persistence chain; unlike feed backfill, this nominated promise is not
    discarded when the provisional profile lacks enough detail to reach
    ``show`` on its own.
    """
    state = _target_state(connection, target_icp_id)
    if state is None or state[0] is None:
        return None
    profile, matching_revision = state
    representatives = _representatives(connection, (opportunity_key,))
    if not representatives:
        return None
    event, award = representatives[0]
    understanding = ContractUnderstandingEngine().understand(award, event)
    needs = NeedGraphEngine().derive(understanding)
    match = MatchingEngine().match(understanding, needs, profile, as_of=as_of)
    # The acquisition decision nominated this exact bait before the account
    # existed. Preserve that decision while retaining the ordinary score,
    # reasons and limitations produced for the provisional profile.
    if match.decision != "show":
        match = match.model_copy(update={"decision": "show", "band": "promising"})
    recency = assess_recency(
        award_date=award.award_date,
        contract_notification_date=award.contract_notification_date,
        publication_date=_publication_date(event),
        discovered_at=event.provenance.retrieved_at.date()
        if event.provenance.retrieved_at
        else None,
        as_of=as_of,
    )
    return {
        "event": event,
        "award": award,
        "understanding": understanding,
        "needs": needs,
        "match": match,
        "recency": recency,
        "as_of": as_of,
        "materialized_at": materialized_at,
        "target_icp_revision": matching_revision,
    }


def materialize_landing_opportunity_in_transaction(
    connection: sa.Connection,
    *,
    target_icp_id: str,
    opportunity_key: str,
    as_of: dt.date,
    materialized_at: dt.datetime,
) -> str | None:
    prepared = _prepare_landing_opportunity(
        connection,
        target_icp_id=target_icp_id,
        opportunity_key=opportunity_key,
        as_of=as_of,
        materialized_at=materialized_at,
    )
    if prepared is None:
        return None
    return materialize_signal(connection, **prepared).signal_key


def _department_code(subdivision: str | None) -> str | None:
    if not subdivision:
        return None
    if subdivision.startswith("FR-"):
        return subdivision.removeprefix("FR-")
    return NUTS3_DEPARTMENTS.get(subdivision)


def materialize_landing_feed_in_transaction(
    connection: sa.Connection,
    *,
    target_icp_id: str,
    opportunity_key: str,
    as_of: dt.date,
    materialized_at: dt.datetime,
) -> str | None:
    """Materialize one promised opportunity plus two recent, distinct procedures."""

    bait = _prepare_landing_opportunity(
        connection,
        target_icp_id=target_icp_id,
        opportunity_key=opportunity_key,
        as_of=as_of,
        materialized_at=materialized_at,
    )
    if bait is None:
        return None
    profile, _revision = _target_state(connection, target_icp_id)
    if profile is None:
        return None
    bait_award = bait["award"]
    bait_event = bait["event"]
    bait_place = bait_award.place_of_performance
    bait_department = _department_code(
        location_subdivision(bait_place.model_dump(mode="json") if bait_place else None)
    )
    prefixes = tuple(profile.included_cpv_prefixes)
    effective_date = sa.func.coalesce(
        contract_award.c.award_date,
        contract_award.c.contract_notification_date,
    )
    statement = (
        sa.select(
            opportunity_representation.c.opportunity_key,
            sa.func.max(effective_date).label("effective_date"),
        )
        .select_from(
            opportunity_representation.join(
                contract_award,
                opportunity_representation.c.award_key == contract_award.c.award_key,
            ).join(source_event, contract_award.c.event_key == source_event.c.event_key)
        )
        .where(
            opportunity_representation.c.opportunity_key != opportunity_key,
            source_event.c.source_country == bait_event.provenance.source_country,
            effective_date >= as_of - dt.timedelta(days=30),
            effective_date <= as_of,
            contract_award.c.amount >= 50000,
            sa.func.nullif(sa.func.trim(sa.func.coalesce(contract_award.c.title, "")), "").isnot(
                None
            ),
        )
    )
    if prefixes:
        statement = statement.where(
            sa.or_(*(contract_award.c.cpv_main.startswith(prefix) for prefix in prefixes))
        )
    candidate_keys = tuple(
        connection.execute(
            statement.group_by(opportunity_representation.c.opportunity_key)
            .order_by(sa.desc("effective_date"), opportunity_representation.c.opportunity_key)
            .limit(80)
        ).scalars()
    )
    representatives = {
        key: representative
        for key, representative in zip(candidate_keys, _representatives(connection, candidate_keys))
    }
    cached_holders = official_holders_for_opportunities(connection, candidate_keys)
    procedure = (
        bait_event.provenance.source_system,
        bait_event.provenance.source_procedure_id or bait_event.provenance.source_notice_id,
    )
    used_procedures = {procedure}
    prepared_rows: list[tuple[str, dict[str, object]]] = [(opportunity_key, bait)]
    for key in candidate_keys:
        representative = representatives.get(key)
        if representative is None:
            continue
        event, award = representative
        place = award.place_of_performance
        department = _department_code(
            location_subdivision(place.model_dump(mode="json") if place else None)
        )
        if bait_department is not None and department != bait_department:
            continue
        if not _has_customer_name(award) and key not in cached_holders:
            continue
        procedure = (
            event.provenance.source_system,
            event.provenance.source_procedure_id or event.provenance.source_notice_id,
        )
        if procedure in used_procedures:
            continue
        candidate = _prepare_landing_opportunity(
            connection,
            target_icp_id=target_icp_id,
            opportunity_key=key,
            as_of=as_of,
            materialized_at=materialized_at,
        )
        if candidate is None:
            continue
        prepared_rows.append((key, candidate))
        used_procedures.add(procedure)
        if len(prepared_rows) == 3:
            break

    signal_keys: dict[str, str] = {}
    for key, prepared in prepared_rows:
        signal_keys[key] = materialize_signal(connection, **prepared).signal_key
    connection.execute(
        sa.update(materialized_signal)
        .where(
            materialized_signal.c.target_icp_id == target_icp_id,
            materialized_signal.c.signal_key.notin_(tuple(signal_keys.values())),
            materialized_signal.c.invalidated_at.is_(None),
        )
        .values(
            invalidated_at=materialized_at,
            invalidation_reason="provisional_landing_cohort_reconciled",
        )
    )
    return signal_keys.get(opportunity_key)
