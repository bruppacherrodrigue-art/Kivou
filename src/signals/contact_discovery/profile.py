"""Kivou-owned deterministic Apollo People Search profile."""

from __future__ import annotations

import hashlib
import json

from signals.contact_discovery.contracts import DecisionMakerSearchProfile

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
    "Directeur des ventes",
    "Directeur du développement commercial",
    "Responsable développement commercial",
    "Responsable commercial",
    "Responsable des ventes",
    "Directeur général",
    "Fondateur",
    "Dirigeant",
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


def _fingerprint(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_decision_maker_profile(
    *,
    acquisition_opportunity_id: str,
    supplier_ref: str,
    provider_organization_id: str,
) -> DecisionMakerSearchProfile:
    values: dict[str, object] = {
        "profile_version": "decision-maker-search-v1",
        "acquisition_opportunity_id": acquisition_opportunity_id,
        "supplier_ref": supplier_ref,
        "provider_organization_id": provider_organization_id,
        "person_titles": PERSON_TITLES,
        "person_seniorities": PERSON_SENIORITIES,
        "contact_email_statuses": ("verified",),
        "include_similar_titles": False,
        "max_pages": 1,
        "per_page": 25,
        "max_enrichment_attempts": 3,
        "search_too_broad_threshold": 250,
    }
    return DecisionMakerSearchProfile(**values, profile_fingerprint=_fingerprint(values))
