"""Persistance non bloquante de la phrase « Pour vous ».

La matérialisation ne contacte jamais le fournisseur : elle rend immédiatement
le repli disponible et dépose seulement un travail durable pour le worker.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

import sqlalchemy as sa

from signals.accounts.icp_input import TargetIcpInput
from signals.accounts.schema import target_icp
from signals.domain.cpv_labels import cpv_label
from signals.domain.subdivisions import subdivision_label
from signals.persistence.schema import for_you_sentence
from signals.personalization.for_you import POLICY_VERSION, ForYouInput, fallback_sentence


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _holder(award: Any) -> str | None:
    for party in award.awardee_parties:
        if party.members:
            return party.members[0].organization.legal_name
    return None


def _location(place: Any) -> str | None:
    if place is None:
        return None
    parts = (
        place.locality,
        subdivision_label(place.subdivision_code) or place.subdivision_code,
        place.country,
    )
    return " · ".join(dict.fromkeys(part for part in parts if part)) or None


def enqueue_for_you_sentence(
    connection: sa.Connection,
    *,
    signal_key: str,
    signal_fingerprint: str,
    award: Any,
    needs: Any,
    match: Any,
    now: dt.datetime,
) -> str | None:
    """Dépose une paire signal/profil et son repli, de façon idempotente."""
    profile = connection.execute(
        sa.select(
            target_icp.c.customer_input,
            target_icp.c.label,
            target_icp.c.matching_revision,
        ).where(target_icp.c.target_icp_id == match.icp_id)
    ).mappings().one_or_none()
    if profile is None:
        # Certains pipelines techniques matérialisent sans compte SaaS.
        return None

    customer_input = TargetIcpInput.model_validate(profile["customer_input"])
    sector = (
        cpv_label(customer_input.sector_cpv_prefixes[0].ljust(8, "0"), lang="fr")
        if customer_input.sector_cpv_prefixes
        else None
    )
    zones = tuple(
        subdivision_label(code) or code for code in customer_input.territory_subdivisions
    ) or customer_input.territories
    value = ForYouInput(
        holder=_holder(award),
        title=award.title,
        amount=(
            f"{award.value.amount} {award.value.currency}" if award.value is not None else None
        ),
        location=_location(award.place_of_performance),
        awarded_on=award.award_date.isoformat() if award.award_date is not None else None,
        cpv=award.cpv_main.code if award.cpv_main is not None else None,
        cpv_label=(
            cpv_label(award.cpv_main.code, lang="fr") if award.cpv_main is not None else None
        ),
        plausible_needs=tuple(need.statement for need in needs.needs),
        fit_reasons=tuple(match.positive_reasons),
        profile_sector=sector,
        profile_zones=zones,
        offer_summary=customer_input.offer_summary,
    )
    profile_fingerprint = _fingerprint(
        {
            "customer_input": customer_input.model_dump(mode="json"),
            "label": profile["label"],
            "matching_revision": profile["matching_revision"],
        }
    )
    identity = _fingerprint(
        [signal_key, match.icp_id, signal_fingerprint, profile_fingerprint, POLICY_VERSION]
    )
    exists = connection.scalar(
        sa.select(sa.literal(True)).where(for_you_sentence.c.for_you_id == identity).limit(1)
    )
    if exists:
        return identity
    fallback = fallback_sentence(value)
    connection.execute(
        sa.insert(for_you_sentence).values(
            for_you_id=identity,
            signal_key=signal_key,
            target_icp_id=match.icp_id,
            signal_fingerprint=signal_fingerprint,
            profile_fingerprint=profile_fingerprint,
            policy_version=POLICY_VERSION,
            sentence=fallback,
            fallback_sentence=fallback,
            provenance="fallback",
            state="pending",
            input_snapshot=value.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
    )
    return identity


__all__ = ["enqueue_for_you_sentence"]
