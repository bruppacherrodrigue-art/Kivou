"""Fail-closed composition for the authenticated Instantly webhook boundary."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy.engine import Engine

from signals.campaigns.contracts import ResponseIngressCapability
from signals.campaigns.webhooks import (
    InstantlyWebhookService,
    WebhookFingerprintKeyring,
)
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.responses.contracts import (
    UNCONFIGURED_CLASSIFIER_VERSION,
    ContentFingerprintKeyring,
)
from signals.responses.service import ResponseWebhookIngress

WEBHOOK_SECRET_ENV = "KIVOU_INSTANTLY_WEBHOOK_SECRET"
WEBHOOK_WORKSPACE_ENV = "KIVOU_INSTANTLY_WORKSPACE_REF"
WEBHOOK_FINGERPRINT_VERSION_ENV = "KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY_VERSION"
WEBHOOK_FINGERPRINT_KEY_ENV = "KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY"
WEBHOOK_FINGERPRINT_RETAINED_ENV = (
    "KIVOU_INSTANTLY_WEBHOOK_RETAINED_FINGERPRINT_KEYS_JSON"
)
SUPPRESSION_VERSION_ENV = "KIVOU_SUPPRESSION_HMAC_KEY_VERSION"
SUPPRESSION_KEY_ENV = "KIVOU_SUPPRESSION_HMAC_KEY"
SUPPRESSION_RETAINED_ENV = "KIVOU_SUPPRESSION_RETAINED_KEYS_JSON"
RESPONSE_SOURCE_VERSION_ENV = "KIVOU_RESPONSE_SOURCE_HMAC_KEY_VERSION"
RESPONSE_SOURCE_KEY_ENV = "KIVOU_RESPONSE_SOURCE_HMAC_KEY"
RESPONSE_SOURCE_RETAINED_ENV = "KIVOU_RESPONSE_SOURCE_RETAINED_KEYS_JSON"
RESPONSE_CONTENT_VERSION_ENV = "KIVOU_RESPONSE_CONTENT_HMAC_KEY_VERSION"
RESPONSE_CONTENT_KEY_ENV = "KIVOU_RESPONSE_CONTENT_HMAC_KEY"
RESPONSE_CONTENT_RETAINED_ENV = "KIVOU_RESPONSE_CONTENT_RETAINED_KEYS_JSON"

_ENVIRONMENT_NAMES = (
    WEBHOOK_SECRET_ENV,
    WEBHOOK_WORKSPACE_ENV,
    WEBHOOK_FINGERPRINT_VERSION_ENV,
    WEBHOOK_FINGERPRINT_KEY_ENV,
    WEBHOOK_FINGERPRINT_RETAINED_ENV,
    SUPPRESSION_VERSION_ENV,
    SUPPRESSION_KEY_ENV,
    SUPPRESSION_RETAINED_ENV,
    RESPONSE_SOURCE_VERSION_ENV,
    RESPONSE_SOURCE_KEY_ENV,
    RESPONSE_SOURCE_RETAINED_ENV,
    RESPONSE_CONTENT_VERSION_ENV,
    RESPONSE_CONTENT_KEY_ENV,
    RESPONSE_CONTENT_RETAINED_ENV,
)


class WebhookRuntimeConfigurationError(ValueError):
    """Machine-safe configuration failure which never includes secret values."""

    def __init__(
        self,
        code: str = "WEBHOOK_NOT_CONFIGURED",
        *,
        message: str | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class InstantlyWebhookRuntimeConfiguration:
    provider_webhook_secret: str = field(repr=False)
    provider_workspace_ref: str
    fingerprint_keyring: WebhookFingerprintKeyring = field(repr=False)
    suppression_keyring: SuppressionIdentityKeyring = field(repr=False)
    response_source_keyring: ContentFingerprintKeyring = field(repr=False)
    response_content_keyring: ContentFingerprintKeyring = field(repr=False)
    response_ingress_capability: ResponseIngressCapability = (
        ResponseIngressCapability.SPEC027_V1
    )

    @property
    def response_ingress_ready(self) -> bool:
        return self.response_ingress_capability is ResponseIngressCapability.SPEC027_V1


def _required(source: Mapping[str, str], name: str, *, maximum: int) -> str:
    value = source.get(name)
    if value is None or not value:
        raise WebhookRuntimeConfigurationError(
            message=(
                "configuration webhook Instantly incomplète : "
                f"{name} doit être définie avec le groupe complet"
            )
        )
    if value != value.strip():
        raise WebhookRuntimeConfigurationError(
            message=f"{name} ne doit pas contenir d'espaces périphériques"
        )
    if len(value) > maximum:
        raise WebhookRuntimeConfigurationError(
            message=f"{name} dépasse la longueur maximale autorisée"
        )
    return value


def _secret(source: Mapping[str, str], name: str) -> bytes:
    value = _required(source, name, maximum=4_096).encode("utf-8")
    if len(value) < 16:
        raise WebhookRuntimeConfigurationError(
            message=f"{name} doit contenir au moins 16 octets"
        )
    return value


def _retained_keys(
    source: Mapping[str, str],
    name: str,
    *,
    version_maximum: int,
) -> dict[str, bytes]:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise TypeError
        retained: dict[str, bytes] = {}
        for version, secret in parsed.items():
            if (
                not isinstance(version, str)
                or not version
                or version != version.strip()
                or len(version) > version_maximum
                or not isinstance(secret, str)
                or secret != secret.strip()
            ):
                raise TypeError
            encoded = secret.encode("utf-8")
            if len(encoded) < 16 or len(encoded) > 4_096:
                raise ValueError
            retained[version] = encoded
        return dict(sorted(retained.items()))
    except (json.JSONDecodeError, TypeError, ValueError):
        raise WebhookRuntimeConfigurationError() from None


def _keyring_values(
    source: Mapping[str, str],
    *,
    version_name: str,
    key_name: str,
    version_maximum: int,
    retained_name: str | None = None,
) -> tuple[str, dict[str, bytes]]:
    version = _required(source, version_name, maximum=version_maximum)
    retained = (
        _retained_keys(source, retained_name, version_maximum=version_maximum)
        if retained_name
        else {}
    )
    if version in retained:
        raise WebhookRuntimeConfigurationError()
    retained[version] = _secret(source, key_name)
    if len(retained) > 8:
        raise WebhookRuntimeConfigurationError()
    return version, retained


def load_instantly_webhook_runtime_config(
    environ: Mapping[str, str] | None = None,
    *,
    required: bool,
) -> InstantlyWebhookRuntimeConfiguration | None:
    """Load one shared crypto configuration for ASGI and acquisition readiness.

    A completely absent optional configuration leaves the public route closed.
    Any partial configuration is an operator error and fails application startup.
    """

    source = os.environ if environ is None else environ
    configured = any(bool(source.get(name, "").strip()) for name in _ENVIRONMENT_NAMES)
    if not configured:
        if required:
            raise WebhookRuntimeConfigurationError()
        return None
    try:
        secret = _required(source, WEBHOOK_SECRET_ENV, maximum=4_096)
        if len(secret.encode("utf-8")) < 16:
            raise WebhookRuntimeConfigurationError(
                message=f"{WEBHOOK_SECRET_ENV} doit contenir au moins 16 octets"
            )
        workspace = _required(source, WEBHOOK_WORKSPACE_ENV, maximum=128)
        fingerprint_version, fingerprint_keys = _keyring_values(
            source,
            version_name=WEBHOOK_FINGERPRINT_VERSION_ENV,
            key_name=WEBHOOK_FINGERPRINT_KEY_ENV,
            version_maximum=64,
            retained_name=WEBHOOK_FINGERPRINT_RETAINED_ENV,
        )
        suppression_version, suppression_keys = _keyring_values(
            source,
            version_name=SUPPRESSION_VERSION_ENV,
            key_name=SUPPRESSION_KEY_ENV,
            version_maximum=64,
            retained_name=SUPPRESSION_RETAINED_ENV,
        )
        source_version, source_keys = _keyring_values(
            source,
            version_name=RESPONSE_SOURCE_VERSION_ENV,
            key_name=RESPONSE_SOURCE_KEY_ENV,
            version_maximum=100,
            retained_name=RESPONSE_SOURCE_RETAINED_ENV,
        )
        content_version, content_keys = _keyring_values(
            source,
            version_name=RESPONSE_CONTENT_VERSION_ENV,
            key_name=RESPONSE_CONTENT_KEY_ENV,
            version_maximum=100,
            retained_name=RESPONSE_CONTENT_RETAINED_ENV,
        )
        return InstantlyWebhookRuntimeConfiguration(
            provider_webhook_secret=secret,
            provider_workspace_ref=workspace,
            fingerprint_keyring=WebhookFingerprintKeyring(
                current_key_version=fingerprint_version,
                keys=fingerprint_keys,
            ),
            suppression_keyring=SuppressionIdentityKeyring(
                current_key_version=suppression_version,
                keys=suppression_keys,
            ),
            response_source_keyring=ContentFingerprintKeyring(
                current_key_version=source_version,
                keys=source_keys,
            ),
            response_content_keyring=ContentFingerprintKeyring(
                current_key_version=content_version,
                keys=content_keys,
            ),
        )
    except WebhookRuntimeConfigurationError:
        raise
    except (TypeError, ValueError):
        raise WebhookRuntimeConfigurationError() from None


def build_instantly_webhook_service(
    engine: Engine,
    configuration: InstantlyWebhookRuntimeConfiguration,
) -> InstantlyWebhookService:
    """Compose authenticated ingress and deterministic SPEC-027 safety handling.

    STOP, complaint and automatic-response safety paths can finalize locally.
    An ordinary reply is only reserved as ``PLANNED`` and still requires the
    separately controlled ResponseWorker; ingress readiness must not be read as
    classifier readiness.
    """

    response_ingress = ResponseWebhookIngress(
        engine,
        suppression_keyring=configuration.suppression_keyring,
        source_keyring=configuration.response_source_keyring,
        content_keyring=configuration.response_content_keyring,
        classifier_version=UNCONFIGURED_CLASSIFIER_VERSION,
        estimated_classifier_cost="0",
    )
    return InstantlyWebhookService(
        engine,
        provider_workspace_ref=configuration.provider_workspace_ref,
        fingerprint_keyring=configuration.fingerprint_keyring,
        suppression_keyring=configuration.suppression_keyring,
        response_ingress_capability=configuration.response_ingress_capability,
        response_ingress=response_ingress,
    )


__all__ = [
    "InstantlyWebhookRuntimeConfiguration",
    "WebhookRuntimeConfigurationError",
    "build_instantly_webhook_service",
    "load_instantly_webhook_runtime_config",
]
