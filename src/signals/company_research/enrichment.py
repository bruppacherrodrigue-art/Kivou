"""One-pass company enrichment: deterministic evidence, one model, short policy."""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from signals.companies.france import ANNUAIRE_BASE_URL, MAX_RESPONSE_BYTES
from signals.company_research.domain import (
    SERPER_SEARCH_URL,
    domain_from_url,
    is_directory_domain,
    rejected_supplier_domain,
)
from signals.company_research.evidence import (
    DirectoryClues,
    PageRenderer,
    PlaywrightPageRenderer,
    RawRenderedPage,
    ReducedRenderedPage,
    directory_clues_from_text,
    reduce_rendered_page,
)
from signals.personalization.prospect_mail import normalize_director_name
from signals.supplier_directory.email_quality import is_placeholder_email
from signals.supplier_directory.store import FRESHNESS, SupplierDirectoryStore
from signals.supplier_discovery.families import (
    default_supplier_family_for_naf,
    supplier_family_keys,
)

MODEL_MAX_TOKENS = 1_000
WEBSITE_CONFIDENCE_THRESHOLD = Decimal("0.8")
EMAIL_CONFIDENCE_THRESHOLD = Decimal("0.8")
FAMILY_CONFIDENCE_THRESHOLD = Decimal("0.7")
logger = logging.getLogger(__name__)

_DOMAIN_MENTION = re.compile(
    r"(?<![@\w-])(?:https?://)?(?:www\.)?"
    r"([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]{2,63})+)",
    re.IGNORECASE,
)


class EnrichmentContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CompanyEnrichmentInput(EnrichmentContract):
    siren: str = Field(pattern=r"^\d{9}$")
    legal_name: str = Field(min_length=1, max_length=512)
    city: str | None = Field(default=None, max_length=512)
    department: str | None = Field(default=None, max_length=3)
    naf_code: str | None = Field(default=None, max_length=8)
    naf_label: str | None = Field(default=None, max_length=512)
    employees: int | None = Field(default=None, ge=0)
    directors_raw: tuple[dict[str, object], ...] = Field(default=(), max_length=20)

    @field_validator("directors_raw", mode="before")
    @classmethod
    def tuple_directors(cls, value):
        return tuple(value or ())


RenderedPage = ReducedRenderedPage


class SearchEvidence(EnrichmentContract):
    title: str = Field(default="", max_length=1024)
    url: str = Field(min_length=8, max_length=2048)
    snippet: str = Field(default="", max_length=2048)
    domain: str | None = Field(default=None, max_length=253)
    is_directory: bool
    directory_clues: DirectoryClues | None = None


class CompanyWebEvidence(EnrichmentContract):
    query: str = Field(min_length=1, max_length=1024)
    results: tuple[SearchEvidence, ...] = Field(max_length=10)
    candidate_pages: tuple[RenderedPage, ...] = Field(max_length=3)


class CompanyEnrichmentDecision(EnrichmentContract):
    website: str | None = Field(max_length=253)
    website_confidence: Decimal = Field(ge=0, le=1)
    email: str | None = Field(max_length=320)
    email_confidence: Decimal = Field(ge=0, le=1)
    email_is_placeholder: bool
    family: str | None = Field(max_length=100)
    family_confidence: Decimal = Field(ge=0, le=1)
    director_display_name: str | None = Field(max_length=256)
    phone: str | None = Field(max_length=32)
    notes: str = Field(max_length=2000)

    @field_validator("website", mode="before")
    @classmethod
    def website_is_a_domain(cls, value):
        if value is None:
            return None
        parsed = domain_from_url(value)
        if parsed is None:
            raise ValueError("website must be a domain")
        return parsed[0]

    @field_validator("email", mode="before")
    @classmethod
    def normalized_email(cls, value):
        return str(value).strip().casefold() if value is not None else None


class CompanyEnrichmentProviderResult(EnrichmentContract):
    decision: CompanyEnrichmentDecision
    model: str = Field(min_length=1, max_length=128)
    cost_usd: Decimal = Field(ge=0, max_digits=12, decimal_places=6)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class CompanyEnrichmentRunResult(EnrichmentContract):
    siren: str
    cached: bool
    website_retained: bool
    email_retained: bool
    family_confirmed: bool
    reverification_required: bool
    cost_usd: Decimal = Field(ge=0)


