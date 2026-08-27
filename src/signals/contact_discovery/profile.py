"""Kivou-owned deterministic Apollo People Search profile."""

from __future__ import annotations

import hashlib
import json

from signals.contact_discovery.contracts import (
    MAX_ENRICHMENT_ATTEMPTS,
    MAX_SEARCH_PAGES,
    MAX_SEARCH_RESULTS,
    PROFILE_VERSION,
    SEARCH_TOO_BROAD_THRESHOLD,
    DecisionMakerSearchProfile,
)

PERSON_TITLES = (
    "Head of Sales",
    "Sales Director",
    "VP Sales",
    "Commercial Director",
    "Chief Revenue Officer",
    "Business Development Director",
    "Head of Business Development",
    "VP Business Development",
    "Sales Manager",
    "Business Development Manager",
    "Managing Director",
    "CEO",
    "Founder",
    "Owner",
    "Directeur commercial",
    "Directrice commerciale",
    "Directeur des ventes",
    "Directrice des ventes",
    "Directeur du développement commercial",
    "Directrice du développement commercial",
    "Responsable du développement commercial",
    "Responsable développement commercial",
    "Responsable commercial",
    "Responsable commerciale",
    "Responsable des ventes",
    "Directeur général",
    "Directrice générale",
    "Fondateur",
    "Fondatrice",
    "Dirigeant",
    "Dirigeante",
)
PERSON_SENIORITIES = (
    "owner",
    "founder",
    "c_suite",
    "vp",
    "head",
    "director",
    "manager",
)
RUNTIME_QA_PROFILE_VERSION = "decision-maker-search-runtime-qa-v1"
RUNTIME_QA_PERSON_SENIORITIES = PERSON_SENIORITIES[:-1]
_SENIORITIES_BY_PROFILE_VERSION = {
    PROFILE_VERSION: PERSON_SENIORITIES,
    RUNTIME_QA_PROFILE_VERSION: RUNTIME_QA_PERSON_SENIORITIES,
}


def _fingerprint(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def decision_maker_profile_semantics(
    profile_version: str = PROFILE_VERSION,
) -> dict[str, object]:
    if not isinstance(profile_version, str) or profile_version not in (
        _SENIORITIES_BY_PROFILE_VERSION
    ):
        raise ValueError("unsupported decision-maker search profile version")
    return {
        "profile_version": profile_version,
        "person_titles": PERSON_TITLES,
        "person_seniorities": _SENIORITIES_BY_PROFILE_VERSION[profile_version],
        "contact_email_statuses": ("verified",),
        "include_similar_titles": False,
        "max_pages": MAX_SEARCH_PAGES,
        "per_page": MAX_SEARCH_RESULTS,
        "max_enrichment_attempts": MAX_ENRICHMENT_ATTEMPTS,
        "search_too_broad_threshold": SEARCH_TOO_BROAD_THRESHOLD,
    }


def build_decision_maker_profile(
    *,
    acquisition_opportunity_id: str,
    supplier_ref: str,
    provider_organization_id: str,
    profile_version: str = PROFILE_VERSION,
) -> DecisionMakerSearchProfile:
    values: dict[str, object] = {
        "acquisition_opportunity_id": acquisition_opportunity_id,
        "supplier_ref": supplier_ref,
        "provider_organization_id": provider_organization_id,
        **decision_maker_profile_semantics(profile_version),
    }
    return DecisionMakerSearchProfile(**values, profile_fingerprint=_fingerprint(values))
