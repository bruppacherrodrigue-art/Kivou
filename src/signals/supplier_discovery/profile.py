"""Deterministic Kivou facts-to-Apollo search profile mapping."""

from __future__ import annotations

import hashlib
import json

from signals.supplier_discovery.contracts import (
    PROFILE_VERSION,
    SupplierSearchProfile,
    SupplierTargetingConfig,
)

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "workforce_capacity": ("staffing", "workforce solutions"),
    "equipment_or_rental": ("equipment rental", "industrial equipment"),
    "materials_or_components": ("building materials", "industrial components"),
    "logistics_and_transport": ("logistics", "transportation services"),
    "specialist_subcontracting": ("specialty contractor", "subcontracting"),
    "safety_and_ppe": ("personal protective equipment", "workplace safety"),
    "waste_and_environment": ("environmental services", "waste management"),
}


def _fingerprint(values: dict[str, object]) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_supplier_search_profile(
    *,
    signal_ref: str,
    representative_award_key: str,
    need_categories: tuple[str, ...],
    targeting: SupplierTargetingConfig,
) -> SupplierSearchProfile:
    categories = tuple(sorted(set(need_categories)))
    unknown = tuple(category for category in categories if category not in _KEYWORDS)
    if unknown:
        raise ValueError(f"unsupported need categories: {unknown}")
    keywords = tuple(sorted({tag for category in categories for tag in _KEYWORDS[category]}))
    values: dict[str, object] = {
        "profile_version": PROFILE_VERSION,
        "signal_ref": signal_ref,
        "representative_award_key": representative_award_key,
        "need_categories": categories,
        "keyword_tags": keywords,
        "organization_locations": targeting.organization_locations,
        "organization_not_locations": targeting.organization_not_locations,
        "employee_ranges": targeting.employee_ranges,
        "excluded_domains": targeting.excluded_domains,
        "max_pages": targeting.max_pages,
        "per_page": targeting.per_page,
        "candidate_cap": targeting.candidate_cap,
        "search_too_broad_threshold": targeting.search_too_broad_threshold,
    }
    values["profile_fingerprint"] = _fingerprint(values)
    return SupplierSearchProfile.model_validate(values)
