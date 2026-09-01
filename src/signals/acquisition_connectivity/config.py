"""Strict environment and deployment-document loading without I/O side effects."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import SecretStr, ValidationError

from signals.acquisition_connectivity.contracts import (
    AcquisitionConnectivityConfig,
    ConnectivityErrorCode,
    ConnectivityFailure,
    ShadowConnectivityDocument,
)

REQUIRED_ENVIRONMENT_VARIABLES = (
    "KIVOU_ACQUISITION_ENVIRONMENT",
    "KIVOU_ACQUISITION_SHADOW_CONFIG",
    "KIVOU_APOLLO_API_KEY",
    "KIVOU_INSTANTLY_API_KEY",
    "KIVOU_HERMES_PYTHON",
    "KIVOU_HERMES_HOME",
    "KIVOU_HERMES_CWD",
)
MAX_DEPLOYMENT_DOCUMENT_BYTES = 65_536
MAX_HERMES_MODEL_CONFIG_BYTES = 16_384
HERMES_SHADOW_MODEL_CONFIG = {
    "model": {
        "provider": "openrouter",
        "default": "anthropic/claude-sonnet-4.6",
    },
    "provider_routing": {
        "require_parameters": True,
        "data_collection": "deny",
    },
}


def _required(source: Mapping[str, str], name: str) -> str:
    value = source.get(name)
    if value is None or not value.strip():
        raise ConnectivityFailure(ConnectivityErrorCode.NOT_CONFIGURED)
    return value


def _absolute_path(source: Mapping[str, str], name: str) -> Path:
    path = Path(_required(source, name).strip())
    if not path.is_absolute():
        raise ConnectivityFailure(ConnectivityErrorCode.NOT_CONFIGURED)
    return path


def _load_document(path: Path) -> ShadowConnectivityDocument:
    try:
        body = path.read_bytes()
        if len(body) > MAX_DEPLOYMENT_DOCUMENT_BYTES:
            raise ValueError("deployment document exceeds bound")
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise TypeError("deployment document must be an object")
        return ShadowConnectivityDocument.model_validate(parsed)
    except (
        OSError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
    ):
        raise ConnectivityFailure(ConnectivityErrorCode.NOT_CONFIGURED) from None


def load_connectivity_config(
    environ: Mapping[str, str] | None = None,
) -> AcquisitionConnectivityConfig:
    source = os.environ if environ is None else environ
    environment = _required(source, "KIVOU_ACQUISITION_ENVIRONMENT")
    if environment not in {"STAGING", "PRODUCTION"}:
        raise ConnectivityFailure(ConnectivityErrorCode.WRONG_ENVIRONMENT)
    shadow_path = _absolute_path(source, "KIVOU_ACQUISITION_SHADOW_CONFIG")
    return AcquisitionConnectivityConfig(
        environment=environment,
        shadow_config_path=shadow_path,
        apollo_api_key=SecretStr(_required(source, "KIVOU_APOLLO_API_KEY")),
        instantly_api_key=SecretStr(_required(source, "KIVOU_INSTANTLY_API_KEY")),
        hermes_python=_absolute_path(source, "KIVOU_HERMES_PYTHON"),
        hermes_home=_absolute_path(source, "KIVOU_HERMES_HOME"),
        hermes_cwd=_absolute_path(source, "KIVOU_HERMES_CWD"),
        deployment=_load_document(shadow_path),
    )


def validate_hermes_shadow_config(config: AcquisitionConnectivityConfig) -> None:
    """Require one exact JSON-compatible YAML model config without fallbacks/tools."""
    try:
        body = (config.hermes_home / "config.yaml").read_bytes()
        if len(body) > MAX_HERMES_MODEL_CONFIG_BYTES:
            raise ValueError("Hermes model config exceeds bound")
        parsed = json.loads(body.decode("utf-8"))
        if parsed != HERMES_SHADOW_MODEL_CONFIG:
            raise ValueError("Hermes model config differs from the frozen shadow contract")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise ConnectivityFailure(ConnectivityErrorCode.NOT_CONFIGURED) from None
