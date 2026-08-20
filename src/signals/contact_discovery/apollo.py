"""Narrow Apollo People Search and People Enrichment client."""

from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import json

import httpx

from signals.contact_discovery.contracts import (
    MAX_RESPONSE_BYTES,
    MAX_SEARCH_RESULTS,
    ApolloContactProviderError,
    ApolloEnrichedPerson,
    ContactCandidateRejection,
    DecisionMakerSearchProfile,
    PeopleSearchCandidate,
    PeopleSearchPage,
)

APOLLO_BASE_URL = "https://api.apollo.io"
PEOPLE_SEARCH_PATH = "/api/v1/mixed_people/api_search"
PEOPLE_ENRICHMENT_PATH = "/api/v1/people/match"


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


def _aware_iso(value: object) -> dt.datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("invalid provider datetime")
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("provider datetime must be timezone-aware")
    return parsed


def _optional_text(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("invalid text")
    stripped = value.strip()
    if len(stripped) > maximum:
        raise ValueError("text exceeds bound")
    return stripped or None


def _search_candidate(
    item: object, *, index: int
) -> PeopleSearchCandidate | ContactCandidateRejection:
    if not isinstance(item, dict):
        return ContactCandidateRejection(item_index=index, reason_code="invalid_person_item")
    raw_id = item.get("id")
    person_id = raw_id.strip() if isinstance(raw_id, str) else None
    if not person_id or len(person_id) > 128:
        return ContactCandidateRejection(item_index=index, reason_code="missing_person_id")
    try:
        title = _optional_text(item.get("title"), 512)
        first_name = _optional_text(item.get("first_name"), 512)
        last_name = _optional_text(item.get("last_name_obfuscated"), 512)
        refreshed = _aware_iso(item.get("last_refreshed_at"))
        organization = item.get("organization")
        if organization is not None and not isinstance(organization, dict):
            raise ValueError("invalid organization diagnostic")
        organization_name = _optional_text(
            organization.get("name") if isinstance(organization, dict) else None,
            512,
        )
    except (TypeError, ValueError):
        return ContactCandidateRejection(
            item_index=index,
            provider_person_id=person_id,
            reason_code="invalid_person_fields",
        )
    if title is None:
        return ContactCandidateRejection(
            item_index=index,
            provider_person_id=person_id,
            reason_code="missing_person_title",
        )
    has_email = item.get("has_email")
    if not isinstance(has_email, bool):
        return ContactCandidateRejection(
            item_index=index,
            provider_person_id=person_id,
            reason_code="invalid_email_availability",
        )
    return PeopleSearchCandidate(
        provider_person_id=person_id,
        first_name=first_name,
        last_name_obfuscated=last_name,
        title=title,
        provider_position=index,
        organization_name=organization_name,
        provider_refreshed_at=refreshed,
        has_email=has_email,
    )


class ApolloContactDiscoveryClient:
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

    def search_people(
        self, profile: DecisionMakerSearchProfile, *, observed_at: dt.datetime
    ) -> PeopleSearchPage:
        params: list[tuple[str, str]] = [
            ("organization_ids[]", profile.provider_organization_id),
            *(("person_titles[]", value) for value in profile.person_titles),
            *(("person_seniorities[]", value) for value in profile.person_seniorities),
            *(("contact_email_status[]", value) for value in profile.contact_email_statuses),
            ("include_similar_titles", "false"),
            ("page", "1"),
            ("per_page", str(profile.per_page)),
        ]
        payload = self._post(PEOPLE_SEARCH_PATH, params, observed_at=observed_at)
        if not isinstance(payload, dict):
            raise ApolloContactProviderError("malformed_response")
        total = payload.get("total_entries")
        people = payload.get("people")
        if (
            not isinstance(total, int)
            or isinstance(total, bool)
            or total < 0
            or not isinstance(people, list)
            or len(people) > MAX_SEARCH_RESULTS
            or total < len(people)
        ):
            raise ApolloContactProviderError("malformed_response")
        if total > 0 and not people:
            raise ApolloContactProviderError(
                "malformed_response", detail="unexpected_empty_search_page"
            )
        candidates: list[PeopleSearchCandidate] = []
        rejections: list[ContactCandidateRejection] = []
        for index, item in enumerate(people):
            parsed = _search_candidate(item, index=index)
            if isinstance(parsed, PeopleSearchCandidate):
                candidates.append(parsed)
            else:
                rejections.append(parsed)
        return PeopleSearchPage(
            total_entries=total,
            candidates=tuple(candidates),
            rejections=tuple(rejections),
            observed_at=observed_at,
        )

    def enrich_person(
        self, provider_person_id: str, *, observed_at: dt.datetime
    ) -> ApolloEnrichedPerson | None:
        if not provider_person_id.strip() or len(provider_person_id.strip()) > 128:
            raise ValueError("provider_person_id outside bounded range")
        params = [
            ("id", provider_person_id.strip()),
            ("reveal_personal_emails", "false"),
            ("reveal_phone_number", "false"),
            ("run_waterfall_email", "false"),
            ("run_waterfall_phone", "false"),
        ]
        payload = self._post(PEOPLE_ENRICHMENT_PATH, params, observed_at=observed_at)
        if not isinstance(payload, dict) or "person" not in payload:
            raise ApolloContactProviderError("malformed_response")
        if payload["person"] is None and set(payload) == {"person"}:
            return None
        if not isinstance(payload["person"], dict):
            raise ApolloContactProviderError("malformed_response")
        person = payload["person"]
        try:
            person_id = _optional_text(person.get("id"), 128)
            if person_id is None:
                raise ValueError("missing person id")
            organization_id = _optional_text(person.get("organization_id"), 128)
            first_name = _optional_text(person.get("first_name"), 512)
            last_name = _optional_text(person.get("last_name"), 512)
            display_name = _optional_text(person.get("name"), 512)
            title = _optional_text(person.get("title"), 512)
            business_email = _optional_text(person.get("email"), 320)
            email_status = _optional_text(person.get("email_status"), 64)
        except (TypeError, ValueError) as exc:
            raise ApolloContactProviderError("malformed_response") from exc
        safe = {
            "provider_person_id": person_id,
            "provider_organization_id": organization_id,
            "first_name": first_name,
            "last_name": last_name,
            "display_name": display_name,
            "title": title,
            "business_email": business_email,
            "provider_email_status": email_status,
        }
        source_fingerprint = hashlib.sha256(
            json.dumps(safe, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ApolloEnrichedPerson(
            **safe,
            provider_observed_at=observed_at,
            source_fingerprint=source_fingerprint,
        )

    def _post(
        self,
        path: str,
        params: list[tuple[str, str]],
        *,
        observed_at: dt.datetime,
    ) -> object:
        try:
            with self._client.stream(
                "POST",
                f"{APOLLO_BASE_URL}{path}",
                params=params,
                headers={"x-api-key": self._api_key, "accept": "application/json"},
            ) as response:
                category = {
                    401: "unauthorized",
                    403: "forbidden",
                    429: "rate_limited",
                }.get(response.status_code)
                if category is None and 500 <= response.status_code:
                    category = "server_error"
                if category is None and response.status_code >= 400:
                    category = "client_error"
                if category is not None:
                    raise ApolloContactProviderError(
                        category,
                        retry_after=(
                            _retry_after(response.headers.get("Retry-After"), observed_at)
                            if category == "rate_limited"
                            else None
                        ),
                    )
                if response.status_code != 200:
                    raise ApolloContactProviderError(
                        "malformed_response", detail="unexpected_http_status"
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > self._max_response_bytes:
                        raise ApolloContactProviderError("malformed_response")
                    body.extend(chunk)
        except httpx.TimeoutException as exc:
            raise ApolloContactProviderError("timeout") from exc
        except (httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise ApolloContactProviderError("network_error") from exc
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise ApolloContactProviderError("malformed_response") from exc
