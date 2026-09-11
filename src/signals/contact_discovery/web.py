"""Official-director plus company-website fallback for named contacts."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
from html.parser import HTMLParser
from typing import Literal, Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from signals.companies.france import ANNUAIRE_BASE_URL, MAX_RESPONSE_BYTES
from signals.company_research.domain import rejected_supplier_domain
from signals.company_research.identity import ascii_text
from signals.contact_discovery.contracts import ContactObservation, DecisionMakerSearchProfile
from signals.contact_discovery.providers import PublishedContactExtractor, coherent_email_domain
from signals.supplier_directory.store import SupplierDirectoryStore

logger = logging.getLogger(__name__)

_CONTACT_WORDS = ("contact", "contactez-nous", "nous-contacter", "coordonnees")
_CONTACT_PATHS = ("/contact", "/contactez-nous", "/nous-contacter", "/contacts")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_TEXT_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63})(?![A-Za-z0-9-])"
)
_OBFUSCATED_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"([A-Za-z0-9._%+-]+)\s*"
    r"(?:@|\[\s*(?:at|arrobase)\s*\]|\(\s*(?:at|arrobase)\s*\)|\bat\b|\barrobase\b)"
    r"\s*([A-Za-z0-9-]+(?:\s*(?:\.|\[\s*(?:dot|point)\s*\]|"
    r"\(\s*(?:dot|point)\s*\)|\bdot\b|\bpoint\b)\s*[A-Za-z0-9-]+)+)",
    re.IGNORECASE,
)
_OBFUSCATED_DOT = re.compile(
    r"\s*(?:\.|\[\s*(?:dot|point)\s*\]|\(\s*(?:dot|point)\s*\)|\bdot\b|\bpoint\b)\s*",
    re.IGNORECASE,
)
_OPERATIONAL_TITLES = (
    "gerant",
    "cogerant",
    "president",
    "president du conseil",
    "directeur general",
    "directrice generale",
    "associe gerant",
    "personne physique dirigeante",
)
_EXCLUDED_TITLES = ("commissaire aux comptes", "representant")


class OfficialDirector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    name: str = Field(min_length=3, max_length=256)
    title: str = Field(min_length=2, max_length=256)
    entity_type: Literal["personne physique", "personne morale"] = "personne physique"
    first_name: str | None = Field(default=None, max_length=128)


class WebsiteEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    url: str = Field(min_length=8, max_length=2048)
    text: str = Field(max_length=40_000)
    published_emails: tuple[EmailStr, ...] = Field(max_length=32)
    has_contact_form: bool = False


class OfficialDirectorSource(Protocol):
    def find(self, siren: str) -> tuple[OfficialDirector, ...]: ...


class WebsitePageSource(Protocol):
    def fetch(self, domain: str) -> tuple[WebsiteEvidence, ...]: ...


class DeliverabilitySource(Protocol):
    def verify(self, email: str) -> bool: ...


class AnnuaireDirectorClient:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        directory: SupplierDirectoryStore | None = None,
        clock=lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._client = client or httpx.Client(timeout=10.0, follow_redirects=False)
        self._directory = directory
        self._clock = clock

    def find(self, siren: str) -> tuple[OfficialDirector, ...]:
        now = self._clock()
        cached = self._directory.fresh_directors(siren, at=now) if self._directory else None
        if cached is not None:
            logger.info(
                "supplier_directory_provider_call_avoided",
                extra={"provider": "annuaire_directors", "siren": siren},
            )
            return tuple(OfficialDirector.model_validate(item) for item in cached.directors)
        try:
            response = self._client.get(
                f"{ANNUAIRE_BASE_URL}/search",
                params={
                    "q": siren,
                    "page": 1,
                    "per_page": 1,
                    "minimal": "true",
                    "include": "dirigeants",
                },
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
                first_name = str(leader.get("prenoms") or "").strip() or None
                physical_name = " ".join(
                    value for value in (first_name, str(leader.get("nom") or "").strip()) if value
                )
                corporate_name = str(leader.get("denomination") or "").strip()
                entity_type = str(leader.get("type_dirigeant") or "personne physique").casefold()
                is_corporate = "morale" in entity_type
                name = corporate_name if is_corporate else physical_name
                title = str(leader.get("qualite") or leader.get("type_dirigeant") or "Dirigeant")
                normalized_title = " ".join(ascii_text(title).casefold().split())
                operational = any(value in normalized_title for value in _OPERATIONAL_TITLES)
                excluded = any(value in normalized_title for value in _EXCLUDED_TITLES)
                if name and operational and not excluded:
                    output.append(
                        OfficialDirector(
                            name=name,
                            title=title,
                            entity_type="personne morale" if is_corporate else "personne physique",
                            first_name=None if is_corporate else first_name,
                        )
                    )
            result = tuple(output)
            if self._directory is not None and result:
                self._directory.record_directors(
                    siren,
                    directors=tuple(item.model_dump() for item in result),
                    observed_at=now,
                )
            return result
        except (httpx.HTTPError, ValueError, TypeError):
            return ()


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.emails: set[str] = set()
        self.links: list[tuple[str, str]] = []
        self.has_form = False
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "form":
            self.has_form = True
        values = dict(attrs)
        href = values.get("href")
        if tag == "a" and isinstance(href, str):
            if href.casefold().startswith("mailto:"):
                email = href[7:].split("?", 1)[0].strip().casefold()
                if _EMAIL.fullmatch(email):
                    self.emails.add(email)
            else:
                self._anchor_href = href
                self._anchor_text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor_href is not None:
            self.links.append((self._anchor_href, " ".join(self._anchor_text)))
            self._anchor_href = None
            self._anchor_text = []

    def handle_data(self, data):
        cleaned = " ".join(data.split())
        if cleaned:
            self.text.append(cleaned)
            if self._anchor_href is not None:
                self._anchor_text.append(cleaned)


def _emails_in_text(text: str) -> tuple[str, ...]:
    output = [match.casefold() for match in _TEXT_EMAIL.findall(text)]
    for match in _OBFUSCATED_EMAIL.finditer(text):
        domain = ".".join(_OBFUSCATED_DOT.split(match.group(2)))
        candidate = f"{match.group(1)}@{domain}".casefold()
        if _EMAIL.fullmatch(candidate):
            output.append(candidate)
    return tuple(dict.fromkeys(output))


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
            text = " ".join(parser.text)[:40_000]
            text_emails = set(_emails_in_text(text))
            ordered_emails = tuple(sorted(parser.emails)) + tuple(
                sorted(text_emails.difference(parser.emails))
            )
            return WebsiteEvidence(
                url=str(response.url),
                text=text,
                published_emails=ordered_emails,
                has_contact_form=parser.has_form,
            ), parser.links
        except (httpx.HTTPError, UnicodeError, ValueError):
            return None, []

    def fetch(self, domain: str) -> tuple[WebsiteEvidence, ...]:
        home_url = f"https://{domain}/"
        home, links = self._one(home_url, domain)
        evidence = [home] if home is not None else []
        contact_urls = [urljoin(home_url, path) for path in _CONTACT_PATHS]
        for link, label in links:
            absolute = urljoin(home_url, link)
            parsed = urlsplit(absolute)
            target_domain = (parsed.hostname or "").casefold().removeprefix("www.")
            if target_domain == domain and any(
                word in parsed.path.casefold() or word in ascii_text(label).casefold()
                for word in _CONTACT_WORDS
            ):
                contact_urls.append(absolute)
        for contact_url in dict.fromkeys(contact_urls):
            if home is not None and contact_url == home.url:
                continue
            contact, _ = self._one(contact_url, domain)
            if contact is not None:
                evidence.append(contact)
        return tuple(evidence)


def _form_domain_is_usable(domain: str) -> bool:
    return not rejected_supplier_domain(domain)


class PublishedWebsiteContactProvider:
    def __init__(self, *, directors, pages, extractor, deliverability, directory=None) -> None:
        self._directors: OfficialDirectorSource = directors
        self._pages: WebsitePageSource = pages
        self._extractor: PublishedContactExtractor = extractor
        self._deliverability: DeliverabilitySource = deliverability
        self._directory: SupplierDirectoryStore | None = directory

    def find(
        self, profile: DecisionMakerSearchProfile, *, observed_at: dt.datetime
    ) -> ContactObservation | None:
        if not profile.supplier_siren or not profile.organization_domain:
            return None
        directors = self._directors.find(profile.supplier_siren)
        evidence = self._pages.fetch(profile.organization_domain)
        if not evidence:
            return None
        candidates = tuple(
            str(email)
            for page in evidence
            for email in page.published_emails
            if coherent_email_domain(str(email), evidence)
        )
        email = next(
            (
                candidate
                for candidate in dict.fromkeys(candidates)
                if self._deliverability.verify(candidate)
            ),
            None,
        )
        extracted_email = None
        if email is None and not candidates:
            extract = getattr(self._extractor, "extract", None)
            extraction = (
                extract(
                    company_name=profile.organization_name or profile.supplier_siren,
                    directors=directors,
                    evidence=evidence,
                )
                if callable(extract)
                else None
            )
            extracted_email = str(extraction.email) if extraction is not None else None
            if (
                extracted_email is not None
                and coherent_email_domain(extracted_email, evidence)
                and self._deliverability.verify(extracted_email)
            ):
                email = extracted_email
        if email is None:
            form = next((page for page in evidence if page.has_contact_form), None)
            form_recorded = False
            if (
                form is not None
                and self._directory is not None
                and _form_domain_is_usable(profile.organization_domain)
            ):
                form_recorded = self._directory.record_contact_form(
                    profile.supplier_siren,
                    url=form.url,
                    observed_at=observed_at,
                )
            logger.info(
                "website_contact_rejected",
                extra={
                    "siren": profile.supplier_siren,
                    "reason": (
                        "mx invalide"
                        if candidates or extracted_email
                        else "contact par formulaire"
                        if form_recorded
                        else "pas d'adresse publiée"
                    ),
                },
            )
            return None
        physical_directors = tuple(
            item for item in directors if item.entity_type == "personne physique"
        )
        director = physical_directors[0] if physical_directors else None
        display_name = (
            director.name if director else (profile.organization_name or profile.supplier_siren)
        )
        title = director.title if director else "Entreprise"
        digest = hashlib.sha256(
            f"{profile.supplier_siren}\0{display_name}\0{email}".encode()
        ).hexdigest()
        return ContactObservation(
            supplier_ref=profile.supplier_ref,
            provider="company_website",
            provider_person_id=f"web-{digest[:24]}",
            provider_organization_id=profile.supplier_siren,
            first_name=director.first_name if director else None,
            display_name=display_name,
            title=title,
            normalized_title="dirigeant" if director else "entreprise",
            role_profile_version=profile.profile_version,
            role_tier=1 if director else 4,
            business_email=email,
            provider_email_status="mx_accepted",
            verification_state="DELIVERABILITY_VERIFIED",
            verification_provider="dns_mx",
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
