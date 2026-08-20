"""Pure deterministic Acquisition Prospect Prebuild derivation."""

from __future__ import annotations

import hashlib
import json

from signals.company_research.contracts import (
    PREBUILD_VERSION,
    SIZE_BAND_VERSION,
    AcquisitionProspectPrebuild,
    ApolloOrganizationObservation,
    CompanySizeBand,
    ProviderResearchStatus,
    ResearchCompleteness,
    SupplierIdentityStatus,
)


def _size_band(employee_count: int | None) -> CompanySizeBand:
    if employee_count is None:
        return CompanySizeBand.UNKNOWN
    if employee_count <= 9:
        return CompanySizeBand.MICRO
    if employee_count <= 249:
        return CompanySizeBand.SMB
    if employee_count <= 999:
        return CompanySizeBand.MID_MARKET
    return CompanySizeBand.ENTERPRISE


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_acquisition_prospect_prebuild(
    *,
    acquisition_opportunity_id: str,
    signal_ref: str,
    supplier_ref: str,
    contact_ref: str,
    supplier_identity_status: SupplierIdentityStatus,
    contact_role_profile_version: str,
    contact_role_tier: int,
    observation: ApolloOrganizationObservation,
) -> AcquisitionProspectPrebuild:
    complete = bool(
        (observation.provider_primary_domain or observation.provider_website_url)
        and observation.provider_country
        and observation.provider_industry
        and observation.provider_employee_count is not None
    )
    values = {
        "acquisition_opportunity_id": acquisition_opportunity_id,
        "signal_ref": signal_ref,
        "supplier_ref": supplier_ref,
        "contact_ref": contact_ref,
        "supplier_identity_status": supplier_identity_status,
        "provider": observation.provider,
        "provider_organization_id": observation.provider_organization_id,
        "provider_company_name": observation.provider_company_name,
        "provider_primary_domain": observation.provider_primary_domain,
        "provider_website_url": observation.provider_website_url,
        "provider_country": observation.provider_country,
        "provider_industry": observation.provider_industry,
        "provider_employee_count": observation.provider_employee_count,
        "provider_founded_year": observation.provider_founded_year,
        "provider_short_description": observation.provider_short_description,
        "provider_keywords": observation.provider_keywords,
        "provider_observed_at": observation.provider_observed_at,
        "provider_source_fingerprint": observation.provider_source_fingerprint,
        "contact_role_profile_version": contact_role_profile_version,
        "contact_role_tier": contact_role_tier,
        "provider_research_status": ProviderResearchStatus.CURRENT_PROVIDER_RECORD,
        "research_completeness": (
            ResearchCompleteness.COMPLETE if complete else ResearchCompleteness.LIMITED
        ),
        "research_gaps": observation.research_gaps,
        "size_band": _size_band(observation.provider_employee_count),
        "size_band_version": SIZE_BAND_VERSION,
        "prebuild_version": PREBUILD_VERSION,
    }
    canonical = {
        key: (value.value if hasattr(value, "value") else value) for key, value in values.items()
    }
    canonical["provider_keywords"] = list(observation.provider_keywords)
    canonical["research_gaps"] = [gap.value for gap in observation.research_gaps]
    canonical["provider_observed_at"] = observation.provider_observed_at.isoformat()
    return AcquisitionProspectPrebuild(
        **values,
        prebuild_fingerprint=_fingerprint(
            {"fingerprint_kind": "acquisition_prospect_prebuild", **canonical}
        ),
    )
