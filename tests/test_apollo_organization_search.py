from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest

from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient
from signals.supplier_discovery.contracts import (
    ApolloProviderError,
    SupplierSearchProfile,
)

NOW = dt.datetime(2026, 8, 20, 9, tzinfo=dt.UTC)


def profile(**overrides: object) -> SupplierSearchProfile:
    values: dict[str, object] = {
        "signal_ref": "procurement-opportunity:opp-public-1",
        "representative_award_key": "award-1",
        "need_categories": ("workforce_capacity",),
        "keyword_tags": ("staffing", "workforce solutions"),
        "organization_locations": ("Switzerland",),
        "organization_not_locations": ("United States",),
        "employee_ranges": ("11,50",),
        "max_pages": 1,
        "per_page": 100,
        "candidate_cap": 100,
        "search_too_broad_threshold": 10_000,
        "profile_fingerprint": "a" * 64,
    }
    values.update(overrides)
    return SupplierSearchProfile.model_validate(values)


def response_payload(organizations: list[dict[str, object]]) -> dict[str, object]:
    return {
        "organizations": organizations,
        "pagination": {
            "page": 1,
            "per_page": 100,
            "total_entries": len(organizations),
            "total_pages": 1,
        },
    }


def test_client_uses_only_official_organization_search_parameters() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=response_payload(
                [
                    {
                        "id": "apollo-org-1",
                        "name": "Acme SA",
                        "website_url": "https://acme.example",
                        "linkedin_url": "https://www.linkedin.com/company/acme",
                        "primary_domain": "acme.example",
                    }
                ]
            ),
        )

    client = ApolloOrganizationSearchClient(
        api_key="fake-apollo-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    page = client.search_page(profile(), page=1, observed_at=NOW)

    assert len(page.candidates) == 1
    assert page.candidates[0].provider_organization_id == "apollo-org-1"
    assert page.partial_results_only is None
    request = captured[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v1/mixed_companies/search"
    assert request.headers["x-api-key"] == "fake-apollo-key"
    assert sorted(request.url.params.multi_items()) == sorted(
        [
            ("organization_num_employees_ranges[]", "11,50"),
            ("organization_locations[]", "Switzerland"),
            ("organization_not_locations[]", "United States"),
            ("q_organization_keyword_tags[]", "staffing"),
            ("q_organization_keyword_tags[]", "workforce solutions"),
            ("page", "1"),
            ("per_page", "100"),
        ]
    )


def test_bad_item_is_rejected_without_losing_valid_organizations() -> None:
    payload = response_payload(
        [
            {"id": "apollo-org-1", "name": "Acme SA", "primary_domain": "acme.example"},
            {"id": "apollo-org-2", "name": "", "primary_domain": "broken.example"},
            {"id": "apollo-org-3", "name": "Bad URL", "website_url": "file:///etc/passwd"},
        ]
    )
    client = ApolloOrganizationSearchClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ),
    )

    page = client.search_page(profile(), page=1, observed_at=NOW)

    assert [item.provider_organization_id for item in page.candidates] == ["apollo-org-1"]
    assert [item.reason_code for item in page.rejections] == [
        "missing_organization_name",
        "invalid_organization_url",
    ]


def test_invalid_domain_type_is_an_item_rejection_not_a_page_failure() -> None:
    payload = response_payload(
        [
            {"id": "apollo-org-1", "name": "Acme SA"},
            {"id": "apollo-org-2", "name": "Bad Domain", "primary_domain": 42},
        ]
    )
    client = ApolloOrganizationSearchClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ),
    )

    page = client.search_page(profile(), page=1, observed_at=NOW)

    assert [item.provider_organization_id for item in page.candidates] == ["apollo-org-1"]
    assert [item.reason_code for item in page.rejections] == [
        "invalid_organization_domain"
    ]


def test_unicode_normalization_expansion_is_a_bounded_item_rejection() -> None:
    payload = response_payload(
        [
            {"id": "apollo-org-1", "name": "Acme SA"},
            {"id": "apollo-org-2", "name": "İ" * 512},
        ]
    )
    client = ApolloOrganizationSearchClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ),
    )

    page = client.search_page(profile(), page=1, observed_at=NOW)

    assert [item.provider_organization_id for item in page.candidates] == ["apollo-org-1"]
    assert [item.reason_code for item in page.rejections] == [
        "invalid_organization_name"
    ]


