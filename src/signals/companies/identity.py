"""Exact, auditable resolution of a public winner into an opaque Kivou company."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from signals.companies.contracts import (
    MAX_OFFICIAL_IDENTIFIERS,
    CompanyOfficialIdentifier,
    CompanyOfficialIdentity,
    safe_https_url,
)
from signals.feed.query import DisplayIdentity

_SPACES = re.compile(r"\s+")


class IdentityMethod(StrEnum):
    OFFICIAL_IDENTIFIER = "official_identifier"
    OFFICIAL_DOMAIN = "official_domain"
    OPPORTUNITY = "opportunity"


@dataclass(frozen=True)
class ResolvedOfficialCompany:
    official: CompanyOfficialIdentity
    identity_fingerprint: str
    identity_method: IdentityMethod
    validation_evidence: dict[str, str]


def company_key() -> str:
    """Generate a non-enumerable identifier containing no source fact."""
    return f"cmp_{secrets.token_urlsafe(24)}"


def _normalized(value: str | None) -> str:
    return _SPACES.sub(" ", (value or "").strip()).casefold()


def _country(value: Any) -> str | None:
    cleaned = str(value or "").strip().upper()
    return cleaned if len(cleaned) == 2 and cleaned.isalpha() else None


def _identifier_values(organization: dict[str, Any]) -> tuple[CompanyOfficialIdentifier, ...]:
    values: list[CompanyOfficialIdentifier] = []
    seen: set[tuple[str, str]] = set()
    raw_identifiers = organization.get("identifiers") or []
    if not isinstance(raw_identifiers, (list, tuple)):
        return ()
    for raw in raw_identifiers:
        if not isinstance(raw, dict):
            continue
        scheme = str(raw.get("scheme") or "").strip()
        value = str(raw.get("value") or "").strip()
        exact = (_normalized(scheme), _normalized(value))
        if not all(exact) or exact in seen:
            continue
        try:
            identifier = CompanyOfficialIdentifier(scheme=scheme, value=value)
        except ValueError:
            continue
        seen.add(exact)
        values.append(identifier)
        if len(values) == MAX_OFFICIAL_IDENTIFIERS:
            break
    return tuple(values)


def _organizations(awardee_parties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    organizations: list[dict[str, Any]] = []
    for party in awardee_parties or []:
        if not isinstance(party, dict):
            continue
        members = party.get("members") or []
        if not isinstance(members, (list, tuple)):
            continue
        for member in members:
            if not isinstance(member, dict):
                continue
            organization = member.get("organization") or {}
            if isinstance(organization, dict):
                organizations.append(organization)
    return organizations


def _matches_display(organization: dict[str, Any], display: DisplayIdentity) -> bool:
    display_identifier = (
        _normalized(display.identifier_scheme),
        _normalized(display.identifier_value),
    )
    organization_identifiers = {
        (_normalized(identifier.scheme), _normalized(identifier.value))
        for identifier in _identifier_values(organization)
    }
    if all(display_identifier):
        display_country = _country(display.country)
        organization_country = _country(organization.get("country"))
        return display_identifier in organization_identifiers and not (
            display_country
            and organization_country
            and display_country != organization_country
        )
    return (
        _normalized(str(organization.get("legal_name") or "")) == _normalized(display.name)
        and _country(organization.get("country")) == _country(display.country)
    )


def _safe_website(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        return safe_https_url(cleaned)
    except ValueError:
        return None


def _fingerprint(method: IdentityMethod, evidence: dict[str, str]) -> str:
    canonical = json.dumps(
        {"method": method.value, "evidence": evidence},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(f"kivou-saas-company-v1:{canonical}".encode()).hexdigest()


def official_company_identity(
    *,
    awardee_parties: list[dict[str, Any]],
    display: DisplayIdentity,
    opportunity_key: str,
    observed_at: dt.datetime,
) -> ResolvedOfficialCompany | None:
    """Resolve one exact published organization; never merge on name similarity."""
    organization = next(
        (candidate for candidate in _organizations(awardee_parties) if _matches_display(candidate, display)),
        None,
    )
    if organization is None:
        return None

    identifiers = _identifier_values(organization)
    country = _country(organization.get("country")) or _country(display.country)
    website = _safe_website(organization.get("website"))
    try:
        official = CompanyOfficialIdentity(
            name=str(organization.get("legal_name") or display.name).strip(),
            country=country,
            address=(str(organization.get("address") or "").strip() or None),
            identifiers=identifiers,
            website_url=website,
            observed_at=observed_at,
        )
    except ValueError:
        return None

    if identifiers and country:
        first = identifiers[0]
        method = IdentityMethod.OFFICIAL_IDENTIFIER
        evidence = {
            "country": country or "",
            "identifier_scheme": _normalized(first.scheme),
            "identifier_value": _normalized(first.value),
        }
    elif website is not None and country:
        method = IdentityMethod.OFFICIAL_DOMAIN
        evidence = {
            "country": country or "",
            "domain": (urlsplit(website).hostname or "").casefold(),
        }
    else:
        method = IdentityMethod.OPPORTUNITY
        evidence = {"opportunity_key": opportunity_key}

    return ResolvedOfficialCompany(
        official=official,
        identity_fingerprint=_fingerprint(method, evidence),
        identity_method=method,
        validation_evidence=evidence,
    )


def official_siret_identity(
    *,
    siret: str,
    legal_name: str,
    address: str | None,
    observed_at: dt.datetime,
) -> ResolvedOfficialCompany:
    """Build the same stable SIRET identity from an exact French register hit."""

    if re.fullmatch(r"\d{14}", siret) is None:
        raise ValueError("SIRET must contain exactly fourteen digits")
    evidence = {
        "country": "FR",
        "identifier_scheme": "siret",
        "identifier_value": siret,
    }
    return ResolvedOfficialCompany(
        official=CompanyOfficialIdentity(
            name=legal_name,
            country="FR",
            address=address,
            identifiers=(CompanyOfficialIdentifier(scheme="SIRET", value=siret),),
            observed_at=observed_at,
            source="official_register",
        ),
        identity_fingerprint=_fingerprint(IdentityMethod.OFFICIAL_IDENTIFIER, evidence),
        identity_method=IdentityMethod.OFFICIAL_IDENTIFIER,
        validation_evidence=evidence,
    )
