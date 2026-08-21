"""Pure country-fact normalization and deterministic compliance routing."""

from __future__ import annotations

from signals.compliance.contracts import (
    JURISDICTION_VERSION,
    ComplianceJurisdiction,
    JurisdictionResolution,
)

EU_MEMBER_CODES = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    }
)

_PROVIDER_COUNTRY_ALIASES = {
    "austria": "AT",
    "belgium": "BE",
    "bulgaria": "BG",
    "croatia": "HR",
    "cyprus": "CY",
    "czech republic": "CZ",
    "czechia": "CZ",
    "denmark": "DK",
    "estonia": "EE",
    "finland": "FI",
    "france": "FR",
    "germany": "DE",
    "greece": "GR",
    "hungary": "HU",
    "ireland": "IE",
    "italy": "IT",
    "latvia": "LV",
    "lithuania": "LT",
    "luxembourg": "LU",
    "malta": "MT",
    "netherlands": "NL",
    "poland": "PL",
    "portugal": "PT",
    "romania": "RO",
    "slovakia": "SK",
    "slovenia": "SI",
    "spain": "ES",
    "sweden": "SE",
    "switzerland": "CH",
    "united states": "US",
    "united states of america": "US",
}


def normalize_provider_country(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.casefold().split())
    if len(normalized) == 2 and normalized.upper().isalpha():
        return normalized.upper()
    return _PROVIDER_COUNTRY_ALIASES.get(normalized)


def resolve_jurisdiction(
    *,
    supplier_country_code: str | None,
    provider_country: str | None,
    supplier_ref: str,
    profile_ref: str,
) -> JurisdictionResolution:
    supplier = supplier_country_code.upper() if supplier_country_code else None
    provider = normalize_provider_country(provider_country)
    refs = []
    if supplier:
        refs.append(f"acquisition-supplier:{supplier_ref}:country")
    if provider:
        refs.append(f"{profile_ref}:provider-country")
    if supplier and provider and supplier != provider:
        return JurisdictionResolution(
            jurisdiction=ComplianceJurisdiction.UNRESOLVED,
            resolvable=True,
            evidence_refs=tuple(refs),
        )
    country = supplier or provider
    if country is None:
        return JurisdictionResolution(
            jurisdiction=ComplianceJurisdiction.UNRESOLVED,
            resolvable=True,
            evidence_refs=(f"{profile_ref}:country-unresolved",),
        )
    if country == "CH":
        jurisdiction = ComplianceJurisdiction.CH
    elif country == "FR":
        jurisdiction = ComplianceJurisdiction.FR
    elif country in EU_MEMBER_CODES:
        jurisdiction = ComplianceJurisdiction.EU_MEMBER_STATE_UNCONFIGURED
    else:
        jurisdiction = ComplianceJurisdiction.OUT_OF_SCOPE
    return JurisdictionResolution(
        jurisdiction=jurisdiction,
        country_code=country,
        resolvable=jurisdiction is not ComplianceJurisdiction.OUT_OF_SCOPE,
        evidence_refs=tuple(refs),
    )


__all__ = [
    "EU_MEMBER_CODES",
    "JURISDICTION_VERSION",
    "normalize_provider_country",
    "resolve_jurisdiction",
]
