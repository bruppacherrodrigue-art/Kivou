"""Conservative Apollo/SIRENE matching via the public French company search API."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import time
import unicodedata
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

import httpx
import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import Engine

from signals.acquisition_programs.legal_pages import LegalPageResolver
from signals.acquisition_programs.pipeline import ActiveCompanyEvidence
from signals.companies.france import ANNUAIRE_BASE_URL, MAX_RESPONSE_BYTES
from signals.company_research.contracts import ApolloOrganizationObservation
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import (
    acquisition_census_company_match,
    acquisition_census_official_cache,
    acquisition_census_run,
    sirene_apollo_binding,
)
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate

SOURCE = "ANNUAIRE_ENTREPRISES_SIRENE"
MATCHER_VERSION = "milomail-fr-company-v2"
_SIREN = re.compile(r"^[0-9]{9}$")
_RETRY_REASONS = frozenset({
    "SOURCE_TIMEOUT", "SOURCE_UNAVAILABLE", "SOURCE_RATE_LIMIT", "SOURCE_REQUEST_CAP",
})


class OfficialSourceRetryLater(RuntimeError):
    """No legal proof was established; resume this candidate after source recovery."""


def _norm(value: str | None) -> str:
    folded = unicodedata.normalize("NFKD", (value or "").casefold())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", "".join(
        char for char in folded if not unicodedata.combining(char)
    )).split())


def _seat(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("siege")
    return value if isinstance(value, dict) else {}


def _minimal_result(item: dict[str, Any]) -> dict[str, Any]:
    # Search responses can contain more fields than the legal proof requires.
    seat = _seat(item)
    return {
        key: item.get(key) for key in (
            "siren", "nom_raison_sociale", "nom_complet", "etat_administratif",
            "activite_principale", "date_mise_a_jour", "date_mise_a_jour_insee",
        )
    } | {"siege": {key: seat.get(key) for key in (
        "siret", "nom_commercial", "libelle_commune", "code_postal", "etat_administratif",
    )}}


class OfficialSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = False
    max_requests: int = Field(default=0, ge=0, le=100_000)
    timeout_seconds: float = Field(default=5, gt=0, le=20)
    cache_ttl_days: int = Field(default=7, ge=1, le=30)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=400)
    source: Literal["ANNUAIRE_ENTREPRISES"] = "ANNUAIRE_ENTREPRISES"

    @classmethod
    def from_environment(cls, source: Mapping[str, str]) -> OfficialSourceConfig:
        enabled = source.get("MILOMAIL_COMPANY_STATUS_ENABLED", "false").casefold()
        if enabled not in {"true", "false"}:
            raise ValueError("invalid official source enabled flag")
        if source.get("MILOMAIL_COMPANY_STATUS_SOURCE", "ANNUAIRE_ENTREPRISES") != "ANNUAIRE_ENTREPRISES":
            raise ValueError("unsupported official source")
        return cls(
            enabled=enabled == "true",
            max_requests=int(source.get("MILOMAIL_COMPANY_STATUS_MAX_REQUESTS", "0")),
            timeout_seconds=float(source.get("MILOMAIL_COMPANY_STATUS_REQUEST_TIMEOUT_SECONDS", "5")),
            cache_ttl_days=int(source.get("MILOMAIL_COMPANY_STATUS_CACHE_TTL_DAYS", "7")),
            rate_limit_per_minute=int(source.get("MILOMAIL_COMPANY_STATUS_RATE_LIMIT", "60")),
            source="ANNUAIRE_ENTREPRISES",
        )


class OfficialMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_name: Literal["ANNUAIRE_ENTREPRISES_SIRENE"] = "ANNUAIRE_ENTREPRISES_SIRENE"
    legal_status: Literal["ACTIVE", "CEASED", "UNKNOWN", "AMBIGUOUS"]
    match_confidence: Literal["CONFIRMED_MATCH", "PROBABLE_MATCH", "AMBIGUOUS_MATCH", "NO_MATCH"]
    siren: str | None = None
    siret: str | None = None
    legal_name: str | None = None
    trade_name: str | None = None
    naf_or_ape: str | None = None
    administrative_status: str | None = None
    postal_code: str | None = None
    source_last_updated_at: str | None = None
    source_reference: str | None = None
    observed_at: dt.datetime
    match_reasons: tuple[str, ...]
    matcher_version: str = MATCHER_VERSION
    legal_page_source_url: str | None = None
    legal_page_observed_at: dt.datetime | None = None

    def activity(self) -> ActiveCompanyEvidence:
        if self.match_confidence != "CONFIRMED_MATCH":
            return ActiveCompanyEvidence(status="UNKNOWN")
        status: Literal["ACTIVE", "INACTIVE", "UNKNOWN"]
        if self.legal_status == "ACTIVE":
            status = "ACTIVE"
        elif self.legal_status == "CEASED":
            status = "INACTIVE"
        else:
            return ActiveCompanyEvidence(status="UNKNOWN")
        return ActiveCompanyEvidence(
            status=status,
            source_url=self.source_reference,
            source_type=SOURCE,
            observed_at=self.observed_at,
            evidence_id=f"sirene:{self.siren}:{self.matcher_version}",
        )


class OfficialCompanyMatcher:
    """Read-only API origin; only dated, unique and corroborated matches prove activity."""

    def __init__(self, engine: Engine, config: OfficialSourceConfig, *,
                 client: httpx.Client | None = None, census_id: str | None = None) -> None:
        self.engine = engine
        self.config = config
        self.client = client
        self.census_id = census_id
        self.requests_made = 0
        self.last_request_at: dt.datetime | None = None

    def _binding(self, provider_id: str, domain: str | None, *, at: dt.datetime) -> str | None:
        with self.engine.connect() as connection:
            rows = connection.execute(sa.select(sirene_apollo_binding).where(
                sirene_apollo_binding.c.apollo_organization_id == provider_id,
                sirene_apollo_binding.c.status == "resolved",
            )).mappings().all()
        if len(rows) != 1 or not domain or rows[0]["domain"] != domain:
            return None
        row = rows[0]
        resolved = row["resolved_at"]
        if (row["resolution_method"] != "domain" or
                row["confidence_score"] is None or row["confidence_score"] < Decimal("0.9") or
                resolved is None or not dt.timedelta(0) <= at - resolved.replace(tzinfo=dt.UTC)
                <= dt.timedelta(days=90)):
            return None
        return str(rows[0]["siren"])

    def assess(self, company: ApolloOrganizationObservation,
               candidate: ApolloOrganizationCandidate, *, at: dt.datetime) -> OfficialMatch:
        matched = self._assess(company, candidate, at=at)
        if self.census_id:
            with self.engine.begin() as connection:
                inserted = insert_if_absent(connection, acquisition_census_company_match, {
                    "census_id": self.census_id,
                    "provider_organization_id": company.provider_organization_id,
                    "match_evidence": matched.model_dump(mode="json"),
                    "observed_at": matched.observed_at,
                })
                if not inserted:
                    connection.execute(sa.update(acquisition_census_company_match).where(
                        acquisition_census_company_match.c.census_id == self.census_id,
                        acquisition_census_company_match.c.provider_organization_id ==
                        company.provider_organization_id,
                        acquisition_census_company_match.c.observed_at <= matched.observed_at,
                    ).values(match_evidence=matched.model_dump(mode="json"),
                             observed_at=matched.observed_at))
        if _RETRY_REASONS.intersection(matched.match_reasons):
            raise OfficialSourceRetryLater("official source is temporarily unavailable")
        return matched

    def assess_search_candidate(self, candidate: ApolloOrganizationCandidate, *,
                                at: dt.datetime) -> OfficialMatch:
        """Match only fields returned by organization search; no Apollo enrichment."""
        observation = ApolloOrganizationObservation(
            provider_organization_id=candidate.provider_organization_id,
            provider_company_name=candidate.display_name,
            provider_primary_domain=candidate.primary_domain,
            provider_website_url=candidate.website_url,
            provider_country=candidate.country_code,
            provider_industry=candidate.industry,
            provider_observed_at=candidate.provider_observed_at,
            provider_source_fingerprint=candidate.source_fingerprint,
        )
        return self.assess(observation, candidate, at=at)

    def assess_with_legal_page(self, candidate: ApolloOrganizationCandidate, *,
                               resolver: LegalPageResolver, at: dt.datetime) -> OfficialMatch:
        """A website identifier is corroborated against exact SIRENE and Apollo identity."""
        if not isinstance(resolver, LegalPageResolver) or not candidate.primary_domain:
            return self.assess_search_candidate(candidate, at=at)
        legal = resolver.resolve(candidate.primary_domain, at=at)
        siren = legal.get("siren")
        if not isinstance(siren, str) or not _SIREN.fullmatch(siren):
            return self.assess_search_candidate(candidate, at=at)
        observation = ApolloOrganizationObservation(
            provider_organization_id=candidate.provider_organization_id,
            provider_company_name=candidate.display_name,
            provider_primary_domain=candidate.primary_domain,
            provider_website_url=candidate.website_url,
            provider_country=candidate.country_code,
            provider_industry=candidate.industry,
            provider_observed_at=candidate.provider_observed_at,
            provider_source_fingerprint=candidate.source_fingerprint,
        )
        matched = self._assess(observation, candidate, at=at, trusted_siren=siren)
        # The site's legal owner may be a web agency or parent company. Require
        # its official legal/trade identity to corroborate Apollo's company name.
        names = {_norm(matched.legal_name), _norm(matched.trade_name)} - {""}
        if matched.match_confidence == "CONFIRMED_MATCH" and _norm(candidate.display_name) not in names:
            matched = matched.model_copy(update={
                "match_confidence": "PROBABLE_MATCH",
                "match_reasons": (*matched.match_reasons, "APOLLO_NAME_NOT_CORROBORATED"),
            })
        matched = matched.model_copy(update={
            "legal_page_source_url": legal.get("source_url"),
            "legal_page_observed_at": at,
            "match_reasons": (*matched.match_reasons, "WEBSITE_LEGAL_IDENTIFIER"),
        })
        if self.census_id:
            with self.engine.begin() as connection:
                connection.execute(sa.delete(acquisition_census_company_match).where(
                    acquisition_census_company_match.c.census_id == self.census_id,
                    acquisition_census_company_match.c.provider_organization_id ==
                    candidate.provider_organization_id,
                ))
                connection.execute(sa.insert(acquisition_census_company_match).values(
                    census_id=self.census_id,
                    provider_organization_id=candidate.provider_organization_id,
                    match_evidence=matched.model_dump(mode="json"), observed_at=at,
                ))
        return matched

    def _assess(self, company: ApolloOrganizationObservation,
                candidate: ApolloOrganizationCandidate, *, at: dt.datetime,
                trusted_siren: str | None = None) -> OfficialMatch:
        siren = trusted_siren or self._binding(company.provider_organization_id,
                                                candidate.primary_domain, at=at)
        query = siren or company.provider_company_name
        if not query or not self.config.enabled:
            return OfficialMatch(legal_status="UNKNOWN", match_confidence="NO_MATCH",
                                 observed_at=at, match_reasons=("SOURCE_DISABLED_OR_QUERY_MISSING",))
        key = hashlib.sha256(f"{MATCHER_VERSION}\0{query}".encode()).hexdigest()
        with self.engine.connect() as connection:
            cached = connection.execute(sa.select(acquisition_census_official_cache).where(
                acquisition_census_official_cache.c.query_hash == key,
            )).mappings().one_or_none()
        if cached and cached["expires_at"].replace(tzinfo=dt.UTC) > at:
            results = cached["evidence"]
            observed = cached["observed_at"].replace(tzinfo=dt.UTC)
        else:
            if (self.requests_made >= self.config.max_requests or
                    self.config.max_requests == 0):
                return OfficialMatch(legal_status="UNKNOWN", match_confidence="NO_MATCH",
                                     observed_at=at, match_reasons=("SOURCE_REQUEST_CAP",))
            if self.last_request_at and (
                at - self.last_request_at
            ).total_seconds() < 60 / self.config.rate_limit_per_minute:
                delay = 60 / self.config.rate_limit_per_minute - (
                    at - self.last_request_at
                ).total_seconds()
                if delay > 5:
                    return OfficialMatch(legal_status="UNKNOWN", match_confidence="NO_MATCH",
                                         observed_at=at, match_reasons=("SOURCE_RATE_LIMIT",))
                time.sleep(max(delay, 0))
                at = dt.datetime.now(dt.UTC)
            if self.census_id:
                with self.engine.begin() as connection:
                    reserved = connection.execute(sa.update(acquisition_census_run).where(
                        acquisition_census_run.c.census_id == self.census_id,
                        acquisition_census_run.c.official_requests_reserved <
                        self.config.max_requests,
                    ).values(official_requests_reserved=
                             acquisition_census_run.c.official_requests_reserved + 1))
                    if reserved.rowcount != 1:
                        return OfficialMatch(legal_status="UNKNOWN", match_confidence="NO_MATCH",
                                             observed_at=at,
                                             match_reasons=("SOURCE_REQUEST_CAP",))
            self.requests_made += 1
            self.last_request_at = at
            try:
                if self.client is None:
                    with httpx.Client(base_url=ANNUAIRE_BASE_URL, follow_redirects=False,
                                      timeout=self.config.timeout_seconds) as client:
                        response = client.get("/search", params={"q": query, "page": 1,
                                                                  "per_page": 25})
                else:
                    response = self.client.get(f"{ANNUAIRE_BASE_URL}/search", params={
                        "q": query, "page": 1, "per_page": 25,
                    }, timeout=self.config.timeout_seconds)
                if response.status_code == 429:
                    return OfficialMatch(legal_status="UNKNOWN", match_confidence="NO_MATCH",
                                         observed_at=at, match_reasons=("SOURCE_RATE_LIMIT",))
                if response.status_code >= 500:
                    return OfficialMatch(legal_status="UNKNOWN", match_confidence="NO_MATCH",
                                         observed_at=at, match_reasons=("SOURCE_UNAVAILABLE",))
                if response.status_code != 200 or len(response.content) > MAX_RESPONSE_BYTES:
                    raise ValueError("official source unavailable or too large")
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                    raise TypeError("invalid official source response")
                if len(payload["results"]) > 25:
                    raise ValueError("invalid result limit")
                results = [_minimal_result(item) for item in payload["results"]
                           if isinstance(item, dict)]
                total = payload.get("total_results")
                if not siren and (type(total) is not int or total < 0 or
                                  total != len(results)):
                    results.append({"truncated": True})
            except httpx.TimeoutException:
                return OfficialMatch(legal_status="UNKNOWN", match_confidence="NO_MATCH",
                                     observed_at=at, match_reasons=("SOURCE_TIMEOUT",))
            except (httpx.HTTPError, TypeError, ValueError):
                return OfficialMatch(legal_status="UNKNOWN", match_confidence="NO_MATCH",
                                     observed_at=at, match_reasons=("SOURCE_UNAVAILABLE",))
            observed = at
            with self.engine.begin() as connection:
                connection.execute(sa.delete(acquisition_census_official_cache).where(
                    acquisition_census_official_cache.c.query_hash == key,
                    acquisition_census_official_cache.c.expires_at <= at,
                ))
                insert_if_absent(connection, acquisition_census_official_cache, {
                    "query_hash": key, "source_name": SOURCE, "evidence": results,
                    "observed_at": at,
                    "expires_at": at + dt.timedelta(days=self.config.cache_ttl_days),
                }, index_elements=["query_hash"])
        return match_official_results(company, candidate, results, observed_at=observed,
                                      trusted_siren=siren)


def match_official_results(company: ApolloOrganizationObservation,
                           candidate: ApolloOrganizationCandidate,
                           results: list[dict[str, Any]], *, observed_at: dt.datetime,
                           trusted_siren: str | None = None) -> OfficialMatch:
    """Name-only matches stay probable; a verified Kivou SIREN binding can confirm."""
    if any(item.get("truncated") for item in results):
        return OfficialMatch(legal_status="AMBIGUOUS", match_confidence="AMBIGUOUS_MATCH",
                             observed_at=observed_at,
                             match_reasons=("OFFICIAL_SEARCH_RESULTS_TRUNCATED",))
    names = {_norm(company.provider_company_name), _norm(candidate.display_name)}
    city = _norm(candidate.location.split(",", 1)[0]) if candidate.location else ""
    qualified: list[tuple[dict[str, Any], bool, bool]] = []
    for item in results:
        if not isinstance(item, dict) or not _SIREN.fullmatch(str(item.get("siren") or "")):
            continue
        if trusted_siren and item["siren"] != trusted_siren:
            continue
        seat = _seat(item)
        official_names = {_norm(item.get("nom_raison_sociale")),
                          _norm(item.get("nom_complet")), _norm(seat.get("nom_commercial"))}
        exact_siren = trusted_siren == item["siren"]
        name_match = bool(names & official_names - {""})
        place_match = bool(city and city == _norm(seat.get("libelle_commune")))
        postal_match = bool(candidate.postal_code and
                            candidate.postal_code == seat.get("code_postal") and
                            candidate.primary_domain and
                            candidate.primary_domain == company.provider_primary_domain)
        if exact_siren or (name_match and place_match):
            qualified.append((item, exact_siren, postal_match and name_match and place_match))
    if not qualified:
        return OfficialMatch(legal_status="UNKNOWN", match_confidence="NO_MATCH",
                             observed_at=observed_at, match_reasons=("NO_CORROBORATED_MATCH",))
    if len(qualified) != 1:
        return OfficialMatch(legal_status="AMBIGUOUS", match_confidence="AMBIGUOUS_MATCH",
                             observed_at=observed_at, match_reasons=("MULTIPLE_CORROBORATED_MATCHES",))
    item, exact_siren, postal_confirmed = qualified[0]
    seat = _seat(item)
    raw_status = item.get("etat_administratif")
    status: Literal["ACTIVE", "CEASED", "UNKNOWN", "AMBIGUOUS"] = (
        "ACTIVE" if raw_status == "A" else "CEASED" if raw_status == "C" else "UNKNOWN"
    )
    confidence: Literal["CONFIRMED_MATCH", "PROBABLE_MATCH"] = (
        "CONFIRMED_MATCH" if exact_siren or postal_confirmed else "PROBABLE_MATCH"
    )
    return OfficialMatch(
        legal_status=status, match_confidence=confidence, siren=item["siren"],
        siret=seat.get("siret"), legal_name=item.get("nom_raison_sociale"),
        trade_name=seat.get("nom_commercial"), naf_or_ape=item.get("activite_principale"),
        administrative_status=raw_status, postal_code=seat.get("code_postal"),
        source_last_updated_at=item.get("date_mise_a_jour_insee") or item.get("date_mise_a_jour"),
        source_reference=f"https://annuaire-entreprises.data.gouv.fr/entreprise/{item['siren']}",
        observed_at=observed_at, match_reasons=(
            ("TRUSTED_SIREN_BINDING",) if exact_siren
            else ("EXACT_NAME_CITY_POSTAL_AND_APOLLO_DOMAIN",) if postal_confirmed
            else ("EXACT_NAME_AND_CITY", "POSTAL_CODE_OR_DOMAIN_NOT_CORROBORATED")
        ),
    )
