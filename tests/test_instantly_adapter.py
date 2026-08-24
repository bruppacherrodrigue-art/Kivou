from __future__ import annotations

import datetime as dt
import json
from copy import deepcopy
from pathlib import Path

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
    normalize_provider_campaign_config,
    normalized_provider_campaign_config_fingerprint,
    provider_campaign_configs_match,
)

OFFICIAL_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "instantly_v2_contract_v1.json").read_text()
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


def test_campaign_create_request_matches_official_v2_fixture_exactly() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json=OFFICIAL_FIXTURE["campaign_patch_response"])

    request_fixture = OFFICIAL_FIXTURE["campaign_create_request"]
    _provider(handler).create_campaign(
        name=request_fixture["name"],
        provider_config=build_provider_campaign_config(
            step_1_execution_date=dt.date(2026, 8, 24),
            step_2_execution_date=dt.date(2026, 8, 28),
            timezone="Europe/Paris",
            provider_account_id="sender@example.invalid",
            daily_limit=3,
        ),
    )

    assert json.loads(observed[0].content) == request_fixture


def test_campaign_schedule_uses_official_nested_shape_and_python_weekdays() -> None:
    config = build_provider_campaign_config(
        step_1_execution_date=dt.date(2026, 8, 24),
        step_2_execution_date=dt.date(2026, 8, 28),
        timezone="Europe/Paris",
        provider_account_id="sender@example.invalid",
        daily_limit=3,
    )

    assert "campaign_schedule" in config
    assert "schedule" not in config
    schedule = config["campaign_schedule"]
    assert schedule["start_date"] == "2026-08-24"
    assert schedule["end_date"] == "2026-08-28"
    assert len(schedule["schedules"]) == 1
    item = schedule["schedules"][0]
    assert item["timezone"] == "Europe/Paris"
    assert item["days"] == {
        "0": True,
        "1": False,
        "2": False,
        "3": False,
        "4": True,
        "5": False,
        "6": False,
    }
    assert "7" not in item["days"]


def test_sequence_uses_one_active_official_variant_and_delay_on_step_one() -> None:
    config = OFFICIAL_FIXTURE["campaign_create_request"] | {}
    steps = config["sequences"][0]["steps"]

    assert len(steps) == 2
    assert all(step["type"] == "email" for step in steps)
    assert all(len(step["variants"]) == 1 for step in steps)
    assert all(step["variants"][0]["v_disabled"] is False for step in steps)
    # Official V2 defines delay as the wait before the NEXT email; therefore
    # the four-day wait belongs to Step 1, and the final step has no delay.
    assert steps[0]["delay"] == 4
    assert steps[0]["delay_unit"] == "days"
    assert "delay" not in steps[1]
    assert "delay_unit" not in steps[1]


def test_transport_flags_use_only_official_v2_representations() -> None:
    config = build_provider_campaign_config(
        step_1_execution_date=dt.date(2026, 8, 24),
        step_2_execution_date=dt.date(2026, 8, 28),
        timezone="Europe/Paris",
        provider_account_id="sender@example.invalid",
        daily_limit=3,
    )

    assert "bounce_protection" not in config
    assert config["disable_bounce_protect"] is False
    assert config["auto_variant_select"] is None
    assert config["auto_variant_select"] is not False


def test_campaign_patch_sends_only_the_official_writable_subset() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json=OFFICIAL_FIXTURE["campaign_patch_response"])

    provider_config = dict(OFFICIAL_FIXTURE["campaign_create_request"])
    provider_config.pop("name")
    campaign_id = OFFICIAL_FIXTURE["campaign_patch_response"]["id"]
    result = _provider(handler).configure_campaign(
        campaign_id, provider_config=provider_config
    )

    assert result.provider_campaign_id == campaign_id
    assert observed[0].method == "PATCH"
    assert observed[0].url == httpx.URL(
        f"{INSTANTLY_V2_BASE_URL}/campaigns/{campaign_id}"
    )
    assert json.loads(observed[0].content) == provider_config


def test_create_binds_identity_without_assuming_full_response_config() -> None:
    response = OFFICIAL_FIXTURE["campaign_patch_response"]

    campaign = _provider(
        lambda _request: httpx.Response(200, json=response)
    ).create_campaign(
        name=response["name"],
        provider_config={
            key: value
            for key, value in OFFICIAL_FIXTURE["campaign_create_request"].items()
            if key != "name"
        },
    )

    assert campaign.provider_campaign_id == response["id"]
    assert campaign.normalized_config is None


def test_get_campaign_requires_full_normalizable_readback() -> None:
    response = OFFICIAL_FIXTURE["campaign_patch_response"]

    with pytest.raises(InstantlyProviderError) as caught:
        _provider(lambda _request: httpx.Response(200, json=response)).get_campaign(
            response["id"]
        )

    assert caught.value.code is InstantlyErrorCode.MALFORMED_RESPONSE


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


