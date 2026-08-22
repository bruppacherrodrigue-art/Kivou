from __future__ import annotations

import datetime as dt
import json
from copy import deepcopy

import httpx
import pytest

from signals.campaigns.contracts import MailboxReadinessState
from signals.campaigns.instantly import (
    INSTANTLY_V2_BASE_URL,
    HttpInstantlyProvider,
    InstantlyErrorCode,
    InstantlyProviderError,
    build_provider_campaign_config,
    normalize_mailbox_readiness,
)


def _provider(handler) -> HttpInstantlyProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpInstantlyProvider(api_key="synthetic-test-key", client=client)


def test_adapter_uses_only_api_v2_and_closed_campaign_payload() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(
            200,
            json={"id": "provider-campaign-1", "name": "KIVOU-deadbeef-FR-fr-wedge", "status": 0},
        )

    result = _provider(handler).create_campaign(
        name="KIVOU-deadbeef-FR-fr-wedge",
        provider_config=build_provider_campaign_config(
            step_1_execution_date=dt.date(2026, 8, 24),
            step_2_execution_date=dt.date(2026, 8, 28),
            timezone="Europe/Paris",
            provider_account_id="provider-account:test",
            daily_limit=3,
        ),
    )

    assert result.provider_campaign_id == "provider-campaign-1"
    assert observed[0].url == httpx.URL(f"{INSTANTLY_V2_BASE_URL}/campaigns")
    assert observed[0].headers["authorization"] == "Bearer synthetic-test-key"
    assert json.loads(observed[0].content)["name"].startswith("KIVOU-")


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, InstantlyErrorCode.AUTH),
        (402, InstantlyErrorCode.PLAN_REQUIRED),
        (403, InstantlyErrorCode.PERMISSION),
        (429, InstantlyErrorCode.RATE_LIMITED),
        (500, InstantlyErrorCode.SERVER_ERROR),
    ],
)
def test_http_failures_are_typed(status: int, code: InstantlyErrorCode) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"Retry-After": "7"})

    with pytest.raises(InstantlyProviderError) as caught:
        _provider(handler).list_campaigns(search="KIVOU-safe")

    assert caught.value.code is code
    assert caught.value.retry_after_seconds == (7 if status == 429 else None)
    assert "synthetic-test-key" not in str(caught.value)


@pytest.mark.parametrize("exc", [httpx.TimeoutException("timeout"), httpx.NetworkError("down")])
def test_mutation_unknown_outcome_requires_reconciliation(exc: Exception) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise exc

    with pytest.raises(InstantlyProviderError) as caught:
        _provider(handler).activate_campaign("provider-campaign-1")

    assert caught.value.reconciliation_required is True
    assert calls == 1


def test_adapter_rejects_unknown_provider_response_shape() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(InstantlyProviderError) as caught:
        _provider(handler).get_campaign("provider-campaign-1")

    assert caught.value.code is InstantlyErrorCode.MALFORMED_RESPONSE


def test_interface_exposes_no_generic_request_method() -> None:
    provider = _provider(lambda _request: httpx.Response(200, json={"items": []}))
    assert not hasattr(provider, "request")
    assert {
        "list_campaigns",
        "get_campaign",
        "create_campaign",
        "configure_campaign",
        "activate_campaign",
        "pause_campaign",
        "get_mailbox_readiness",
        "create_lead_or_batch",
        "list_leads",
        "get_lead",
        "pause_lead",
        "list_webhooks",
        "get_webhook_events",
    } <= {name for name in dir(provider) if not name.startswith("_")}


def test_campaign_readback_preserves_unknown_configuration_for_fail_closed_diff() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "provider-campaign-1",
                "name": "KIVOU-safe",
                "status": "draft",
                "schedule": {"timezone": "Europe/Paris"},
                "stop_on_reply": True,
                "provider_internal_field": "must-not-enter-readback",
            },
        )

    campaign = _provider(handler).get_campaign("provider-campaign-1")

    assert campaign.raw_config == {
        "schedule": {"timezone": "Europe/Paris"},
        "stop_on_reply": True,
        "provider_internal_field": "must-not-enter-readback",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(auto_variant_select=True),
        lambda value: value.update(ai_sdr=True),
        lambda value: value["sequences"][0]["steps"][0].update(
            body="{% if lead %}{{kivou_envelope}}{% endif %}"
        ),
        lambda value: value["sequences"][0]["steps"][1].update(
            body="{{kivou_follow_up|spin}}"
        ),
        lambda value: value["sequences"][0]["steps"].append(
            {"step": 3, "subject": "", "body": "forbidden"}
        ),
    ],
)
def test_campaign_payload_rejects_ai_variants_liquid_spintax_and_step_three(
    mutate,
) -> None:
    config = deepcopy(
        build_provider_campaign_config(
            step_1_execution_date=dt.date(2026, 8, 24),
            step_2_execution_date=dt.date(2026, 8, 28),
            timezone="Europe/Paris",
            provider_account_id="provider-account:test",
            daily_limit=3,
        )
    )
    mutate(config)

    with pytest.raises(ValueError):
        _provider(lambda _request: httpx.Response(500)).create_campaign(
            name="KIVOU-safe",
            provider_config=config,
        )


def test_single_lead_uses_official_v2_shape_and_transient_email_only() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={"id": "provider-lead-1", "status": "active"})

    result = _provider(handler).create_lead_or_batch(
        provider_campaign_id="provider-campaign-1",
        leads=(
            {
                "email": "synthetic@example.invalid",
                "custom_variables": {"kivou_member_ref": "member-safe"},
                "skip_if_in_workspace": True,
            },
        ),
    )

    body = json.loads(observed[0].content)
    assert result["id"] == "provider-lead-1"
    assert observed[0].url == httpx.URL(f"{INSTANTLY_V2_BASE_URL}/leads")
    assert body == {
        "email": "synthetic@example.invalid",
        "custom_variables": {"kivou_member_ref": "member-safe"},
        "skip_if_in_workspace": True,
        "campaign": "provider-campaign-1",
    }


def test_oversized_provider_response_is_rejected_before_json_decode() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1_048_577)

    with pytest.raises(InstantlyProviderError) as caught:
        _provider(handler).list_webhooks()

    assert caught.value.code is InstantlyErrorCode.MALFORMED_RESPONSE


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, MailboxReadinessState.READY),
        ({"status": "paused"}, MailboxReadinessState.TEMPORARILY_UNAVAILABLE),
        ({"daily_limit": 0}, MailboxReadinessState.TEMPORARILY_UNAVAILABLE),
        ({"status": "connection error"}, MailboxReadinessState.UNHEALTHY),
        ({"warmup_status": "banned"}, MailboxReadinessState.UNHEALTHY),
        ({"tracking_domain_status": "invalid"}, MailboxReadinessState.UNHEALTHY),
        ({"status": "provider-new-state"}, MailboxReadinessState.UNKNOWN),
        ({"setup_pending": None}, MailboxReadinessState.UNKNOWN),
    ],
)
def test_mailbox_readiness_mapper_is_typed_and_fail_closed(changes, expected) -> None:
    raw = {
        "status": "active",
        "warmup_status": "completed",
        "setup_pending": False,
        "daily_limit": 3,
        "sending_gap": 300,
        "tracking_domain_status": "verified",
    }
    raw.update(changes)

    result = normalize_mailbox_readiness(
        raw, observed_at=dt.datetime(2026, 8, 21, 13, tzinfo=dt.UTC)
    )

    assert result.state is expected
    assert "email" not in result.model_dump(mode="json")
