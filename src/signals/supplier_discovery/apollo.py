"""Narrow Apollo Organization Search client; company data only."""

from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import json
import re
from urllib.parse import urlsplit

import httpx

from signals.supplier_discovery.contracts import (
    MAX_RESPONSE_BYTES,
    ApolloOrganizationCandidate,
    ApolloProviderError,
    CandidateRejection,
    SupplierSearchPage,
    SupplierSearchProfile,
)

APOLLO_BASE_URL = "https://api.apollo.io"
ORGANIZATION_SEARCH_PATH = "/api/v1/mixed_companies/search"
_DOMAIN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_COUNTRY_TO_CODE = {
    "switzerland": "CH",
    "france": "FR",
    "germany": "DE",
    "italy": "IT",
    "austria": "AT",
    "belgium": "BE",
}


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


def _safe_url(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError("invalid URL")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("invalid URL")
    return value.strip()


def _domain(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("invalid domain")
    normalized = value.strip().lower().rstrip(".")
    if not _DOMAIN.fullmatch(normalized):
        raise ValueError("invalid domain")
    return normalized


def _optional_text(value: object, *, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > maximum:
        raise ValueError("invalid text")
    return value.strip() or None


def _candidate(
    item: object, *, index: int, observed_at: dt.datetime
) -> ApolloOrganizationCandidate | CandidateRejection:
    if not isinstance(item, dict):
        return CandidateRejection(item_index=index, reason_code="invalid_organization_item")
    provider_id = item.get("id")
    safe_id = provider_id.strip() if isinstance(provider_id, str) else None
    if not safe_id or len(safe_id) > 128:
        return CandidateRejection(item_index=index, reason_code="missing_organization_id")
    name = item.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 512:
        return CandidateRejection(
            item_index=index,
            provider_organization_id=safe_id,
            reason_code="missing_organization_name",
        )
    try:
        website = _safe_url(item.get("website_url"))
        linkedin = _safe_url(item.get("linkedin_url"))
    except (TypeError, ValueError):
        return CandidateRejection(
            item_index=index,
            provider_organization_id=safe_id,
            reason_code="invalid_organization_url",
        )
    try:
        domain = _domain(item.get("primary_domain"))
    except (TypeError, ValueError):
        return CandidateRejection(
            item_index=index,
            provider_organization_id=safe_id,
            reason_code="invalid_organization_domain",
        )
    try:
        country = _optional_text(item.get("country"), maximum=100)
        city = _optional_text(item.get("city"), maximum=200)
        industry = _optional_text(item.get("industry"), maximum=256)
    except ValueError:
        return CandidateRejection(
            item_index=index,
            provider_organization_id=safe_id,
            reason_code="invalid_organization_location",
        )
    location = ", ".join(value for value in (city, country) if value) or None
    country_code = _COUNTRY_TO_CODE.get(country.casefold()) if country else None
    normalized_name = " ".join(name.casefold().split())
    if len(normalized_name) > 512:
        return CandidateRejection(
            item_index=index,
            provider_organization_id=safe_id,
            reason_code="invalid_organization_name",
        )
    canonical = {
        "provider": "apollo",
        "provider_organization_id": safe_id,
        "display_name": name.strip(),
        "normalized_name": normalized_name,
        "primary_domain": domain,
        "website_url": website,
        "linkedin_company_url": linkedin,
        "country_code": country_code,
        "location": location,
        "industry": industry,
    }
    source_fingerprint = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ApolloOrganizationCandidate(
        **canonical,
        provider_observed_at=observed_at,
        source_fingerprint=source_fingerprint,
    )


class ApolloOrganizationSearchClient:
    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Apollo API key is required")
        if not 1 <= max_response_bytes <= MAX_RESPONSE_BYTES:
            raise ValueError("max_response_bytes outside bounded range")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout)
        self._max_response_bytes = max_response_bytes

    def search_page(
        self,
        profile: SupplierSearchProfile,
        *,
        page: int,
        observed_at: dt.datetime,
    ) -> SupplierSearchPage:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not 1 <= page <= profile.max_pages:
            raise ValueError("page exceeds approved profile bounds")
        params: list[tuple[str, str]] = []
        params.extend(("organization_num_employees_ranges[]", value) for value in profile.employee_ranges)
        params.extend(("organization_locations[]", value) for value in profile.organization_locations)
        params.extend(
            ("organization_not_locations[]", value)
            for value in profile.organization_not_locations
        )
        params.extend(("q_organization_keyword_tags[]", value) for value in profile.keyword_tags)
        params.extend((("page", str(page)), ("per_page", str(profile.per_page))))
        try:
            with self._client.stream(
                "POST",
                APOLLO_BASE_URL + ORGANIZATION_SEARCH_PATH,
                params=params,
                headers={"x-api-key": self._api_key, "accept": "application/json"},
            ) as response:
                if response.status_code == 401:
                    raise ApolloProviderError("unauthorized")
                if response.status_code == 403:
                    raise ApolloProviderError("forbidden")
                if response.status_code == 429:
                    raise ApolloProviderError(
                        "rate_limited",
                        retry_after=_retry_after(
                            response.headers.get("Retry-After"), observed_at
                        ),
                    )
                if response.status_code >= 500:
                    raise ApolloProviderError("server_error")
                if response.status_code >= 400:
                    raise ApolloProviderError("client_error")
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > self._max_response_bytes:
                        raise ApolloProviderError(
                            "malformed_response",
                            detail="response size limit exceeded",
                        )
                    content.extend(chunk)
        except httpx.TimeoutException as exc:
            raise ApolloProviderError("timeout") from exc
        except httpx.NetworkError as exc:
            raise ApolloProviderError("network_error") from exc
        except httpx.DecodingError as exc:
            raise ApolloProviderError("malformed_response") from exc
        except httpx.RequestError as exc:
            raise ApolloProviderError("network_error") from exc
        try:
            payload = json.loads(content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ApolloProviderError("malformed_response", detail="invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ApolloProviderError("malformed_response", detail="invalid root shape")
        organizations = payload.get("organizations")
        pagination = payload.get("pagination")
        if not isinstance(organizations, list) or not isinstance(pagination, dict):
            raise ApolloProviderError("malformed_response", detail="invalid page shape")
        try:
            values = {
                key: pagination[key]
                for key in ("page", "per_page", "total_entries", "total_pages")
            }
        except KeyError as exc:
            raise ApolloProviderError("malformed_response", detail="incomplete pagination") from exc
        if any(type(value) is not int for value in values.values()):
            raise ApolloProviderError("malformed_response", detail="invalid pagination values")
        if (
            values["page"] != page
            or values["per_page"] != profile.per_page
            or len(organizations) > values["per_page"]
            or len(organizations) > values["total_entries"]
            or (organizations and values["total_pages"] < page)
        ):
            raise ApolloProviderError(
                "malformed_response", detail="inconsistent pagination"
            )
        partial = payload.get("partial_results_only")
        if partial is not None and type(partial) is not bool:
            raise ApolloProviderError("malformed_response", detail="invalid partial-results marker")
        accepted = []
        rejected = []
        for index, item in enumerate(organizations):
            result = _candidate(item, index=index, observed_at=observed_at)
            if isinstance(result, CandidateRejection):
                rejected.append(result)
            else:
                accepted.append(result)
        try:
            return SupplierSearchPage(
                **values,
                partial_results_only=partial,
                candidates=tuple(accepted),
                rejections=tuple(rejected),
            )
        except ValueError as exc:
            raise ApolloProviderError("malformed_response", detail="pagination out of bounds") from exc
