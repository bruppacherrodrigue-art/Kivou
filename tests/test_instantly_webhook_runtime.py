from __future__ import annotations

import pytest

from signals.api.config import ApiConfig
from signals.campaigns.runtime_webhook import (
    WebhookRuntimeConfigurationError,
    load_instantly_webhook_runtime_config,
)


def _environment() -> dict[str, str]:
    return {
        "KIVOU_INSTANTLY_WEBHOOK_SECRET": "synthetic-route-secret",
        "KIVOU_INSTANTLY_WORKSPACE_REF": "workspace:test",
        "KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY_VERSION": "event-v2",
        "KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY": "synthetic-event-fingerprint-secret",
        "KIVOU_SUPPRESSION_HMAC_KEY_VERSION": "suppression-v2",
        "KIVOU_SUPPRESSION_HMAC_KEY": "synthetic-suppression-current-secret",
        "KIVOU_SUPPRESSION_RETAINED_KEYS_JSON": (
            '{"suppression-v1":"synthetic-suppression-retained-secret"}'
        ),
        "KIVOU_RESPONSE_SOURCE_HMAC_KEY_VERSION": "response-source-v1",
        "KIVOU_RESPONSE_SOURCE_HMAC_KEY": "synthetic-response-source-secret",
        "KIVOU_RESPONSE_SOURCE_RETAINED_KEYS_JSON": (
            '{"response-source-v0":"synthetic-response-source-retained"}'
        ),
        "KIVOU_RESPONSE_CONTENT_HMAC_KEY_VERSION": "response-content-v1",
        "KIVOU_RESPONSE_CONTENT_HMAC_KEY": "synthetic-response-content-secret",
        "KIVOU_RESPONSE_CONTENT_RETAINED_KEYS_JSON": (
            '{"response-content-v0":"synthetic-response-content-retained"}'
        ),
    }


def test_webhook_runtime_is_optional_only_when_completely_absent() -> None:
    assert load_instantly_webhook_runtime_config({}, required=False) is None
    with pytest.raises(WebhookRuntimeConfigurationError) as error:
        load_instantly_webhook_runtime_config(
            {"KIVOU_INSTANTLY_WEBHOOK_SECRET": "partial-secret"},
            required=False,
        )
    assert error.value.code == "WEBHOOK_NOT_CONFIGURED"
    assert "partial-secret" not in str(error.value)


def test_required_webhook_runtime_fails_closed_when_absent() -> None:
    with pytest.raises(WebhookRuntimeConfigurationError) as error:
        load_instantly_webhook_runtime_config({}, required=True)
    assert error.value.code == "WEBHOOK_NOT_CONFIGURED"


def test_webhook_runtime_loads_shared_suppression_rotation_without_secret_repr() -> None:
    loaded = load_instantly_webhook_runtime_config(_environment(), required=True)
    assert loaded is not None
    assert loaded.provider_workspace_ref == "workspace:test"
    assert loaded.response_ingress_ready is True
    assert loaded.suppression_keyring.current_key_version == "suppression-v2"
    assert tuple(loaded.suppression_keyring.keys) == (
        "suppression-v1",
        "suppression-v2",
    )
    assert tuple(loaded.response_source_keyring.keys) == (
        "response-source-v0",
        "response-source-v1",
    )
    assert tuple(loaded.response_content_keyring.keys) == (
        "response-content-v0",
        "response-content-v1",
    )
    rendered = repr(loaded)
    assert "synthetic-route-secret" not in rendered
    assert "synthetic-suppression-current-secret" not in rendered
    assert "synthetic-event-fingerprint-secret" not in repr(
        loaded.fingerprint_keyring
    )
    assert "synthetic-response-source-secret" not in repr(
        loaded.response_source_keyring
    )
    assert "synthetic-response-content-secret" not in repr(
        loaded.response_content_keyring
    )


def test_api_config_never_renders_the_webhook_authentication_secret() -> None:
    config = ApiConfig(instantly_webhook_secret="synthetic-route-secret")
    assert "synthetic-route-secret" not in repr(config)


def test_suppression_keyring_is_bounded_to_current_plus_seven_retained() -> None:
    environment = _environment()
    environment["KIVOU_SUPPRESSION_RETAINED_KEYS_JSON"] = "{" + ",".join(
        f'"retained-{index}":"synthetic-retained-secret-{index}"'
        for index in range(8)
    ) + "}"
    with pytest.raises(WebhookRuntimeConfigurationError) as error:
        load_instantly_webhook_runtime_config(environment, required=True)
    assert error.value.code == "WEBHOOK_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "name",
    (
        "KIVOU_SUPPRESSION_HMAC_KEY",
        "KIVOU_RESPONSE_SOURCE_HMAC_KEY",
        "KIVOU_RESPONSE_CONTENT_HMAC_KEY",
    ),
)
def test_cryptographic_material_must_be_bounded_and_nonempty(name: str) -> None:
    environment = _environment()
    environment[name] = "short"
    with pytest.raises(WebhookRuntimeConfigurationError) as error:
        load_instantly_webhook_runtime_config(environment, required=True)
    assert error.value.code == "WEBHOOK_NOT_CONFIGURED"
