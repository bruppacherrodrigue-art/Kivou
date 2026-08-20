from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest

from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.contact_discovery.contracts import ApolloContactProviderError
from signals.contact_discovery.profile import build_decision_maker_profile

NOW = dt.datetime(2026, 8, 20, 10, tzinfo=dt.UTC)


def _profile():
    return build_decision_maker_profile(
        acquisition_opportunity_id="ao-1",
        supplier_ref="supplier-1",
        provider_organization_id="apollo-org-1",
    )


def _search_payload(*, total: int = 1, organization_name: str = "Acme Group"):
    return {
        "total_entries": total,
        "people": [
            {
                "id": "apollo-person-1",
                "first_name": "Alice",
                "last_name_obfuscated": "Du***d",
                "title": "Sales Director",
                "last_refreshed_at": "2026-08-19T12:00:00+00:00",
                "has_email": True,
                "organization": {"name": organization_name},
            }
        ],
    }


def test_people_search_uses_only_approved_official_parameters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_search_payload())

    client = ApolloContactDiscoveryClient(
        api_key="fake-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    page = client.search_people(_profile(), observed_at=NOW)

    assert page.total_entries == 1
    assert len(page.candidates) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v1/mixed_people/api_search"
    params = request.url.params.multi_items()
    assert ("organization_ids[]", "apollo-org-1") in params
    assert ("contact_email_status[]", "verified") in params
    assert ("include_similar_titles", "false") in params
    assert ("page", "1") in params
    assert ("per_page", "25") in params
    assert not any(key in {"q_keywords", "person_locations[]"} for key, _ in params)


def test_search_organization_name_difference_is_diagnostic_not_rejection() -> None:
    client = ApolloContactDiscoveryClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=_search_payload(organization_name="ACME International Holdings"),
                )
            )
        ),
    )

    page = client.search_people(_profile(), observed_at=NOW)

    assert [item.provider_person_id for item in page.candidates] == ["apollo-person-1"]
    assert page.rejections == ()


def test_bad_search_item_is_rejected_without_losing_valid_candidate() -> None:
    payload = _search_payload(total=2)
    payload["people"].append({"id": "", "title": "VP Sales"})
    client = ApolloContactDiscoveryClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ),
    )

    page = client.search_people(_profile(), observed_at=NOW)

    assert len(page.candidates) == 1
    assert [item.reason_code for item in page.rejections] == ["missing_person_id"]


def test_enrichment_uses_id_and_explicitly_disables_sensitive_options() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "person": {
                    "id": "apollo-person-1",
                    "first_name": "Alice",
                    "last_name": "Dupont",
                    "name": "Alice Dupont",
                    "title": "Sales Director",
                    "organization_id": "apollo-org-1",
                    "email": "alice@acme.example",
                    "email_status": "verified",
                }
            },
        )

    client = ApolloContactDiscoveryClient(
        api_key="fake",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    person = client.enrich_person("apollo-person-1", observed_at=NOW)

    assert person.provider_person_id == "apollo-person-1"
    assert person.provider_organization_id == "apollo-org-1"
    assert person.business_email == "alice@acme.example"
    request = requests[0]
    assert request.url.path == "/api/v1/people/match"
    assert request.url.params["id"] == "apollo-person-1"
    assert request.url.params["reveal_personal_emails"] == "false"
    assert request.url.params["reveal_phone_number"] == "false"
    assert request.url.params["run_waterfall_email"] == "false"
    assert request.url.params["run_waterfall_phone"] == "false"
    assert "webhook_url" not in request.url.params


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "unauthorized"),
        (403, "forbidden"),
        (422, "client_error"),
        (429, "rate_limited"),
        (500, "server_error"),
    ],
)
def test_search_and_enrichment_http_failures_are_typed(status: int, category: str) -> None:
    client = ApolloContactDiscoveryClient(
        api_key="fake",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status))),
    )

    with pytest.raises(ApolloContactProviderError) as search_error:
        client.search_people(_profile(), observed_at=NOW)
    assert search_error.value.category == category

    with pytest.raises(ApolloContactProviderError) as enrich_error:
        client.enrich_person("person-1", observed_at=NOW)
    assert enrich_error.value.category == category


def test_rate_limit_preserves_authoritative_retry_after() -> None:
    client = ApolloContactDiscoveryClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(429, headers={"Retry-After": "120"})
            )
        ),
    )

    with pytest.raises(ApolloContactProviderError) as caught:
        client.enrich_person("person-1", observed_at=NOW)

    assert caught.value.retry_after == NOW + dt.timedelta(seconds=120)


@pytest.mark.parametrize(
    "payload",
    [
        {"people": []},
        {"total_entries": 1, "people": {}},
        {"total_entries": -1, "people": []},
    ],
)
def test_malformed_search_page_fails_closed(payload: dict[str, object]) -> None:
    client = ApolloContactDiscoveryClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ),
    )

    with pytest.raises(ApolloContactProviderError) as caught:
        client.search_people(_profile(), observed_at=NOW)

    assert caught.value.category == "malformed_response"


def test_oversized_timeout_and_network_failures_are_typed() -> None:
    oversized = ApolloContactDiscoveryClient(
        api_key="fake",
        max_response_bytes=100,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=json.dumps({"x": "y" * 200}))
            )
        ),
    )
    with pytest.raises(ApolloContactProviderError) as too_large:
        oversized.search_people(_profile(), observed_at=NOW)
    assert too_large.value.category == "malformed_response"

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    timed = ApolloContactDiscoveryClient(
        api_key="fake",
        client=httpx.Client(transport=httpx.MockTransport(timeout)),
    )
    with pytest.raises(ApolloContactProviderError) as timed_out:
        timed.enrich_person("person-1", observed_at=NOW)
    assert timed_out.value.category == "timeout"

    def disconnected(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    network = ApolloContactDiscoveryClient(
        api_key="fake",
        client=httpx.Client(transport=httpx.MockTransport(disconnected)),
    )
    with pytest.raises(ApolloContactProviderError) as unavailable:
        network.search_people(_profile(), observed_at=NOW)
    assert unavailable.value.category == "network_error"


def test_oversized_response_is_aborted_while_streaming() -> None:
    yielded = 0

    class LargeStream(httpx.SyncByteStream):
        def __iter__(self):
            nonlocal yielded
            for _ in range(10):
                yielded += 1
                yield b"x" * 600_000

    client = ApolloContactDiscoveryClient(
        api_key="fake",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=LargeStream()))
        ),
    )

    with pytest.raises(ApolloContactProviderError) as caught:
        client.search_people(_profile(), observed_at=NOW)

    assert caught.value.category == "malformed_response"
    assert yielded == 2
