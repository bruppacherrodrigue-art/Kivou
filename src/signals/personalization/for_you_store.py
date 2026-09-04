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
from signals.persistence.schema import contract_award, for_you_sentence, materialized_signal
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


def _stored_location(place: dict[str, Any] | None) -> str | None:
    if not place:
        return None
    parts = (
        place.get("locality"),
        subdivision_label(place.get("subdivision_code")) or place.get("subdivision_code"),
        place.get("country"),
    )
    return " · ".join(dict.fromkeys(part for part in parts if part)) or None


def _profile_context(
    profile: dict[str, Any],
) -> tuple[TargetIcpInput, str | None, tuple[str, ...], str]:
    customer_input = TargetIcpInput.model_validate(profile["customer_input"])
    sector = (
        cpv_label(customer_input.sector_cpv_prefixes[0].ljust(8, "0"), lang="fr")
        if customer_input.sector_cpv_prefixes
        else None
    )
    zones = (
        tuple(subdivision_label(code) or code for code in customer_input.territory_subdivisions)
        or customer_input.territories
    )
    fingerprint = _fingerprint(
        {
            "customer_input": customer_input.model_dump(mode="json"),
            "label": profile["label"],
            "matching_revision": profile["matching_revision"],
        }
    )
    return customer_input, sector, zones, fingerprint


def _persist(
    connection: sa.Connection,
    *,
    signal_key: str,
    target_icp_id: str,
    signal_fingerprint: str,
    profile_fingerprint: str,
    value: ForYouInput,
    now: dt.datetime,
) -> str:
    identity = _fingerprint(
        [signal_key, target_icp_id, signal_fingerprint, profile_fingerprint, POLICY_VERSION]
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
            target_icp_id=target_icp_id,
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
    profile = (
        connection.execute(
            sa.select(
                target_icp.c.customer_input,
                target_icp.c.label,
                target_icp.c.matching_revision,
            ).where(target_icp.c.target_icp_id == match.icp_id)
        )
        .mappings()
        .one_or_none()
    )
    if profile is None:
        # Certains pipelines techniques matérialisent sans compte SaaS.
        return None

    customer_input, sector, zones, profile_fingerprint = _profile_context(profile)
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
    return _persist(
        connection,
        signal_key=signal_key,
        target_icp_id=match.icp_id,
        signal_fingerprint=signal_fingerprint,
        profile_fingerprint=profile_fingerprint,
        value=value,
        now=now,
    )


def enqueue_stored_for_you_sentence(
    connection: sa.Connection, *, signal_key: str, now: dt.datetime
) -> str | None:
    row = (
        connection.execute(
            sa.select(materialized_signal, contract_award, target_icp)
            .select_from(
                materialized_signal.join(
                    contract_award,
                    materialized_signal.c.materialization_award_key == contract_award.c.award_key,
                ).join(
                    target_icp,
                    materialized_signal.c.target_icp_id == target_icp.c.target_icp_id,
                )
            )
            .where(materialized_signal.c.signal_key == signal_key)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    customer_input, sector, zones, profile_fingerprint = _profile_context(row)
    parties = row["awardee_parties"] or []
    members = parties[0].get("members") if parties else []
    organization = (members[0].get("organization") or {}) if members else {}
    needs = row["plausible_needs"] or []
    from signals.feed import copy as feed_copy

    reasons = tuple(
        f"Besoin visé : {label}"
        for category in row["icp_matched_needs"] or []
        if (label := feed_copy.translate(feed_copy.NEED_LABELS, category, "fr"))
    )
    value = ForYouInput(
        holder=organization.get("legal_name") or row["winner_name"],
        title=row["title"],
        amount=(
            f"{row['amount']} {row['currency']}"
            if row["amount"] is not None and row["currency"]
            else None
        ),
        location=_stored_location(row["place_of_performance"]),
        awarded_on=row["award_date"].isoformat() if row["award_date"] is not None else None,
        cpv=row["cpv_main"],
        cpv_label=cpv_label(row["cpv_main"], lang="fr"),
        plausible_needs=tuple(item.get("statement") for item in needs if item.get("statement")),
        fit_reasons=reasons,
        profile_sector=sector,
        profile_zones=zones,
        offer_summary=customer_input.offer_summary,
    )
    return _persist(
        connection,
        signal_key=signal_key,
        target_icp_id=row["target_icp_id"],
        signal_fingerprint=row["content_fingerprint"],
        profile_fingerprint=profile_fingerprint,
        value=value,
        now=now,
    )


__all__ = ["enqueue_for_you_sentence", "enqueue_stored_for_you_sentence"]
