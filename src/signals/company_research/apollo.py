"""Narrow Apollo exact-organization-ID research client."""

from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import json
import re
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from signals.company_research.contracts import (
    MAX_DESCRIPTION_LENGTH,
    MAX_EMPLOYEE_COUNT,
    MAX_KEYWORD_LENGTH,
    MAX_KEYWORDS,
    MAX_RESPONSE_BYTES,
    ApolloOrganizationObservation,
    CompanyResearchProfile,
    CompanyResearchProviderError,
    ResearchGap,
)

APOLLO_BASE_URL = "https://api.apollo.io"
ORGANIZATION_PATH_PREFIX = "/api/v1/organizations/"
_DOMAIN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("company research clock must be timezone-aware")
    return value


def _retry_after(value: str | None, observed_at: dt.datetime) -> dt.datetime | None:
    if not value:
        return None
    if value.isdigit():
        try:
            return observed_at + dt.timedelta(seconds=int(value))
        except (OverflowError, ValueError):
            return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)


def _required_text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > maximum:
        return None
    return stripped


def _optional_text(
    value: object,
    maximum: int,
    *,
    invalid_gap: ResearchGap,
    gaps: set[ResearchGap],
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        gaps.add(invalid_gap)
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > maximum:
        gaps.add(invalid_gap)
        return None
    return stripped


def _domain(value: object, gaps: set[ResearchGap]) -> str | None:
    candidate = _optional_text(
        value, 253, invalid_gap=ResearchGap.INVALID_PRIMARY_DOMAIN, gaps=gaps
    )
    if candidate is None:
        return None
    normalized = candidate.casefold().rstrip(".")
    if not _DOMAIN.fullmatch(normalized):
        gaps.add(ResearchGap.INVALID_PRIMARY_DOMAIN)
        return None
    return normalized


def _website(value: object, gaps: set[ResearchGap]) -> str | None:
    candidate = _optional_text(value, 2048, invalid_gap=ResearchGap.INVALID_WEBSITE_URL, gaps=gaps)
    if candidate is None:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        gaps.add(ResearchGap.INVALID_WEBSITE_URL)
        return None
    return candidate


def _employee_count(value: object, gaps: set[ResearchGap]) -> int | None:
    if value is None:
        gaps.add(ResearchGap.MISSING_EMPLOYEE_COUNT)
        return None
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= MAX_EMPLOYEE_COUNT
    ):
        gaps.add(ResearchGap.INVALID_EMPLOYEE_COUNT)
        return None
    return value


def _founded_year(value: object, observed_at: dt.datetime, gaps: set[ResearchGap]) -> int | None:
    if value is None:
        return None
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1000 <= value <= observed_at.year + 1
    ):
        gaps.add(ResearchGap.INVALID_FOUNDED_YEAR)
        return None
    return value


