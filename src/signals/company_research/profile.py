"""Deterministic Kivou company-research and action fingerprints."""

from __future__ import annotations

import hashlib
import json

from signals.company_research.contracts import (
    ALLOWED_PROVIDER_FIELDS,
    ENDPOINT_KIND,
    MAX_DESCRIPTION_LENGTH,
    MAX_KEYWORD_LENGTH,
    MAX_KEYWORDS,
    MAX_RESPONSE_BYTES,
    NORMALIZATION_VERSION,
    PROFILE_VERSION,
    PROVIDER,
    RESPONSE_CONTRACT_VERSION,
    CompanyResearchProfile,
)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _profile_values(provider_organization_id: str) -> dict[str, object]:
    return {
        "profile_version": PROFILE_VERSION,
        "provider": PROVIDER,
        "provider_organization_id": provider_organization_id,
        "endpoint_kind": ENDPOINT_KIND,
        "response_contract_version": RESPONSE_CONTRACT_VERSION,
        "allowed_provider_fields": ALLOWED_PROVIDER_FIELDS,
        "max_response_bytes": MAX_RESPONSE_BYTES,
        "max_keywords": MAX_KEYWORDS,
        "max_keyword_length": MAX_KEYWORD_LENGTH,
        "max_description_length": MAX_DESCRIPTION_LENGTH,
        "normalization_version": NORMALIZATION_VERSION,
    }


def build_company_research_profile(
    provider_organization_id: str,
) -> CompanyResearchProfile:
    values = _profile_values(provider_organization_id)
    return CompanyResearchProfile(
        **values,
        profile_fingerprint=_fingerprint(
            {"fingerprint_kind": "company_research_profile", **values}
        ),
    )


def provider_request_fingerprint(profile: CompanyResearchProfile) -> str:
    values = profile.model_dump(mode="json", exclude={"profile_fingerprint"})
    return _fingerprint({"fingerprint_kind": "company_research_provider_request", **values})


def policy_action_fingerprint(
    profile: CompanyResearchProfile,
    *,
    acquisition_opportunity_id: str,
    supplier_ref: str,
    contact_ref: str,
) -> str:
    return _fingerprint(
        {
            "fingerprint_kind": "company_research_policy_action",
            "command": "enrich_company",
            "acquisition_opportunity_id": acquisition_opportunity_id,
            "supplier_ref": supplier_ref,
            "contact_ref": contact_ref,
            "profile": profile.model_dump(mode="json"),
        }
    )
