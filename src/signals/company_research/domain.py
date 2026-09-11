"""Bounded official/Serper discovery of one supplier-owned web domain."""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from typing import Literal, Protocol
from urllib.parse import urljoin, urlsplit

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
logger = logging.getLogger(__name__)
_DOMAIN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_DIRECTORY_DOMAINS = frozenset(
    {
        "118712.fr",
        "acpresse.fr",
        "annuaire-entreprises-rge.fr",
        "annuaire-entreprises.data.gouv.fr",
        "cataloxy.org",
        "companieshouse.com",
        "compao.fr",
        "cci.fr",
        "data.inpi.fr",
        "dnb.com",
        "doctrine.fr",
        "e-pro.fr",
        "europages.fr",
        "facebook.com",
        "france-artisan.fr",
        "hoodspot.fr",
        "infogreffe.fr",
        "instagram.com",
        "kompass.com",
        "lagazettefrance.fr",
        "lefigaro.fr",
        "linkedin.com",
        "manageo.fr",
        "mappy.com",
        "monartisan.info",
        "pagesjaunes.fr",
        "pappers.fr",
        "placegrenet.fr",
        "pple.fr",
        "rubypayeur.com",
        "bilansgratuits.fr",
        "socs.fr",
        "societeinfo.com",
        "societe.com",
        "usinenouvelle.com",
        "verif.com",
        "gowork.fr",
        "actulegales.fr",
        "lavieduvillage.fr",
    }
)

_PUBLIC_TITLE_WORDS = frozenset({"mairie", "commune", "municipalite"})
_IGNORED_COMPANY_WORDS = frozenset(
    {"etablissement", "etablissements", "ets", "groupe", "societe"}
)
_LEGAL_PATH_WORDS = ("mention", "legal", "juridique", "impressum")
_REGISTRATION_PATHS = (
    "/mentions-legales",
    "/mentions-legales.html",
    "/cgv",
    "/conditions-generales",
    "/contact",
    "/a-propos",
    "/legal",
)
_REGISTRATION_NUMBER = re.compile(r"(?<!\d)(?:\d[ .-]?){8,13}\d(?!\d)")


class DomainResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: str = Field(min_length=3, max_length=253)
    website_url: str = Field(min_length=8, max_length=2048)
    source: Literal["annuaire_entreprises", "serper"]
    query: str | None = Field(default=None, max_length=1024)
    search_title: str | None = Field(default=None, max_length=1024)
    validation_method: Literal["name_word", "registration_number"] | None = None
    validation_evidence_url: str | None = Field(default=None, max_length=2048)
    observed_at: dt.datetime


class DomainSource(Protocol):
    def __call__(self, identity: SireneOrganizationCandidate) -> DomainResolution | None: ...


class RegistrationSource(Protocol):
    def __call__(
        self, resolution: DomainResolution, identity: SireneOrganizationCandidate
    ) -> str | None: ...


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


def _public_or_municipal(domain: str, title: str) -> bool:
    labels = domain.split(".")
    title_words = set(significant_name_words(title))
    return (
        domain == "gouv.fr"
        or domain.endswith(".gouv.fr")
        or any(
            label.startswith(("commune-", "mairie-", "ville-")) or label in {"commune", "mairie"}
            for label in labels
        )
        or bool(title_words.intersection(_PUBLIC_TITLE_WORDS))
    )


def rejected_supplier_domain(domain: str, title: str = "") -> bool:
    """Return whether a domain is a directory or public/municipal surface."""

    normalized = domain.casefold().removeprefix("www.")
    return _directory(normalized) or _public_or_municipal(normalized, title)


def _normalized_company_words(company_name: str) -> tuple[str, ...]:
    return tuple(
        word
        for word in significant_name_words(company_name)
        if word not in _IGNORED_COMPANY_WORDS
    )


def _domain_contains_company_word(domain: str, company_name: str) -> bool:
    compact_domain = "".join(re.findall(r"[a-z0-9]+", domain.casefold().rsplit(".", 1)[0]))
    company_words = _normalized_company_words(company_name)
    if any(len(word) >= 4 and word in compact_domain for word in company_words):
        return True
    initials = "".join(word[0] for word in company_words if word)
    return len(initials) >= 2 and initials in compact_domain


