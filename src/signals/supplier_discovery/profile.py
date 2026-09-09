"""Deterministic Kivou facts-to-Apollo search profile mapping."""

from __future__ import annotations

import hashlib
import json

from signals.supplier_discovery.contracts import (
    PROFILE_VERSION,
    SupplierSearchNotActionable,
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

_CPV_KEYWORDS: dict[str, tuple[str, ...]] = {
    "452612": ("couverture",),
    "4526265": ("bardage",),
    "452613": ("zinguerie",),
}

_TRADE_TERMS_BY_VERTICAL: dict[str, tuple[str, ...]] = {
    "general_building": ("bardage", "couverture", "zinguerie"),
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
    cpv_codes: tuple[str, ...] = (),
    trade_terms: tuple[str, ...] = (),
    sirene_naf_codes: tuple[str, ...] = (),
    sirene_departments: tuple[str, ...] = (),
    supplier_family_keys: tuple[str, ...] = (),
) -> SupplierSearchProfile:
    categories = tuple(sorted(set(need_categories)))
    unknown = tuple(category for category in categories if category not in _KEYWORDS)
    if unknown:
        raise ValueError(f"unsupported need categories: {unknown}")
    cpv_keywords = {
        keyword
        for code in cpv_codes
        for prefix, terms in _CPV_KEYWORDS.items()
        if code.replace("-", "").startswith(prefix)
        for keyword in terms
    }
    explicit_terms = {term.strip().casefold() for term in trade_terms if term.strip()}
    keywords = tuple(
        sorted(
            {
                tag
                for category in categories
                for tag in _KEYWORDS[category]
            }
            | cpv_keywords
            | explicit_terms
        )
    )
    if not keywords:
        raise SupplierSearchNotActionable
    values: dict[str, object] = {
        "profile_version": PROFILE_VERSION,
        "signal_ref": signal_ref,
        "representative_award_key": representative_award_key,
        "need_categories": categories,
        "cpv_codes": tuple(sorted(set(cpv_codes))),
        "trade_terms": tuple(sorted(explicit_terms)),
        "keyword_tags": keywords,
        "sirene_naf_codes": tuple(sorted(set(sirene_naf_codes))),
        "sirene_departments": tuple(sorted(set(sirene_departments))),
        "supplier_family_keys": tuple(sorted(set(supplier_family_keys))),
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


def narrow_supplier_search_profile(profile: SupplierSearchProfile) -> SupplierSearchProfile:
    """Tighten one Apollo query without widening its business meaning."""

    if profile.narrowing_level >= 2:
        return profile
    terms = tuple(profile.trade_terms)
    extra = terms[profile.narrowing_level : profile.narrowing_level + 1]
    locations = tuple(
        f"{location}, rayon {100 - profile.narrowing_level * 25} km"
        for location in profile.organization_locations
    )
    values = profile.model_copy(
        update={
            "keyword_tags": tuple(sorted(set(profile.keyword_tags) | set(extra))),
            "organization_locations": locations,
            "narrowing_level": profile.narrowing_level + 1,
        }
    )
    raw = values.model_dump(mode="json", exclude={"profile_fingerprint"})
    return values.model_copy(update={"profile_fingerprint": _fingerprint(raw)})
