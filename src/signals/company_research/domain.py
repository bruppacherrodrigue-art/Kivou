"""Bounded official/Serper discovery of one supplier-owned web domain."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from signals.companies.france import ANNUAIRE_BASE_URL, MAX_RESPONSE_BYTES
from signals.company_research.identity import (
    normalized_city,
    normalized_organization_name,
    significant_name_words,
)
from signals.supplier_discovery.contracts import SireneOrganizationCandidate

SERPER_SEARCH_URL = "https://google.serper.dev/search"
_DOMAIN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_DIRECTORY_DOMAINS = frozenset(
    {
        "annuaire-entreprises.data.gouv.fr",
        "companieshouse.com",
        "europages.fr",
        "facebook.com",
        "kompass.com",
        "linkedin.com",
        "manageo.fr",
        "pagesjaunes.fr",
        "pappers.fr",
        "societe.com",
        "verif.com",
    }
)


class DomainResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: str = Field(min_length=3, max_length=253)
    website_url: str = Field(min_length=8, max_length=2048)
    source: Literal["annuaire_entreprises", "serper"]
    query: str | None = Field(default=None, max_length=1024)
    observed_at: dt.datetime


class DomainSource(Protocol):
    def __call__(self, identity: SireneOrganizationCandidate) -> DomainResolution | None: ...


def _domain_from_url(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return None
    host = (parsed.hostname or "").casefold().removeprefix("www.").rstrip(".")
    if not _DOMAIN.fullmatch(host):
        return None
    return host, candidate if "://" in candidate else f"https://{candidate}"


def _directory(domain: str) -> bool:
    return any(
        domain == blocked or domain.endswith(f".{blocked}") for blocked in _DIRECTORY_DOMAINS
    )


class AnnuaireWebsiteClient:
    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0, follow_redirects=False)

    def __call__(self, identity: SireneOrganizationCandidate) -> DomainResolution | None:
        response = self._client.get(
            f"{ANNUAIRE_BASE_URL}/search",
            params={"q": identity.provider_organization_id, "page": 1, "per_page": 1},
            headers={"accept": "application/json", "user-agent": "Kivou/1.0"},
        )
        if response.status_code != 200 or len(response.content) > MAX_RESPONSE_BYTES:
            return None
        payload = response.json()
        results = payload.get("results") if isinstance(payload, dict) else None
        item = results[0] if isinstance(results, list) and len(results) == 1 else None
        if (
            not isinstance(item, dict)
            or str(item.get("siren") or "") != identity.provider_organization_id
        ):
            return None
        raw = item.get("site_web") or item.get("site_internet") or item.get("website_url")
        parsed = _domain_from_url(raw)
        if parsed is None:
            return None
        domain, website_url = parsed
        return DomainResolution(
            domain=domain,
            website_url=website_url,
            source="annuaire_entreprises",
            observed_at=identity.provider_observed_at,
        )


class SerperDomainSearchClient:
    def __init__(self, *, api_key: str, client: httpx.Client | None = None) -> None:
        if not api_key.strip():
            raise ValueError("Serper API key is required")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=15.0, follow_redirects=False)

    def __call__(self, identity: SireneOrganizationCandidate) -> DomainResolution | None:
        name = normalized_organization_name(identity.display_name)
        city = normalized_city(identity.location or "")
        query = " ".join(part for part in (name, city) if part)
        response = self._client.post(
            SERPER_SEARCH_URL,
            json={"q": query, "gl": "fr", "hl": "fr", "num": 10},
            headers={"x-api-key": self._api_key, "content-type": "application/json"},
        )
        if response.status_code != 200 or len(response.content) > MAX_RESPONSE_BYTES:
            return None
        payload = response.json()
        organic = payload.get("organic") if isinstance(payload, dict) else None
        if not isinstance(organic, list) or len(organic) > 10:
            return None
        expected = set(significant_name_words(name))
        for item in organic:
            if not isinstance(item, dict):
                continue
            parsed = _domain_from_url(item.get("link"))
            if parsed is None:
                continue
            domain, website_url = parsed
            if _directory(domain):
                continue
            title_words = set(significant_name_words(str(item.get("title") or "")))
            url_words = set(significant_name_words(website_url.replace(".", " ")))
            if expected and (expected.issubset(title_words) or expected.issubset(url_words)):
                return DomainResolution(
                    domain=domain,
                    website_url=website_url,
                    source="serper",
                    query=query,
                    observed_at=identity.provider_observed_at,
                )
        return None


class CompanyDomainResolver:
    def __init__(
        self,
        *,
        official: DomainSource,
        serper: DomainSource,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._official = official
        self._serper = serper
        self._clock = clock

    def resolve(self, identity: SireneOrganizationCandidate) -> DomainResolution | None:
        for source in (self._official, self._serper):
            resolution = source(identity)
            if resolution is not None:
                return resolution.model_copy(update={"observed_at": self._clock()})
        return None


__all__ = [
    "AnnuaireWebsiteClient",
    "CompanyDomainResolver",
    "DomainResolution",
    "SerperDomainSearchClient",
]