class CompanyEnrichmentProvider(Protocol):
    def enrich(
        self, identity: CompanyEnrichmentInput, evidence: CompanyWebEvidence
    ) -> CompanyEnrichmentProviderResult: ...


def _mentioned_domains(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            match.casefold().removeprefix("www.").rstrip(".")
            for match in _DOMAIN_MENTION.findall(value)
        )
    )


class CompanyWebCollector:
    """Collect bounded web evidence without deciding whether it belongs to a company."""

    def __init__(
        self,
        *,
        serper_api_key: str,
        client: httpx.Client | None = None,
        renderer: PageRenderer | None = None,
    ) -> None:
        if not serper_api_key.strip():
            raise ValueError("Serper API key is required")
        self._key = serper_api_key
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=True
        )
        self._renderer = renderer or PlaywrightPageRenderer()

    def _fetch(self, url: str) -> RenderedPage | None:
        raw = self._renderer.render(url)
        return reduce_rendered_page(raw) if raw is not None else None

    def collect(self, identity: CompanyEnrichmentInput) -> CompanyWebEvidence:
        query = " ".join(part for part in (identity.legal_name, identity.city) if part)
        try:
            response = self._client.post(
                SERPER_SEARCH_URL,
                json={"q": query, "gl": "fr", "hl": "fr", "num": 10},
                headers={"x-api-key": self._key, "content-type": "application/json"},
            )
            if response.status_code != 200 or len(response.content) > MAX_RESPONSE_BYTES:
                raise RuntimeError("Serper collection failed")
            payload = response.json()
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise RuntimeError("Serper collection failed") from error
        organic = payload.get("organic") if isinstance(payload, dict) else None
        if not isinstance(organic, list):
            raise TypeError("Serper collection returned invalid JSON")

        parsed_results: list[tuple[str, str, str, str, bool]] = []
        for raw in organic[:10]:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "")[:1024]
            url = str(raw.get("link") or "")[:2048]
            snippet = str(raw.get("snippet") or "")[:2048]
            parsed = domain_from_url(url)
            if parsed is None:
                continue
            domain, _ = parsed
            directory = is_directory_domain(domain)
            parsed_results.append((title, url, snippet, domain, directory))

        results: list[SearchEvidence] = []
        candidate_domains: list[str] = []
        for title, url, snippet, domain, directory in parsed_results:
            clues = None
            if directory:
                raw = self._renderer.render(url)
                if raw is not None:
                    clues = directory_clues_from_text(raw.body_text or raw.main_text)
            results.append(
                SearchEvidence(
                    title=title,
                    url=url,
                    snippet=snippet,
                    domain=domain,
                    is_directory=directory,
                    directory_clues=clues,
                )
            )
            if directory:
                clue_values = " ".join(
                    value for value in (title, snippet, clues.website if clues else None) if value
                )
                for mentioned in _mentioned_domains(clue_values):
                    if not is_directory_domain(mentioned) and not rejected_supplier_domain(mentioned):
                        candidate_domains.append(mentioned)
            else:
                candidate_domains.append(domain)

        candidate_domains = list(dict.fromkeys(candidate_domains))[:10]
        pages: list[RenderedPage] = []
        for domain in candidate_domains[:1]:
            for path in ("/", "/contact"):
                url = urljoin(f"https://{domain}/", path)
                page = self._fetch(url)
                if page is not None:
                    pages.append(page)
        unique_pages = tuple({page.url: page for page in pages}.values())[:2]
        return CompanyWebEvidence(
            query=query,
            results=tuple(results),
            candidate_pages=unique_pages,
        )

    @staticmethod
    def empty_evidence(identity: CompanyEnrichmentInput) -> CompanyWebEvidence:
        return CompanyWebEvidence(
            query=" ".join(part for part in (identity.legal_name, identity.city) if part),
            results=(),
            candidate_pages=(),
        )

    @staticmethod
    def evidence_for_test(
        identity: CompanyEnrichmentInput, *, domain: str, contact_text: str
    ) -> CompanyWebEvidence:
        home = RenderedPage(
            url=f"https://{domain}/",
            status_code=200,
            title=identity.legal_name,
            text=identity.legal_name,
        )
        contact = RenderedPage(
            **reduce_rendered_page(
                RawRenderedPage(
                    url=f"https://{domain}/contact",
                    status_code=200,
                    title="Contact",
                    main_text=contact_text,
                    body_text=contact_text,
                )
            ).model_dump()
        )
        return CompanyWebEvidence(
            query=f"{identity.legal_name} {identity.city or ''}".strip(),
            results=(
                SearchEvidence(
                    title=identity.legal_name,
                    url=home.url,
                    snippet="",
                    domain=domain,
                    is_directory=False,
                ),
            ),
            candidate_pages=(home, contact),
        )


