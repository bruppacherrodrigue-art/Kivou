"""La frontière applicative : des sorties de moteur entrent, un signal durable sort.

    materialize_signal(connection, event=…, award=…, understanding=…,
                       needs=…, match=…, recency=…, as_of=…, materialized_at=…)

Ce service ne calcule rien. Il ne relance aucune ingestion, n'ouvre aucune
connexion réseau, ne touche ni au Need Graph ni au Matching, et ignore tout de
la facturation comme du rendu. Son entrée est ce que le moteur a **déjà**
produit ; sa sortie est un signal relisible.

    Idempotence (§7, closeout §2, §4)
    ─────────────────────────────────
    La clé logique d'un signal est `(opportunité, TargetICP)` — sans version de
    moteur. L'unité n'est PAS la représentation source : le BOAMP et DECP
    décrivent parfois le même contrat, et un client ne doit en voir qu'un. La
    contrainte `UNIQUE(opportunity_key, target_icp_id)` le garantit même si un
    appelant oubliait de vérifier.

    La révision avance quand le **contenu** matérialisé change — inférence,
    score, statut ou version de moteur, indifféremment. Une empreinte
    déterministe de la charge la détecte ; faire dépendre la révision des seules
    versions de moteur laisserait passer un changement de sortie à version
    constante.

    Faits et inférences (§5)
    ────────────────────────
    Les faits — événement, contrat, preuves — sont écrits une fois et partagés
    par tous les contextes clients. Deux clients qui regardent le même marché ne
    dupliquent pas ses faits ; ils obtiennent deux signaux distincts au-dessus
    d'un seul contrat.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from signals.persistence.identity import award_key, event_key, signal_key
from signals.persistence.opportunity import resolve_or_create_opportunity
from signals.persistence.schema import (
    contract_award,
    evidence,
    materialized_signal,
    source_event,
)


@dataclasses.dataclass(frozen=True)
class MaterializationResult:
    """Ce qui s'est réellement passé — pour qu'un appelant puisse le journaliser."""

    signal_key: str
    opportunity_key: str
    materialization_award_key: str
    revision: int
    created: bool
    updated: bool


@dataclasses.dataclass(frozen=True)
class FactPersistenceResult:
    """Stable source-fact and opportunity identities, independent of customers."""

    event_key: str
    award_key: str
    opportunity_key: str
    opportunity_created: bool


def _json(value: Any) -> Any:
    """Une charge structurée, sérialisée comme le domaine la sérialise déjà."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, tuple | list):
        return [_json(item) for item in value]
    return value


def _date(value: Any) -> dt.date | None:
    if value is None:
        return None
    return value.date() if isinstance(value, dt.datetime) else value


def _engine_versions(
    understanding: Any, needs: Any, match: Any, recency: Any, override: dict[str, str] | None
) -> dict[str, str]:
    """§8 — les versions telles que les moteurs les exposent, jamais recopiées ici.

    `override` sert à rejouer une matérialisation sous une version différente
    sans avoir à faire tourner un autre moteur : c'est ce qui rend le passage
    d'une révision à la suivante testable.
    """
    versions = {
        "understanding": understanding.engine_version,
        "need": needs.engine_version,
        "match_policy": match.match_policy_version,
        "score_policy": match.score_policy_version,
        "recency_policy": recency.policy_version,
    }
    versions.update(override or {})
    return {name: value for name, value in versions.items() if value}


def _upsert_source_event(connection: sa.Connection, event: Any, *, now: dt.datetime) -> str:
    key = event_key(event)
    published = event.published_at
    values = {
        "event_key": key,
        "source_system": event.provenance.source_system,
        "source_notice_id": event.provenance.source_notice_id,
        "notice_version": event.provenance.notice_version,
        "source_country": event.provenance.source_country,
        "source_procedure_id": event.provenance.source_procedure_id,
        "source_url": event.provenance.source_url,
        "event_type": event.event_type,
        # La forme brute conserve la précision publiée ; le jour sert au filtrage.
        "published_at_raw": published.isoformat() if published is not None else None,
        "published_on": _date(published),
        "published_precision": event.published_precision(),
        "discovered_at": event.provenance.retrieved_at,
        "procedure_buyers": _json(event.procedure_buyers),
        "created_at": now,
    }
    _insert_if_absent(connection, source_event, source_event.c.event_key == key, values)
    return key


