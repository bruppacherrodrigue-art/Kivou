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
    if environment != "STAGING":
        raise ConnectivityFailure(ConnectivityErrorCode.WRONG_ENVIRONMENT)
    shadow_path = _absolute_path(source, "KIVOU_ACQUISITION_SHADOW_CONFIG")
    return AcquisitionConnectivityConfig(
        environment="STAGING",
        shadow_config_path=shadow_path,
        apollo_api_key=SecretStr(_required(source, "KIVOU_APOLLO_API_KEY")),
        instantly_api_key=SecretStr(_required(source, "KIVOU_INSTANTLY_API_KEY")),
        hermes_python=_absolute_path(source, "KIVOU_HERMES_PYTHON"),
        hermes_home=_absolute_path(source, "KIVOU_HERMES_HOME"),
        hermes_cwd=_absolute_path(source, "KIVOU_HERMES_CWD"),
        deployment=_load_document(shadow_path),
    )
