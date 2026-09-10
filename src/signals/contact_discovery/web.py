"""Official-director plus company-website fallback for named contacts."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from signals.companies.france import ANNUAIRE_BASE_URL, MAX_RESPONSE_BYTES
from signals.contact_discovery.contracts import ContactObservation, DecisionMakerSearchProfile
from signals.contact_discovery.providers import PublishedContactExtractor

_CONTACT_WORDS = ("contact", "nous-contacter", "coordonnees")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class OfficialDirector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    name: str = Field(min_length=3, max_length=256)
    title: str = Field(min_length=2, max_length=256)


class WebsiteEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    url: str = Field(min_length=8, max_length=2048)
    text: str = Field(max_length=40_000)
    published_emails: tuple[EmailStr, ...] = Field(max_length=32)


class OfficialDirectorSource(Protocol):
    def find(self, siren: str) -> tuple[OfficialDirector, ...]: ...


class WebsitePageSource(Protocol):
    def fetch(self, domain: str) -> tuple[WebsiteEvidence, ...]: ...


class DeliverabilitySource(Protocol):
    def verify(self, email: str) -> bool: ...


class AnnuaireDirectorClient:
    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0, follow_redirects=False)

    def find(self, siren: str) -> tuple[OfficialDirector, ...]:
        try:
            response = self._client.get(
                f"{ANNUAIRE_BASE_URL}/search",
                params={"q": siren, "page": 1, "per_page": 1},
                headers={"accept": "application/json", "user-agent": "Kivou/1.0"},
            )
            if response.status_code != 200 or len(response.content) > MAX_RESPONSE_BYTES:
                return ()
            payload = response.json()
            results = payload.get("results") if isinstance(payload, dict) else None
            item = results[0] if isinstance(results, list) and len(results) == 1 else None
            leaders = item.get("dirigeants") if isinstance(item, dict) else None
            if not isinstance(leaders, list):
                return ()
            output = []
            for leader in leaders[:20]:
                if not isinstance(leader, dict):
                    continue
                name = " ".join(
                    str(leader.get(key) or "").strip() for key in ("prenoms", "nom")
                ).strip()
                title = str(leader.get("qualite") or leader.get("type_dirigeant") or "Dirigeant")
                if name:
                    output.append(OfficialDirector(name=name, title=title))
            return tuple(output)
        except (httpx.HTTPError, ValueError, TypeError):
            return ()


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.emails: set[str] = set()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        href = values.get("href")
        if tag == "a" and isinstance(href, str):
            if href.casefold().startswith("mailto:"):
                email = href[7:].split("?", 1)[0].strip().casefold()
                if _EMAIL.fullmatch(email):
                    self.emails.add(email)
            else:
                self.links.append(href)

    def handle_data(self, data):
        cleaned = " ".join(data.split())
        if cleaned:
            self.text.append(cleaned)


class CompanyWebsiteClient:
    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=12.0, follow_redirects=True)

    def _one(self, url: str, domain: str) -> tuple[WebsiteEvidence | None, list[str]]:
        try:
            response = self._client.get(url, headers={"user-agent": "Kivou/1.0"})
            final_domain = (response.url.host or "").casefold().removeprefix("www.")
            if (
                response.status_code != 200
                or final_domain != domain
                or len(response.content) > 1_000_000
                or "html" not in response.headers.get("content-type", "text/html")
            ):
                return None, []
            parser = _PageParser()
            parser.feed(response.text)
            return WebsiteEvidence(
                url=str(response.url),
                text=" ".join(parser.text)[:40_000],
                published_emails=tuple(sorted(parser.emails)),
            ), parser.links
        except (httpx.HTTPError, UnicodeError, ValueError):
            return None, []

    def fetch(self, domain: str) -> tuple[WebsiteEvidence, ...]:
        home_url = f"https://{domain}/"
        home, links = self._one(home_url, domain)
        evidence = [home] if home is not None else []
        contact_url = None
        for link in links:
            absolute = urljoin(home_url, link)
            parsed = urlsplit(absolute)
            target_domain = (parsed.hostname or "").casefold().removeprefix("www.")
            if target_domain == domain and any(
                word in parsed.path.casefold() for word in _CONTACT_WORDS
            ):
                contact_url = absolute
                break
        if contact_url and (home is None or contact_url != home.url):
            contact, _ = self._one(contact_url, domain)
            if contact is not None:
                evidence.append(contact)
        return tuple(evidence)


class PublishedWebsiteContactProvider:
    def __init__(self, *, directors, pages, extractor, deliverability) -> None:
        self._directors: OfficialDirectorSource = directors
        self._pages: WebsitePageSource = pages
        self._extractor: PublishedContactExtractor = extractor
        self._deliverability: DeliverabilitySource = deliverability

    def find(
        self, profile: DecisionMakerSearchProfile, *, observed_at: dt.datetime
    ) -> ContactObservation | None:
        if not profile.supplier_siren or not profile.organization_domain:
            return None
        directors = self._directors.find(profile.supplier_siren)
        evidence = self._pages.fetch(profile.organization_domain)
        extraction = self._extractor.extract(
            company_name=profile.organization_name or profile.supplier_siren,
            directors=directors,
            evidence=evidence,
        )
        if extraction is None or not self._deliverability.verify(str(extraction.email)):
            return None
        digest = hashlib.sha256(
            f"{profile.supplier_siren}\0{extraction.director_name}\0{extraction.email}".encode()
        ).hexdigest()
        return ContactObservation(
            supplier_ref=profile.supplier_ref,
            provider="company_website",
            provider_person_id=f"web-{digest[:24]}",
            provider_organization_id=profile.supplier_siren,
            display_name=extraction.director_name,
            title=extraction.title,
            normalized_title="dirigeant",
            role_profile_version=profile.profile_version,
            role_tier=1,
            business_email=str(extraction.email),
            provider_email_status="smtp_accepted",
            verification_state="DELIVERABILITY_VERIFIED",
            verification_provider="mx_smtp",
            provider_observed_at=observed_at,
            email_observed_at=observed_at,
            source_fingerprint=digest,
        )


__all__ = [
    "AnnuaireDirectorClient",
    "CompanyWebsiteClient",
    "OfficialDirector",
    "PublishedWebsiteContactProvider",
    "WebsiteEvidence",
]