def _upsert_award(
    connection: sa.Connection, award: Any, *, event_reference: str, now: dt.datetime
) -> str:
    key = award_key(award)
    place = award.place_of_performance
    values = {
        "award_key": key,
        "event_key": event_reference,
        "source_award_id": award.source_award_id,
        "lot_identifier": award.lot.identifier if award.lot else None,
        "lot_title": award.lot.title if award.lot else None,
        "contract_reference": award.contract_reference,
        "title": award.title,
        "description": award.description,
        "cpv_main": award.cpv_main.code if award.cpv_main else None,
        "cpv_check_digit": award.cpv_main.check_digit if award.cpv_main else None,
        "cpv_additional": _json(award.cpv_additional),
        "amount": award.value.amount if award.value else None,
        "currency": award.value.currency if award.value else None,
        "vat_category": award.value.vat_category if award.value else None,
        "winner_status": award.winner_status,
        "awardee_parties": _json(award.awardee_parties),
        "contract_signatories": _json(award.contract_signatories),
        "place_of_performance": _json(place),
        "place_country": place.country if place else None,
        # §6 — quatre horloges, quatre colonnes, jamais repliées.
        "award_date": award.award_date,
        "contract_signature_date": award.contract_signature_date,
        "contract_notification_date": award.contract_notification_date,
        "contract_start_date": award.contract_start_date,
        "contract_end_date": award.contract_end_date,
        "duration_value": award.duration.value if award.duration else None,
        "duration_unit": award.duration.unit if award.duration else None,
        "created_at": now,
    }
    _insert_if_absent(connection, contract_award, contract_award.c.award_key == key, values)
    return key


def _insert_if_absent(
    connection: sa.Connection, table: sa.Table, where: Any, values: dict[str, Any]
) -> bool:
    """Écrit une ligne de FAIT si elle manque, sans jamais réécrire l'existante.

    Un fait publié ne se corrige pas silencieusement : une republication qui
    changerait un montant doit produire un nouvel événement, pas remplacer
    l'ancien à son insu.
    """
    existing = connection.execute(sa.select(sa.literal(1)).where(where).limit(1)).scalar()
    if existing:
        return False
    connection.execute(sa.insert(table).values(**values))
    return True


