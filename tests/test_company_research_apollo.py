from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest

from signals.company_research.apollo import ApolloCompanyResearchClient
from signals.company_research.contracts import CompanyResearchProviderError, ResearchGap
from signals.company_research.profile import build_company_research_profile

AFTER_RESPONSE = dt.datetime(2026, 8, 20, 12, 0, 2, tzinfo=dt.UTC)


def _payload(**organization_overrides: object) -> dict[str, object]:
    organization: dict[str, object] = {
        "id": "apollo-org-1",
        "name": "Acme SA",
        "primary_domain": "Acme.Example",
        "website_url": "https://www.acme.example/about",
        "country": "Switzerland",
        "industry": "Software",
        "estimated_num_employees": 120,
        "founded_year": 2015,
        "short_description": "A B2B software company",
        "keywords": ["B2B", "software", "B2B"],
        "phone": "+41 00 000 00 00",
        "annual_revenue": 10_000_000,
        "technology_names": ["SecretStack"],
    }
    organization.update(organization_overrides)
    return {"organization": organization}


def _client(handler, *, clock=lambda: AFTER_RESPONSE, max_response_bytes=1_048_576):
    return ApolloCompanyResearchClient(
        api_key="fake-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock,
        max_response_bytes=max_response_bytes,
    )


def test_exact_id_get_uses_fixed_host_path_and_allowlisted_response() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_payload())

    observation = _client(handler).fetch_organization(
        build_company_research_profile("apollo-org-1")
    )

    request = requests[0]
    assert request.method == "GET"
    assert request.url.scheme == "https"
    assert request.url.host == "api.apollo.io"
    assert request.url.path == "/api/v1/organizations/apollo-org-1"
    assert request.headers["x-api-key"] == "fake-key"
    assert request.headers["accept"] == "application/json"
    assert observation.provider_observed_at == AFTER_RESPONSE
    assert observation.provider_primary_domain == "acme.example"
    assert observation.provider_keywords == ("B2B", "software")
    dumped = observation.model_dump(mode="json")
    assert "phone" not in dumped
    assert "annual_revenue" not in dumped
    assert "technology_names" not in dumped


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "unauthorized"),
        (403, "forbidden"),
        (404, "not_found"),
        (422, "unprocessable_entity"),
        (429, "rate_limited"),
        (418, "client_error"),
        (500, "server_error"),
    ],
)
def test_http_failures_remain_distinct(status: int, category: str) -> None:
    client = _client(lambda request: httpx.Response(status))

    with pytest.raises(CompanyResearchProviderError) as caught:
        client.fetch_organization(build_company_research_profile("apollo-org-1"))

    assert caught.value.category == category


def test_429_preserves_only_authoritative_retry_after() -> None:
    client = _client(lambda request: httpx.Response(429, headers={"Retry-After": "120"}))

    with pytest.raises(CompanyResearchProviderError) as caught:
        client.fetch_organization(build_company_research_profile("apollo-org-1"))

    assert caught.value.retry_after == AFTER_RESPONSE + dt.timedelta(seconds=120)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"organization": None},
        {"organization": {"id": "apollo-org-1"}},
        {"organization": {"id": "", "name": "Acme"}},
        {"organization": {"id": "apollo-org-1", "name": ""}},
    ],
)
def test_identity_critical_malformed_response_fails(payload: object) -> None:
    client = _client(lambda request: httpx.Response(200, json=payload))

    with pytest.raises(CompanyResearchProviderError) as caught:
        client.fetch_organization(build_company_research_profile("apollo-org-1"))

    assert caught.value.category == "malformed_response"


def test_provider_identity_mismatch_is_not_optional_degradation() -> None:
    client = _client(lambda request: httpx.Response(200, json=_payload(id="apollo-org-2")))

    with pytest.raises(CompanyResearchProviderError) as caught:
        client.fetch_organization(build_company_research_profile("apollo-org-1"))

    assert caught.value.category == "provider_identity_mismatch"


def test_optional_invalid_fields_are_dropped_and_safe_facts_survive() -> None:
    client = _client(
        lambda request: httpx.Response(
            200,
            json=_payload(
                primary_domain="not a domain",
                website_url="javascript:alert(1)",
                estimated_num_employees=-1,
                founded_year=3026,
                keywords=["valid", 7, "x" * 129],
            ),
        )
    )

    observation = client.fetch_organization(build_company_research_profile("apollo-org-1"))

    assert observation.provider_company_name == "Acme SA"
    assert observation.provider_country == "Switzerland"
    assert observation.provider_industry == "Software"
    assert observation.provider_primary_domain is None
    assert observation.provider_website_url is None
    assert observation.provider_employee_count is None
    assert observation.provider_founded_year is None
    assert observation.provider_keywords == ("valid",)
    assert observation.research_gaps == tuple(
        sorted(
            {
                ResearchGap.INVALID_EMPLOYEE_COUNT,
                ResearchGap.INVALID_FOUNDED_YEAR,
                ResearchGap.INVALID_KEYWORDS,
                ResearchGap.INVALID_PRIMARY_DOMAIN,
                ResearchGap.INVALID_WEBSITE_URL,
                ResearchGap.MISSING_DOMAIN_OR_WEBSITE,
            },
            key=lambda item: item.value,
        )
    )


def test_keywords_and_description_are_bounded_deterministically() -> None:
    profile = build_company_research_profile("apollo-org-1")
    client = _client(
        lambda request: httpx.Response(
            200,
            json=_payload(
                short_description="x" * 2_100,
                keywords=[f"keyword-{index:02d}" for index in range(40)],
            ),
        )
    )

    observation = client.fetch_organization(profile)

    assert len(observation.provider_short_description or "") == 2_000
    assert len(observation.provider_keywords) == 32
    assert ResearchGap.TRUNCATED_DESCRIPTION in observation.research_gaps
    assert ResearchGap.TRUNCATED_KEYWORDS in observation.research_gaps


def test_provider_source_fingerprint_excludes_observation_time() -> None:
    times = iter(
        [
            dt.datetime(2026, 8, 20, 12, tzinfo=dt.UTC),
            dt.datetime(2026, 8, 21, 12, tzinfo=dt.UTC),
        ]
    )
    client = _client(
        lambda request: httpx.Response(200, json=_payload()), clock=lambda: next(times)
    )
    profile = build_company_research_profile("apollo-org-1")

    first = client.fetch_organization(profile)
    second = client.fetch_organization(profile)

    assert first.provider_observed_at != second.provider_observed_at
    assert first.provider_source_fingerprint == second.provider_source_fingerprint


def test_streaming_response_aborts_above_profile_bound() -> None:
    body = json.dumps(_payload(short_description="x" * 2_000)).encode()
    client = _client(lambda request: httpx.Response(200, content=body), max_response_bytes=100)

    with pytest.raises(CompanyResearchProviderError) as caught:
        client.fetch_organization(build_company_research_profile("apollo-org-1"))

    assert caught.value.category == "response_too_large"


def test_timeout_and_network_are_typed() -> None:
    for error, category in (
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("offline"), "network_error"),
    ):
        client = _client(lambda request, error=error: (_ for _ in ()).throw(error))
        with pytest.raises(CompanyResearchProviderError) as caught:
            client.fetch_organization(build_company_research_profile("apollo-org-1"))
        assert caught.value.category == category
