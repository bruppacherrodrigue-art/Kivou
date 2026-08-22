from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from signals.campaigns.instantly import InstantlyErrorCode, InstantlyProviderError
from signals.responses.instantly_email import (
    INSTANTLY_EMAIL_SCOPE,
    HttpInstantlyEmailReader,
    ListEmailsQuery,
    UnconfiguredInstantlyEmailReader,
)

FIXTURE = Path(__file__).parent / "fixtures" / "instantly_v2_email_response_2026-08-22.json"
VALUES = json.loads(FIXTURE.read_text())
NOW = dt.datetime(2026, 8, 22, 10, tzinfo=dt.UTC)


def _query(**updates) -> ListEmailsQuery:
    values = {
        "campaign_id": "01a028e4-5069-7b56-ae56-b7e622c7fbf1",
        "lead": "buyer@example.invalid",
        "eaccount": "sender@example.invalid",
        "min_timestamp_created": NOW - dt.timedelta(minutes=5),
        "max_timestamp_created": NOW + dt.timedelta(minutes=15),
    }
    values.update(updates)
    return ListEmailsQuery.model_validate(values)


def test_official_list_contract_uses_only_bounded_get_query() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=VALUES["list"])

    reader = HttpInstantlyEmailReader(
        api_key="synthetic-email-read-key",
        workspace_ref="workspace:test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )

    result = reader.list_emails(_query())

    assert INSTANTLY_EMAIL_SCOPE == "emails:read"
    assert len(result.items) == 1
    assert result.items[0].id == "01a028e4-5069-7b56-ae56-b7e4352c53fa"
    assert result.items[0].lead == "buyer@example.invalid"
    assert result.items[0].eaccount == "sender@example.invalid"
    assert result.items[0].from_address_email == "sender@example.invalid"
    assert result.items[0].from_address_email != result.items[0].lead
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "GET"
    assert request.url.path == "/api/v2/emails"
    assert dict(request.url.params) == {
        "campaign_id": "01a028e4-5069-7b56-ae56-b7e622c7fbf1",
        "lead": "buyer@example.invalid",
        "eaccount": "sender@example.invalid",
        "email_type": "received",
        "min_timestamp_created": "2026-08-22T09:55:00Z",
        "max_timestamp_created": "2026-08-22T10:15:00Z",
        "sort_order": "asc",
        "limit": "100",
    }
    assert request.headers["authorization"] == "Bearer synthetic-email-read-key"
    assert not hasattr(reader, "request")


def test_get_uses_exact_uuid_and_ignores_provider_ai_and_attachment_enrichment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/emails/01a028e4-5069-7b56-ae56-b7e4352c53fa")
        return httpx.Response(200, json=VALUES["get"])

    reader = HttpInstantlyEmailReader(
        api_key="synthetic-email-read-key",
        workspace_ref="workspace:test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )

    email = reader.get_email("01a028e4-5069-7b56-ae56-b7e4352c53fa")

    assert email.body.text == "Yes, please show me examples."
    assert not hasattr(email, "ai_interest_value")
    assert not hasattr(email, "attachment_json")
    serialized = repr(email)
    for marker in (
        "synthetic-response@example.invalid",
        "Synthetic inquiry",
        "show me examples",
        "SYNTHETIC-CONTENT-PREVIEW",
        "SYNTHETIC-ATTACHMENT",
    ):
        assert marker not in serialized


def test_query_contract_is_exact_and_bounded() -> None:
    with pytest.raises(ValidationError):
        _query(limit=101)
    with pytest.raises(ValidationError, match="resolution interval"):
        _query(max_timestamp_created=NOW + dt.timedelta(minutes=16))
    with pytest.raises(ValidationError):
        ListEmailsQuery.model_validate(
            {**_query().model_dump(), "subject_search": "forbidden heuristic"}
        )


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, InstantlyErrorCode.AUTH),
        (402, InstantlyErrorCode.PLAN_REQUIRED),
        (403, InstantlyErrorCode.PERMISSION),
        (404, InstantlyErrorCode.CLIENT_CONTRACT_ERROR),
        (500, InstantlyErrorCode.SERVER_ERROR),
    ],
)
def test_read_failures_are_typed_without_reflecting_provider_payload(status, code) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "SENSITIVE-PROVIDER-PAYLOAD"})

    reader = HttpInstantlyEmailReader(
        api_key="SENSITIVE-API-KEY",
        workspace_ref="workspace:test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )

    with pytest.raises(InstantlyProviderError) as captured:
        reader.list_emails(_query())

    assert captured.value.code is code
    assert "SENSITIVE" not in str(captured.value)
    assert "SENSITIVE" not in repr(reader)


def test_429_honors_bounded_retry_after() -> None:
    reader = HttpInstantlyEmailReader(
        api_key="synthetic-email-read-key",
        workspace_ref="workspace:test",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(429, headers={"Retry-After": "17"})
            )
        ),
        clock=lambda: NOW,
    )
    with pytest.raises(InstantlyProviderError) as captured:
        reader.list_emails(_query())
    assert captured.value.code is InstantlyErrorCode.RATE_LIMITED
    assert captured.value.retry_after_seconds == 17


def test_kivou_rate_budget_is_ten_list_or_get_requests_per_workspace_minute() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=VALUES["list"])

    reader = HttpInstantlyEmailReader(
        api_key="synthetic-email-read-key",
        workspace_ref="workspace:test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )
    for _ in range(10):
        reader.list_emails(_query())
    with pytest.raises(InstantlyProviderError) as captured:
        reader.list_emails(_query())
    assert captured.value.code is InstantlyErrorCode.RATE_LIMITED
    assert calls == 10


def test_invalid_uuid_and_unconfigured_reader_fail_before_network() -> None:
    reader = UnconfiguredInstantlyEmailReader()
    with pytest.raises(InstantlyProviderError) as captured:
        reader.list_emails(_query())
    assert captured.value.code is InstantlyErrorCode.AUTH

    configured = HttpInstantlyEmailReader(
        api_key="synthetic-email-read-key",
        workspace_ref="workspace:test",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: pytest.fail("invalid UUID attempted network")
            )
        ),
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="UUID"):
        configured.get_email("webhook-reply-to-uuid-is-not-an-inbound-email-id")