def test_empty_official_page_is_valid_without_partial_results_marker() -> None:
    client = ApolloOrganizationSearchClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response_payload([]))
            )
        ),
    )

    page = client.search_page(profile(), page=1, observed_at=NOW)

    assert page.candidates == ()
    assert page.rejections == ()
    assert page.partial_results_only is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"pagination": {}}),
        httpx.Response(200, json={"organizations": {}, "pagination": {}}),
        httpx.Response(200, json={"organizations": [], "pagination": "bad"}),
    ],
)
def test_page_level_malformed_response_fails_the_page(response: httpx.Response) -> None:
    client = ApolloOrganizationSearchClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: response)
        ),
    )
    with pytest.raises(ApolloProviderError) as caught:
        client.search_page(profile(), page=1, observed_at=NOW)
    assert caught.value.category == "malformed_response"


@pytest.mark.parametrize(
    "pagination",
    [
        {"page": 2, "per_page": 100, "total_entries": 0, "total_pages": 1},
        {"page": 1, "per_page": 99, "total_entries": 0, "total_pages": 1},
        {"page": 1, "per_page": 100, "total_entries": 0, "total_pages": 0},
    ],
)
def test_inconsistent_pagination_fails_closed(pagination: dict[str, int]) -> None:
    organizations = (
        [{"id": "apollo-org-1", "name": "Acme SA"}]
        if pagination["total_pages"] == 0
        else []
    )
    client = ApolloOrganizationSearchClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"organizations": organizations, "pagination": pagination},
                )
            )
        ),
    )

    with pytest.raises(ApolloProviderError) as caught:
        client.search_page(profile(), page=1, observed_at=NOW)

    assert caught.value.category == "malformed_response"


@pytest.mark.parametrize(
    ("status", "category"),
    [(401, "unauthorized"), (403, "forbidden"), (422, "client_error"), (500, "server_error")],
)
def test_http_failures_are_typed(status: int, category: str) -> None:
    client = ApolloOrganizationSearchClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status))
        ),
    )
    with pytest.raises(ApolloProviderError) as caught:
        client.search_page(profile(), page=1, observed_at=NOW)
    assert caught.value.category == category


def test_rate_limit_preserves_only_authoritative_retry_after() -> None:
    client = ApolloOrganizationSearchClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(429, headers={"Retry-After": "120"})
            )
        ),
    )
    with pytest.raises(ApolloProviderError) as caught:
        client.search_page(profile(), page=1, observed_at=NOW)
    assert caught.value.category == "rate_limited"
    assert caught.value.retry_after == NOW + dt.timedelta(seconds=120)


def test_unrepresentable_retry_after_is_not_invented_or_raised() -> None:
    client = ApolloOrganizationSearchClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    429, headers={"Retry-After": "9" * 100}
                )
            )
        ),
    )

    with pytest.raises(ApolloProviderError) as caught:
        client.search_page(profile(), page=1, observed_at=NOW)

    assert caught.value.category == "rate_limited"
    assert caught.value.retry_after is None


def test_oversized_body_and_timeout_are_typed() -> None:
    oversized = ApolloOrganizationSearchClient(
        api_key="fake",
        max_response_bytes=100,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=json.dumps({"x": "y" * 200}))
            )
        ),
    )
    with pytest.raises(ApolloProviderError) as caught:
        oversized.search_page(profile(), page=1, observed_at=NOW)
    assert caught.value.category == "malformed_response"

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("bounded timeout", request=request)

    timed = ApolloOrganizationSearchClient(
        api_key="fake",
        client=httpx.Client(transport=httpx.MockTransport(timeout)),
    )
    with pytest.raises(ApolloProviderError) as caught:
        timed.search_page(profile(), page=1, observed_at=NOW)
    assert caught.value.category == "timeout"


def test_network_failure_is_typed_and_does_not_expose_api_key() -> None:
    api_key = "fake-apollo-key-must-not-leak"

    def disconnected(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider unavailable", request=request)

    client = ApolloOrganizationSearchClient(
        api_key=api_key,
        client=httpx.Client(transport=httpx.MockTransport(disconnected)),
    )

    with pytest.raises(ApolloProviderError) as caught:
        client.search_page(profile(), page=1, observed_at=NOW)

    assert caught.value.category == "network_error"
    assert api_key not in str(caught.value)


def test_remote_protocol_failure_is_typed() -> None:
    def broken_protocol(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("truncated response", request=request)

    client = ApolloOrganizationSearchClient(
        api_key="fake",
        client=httpx.Client(transport=httpx.MockTransport(broken_protocol)),
    )

    with pytest.raises(ApolloProviderError) as caught:
        client.search_page(profile(), page=1, observed_at=NOW)

    assert caught.value.category == "network_error"