def _description(value: object, gaps: set[ResearchGap]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        gaps.add(ResearchGap.INVALID_DESCRIPTION)
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > MAX_DESCRIPTION_LENGTH:
        gaps.add(ResearchGap.TRUNCATED_DESCRIPTION)
        return stripped[:MAX_DESCRIPTION_LENGTH]
    return stripped


def _keywords(value: object, gaps: set[ResearchGap]) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        gaps.add(ResearchGap.INVALID_KEYWORDS)
        return ()
    accepted: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            gaps.add(ResearchGap.INVALID_KEYWORDS)
            continue
        stripped = item.strip()
        if not stripped or len(stripped) > MAX_KEYWORD_LENGTH:
            gaps.add(ResearchGap.INVALID_KEYWORDS)
            continue
        accepted.add(stripped)
    ordered = sorted(accepted, key=lambda item: (item.casefold(), item))
    if len(ordered) > MAX_KEYWORDS:
        gaps.add(ResearchGap.TRUNCATED_KEYWORDS)
        ordered = ordered[:MAX_KEYWORDS]
    return tuple(ordered)


def _source_fingerprint(values: dict[str, object], gaps: tuple[ResearchGap, ...]) -> str:
    canonical = {
        **values,
        "provider_keywords": list(values["provider_keywords"]),
        "research_gaps": [gap.value for gap in gaps],
    }
    return hashlib.sha256(
        json.dumps(canonical, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ApolloCompanyResearchClient:
    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        clock: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Apollo API key is required")
        if not 1 <= max_response_bytes <= MAX_RESPONSE_BYTES:
            raise ValueError("max_response_bytes outside bounded range")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout)
        self._max_response_bytes = max_response_bytes
        self._clock = clock

    def fetch_organization(self, profile: CompanyResearchProfile) -> ApolloOrganizationObservation:
        payload = self._get(profile)
        observed_at = _aware(self._clock())
        if not isinstance(payload, dict):
            raise CompanyResearchProviderError("malformed_response")
        organization = payload.get("organization")
        if not isinstance(organization, dict):
            raise CompanyResearchProviderError("malformed_response")
        provider_id = _required_text(organization.get("id"), 128)
        company_name = _required_text(organization.get("name"), 512)
        if provider_id is None or company_name is None:
            raise CompanyResearchProviderError("malformed_response")
        if provider_id != profile.provider_organization_id:
            raise CompanyResearchProviderError("provider_identity_mismatch")

        gaps: set[ResearchGap] = set()
        primary_domain = _domain(organization.get("primary_domain"), gaps)
        website_url = _website(organization.get("website_url"), gaps)
        if primary_domain is None and website_url is None:
            gaps.add(ResearchGap.MISSING_DOMAIN_OR_WEBSITE)
        country = _optional_text(
            organization.get("country"),
            128,
            invalid_gap=ResearchGap.INVALID_COUNTRY,
            gaps=gaps,
        )
        if country is None and ResearchGap.INVALID_COUNTRY not in gaps:
            gaps.add(ResearchGap.MISSING_COUNTRY)
        industry = _optional_text(
            organization.get("industry"),
            256,
            invalid_gap=ResearchGap.INVALID_INDUSTRY,
            gaps=gaps,
        )
        if industry is None and ResearchGap.INVALID_INDUSTRY not in gaps:
            gaps.add(ResearchGap.MISSING_INDUSTRY)
        employee_count = _employee_count(organization.get("estimated_num_employees"), gaps)
        founded_year = _founded_year(organization.get("founded_year"), observed_at, gaps)
        description = _description(organization.get("short_description"), gaps)
        keywords = _keywords(organization.get("keywords"), gaps)
        ordered_gaps = tuple(sorted(gaps, key=lambda item: item.value))
        safe: dict[str, object] = {
            "provider": "apollo",
            "provider_organization_id": provider_id,
            "provider_company_name": company_name,
            "provider_primary_domain": primary_domain,
            "provider_website_url": website_url,
            "provider_country": country,
            "provider_industry": industry,
            "provider_employee_count": employee_count,
            "provider_founded_year": founded_year,
            "provider_short_description": description,
            "provider_keywords": keywords,
        }
        return ApolloOrganizationObservation(
            **safe,
            provider_observed_at=observed_at,
            provider_source_fingerprint=_source_fingerprint(safe, ordered_gaps),
            research_gaps=ordered_gaps,
        )

    def _get(self, profile: CompanyResearchProfile) -> object:
        try:
            with self._client.stream(
                "GET",
                f"{APOLLO_BASE_URL}{ORGANIZATION_PATH_PREFIX}{profile.provider_organization_id}",
                headers={"x-api-key": self._api_key, "accept": "application/json"},
            ) as response:
                category = {
                    401: "unauthorized",
                    403: "forbidden",
                    404: "not_found",
                    422: "unprocessable_entity",
                    429: "rate_limited",
                }.get(response.status_code)
                if category is None and 400 <= response.status_code < 500:
                    category = "client_error"
                if category is None and response.status_code >= 500:
                    category = "server_error"
                if category is not None:
                    now = _aware(self._clock())
                    raise CompanyResearchProviderError(
                        category,
                        retry_after=(
                            _retry_after(response.headers.get("Retry-After"), now)
                            if category == "rate_limited"
                            else None
                        ),
                    )
                if response.status_code != 200:
                    raise CompanyResearchProviderError(
                        "malformed_response", detail="unexpected_http_status"
                    )
                body = bytearray()
                maximum = min(self._max_response_bytes, profile.max_response_bytes)
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > maximum:
                        raise CompanyResearchProviderError("response_too_large")
                    body.extend(chunk)
        except httpx.TimeoutException as exc:
            raise CompanyResearchProviderError("timeout") from exc
        except (httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise CompanyResearchProviderError("network_error") from exc
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise CompanyResearchProviderError("malformed_response") from exc
