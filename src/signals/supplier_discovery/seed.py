"""Resolve a public procurement opportunity into a customer-independent seed."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from signals.domain.awards import ContractAward
from signals.domain.events import PublicEvent
from signals.ingestion.persisted import canonical_award, canonical_event
from signals.needs import NeedGraphEngine, NeedGraphResult
from signals.persistence.schema import (
    contract_award,
    opportunity_representation,
    source_event,
)
from signals.supplier_discovery.contracts import (
    SupplierSearchProfile,
    SupplierTargetingConfig,
)
from signals.supplier_discovery.profile import build_supplier_search_profile
from signals.understanding import ContractUnderstanding, ContractUnderstandingEngine


class AcquisitionSeedNotFound(LookupError):
    pass


@dataclass(frozen=True)
class AcquisitionSeed:
    signal_ref: str
    opportunity_key: str
    representative_award_key: str
    event: PublicEvent
    award: ContractAward
    understanding: ContractUnderstanding
    needs: NeedGraphResult
    public_evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class PublicAcquisitionContext:
    """Customer-independent public facts shared by acquisition consumers."""

    signal_ref: str
    opportunity_key: str
    representative_award_key: str
    event: PublicEvent
    award: ContractAward
    public_evidence_refs: tuple[str, ...]


def _publication_rank(value: dt.date | dt.datetime | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, dt.datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    else:
        aware = dt.datetime.combine(value, dt.time.min, tzinfo=dt.UTC)
    return aware.timestamp()


def _completeness(event: PublicEvent, award: ContractAward) -> int:
    return sum(
        (
            bool(award.title or award.description),
            bool(award.cpv_main or award.cpv_additional),
            any(organization.legal_name for organization in award.awardee_organizations()),
            award.award_date is not None,
            award.contract_notification_date is not None,
            event.published_at is not None,
        )
    )


def resolve_public_acquisition_context_in_transaction(
    connection: Connection, opportunity_key: str
) -> PublicAcquisitionContext:
    """Resolve public context on a caller-owned connection without nested I/O."""

    rows = connection.execute(
        sa.select(opportunity_representation.c.award_key, source_event, contract_award)
        .select_from(
            opportunity_representation.join(
                contract_award,
                opportunity_representation.c.award_key == contract_award.c.award_key,
            ).join(source_event, contract_award.c.event_key == source_event.c.event_key)
        )
        .where(opportunity_representation.c.opportunity_key == opportunity_key)
        .order_by(contract_award.c.award_key)
    ).all()
    if not rows:
        raise AcquisitionSeedNotFound(opportunity_key)
    choices = []
    for row in rows:
        event = canonical_event(row)
        award = canonical_award(row, event)
        choices.append((row.award_key, event, award))
    award_key, event, award = min(
        choices,
        key=lambda item: (
            -_completeness(item[1], item[2]),
            -_publication_rank(item[1].published_at),
            item[0],
        ),
    )
    return PublicAcquisitionContext(
        signal_ref=f"procurement-opportunity:{opportunity_key}",
        opportunity_key=opportunity_key,
        representative_award_key=award_key,
        event=event,
        award=award,
        public_evidence_refs=(
            f"source-event:{event.ref().key()}",
            f"contract-award:{award_key}",
        ),
    )


def resolve_public_acquisition_context(
    engine: Engine, opportunity_key: str
) -> PublicAcquisitionContext:
    with engine.connect() as connection:
        return resolve_public_acquisition_context_in_transaction(connection, opportunity_key)


def resolve_acquisition_seed(engine: Engine, opportunity_key: str) -> AcquisitionSeed:
    public = resolve_public_acquisition_context(engine, opportunity_key)
    event = public.event
    award = public.award
    understanding = ContractUnderstandingEngine().understand(award, event)
    needs = NeedGraphEngine().derive(understanding)
    return AcquisitionSeed(
        signal_ref=public.signal_ref,
        opportunity_key=public.opportunity_key,
        representative_award_key=public.representative_award_key,
        event=event,
        award=award,
        understanding=understanding,
        needs=needs,
        public_evidence_refs=public.public_evidence_refs,
    )


def build_profile_from_seed(
    seed: AcquisitionSeed, *, targeting: SupplierTargetingConfig
) -> SupplierSearchProfile:
    return build_supplier_search_profile(
        signal_ref=seed.signal_ref,
        representative_award_key=seed.representative_award_key,
        need_categories=tuple(need.category for need in seed.needs.needs),
        targeting=targeting,
    )
