from __future__ import annotations

import httpx
import pytest

from signals.acquisition_connectivity.apollo import (
    APOLLO_HEALTH_URL,
    APOLLO_PROFILE_URL,
    ApolloIdentityProbe,
    build_apollo_components,
)
from signals.acquisition_connectivity.contracts import ConnectivityErrorCode, ConnectivityFailure
from signals.company_research.apollo import ApolloCompanyResearchClient
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient


def _probe(handler) -> ApolloIdentityProbe:
    return ApolloIdentityProbe(
        api_key="synthetic-apollo-value",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_composition_reuses_all_three_existing_apollo_clients() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500))
    )

    components = build_apollo_components(
        api_key="synthetic-apollo-value",
        client=client,
    )

    assert isinstance(components.organization_search, ApolloOrganizationSearchClient)
    assert isinstance(components.contact_discovery, ApolloContactDiscoveryClient)
    assert isinstance(components.company_research, ApolloCompanyResearchClient)
    assert isinstance(components.identity, ApolloIdentityProbe)


def test_identity_probe_calls_only_the_two_official_zero_credit_gets() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url == httpx.URL(APOLLO_HEALTH_URL):
            return httpx.Response(200, json={"healthy": True, "is_logged_in": True})
        return httpx.Response(200, json={"id": "acting-user-opaque-provider-id"})

    evidence = _probe(handler).check()

    assert [(request.method, str(request.url)) for request in requests] == [
        ("GET", APOLLO_HEALTH_URL),
        ("GET", APOLLO_PROFILE_URL),
    ]
    assert all(request.headers["x-api-key"] == "synthetic-apollo-value" for request in requests)
    assert all("authorization" not in request.headers for request in requests)
    assert all(request.content == b"" for request in requests)
    assert all(request.extensions["timeout"]["read"] == 10.0 for request in requests)
    assert evidence.auth == "READY"
    assert evidence.acting_profile == "BOUND"
    assert len(evidence.acting_profile_fingerprint) == 64
    assert "acting-user-opaque-provider-id" not in repr(evidence)


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, ConnectivityErrorCode.AUTH),
        (403, ConnectivityErrorCode.PERMISSION),
        (429, ConnectivityErrorCode.RATE_LIMITED),
        (500, ConnectivityErrorCode.SERVER_ERROR),
    ],
)
def test_http_failures_map_to_the_closed_safe_vocabulary(
    status: int, code: ConnectivityErrorCode
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"Retry-After": "7"})

    with pytest.raises(ConnectivityFailure) as caught:
        _probe(handler).check()

    assert caught.value.code is code
    assert caught.value.retry_after_seconds == (7 if status == 429 else None)
    assert "synthetic-apollo-value" not in str(caught.value)


@pytest.mark.parametrize(
    "exception,code",
    [
        (httpx.TimeoutException("contains-sensitive-detail"), ConnectivityErrorCode.TIMEOUT),
        (httpx.NetworkError("contains-sensitive-detail"), ConnectivityErrorCode.NETWORK),
    ],
)
def test_transport_failures_are_bounded_and_never_retried(
    exception: Exception, code: ConnectivityErrorCode
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise exception

    with pytest.raises(ConnectivityFailure) as caught:
        _probe(handler).check()

    assert caught.value.code is code
    assert calls == 1
    assert "contains-sensitive-detail" not in str(caught.value)


@pytest.mark.parametrize(
    "health",
    [
        {},
        {"healthy": True},
        {"healthy": False, "is_logged_in": True},
        {"healthy": True, "is_logged_in": False},
        [],
    ],
)
def test_unhealthy_or_malformed_health_fails_closed(health: object) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=health)

    with pytest.raises(ConnectivityFailure) as caught:
        _probe(handler).check()

    assert caught.value.code in {
        ConnectivityErrorCode.AUTH,
        ConnectivityErrorCode.MALFORMED_RESPONSE,
    }


@pytest.mark.parametrize("profile", [{}, {"id": ""}, {"id": 12}, [], None])
def test_profile_requires_only_one_bounded_acting_user_id(profile: object) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"healthy": True, "is_logged_in": True})
        return httpx.Response(200, json=profile)

    with pytest.raises(ConnectivityFailure) as caught:
        _probe(handler).check()

    assert caught.value.code is ConnectivityErrorCode.MALFORMED_RESPONSE


def test_response_body_size_is_bounded_before_json_parsing() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 65_537)

    with pytest.raises(ConnectivityFailure) as caught:
        _probe(handler).check()

    assert caught.value.code is ConnectivityErrorCode.MALFORMED_RESPONSE
