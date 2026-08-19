"""Persisted France sibling lookup; the approved linkage policy remains authoritative."""

from __future__ import annotations

import datetime as dt
from typing import Any

import sqlalchemy as sa

from signals.domain.awards import ContractAward
from signals.domain.events import PublicEvent
from signals.france.link import (
    NOTIFICATION_TOLERANCE_DAYS,
    resolve_candidates,
    unique_strong,
)
from signals.ingestion.persisted import canonical_award, canonical_event
from signals.ingestion.pipeline import LinkResolution
from signals.persistence.schema import contract_award, source_event


def _decp_record(event: PublicEvent, award: ContractAward) -> dict[str, Any]:
    buyers = [
        identifier.value
        for buyer in event.procedure_buyers
        for identifier in buyer.identifiers
        if identifier.scheme == "SIRET"
    ]
    record: dict[str, Any] = {
        "id": award.source_award_id or event.provenance.source_notice_id,
        "idaccordcadre": award.contract_reference,
        "acheteur_id": buyers[0] if buyers else None,
        "datenotification": (
            award.contract_notification_date.isoformat()
            if award.contract_notification_date
            else None
        ),
        "codecpv": str(award.cpv_main) if award.cpv_main else None,
        "montant": str(award.value.amount) if award.value else None,
    }
    identifiers = [
        identifier
        for party in award.awardee_parties
        for member in party.members
        for identifier in member.organization.identifiers
    ][:3]
    for index, identifier in enumerate(identifiers, start=1):
        record[f"titulaire_typeidentifiant_{index}"] = identifier.scheme
        record[f"titulaire_id_{index}"] = identifier.value
    return record


def _rows_near(
    connection: sa.Connection,
    *,
    source: str,
    clock: sa.Column,
    target: dt.date,
) -> tuple[sa.Row, ...]:
    delta = dt.timedelta(days=NOTIFICATION_TOLERANCE_DAYS)
    return tuple(
        connection.execute(
            sa.select(source_event, contract_award)
            .select_from(
                contract_award.join(source_event, contract_award.c.event_key == source_event.c.event_key)
            )
            .where(
                source_event.c.source_system == source,
                clock >= target - delta,
                clock <= target + delta,
            )
            .order_by(contract_award.c.award_key)
        ).all()
    )


class FranceLinker:
    """Find persisted siblings, then delegate every decision to france-link-v0.3."""

    def resolve(
        self, connection: sa.Connection, *, event: PublicEvent, award: ContractAward
    ) -> LinkResolution:
        source = event.provenance.source_system
        if source == "boamp" and award.contract_signature_date is not None:
            candidates: list[tuple[ContractAward, dict[str, Any]]] = []
            for row in _rows_near(
                connection,
                source="decp",
                clock=contract_award.c.contract_notification_date,
                target=award.contract_signature_date,
            ):
                sibling_event = canonical_event(row)
                sibling_award = canonical_award(row, sibling_event)
                candidates.append((sibling_award, _decp_record(sibling_event, sibling_award)))
            decision = unique_strong(
                resolve_candidates(award, event, [record for _, record in candidates])
            )
            if decision is None:
                return LinkResolution()
            linked = tuple(
                sibling
                for sibling, record in candidates
                if str(record.get("id") or "") == decision.decp_id
            )
            return LinkResolution(linked_to=linked, strength="strong")

        if source == "decp" and award.contract_notification_date is not None:
            record = _decp_record(event, award)
            linked = []
            for row in _rows_near(
                connection,
                source="boamp",
                clock=contract_award.c.contract_signature_date,
                target=award.contract_notification_date,
            ):
                sibling_event = canonical_event(row)
                sibling_award = canonical_award(row, sibling_event)
                if unique_strong(resolve_candidates(sibling_award, sibling_event, [record])):
                    linked.append(sibling_award)
            return (
                LinkResolution(linked_to=tuple(linked), strength="strong")
                if linked
                else LinkResolution()
            )
        return LinkResolution()