def test_campaign_readback_normalizes_official_response_enrichment() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=OFFICIAL_FIXTURE["campaign_get_response"])

    campaign = _provider(handler).get_campaign(
        OFFICIAL_FIXTURE["campaign_get_response"]["id"]
    )
    desired = dict(OFFICIAL_FIXTURE["campaign_create_request"])
    desired.pop("name")

    assert campaign.normalized_config == normalize_provider_campaign_config(
        OFFICIAL_FIXTURE["campaign_get_response"]
    )
    assert provider_campaign_configs_match(campaign.normalized_config, desired)
    assert normalized_provider_campaign_config_fingerprint(
        campaign.normalized_config
    ) == normalized_provider_campaign_config_fingerprint(desired)
    assert "status" not in campaign.normalized_config
    assert "not_sending_status" not in campaign.normalized_config
    assert "analytics" not in campaign.normalized_config


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["campaign_schedule"]["schedules"][0]["timing"].update(
            to="16:59"
        ),
        lambda value: value["sequences"][0]["steps"][0]["variants"][0].update(
            body="provider drift"
        ),
        lambda value: value.update(stop_on_reply=False),
        lambda value: value.update(open_tracking=True),
    ],
)
def test_material_campaign_readback_drift_fails_semantic_comparison(mutate) -> None:
    response = deepcopy(OFFICIAL_FIXTURE["campaign_get_response"])
    mutate(response)
    desired = dict(OFFICIAL_FIXTURE["campaign_create_request"])
    desired.pop("name")

    normalized = normalize_provider_campaign_config(response)

    assert not provider_campaign_configs_match(normalized, desired)


def test_campaign_status_is_checked_separately_from_config() -> None:
    response = deepcopy(OFFICIAL_FIXTURE["campaign_get_response"])
    normalized_draft = normalize_provider_campaign_config(response)
    response["status"] = 1
    normalized_active = normalize_provider_campaign_config(response)

    assert normalized_active == normalized_draft
    assert response["status"] == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("is_evergreen", True),
        ("cc_list", ["unapproved@example.invalid"]),
        ("bcc_list", ["unapproved@example.invalid"]),
        ("ai_sdr_id", "019c0000-0000-7000-8000-000000000009"),
        ("prioritize_new_leads", True),
        ("match_lead_esp", True),
        (
            "provider_routing_rules",
            [
                {
                    "action": "send",
                    "recipient_esp": ["gmail"],
                    "sender_esp": ["all"],
                }
            ],
        ),
    ],
)
def test_material_response_only_execution_fields_fail_closed(field, value) -> None:
    response = deepcopy(OFFICIAL_FIXTURE["campaign_get_response"])
    response[field] = value

    with pytest.raises(ValueError):
        normalize_provider_campaign_config(response)


def test_unknown_campaign_response_field_fails_closed() -> None:
    response = deepcopy(OFFICIAL_FIXTURE["campaign_get_response"])
    response["provider_future_send_mode"] = "unbounded"

    with pytest.raises(ValueError, match="unknown provider campaign response"):
        normalize_provider_campaign_config(response)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(auto_variant_select={"trigger": "click_rate"}),
        lambda value: value.update(ai_sdr=True),
        lambda value: value["sequences"][0]["steps"][0]["variants"][0].update(
            body="{% if lead %}{{kivou_envelope}}{% endif %}"
        ),
        lambda value: value["sequences"][0]["steps"][1]["variants"][0].update(
            body="{{kivou_follow_up|spin}}"
        ),
        lambda value: value["sequences"][0]["steps"].append(
            {
                "type": "email",
                "variants": [
                    {"subject": "", "body": "forbidden", "v_disabled": False}
                ],
            }
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


def test_official_lead_get_and_list_shapes_normalize_payload_binding() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.method == "GET":
            return httpx.Response(200, json=OFFICIAL_FIXTURE["lead_get_response"])
        return httpx.Response(200, json=OFFICIAL_FIXTURE["lead_list_response"])

    provider = _provider(handler)
    lead = provider.get_lead(OFFICIAL_FIXTURE["lead_get_response"]["id"])
    listed = provider.list_leads(
        provider_campaign_id=OFFICIAL_FIXTURE["campaign_get_response"]["id"]
    )

    assert lead["custom_variables"] == {"kivou_member_ref": "member-safe"}
    assert lead["campaign_id"] == OFFICIAL_FIXTURE["campaign_get_response"]["id"]
    assert listed["items"][0]["custom_variables"] == {
        "kivou_member_ref": "member-safe"
    }
    assert calls == 2


def test_lead_list_uses_official_post_endpoint_and_campaign_filter() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json=OFFICIAL_FIXTURE["lead_list_response"])

    campaign_id = OFFICIAL_FIXTURE["campaign_get_response"]["id"]
    _provider(handler).list_leads(provider_campaign_id=campaign_id)

    assert observed[0].method == "POST"
    assert observed[0].url == httpx.URL(f"{INSTANTLY_V2_BASE_URL}/leads/list")
    assert json.loads(observed[0].content) == {"campaign_id": campaign_id}


def test_official_patch_lead_has_no_contractual_pause_mutation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    with pytest.raises(InstantlyProviderError) as caught:
        _provider(handler).pause_lead("019c0000-0000-7000-8000-000000000004")

    assert caught.value.code is InstantlyErrorCode.CLIENT_CONTRACT_ERROR
    assert caught.value.reconciliation_required is False
    assert requests == []


def test_oversized_provider_response_is_rejected_before_json_decode() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1_048_577)

    with pytest.raises(InstantlyProviderError) as caught:
        _provider(handler).list_webhooks()

    assert caught.value.code is InstantlyErrorCode.MALFORMED_RESPONSE


def test_oversized_provider_stream_stops_at_the_configured_read_bound() -> None:
    class OversizedStream(httpx.SyncByteStream):
        def __init__(self) -> None:
            self.chunks_read = 0

        def __iter__(self):
            for _ in range(10):
                self.chunks_read += 1
                yield b"x" * 262_144

    stream = OversizedStream()
    provider = _provider(
        lambda _request: httpx.Response(200, stream=stream)
    )

    with pytest.raises(InstantlyProviderError) as caught:
        provider.list_webhooks()

    assert caught.value.code is InstantlyErrorCode.MALFORMED_RESPONSE
    assert stream.chunks_read == 5


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