def _homepage_title_contains_company_name(title: str, company_name: str) -> bool:
    company_words = _normalized_company_words(company_name)
    if not company_words:
        return False
    title_words = significant_name_words(title)
    return " ".join(company_words) in " ".join(title_words)


def _contains_registration_number(text: str, siren: str) -> bool:
    for raw in _REGISTRATION_NUMBER.findall(text):
        digits = "".join(character for character in raw if character.isdigit())
        if digits == siren or (len(digits) == 14 and digits.startswith(siren)):
            return True
    return False


class _RegistrationPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._footer_depth = 0
        self._title_depth = 0
        self.all_text: list[str] = []
        self.footer_text: list[str] = []
        self.title_text: list[str] = []
        self.legal_links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "footer":
            self._footer_depth += 1
        if tag == "title":
            self._title_depth += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if isinstance(href, str) and any(word in href.casefold() for word in _LEGAL_PATH_WORDS):
                self.legal_links.append(href)

    def handle_endtag(self, tag):
        if tag == "footer" and self._footer_depth:
            self._footer_depth -= 1
        if tag == "title" and self._title_depth:
            self._title_depth -= 1

    def handle_data(self, data):
        self.all_text.append(data)
        if self._footer_depth:
            self.footer_text.append(data)
        if self._title_depth:
            self.title_text.append(data)


class CompanyWebsiteRegistrationClient:
    """Confirm one SIREN/SIRET only from the company footer or legal page."""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0, follow_redirects=True)

    def _get(
        self, url: str, domain: str
    ) -> tuple[str, str, str, str, tuple[str, ...]] | None:
        try:
            response = self._client.get(url, headers={"user-agent": "Kivou/1.0"})
            final_domain = (response.url.host or "").casefold().removeprefix("www.")
            if (
                response.status_code != 200
                or final_domain != domain
                or len(response.content) > 1_000_000
                or "html" not in response.headers.get("content-type", "text/html")
            ):
                return None
            parser = _RegistrationPageParser()
            parser.feed(response.text)
            return (
                str(response.url),
                " ".join(parser.all_text),
                " ".join(parser.footer_text),
                " ".join(parser.title_text),
                tuple(parser.legal_links[:3]),
            )
        except (httpx.HTTPError, UnicodeError, ValueError):
            return None

    def __call__(
        self, resolution: DomainResolution, identity: SireneOrganizationCandidate
    ) -> str | None:
        evidence = self.inspect(resolution, identity)
        return evidence[1] if evidence is not None and evidence[0] == "registration_number" else None

    def inspect(
        self, resolution: DomainResolution, identity: SireneOrganizationCandidate
    ) -> tuple[Literal["registration_number", "homepage_title"], str] | None:
        home_url = f"https://{resolution.domain}/"
        home = self._get(home_url, resolution.domain)
        if home is None:
            return None
        final_url, _home_text, footer_text, title, links = home
        siren = identity.provider_organization_id
        if _contains_registration_number(footer_text, siren):
            return "registration_number", final_url
        candidate_links = tuple(dict.fromkeys((*_REGISTRATION_PATHS, *links)))
        for link in candidate_links:
            legal_url = urljoin(final_url, link)
            legal = self._get(legal_url, resolution.domain)
            if legal is None:
                continue
            evidence_url, legal_text, _legal_footer, _legal_title, _ = legal
            if _contains_registration_number(legal_text, siren):
                return "registration_number", evidence_url
        if _homepage_title_contains_company_name(title, identity.display_name):
            return "homepage_title", final_url
        return None


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
        candidates = self.candidates(identity)
        return candidates[0] if candidates else None

    def candidates(self, identity: SireneOrganizationCandidate) -> tuple[DomainResolution, ...]:
        for candidates in self.candidate_batches(identity):
            if candidates:
                return candidates
        return ()

    def candidate_batches(
        self, identity: SireneOrganizationCandidate
    ) -> Iterator[tuple[DomainResolution, ...]]:
        name = normalized_organization_name(identity.display_name)
        city = normalized_city(identity.location or "")
        queries = tuple(
            dict.fromkeys(
                (
                    " ".join(part for part in (name, city) if part),
                    " ".join(part for part in (name, city, "site officiel") if part),
                    " ".join(part for part in (name, identity.department) if part),
                )
            )
        )
        for query in queries:
            response = self._client.post(
                SERPER_SEARCH_URL,
                json={"q": query, "gl": "fr", "hl": "fr", "num": 10},
                headers={"x-api-key": self._api_key, "content-type": "application/json"},
            )
            if response.status_code != 200 or len(response.content) > MAX_RESPONSE_BYTES:
                continue
            payload = response.json()
            organic = payload.get("organic") if isinstance(payload, dict) else None
            if not isinstance(organic, list) or len(organic) > 10:
                continue
            candidates: list[DomainResolution] = []
            for item in organic:
                if not isinstance(item, dict):
                    continue
                parsed = _domain_from_url(item.get("link"))
                if parsed is None:
                    continue
                domain, website_url = parsed
                title = str(item.get("title") or "")
                if rejected_supplier_domain(domain, title):
                    continue
                candidates.append(
                    DomainResolution(
                        domain=domain,
                        website_url=website_url,
                        source="serper",
                        query=query,
                        search_title=title[:1024] or None,
                        observed_at=identity.provider_observed_at,
                    )
                )
            if candidates:
                yield tuple(candidates)
            else:
                yield ()


