"""Deterministic publication checks; QA Signals cannot override these gates."""

from __future__ import annotations

import dataclasses
import re
import unicodedata

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    ClaimKind,
    PresentationInput,
    PresentationVariant,
)
from signals.card_intelligence.fallback import actor_label

# These certainty patterns retain a useful invariant learned in the isolated
# SPEC-009A experiment. The experimental verifier itself is intentionally not
# imported or activated: its model/policy failed development gates.
_CERTAINTY_PATTERNS = (
    "will buy",
    "will hire",
    "confirmed need",
    "confirmed demand",
    "must purchase",
    "va acheter",
    "va recruter",
    "besoin confirmé",
    "demande certaine",
    "achat certain",
    "opportunité certaine",
)

_STAFFING_TERMS = (
    "personnel",
    "main d'oeuvre",
    "main-d'oeuvre",
    "recrut",
    "embauch",
    "intérim",
    "interim",
    "staffing",
    "workforce",
    "hire",
)
_MATERIAL_TERMS = (
    "matériau",
    "materiau",
    "fourniture",
    "composant",
    "materials_and_components",
    "material",
)
_VOLATILE_URGENCY = (
    "urgent",
    "immédiatement",
    "immediatement",
    "agir maintenant",
    "vient de",
    "tout juste",
    "récent",
    "recent",
)
_ISO_DATE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _all_text(payload: CardPresentationPayload) -> str:
    values = (
        payload.headline,
        payload.award_summary,
        payload.commercial_importance or "",
        payload.fit_reason or "",
        payload.timing or "",
        payload.recommended_action or "",
        *payload.target_roles,
        *payload.fit_need_categories,
        *payload.unknowns,
        *(claim.text for claim in payload.claims),
    )
    return "\n".join(values)


def _mostly_uppercase(value: str) -> bool:
    letters = [character for character in value if character.isalpha()]
    if len(letters) < 12:
        return False
    return sum(character.isupper() for character in letters) / len(letters) > 0.72


def _mentions_actor(summary: str, actor: str) -> bool:
    full = _fold(" ".join(actor.split()))
    clipped = _fold(actor_label(actor)).rstrip("…")
    return full in summary or clipped in summary


@dataclasses.dataclass(frozen=True)
class ValidationOutcome:
    valid: bool
    errors: tuple[str, ...] = ()


def validate_payload(
    payload: CardPresentationPayload, source: PresentationInput
) -> ValidationOutcome:
    """Validate generated copy against facts, ICP and durable-display rules."""
    errors: list[str] = []
    facts = source.facts
    text = _all_text(payload)
    folded = _fold(text)
    summary_folded = _fold(payload.award_summary)

    if not _mentions_actor(summary_folded, facts.winner_name):
        errors.append("award_summary_missing_winner")
    if facts.buyer_name:
        if not _mentions_actor(summary_folded, facts.buyer_name):
            errors.append("award_summary_missing_buyer")
        if _fold(facts.buyer_name) == _fold(facts.winner_name):
            errors.append("actor_role_collision")
    elif not any(
        phrase in summary_folded
        for phrase in ("acheteur non publie", "buyer not published")
    ):
        errors.append("missing_buyer_not_disclosed")

    known_evidence = set(facts.evidence_refs)
    claim_ids: set[str] = set()
    for claim in payload.claims:
        if claim.claim_id in claim_ids:
            errors.append(f"duplicate_claim_id:{claim.claim_id}")
        claim_ids.add(claim.claim_id)
        unknown = set(claim.evidence_refs) - known_evidence
        if unknown:
            errors.append(f"unknown_evidence_ref:{claim.claim_id}:{','.join(sorted(unknown))}")
        if claim.kind is ClaimKind.RECOMMENDATION and not claim.evidence_refs:
            errors.append(f"recommendation_without_basis:{claim.claim_id}")

    dates = {
        value.isoformat()
        for value in (
            facts.award_date,
            facts.contract_notification_date,
            facts.publication_date,
        )
        if value is not None
    }
    for rendered in _ISO_DATE.findall(text):
        if rendered not in dates:
            errors.append(f"unknown_date:{rendered}")
    if facts.award_date is None and re.search(r"(?:attribu[eé]|attribution)\s+le\s+20\d{2}", folded):
        errors.append("publication_or_notification_presented_as_award_date")

    if _mostly_uppercase(payload.headline):
        errors.append("headline_mostly_uppercase")
    if payload.headline.count("\n") > 2 or payload.award_summary.count("\n") > 2:
        errors.append("copy_exceeds_three_lines")
    if _fold(payload.headline) == _fold(payload.award_summary):
        errors.append("headline_repeats_summary")
    if facts.award_title:
        raw = _fold(facts.award_title)
        if len(raw) > 80 and (raw == _fold(payload.headline) or raw == summary_folded):
            errors.append("raw_administrative_title_reused")

    for pattern in _CERTAINTY_PATTERNS:
        if _fold(pattern) in folded:
            errors.append(f"unsupported_certainty:{pattern}")

    profile = _fold(
        source.target_icp_label
        + " "
        + repr(source.target_icp_customer_input)
    )
    unbound_fit = set(payload.fit_need_categories) - set(source.icp_matched_needs)
    if unbound_fit:
        errors.append(f"fit_need_not_matched:{','.join(sorted(unbound_fit))}")
    if any(_fold(term) in profile for term in _MATERIAL_TERMS) and any(
        _fold(term) in folded for term in _STAFFING_TERMS
    ):
        errors.append("icp_category_mismatch:materials_vs_staffing")

    if payload.variant is PresentationVariant.FULL and any(
        _fold(term) in _fold(payload.timing or "") for term in _VOLATILE_URGENCY
    ):
        errors.append("volatile_urgency_copy_not_publishable")

    # Contract validation already excludes commercial fields; this explicit
    # check protects callers that construct objects without Pydantic later.
    if payload.variant is PresentationVariant.FACTUAL_FALLBACK and any(
        claim.kind is not ClaimKind.FACT for claim in payload.claims
    ):
        errors.append("fallback_contains_non_fact_claim")

    return ValidationOutcome(valid=not errors, errors=tuple(errors))