class AnnuaireRawDirectorClient:
    """Read the registry's bounded director payload without classifying roles."""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0, follow_redirects=False)

    def find(self, siren: str) -> tuple[dict[str, object], ...]:
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
            output: list[dict[str, object]] = []
            for leader in leaders[:20]:
                if not isinstance(leader, dict):
                    continue
                first_name = str(leader.get("prenoms") or "").strip()
                last_name = str(leader.get("nom") or "").strip()
                corporate_name = str(leader.get("denomination") or "").strip()
                entity_type = str(leader.get("type_dirigeant") or "personne physique")
                is_corporate = "morale" in entity_type.casefold()
                name = corporate_name if is_corporate else " ".join(
                    part for part in (first_name, last_name) if part
                )
                if not name:
                    continue
                value: dict[str, object] = {
                    "name": name,
                    "title": str(leader.get("qualite") or entity_type or "Dirigeant"),
                    "entity_type": entity_type,
                }
                if first_name and not is_corporate:
                    value["first_name"] = first_name
                output.append(value)
            return tuple(output)
        except (httpx.HTTPError, TypeError, ValueError):
            return ()


def _page_for_email(
    email: str, website: str, evidence: CompanyWebEvidence
) -> RenderedPage | None:
    normalized = email.casefold()
    for page in evidence.candidate_pages:
        host = (urlsplit(page.url).hostname or "").casefold().removeprefix("www.")
        publication_text = page.text.casefold()
        for source, replacement in (
            ("[at]", "@"),
            ("(at)", "@"),
            (" at ", "@"),
            ("[dot]", "."),
            ("(dot)", "."),
            (" dot ", "."),
            ("[arrobase]", "@"),
            ("[point]", "."),
        ):
            publication_text = publication_text.replace(source, replacement)
        publication_text = re.sub(r"\s*([@.])\s*", r"\1", publication_text)
        if host == website and (
            normalized in page.published_emails or normalized in publication_text
        ):
            return page
    return None


def _director_title(name: str | None, directors: tuple[dict[str, object], ...]) -> str:
    if name:
        folded = name.casefold()
        for director in directors:
            if normalize_director_name(director.get("name")) == name or folded in str(
                director.get("name") or ""
            ).casefold():
                return str(director.get("title") or "Dirigeant")[:256]
    return "Entreprise"