class CompanyDomainResolver:
    def __init__(
        self,
        *,
        official: DomainSource,
        serper: DomainSource,
        registration: RegistrationSource | None = None,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._official = official
        self._serper = serper
        self._registration = registration or (lambda _resolution, _identity: None)
        self._clock = clock

    def resolve(self, identity: SireneOrganizationCandidate) -> DomainResolution | None:
        for source in (self._official, self._serper):
            batch_method = getattr(source, "candidate_batches", None)
            candidate_method = getattr(source, "candidates", None)
            if callable(batch_method):
                candidate_batches = batch_method(identity)
            elif callable(candidate_method):
                candidate_batches = (candidate_method(identity),)
            else:
                resolution = source(identity)
                candidate_batches = ((),) if resolution is None else ((resolution,),)
            for candidates in candidate_batches:
                for resolution in candidates:
                    if rejected_supplier_domain(resolution.domain):
                        self._log(identity, resolution, accepted=False, criterion="blocklist")
                        continue
                    if _domain_contains_company_word(resolution.domain, identity.display_name):
                        self._log(identity, resolution, accepted=True, criterion="name_word")
                        return resolution.model_copy(
                            update={"observed_at": self._clock(), "validation_method": "name_word"}
                        )
                    if resolution.search_title and _homepage_title_contains_company_name(
                        resolution.search_title, identity.display_name
                    ):
                        self._log(identity, resolution, accepted=True, criterion="search_title")
                        return resolution.model_copy(
                            update={"observed_at": self._clock(), "validation_method": "name_word"}
                        )
                    inspect = getattr(self._registration, "inspect", None)
                    evidence = inspect(resolution, identity) if callable(inspect) else None
                    if evidence is not None:
                        criterion, evidence_url = evidence
                        validation_method = (
                            "registration_number"
                            if criterion == "registration_number"
                            else "name_word"
                        )
                        self._log(identity, resolution, accepted=True, criterion=criterion)
                        return resolution.model_copy(
                            update={
                                "observed_at": self._clock(),
                                "validation_method": validation_method,
                                "validation_evidence_url": evidence_url,
                            }
                        )
                    evidence_url = (
                        self._registration(resolution, identity) if not callable(inspect) else None
                    )
                    if evidence_url is not None:
                        self._log(
                            identity, resolution, accepted=True, criterion="registration_number"
                        )
                        return resolution.model_copy(
                            update={
                                "observed_at": self._clock(),
                                "validation_method": "registration_number",
                                "validation_evidence_url": evidence_url,
                            }
                        )
                    self._log(
                        identity, resolution, accepted=False, criterion="identity_unconfirmed"
                    )
        return None

    @staticmethod
    def _log(identity, resolution, *, accepted: bool, criterion: str) -> None:
        logger.info(
            "supplier_domain_validation",
            extra={
                "supplier_siren": identity.provider_organization_id,
                "supplier_domain": resolution.domain,
                "domain_validation_accepted": accepted,
                "domain_validation_criterion": criterion,
            },
        )


__all__ = [
    "AnnuaireWebsiteClient",
    "CompanyDomainResolver",
    "CompanyWebsiteRegistrationClient",
    "DomainResolution",
    "SerperDomainSearchClient",
    "rejected_supplier_domain",
]