def _evidence_key(award_reference: str, kind: str, reference: str, item: Any) -> str:
    payload = json.dumps(
        [award_reference, kind, reference, _json(item)], ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


def _store_evidence(
    connection: sa.Connection,
    *,
    award_reference: str,
    understanding: Any,
    needs: Any,
    match: Any,
    now: dt.datetime,
) -> int:
    """Les ancrages vérifiables des faits affichés, dédupliqués par contenu."""
    anchored: list[tuple[str, str, Any]] = []
    for name, claim in understanding.facts.items():
        anchored += [("award_fact", name, item) for item in claim.evidence]
    for need in needs.needs:
        anchored += [("plausible_need", need.category, item) for item in need.evidence_refs]
    anchored += [("icp_match", match.icp_id, item) for item in match.evidence_refs]

    written = 0
    for kind, reference, item in anchored:
        key = _evidence_key(award_reference, kind, reference, item)
        written += _insert_if_absent(
            connection,
            evidence,
            evidence.c.evidence_key == key,
            {
                "evidence_key": key,
                "award_key": award_reference,
                "anchors_kind": kind,
                "anchors_ref": str(reference),
                "source_system": item.source_system,
                "source_kind": item.source_kind,
                "source_notice_id": item.source_notice_id,
                "source_procedure_id": item.source_procedure_id,
                "source_url": item.source_url,
                "path": item.path,
                "raw_value": item.raw_value,
                "excerpt": item.excerpt,
                "retrieved_at": item.retrieved_at,
                "engine_version": item.engine_version,
                "created_at": now,
            },
        )
    return written


def content_fingerprint(payload: dict[str, Any]) -> str:
    """Empreinte déterministe de ce qui sera montré au client (closeout §4).

    Elle couvre tout le contenu matérialisé — statuts, inférences, score,
    versions de moteur — et rien d'autre. Les horodatages et le numéro de
    révision en sont exclus : sinon chaque exécution produirait une empreinte
    neuve, et l'idempotence disparaîtrait.
    """
    serialisable = {
        name: (value.isoformat() if isinstance(value, dt.date | dt.datetime) else value)
        for name, value in payload.items()
        if name
        not in {
            "materialized_at",
            "created_at",
            "revision",
            "content_fingerprint",
            "invalidated_at",
            "invalidation_reason",
        }
    }
    encoded = json.dumps(serialisable, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _winner_identity(award: Any) -> dict[str, Any]:
    members = [member for party in award.awardee_parties for member in party.members]
    if not members:
        return {
            "winner_name": None,
            "winner_country": None,
            "winner_identifier_scheme": None,
            "winner_identifier_value": None,
        }
    organization = members[0].organization
    identifier = organization.identifiers[0] if organization.identifiers else None
    return {
        "winner_name": organization.legal_name,
        "winner_country": organization.country,
        "winner_identifier_scheme": identifier.scheme if identifier else None,
        "winner_identifier_value": identifier.value if identifier else None,
    }


def _need_payload(needs: Any) -> list[dict[str, Any]]:
    """Ce qu'un feed affiche d'un besoin — plausible, et nommé comme tel."""
    return [
        {
            "category": need.category,
            "statement": need.statement,
            "reasoning": need.reasoning,
            "timing": need.timing,
            "externalisability": need.externalisability,
            "confidence": need.confidence,
            "rule_ids": list(need.rule_ids),
        }
        for need in needs.needs
    ]


def persist_award_facts(
    connection: sa.Connection,
    *,
    event: Any,
    award: Any,
    persisted_at: dt.datetime,
    linked_to: Sequence[Any] = (),
    link_strength: str = "unresolved",
) -> FactPersistenceResult:
    """Persist published facts and stable opportunity identity without a customer match."""
    event_reference = _upsert_source_event(connection, event, now=persisted_at)
    award_reference = _upsert_award(
        connection, award, event_reference=event_reference, now=persisted_at
    )
    resolved = resolve_or_create_opportunity(
        connection,
        award,
        now=persisted_at,
        linked_to=linked_to,
        link_strength=link_strength,
    )
    return FactPersistenceResult(
        event_key=event_reference,
        award_key=award_reference,
        opportunity_key=resolved.opportunity_key,
        opportunity_created=resolved.created,
    )


def materialize_signal(
    connection: sa.Connection,
    *,
    event: Any,
    award: Any,
    understanding: Any,
    needs: Any,
    match: Any,
    recency: Any,
    as_of: dt.date,
    materialized_at: dt.datetime,
    linked_to: Sequence[Any] = (),
    link_strength: str = "unresolved",
    engine_version_override: dict[str, str] | None = None,
    target_icp_revision: int = 1,
) -> MaterializationResult:
    """Persiste un signal client à partir de résultats de moteur déjà calculés.

    `linked_to` et `link_strength` décrivent un rapprochement inter-sources déjà
    établi par le produit. Un lien **fort** fait converger cette représentation
    vers l'opportunité de l'autre ; tout le reste la laisse sur la sienne. Le
    résolveur lit la base : l'identité d'une opportunité déjà écrite ne bouge
    jamais, même quand une représentation la rejoint des semaines plus tard.

    L'écriture se fait dans la transaction de l'appelant : c'est lui qui décide
    quand valider, et un signal à moitié écrit ne peut donc pas exister.
    """
    from signals.recency.claim import mvp_event_type

    persisted = persist_award_facts(
        connection,
        event=event,
        award=award,
        persisted_at=materialized_at,
        linked_to=linked_to,
        link_strength=link_strength,
    )
    _store_evidence(
        connection,
        award_reference=persisted.award_key,
        understanding=understanding,
        needs=needs,
        match=match,
        now=materialized_at,
    )

    key = signal_key(persisted.opportunity_key, target_icp_id=match.icp_id)
    versions = _engine_versions(understanding, needs, match, recency, engine_version_override)
    payload = {
        "signal_key": key,
        "opportunity_key": persisted.opportunity_key,
        "materialization_award_key": persisted.award_key,
        "target_icp_id": match.icp_id,
        "target_icp_revision": target_icp_revision,
        "invalidated_at": None,
        "invalidation_reason": None,
        "materialized_recency_status": recency.status,
        "materialized_primary_event": mvp_event_type(recency.status),
        "materialized_award_clock_status": recency.award_clock.status,
        "materialized_notification_clock_status": recency.notification_clock.status,
        "materialized_publication_clock_status": recency.publication_clock.status,
        "materialized_award_age_days": recency.award_age_days,
        "materialized_notification_age_days": recency.notification_age_days,
        "materialized_publication_age_days": recency.publication_age_days,
        "materialized_as_of": as_of,
        "recency_policy_version": recency.policy_version,
        "inferred_contract_type": understanding.contract_type.value,
        "inferred_sector": understanding.sector.value,
        "inferred_trade_domain": (
            understanding.trade_domain.value if understanding.trade_domain else None
        ),
        "inferred_contract_summary": understanding.object_summary.value,
        "plausible_needs": _need_payload(needs),
        "icp_match_decision": match.decision,
        "icp_match_band": match.band,
        "icp_match_confidence": match.confidence,
        "icp_match_normalized_score": match.normalized_score,
        "icp_matched_needs": list(match.matched_needs),
        "engine_versions": versions,
        "materialized_at": materialized_at,
    } | _winner_identity(award)

    fingerprint = content_fingerprint(payload)
    current = connection.execute(
        sa.select(materialized_signal.c.revision, materialized_signal.c.content_fingerprint).where(
            materialized_signal.c.signal_key == key
        )
    ).one_or_none()

    if current is None:
        connection.execute(
            sa.insert(materialized_signal).values(
                **payload,
                revision=1,
                content_fingerprint=fingerprint,
                created_at=materialized_at,
            )
        )
        return MaterializationResult(
            key,
            persisted.opportunity_key,
            persisted.award_key,
            1,
            created=True,
            updated=False,
        )

    revision, stored_fingerprint = current
    if stored_fingerprint == fingerprint:
        # Contenu identique au bit près : rien à réécrire, et surtout pas de révision.
        return MaterializationResult(
            key,
            persisted.opportunity_key,
            persisted.award_key,
            revision,
            created=False,
            updated=False,
        )

    connection.execute(
        sa.update(materialized_signal)
        .where(materialized_signal.c.signal_key == key)
        .values(**payload, revision=revision + 1, content_fingerprint=fingerprint)
    )
    return MaterializationResult(
        key,
        persisted.opportunity_key,
        persisted.award_key,
        revision + 1,
        created=False,
        updated=True,
    )