class CompanyEnrichmentService:
    def __init__(
        self,
        *,
        directory: SupplierDirectoryStore,
        collector: CompanyWebCollector,
        provider: CompanyEnrichmentProvider,
        mx_verifier: Callable[[str], bool],
        director_source: Callable[[str], tuple[Mapping[str, object], ...]] | None = None,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._directory = directory
        self._collector = collector
        self._provider = provider
        self._mx = mx_verifier
        self._director_source = director_source
        self._clock = clock

    def enrich(
        self,
        siren: str,
        *,
        directors_raw: tuple[Mapping[str, object], ...] = (),
        force: bool = False,
    ) -> CompanyEnrichmentRunResult:
        now = self._clock()
        current = self._directory.get(siren)
        if current is None:
            raise KeyError(siren)
        if (
            not force
            and current.enrichment_observed_at is not None
            and now - current.enrichment_observed_at <= FRESHNESS
        ):
            return CompanyEnrichmentRunResult(
                siren=siren,
                cached=True,
                website_retained=bool(current.domain),
                email_retained=bool(current.professional_email),
                family_confirmed=current.family_confirmation_status == "confirmed",
                reverification_required=current.reverification_required_at is not None,
                cost_usd=Decimal("0"),
            )
        available_directors = directors_raw or current.directors
        if self._director_source is not None and (force or not available_directors):
            available_directors = self._director_source(siren)
        raw_directors = tuple(dict(item) for item in available_directors)[:20]
        identity = CompanyEnrichmentInput(
            siren=current.siren,
            legal_name=current.legal_name,
            city=current.city,
            department=current.department,
            naf_code=current.naf_code,
            naf_label=current.naf_label,
            employees=current.employees,
            directors_raw=raw_directors,
        )
        evidence = self._collector.collect(identity)
        provided = self._provider.enrich(identity, evidence)
        decision = provided.decision
        candidate_domains = {
            (urlsplit(page.url).hostname or "").casefold().removeprefix("www.")
            for page in evidence.candidate_pages
        }
        website = (decision.website or "").casefold().removeprefix("www.").rstrip(".") or None
        website_ok = bool(
            website
            and decision.website_confidence >= WEBSITE_CONFIDENCE_THRESHOLD
            and website in candidate_domains
            and not rejected_supplier_domain(website)
        )
        retained_website = website if website_ok else None
        email = (decision.email or "").casefold() or None
        email_page = (
            _page_for_email(email, retained_website, evidence)
            if email and retained_website
            else None
        )
        email_ok = bool(
            email
            and "@" in email
            and decision.email_confidence >= EMAIL_CONFIDENCE_THRESHOLD
            and not decision.email_is_placeholder
            and not is_placeholder_email(email)
            and not rejected_supplier_domain(email.rsplit("@", 1)[-1])
            and email_page is not None
            and self._mx(email)
        )
        known_families = supplier_family_keys()
        family_ok = bool(
            decision.family in known_families
            and decision.family_confidence >= FAMILY_CONFIDENCE_THRESHOLD
        )
        fallback_family = (
            current.family_keys[0]
            if current.family_source == "naf" and current.family_keys
            else default_supplier_family_for_naf(current.naf_code)
        )
        family = decision.family if family_ok else fallback_family
        display_name = normalize_director_name(decision.director_display_name)
        known_director_names = {
            normalize_director_name(item.get("name")) for item in raw_directors
        }
        if display_name not in known_director_names:
            display_name = None
        needs_review = not (website_ok and email_ok and family_ok)
        reason = "model_confidence_below_threshold" if needs_review else None
        self._directory.record_model_enrichment(
            siren,
            website=retained_website,
            website_confidence=(decision.website_confidence if website_ok else None),
            website_evidence_url=(
                next(
                    (
                        page.url
                        for page in evidence.candidate_pages
                        if (urlsplit(page.url).hostname or "")
                        .casefold()
                        .removeprefix("www.")
                        == retained_website
                    ),
                    None,
                )
                if retained_website
                else None
            ),
            email=email if email_ok else None,
            email_confidence=(decision.email_confidence if email_ok else None),
            email_evidence_url=email_page.url if email_ok and email_page is not None else None,
            family=family,
            family_confidence=(decision.family_confidence if family_ok else None),
            family_confirmed=family_ok,
            director_display_name=display_name,
            director_title=_director_title(display_name, raw_directors),
            phone=decision.phone,
            directors=raw_directors,
            notes=decision.notes,
            model=provided.model,
            cost_usd=provided.cost_usd,
            input_tokens=provided.input_tokens,
            output_tokens=provided.output_tokens,
            evidence=evidence.model_dump(mode="json"),
            decision=decision.model_dump(mode="json"),
            reverification_reason=reason,
            observed_at=now,
        )
        logger.info(
            "supplier_company_enrichment",
            extra={
                "siren": siren,
                "model": provided.model,
                "cost_usd": str(provided.cost_usd),
                "input_tokens": provided.input_tokens,
                "output_tokens": provided.output_tokens,
                "website_retained": website_ok,
                "email_retained": email_ok,
                "family_confirmed": family_ok,
            },
        )
        return CompanyEnrichmentRunResult(
            siren=siren,
            cached=False,
            website_retained=website_ok,
            email_retained=email_ok,
            family_confirmed=family_ok,
            reverification_required=needs_review,
            cost_usd=provided.cost_usd,
        )


__all__ = [
    "MODEL_MAX_TOKENS",
    "AnnuaireRawDirectorClient",
    "CompanyEnrichmentDecision",
    "CompanyEnrichmentInput",
    "CompanyEnrichmentProvider",
    "CompanyEnrichmentProviderResult",
    "CompanyEnrichmentRunResult",
    "CompanyEnrichmentService",
    "CompanyWebCollector",
    "CompanyWebEvidence",
    "RenderedPage",
    "SearchEvidence",
]
