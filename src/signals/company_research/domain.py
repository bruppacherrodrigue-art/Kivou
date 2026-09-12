"""Domain syntax and the sole deterministic destination blocklist."""

from __future__ import annotations

import datetime as dt
import re
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from signals.supplier_discovery.contracts import SireneOrganizationCandidate

SERPER_SEARCH_URL = "https://google.serper.dev/search"
_DOMAIN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_DIRECTORY_DOMAINS = frozenset(
    {
        "118712.fr",
        "acpresse.fr",
        "actulegales.fr",
        "annuaire-entreprises-rge.fr",
        "annuaire-entreprises.data.gouv.fr",
        "bilansgratuits.fr",
        "cataloxy.org",
        "cci.fr",
        "companieshouse.com",
        "compao.fr",
        "data.inpi.fr",
        "dnb.com",
        "doctrine.fr",
        "e-pro.fr",
        "europages.fr",
        "facebook.com",
        "france-artisan.fr",
        "gowork.fr",
        "groupement-mh.org",
        "hoodspot.fr",
        "infogreffe.fr",
        "instagram.com",
        "kompass.com",
        "lagazettefrance.fr",
        "lavieduvillage.fr",
        "lefigaro.fr",
        "linkedin.com",
        "localbiz.fr",
        "manageo.fr",
        "mappy.com",
        "monartisan.info",
        "pagesjaunes.fr",
        "pappers.fr",
        "placegrenet.fr",
        "pple.fr",
        "publikconnect.fr",
        "rubypayeur.com",
        "societe.com",
        "societeinfo.com",
        "socs.fr",
        "usinenouvelle.com",
        "verif.com",
        "viviany.fr",
        "win2win-france.fr",
    }
)


class DomainResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: str = Field(min_length=3, max_length=253)
    website_url: str = Field(min_length=8, max_length=2048)
    source: Literal["annuaire_entreprises", "serper", "model"]
    query: str | None = Field(default=None, max_length=1024)
    search_title: str | None = Field(default=None, max_length=1024)
    validation_method: Literal["name_word", "registration_number", "model"] | None = None
    validation_evidence_url: str | None = Field(default=None, max_length=2048)
    homepage_title: str | None = Field(default=None, max_length=1024)
    observed_at: dt.datetime


class DomainResolutionTemporaryFailure(RuntimeError):
    """A provider lookup failed without proving that no website exists."""


class CompanyDomainResolver(Protocol):
    """Compatibility boundary for injected test doubles; production uses model enrichment."""

    def resolve(self, identity: SireneOrganizationCandidate) -> DomainResolution | None: ...


def domain_from_url(value: object) -> tuple[str, str] | None:
    """Return one canonical host/URL pair without deciding company ownership."""

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


def is_directory_domain(domain: str) -> bool:
    """Keep registry/directory surfaces usable as clues, never as destinations."""

    normalized = domain.casefold().removeprefix("www.").rstrip(".")
    return any(
        normalized == blocked or normalized.endswith(f".{blocked}")
        for blocked in _DIRECTORY_DOMAINS
    )


def rejected_supplier_domain(domain: str, _title: str = "") -> bool:
    """Apply only the destination blocklist; no name/title ownership heuristic."""

    normalized = domain.casefold().removeprefix("www.").rstrip(".")
    labels = normalized.split(".")
    return (
        is_directory_domain(normalized)
        or normalized == "gouv.fr"
        or normalized.endswith(".gouv.fr")
        or any(
            label.startswith(("commune-", "mairie-", "ville-"))
            or label in {"commune", "mairie"}
            for label in labels
        )
    )


__all__ = [
    "SERPER_SEARCH_URL",
    "CompanyDomainResolver",
    "DomainResolution",
    "DomainResolutionTemporaryFailure",
    "domain_from_url",
    "is_directory_domain",
    "rejected_supplier_domain",
]
