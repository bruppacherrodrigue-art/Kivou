"""Strict acquisition runtime configuration loader for staging and production."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeConfig,
    AcquisitionRuntimeDeployment,
)

MAX_RUNTIME_DOCUMENT_BYTES = 65_536


class RuntimeConfigurationError(RuntimeError):
    """A bounded configuration result which never contains configuration values."""

    def __init__(self, code: str) -> None:
        super().__init__(f"acquisition runtime configuration error: {code}")
        self.code = code


def _required(source: Mapping[str, str], name: str) -> str:
    value = source.get(name)
    if value is None or not value.strip():
        raise RuntimeConfigurationError("NOT_CONFIGURED")
    return value.strip()


def _deployment(path: Path) -> AcquisitionRuntimeDeployment:
    try:
        if not path.is_absolute():
            raise ValueError("runtime document path is not absolute")
        body = path.read_bytes()
        if len(body) > MAX_RUNTIME_DOCUMENT_BYTES:
            raise ValueError("runtime document exceeds bound")
        raw = json.loads(body.decode("utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("runtime document is not an object")
        return AcquisitionRuntimeDeployment.model_validate(raw)
    except (
        OSError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
        ValidationError,
    ):
        raise RuntimeConfigurationError("NOT_CONFIGURED") from None


def _identity_hmac(address: str, key: str) -> str:
    return hmac.new(
        key.encode("utf-8"),
        address.strip().casefold().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _load_production(
    source: Mapping[str, str], path: Path, deployment: AcquisitionRuntimeDeployment
) -> AcquisitionRuntimeConfig:
    for name in (
        "KIVOU_ACQUISITION_QA_RECIPIENT",
        "KIVOU_ACQUISITION_QA_RECIPIENT_KEY",
    ):
        # PRESENCE, not truthiness: a var declared empty by a failed template
        # substitution must refuse to start, not read as absent.
        if name in source:
            raise RuntimeConfigurationError("PRODUCTION_FORBIDS_FALLBACK_RECIPIENT")
    if not deployment.is_production:
        raise RuntimeConfigurationError("WRONG_DEPLOYMENT_SCHEMA")
    try:
        return AcquisitionRuntimeConfig(
            environment="PRODUCTION",
            deployment_path=path,
            deployment=deployment,
        )
    except (TypeError, ValueError, ValidationError):
        raise RuntimeConfigurationError("NOT_CONFIGURED") from None


def _load_staging(
    source: Mapping[str, str], path: Path, deployment: AcquisitionRuntimeDeployment
) -> AcquisitionRuntimeConfig:
    if deployment.is_production:
        raise RuntimeConfigurationError("WRONG_DEPLOYMENT_SCHEMA")
    recipient = _required(source, "KIVOU_ACQUISITION_QA_RECIPIENT")
    key = _required(source, "KIVOU_ACQUISITION_QA_RECIPIENT_KEY")
    try:
        config = AcquisitionRuntimeConfig(
            environment="STAGING",
            deployment_path=path,
            deployment=deployment,
            qa_recipient=recipient,
            qa_recipient_hmac_key=key,
        )
        normalized = config.normalized_qa_recipient()
    except (TypeError, ValueError, ValidationError):
        raise RuntimeConfigurationError("NOT_CONFIGURED") from None
    observed = _identity_hmac(normalized, key)
    assert deployment.qa_recipient_identity_hmac is not None
    if not hmac.compare_digest(observed, deployment.qa_recipient_identity_hmac):
        raise RuntimeConfigurationError("QA_RECIPIENT_BINDING_MISMATCH")
    return config


def load_runtime_config(
    environ: Mapping[str, str] | None = None,
) -> AcquisitionRuntimeConfig:
    source = os.environ if environ is None else environ
    environment = _required(source, "KIVOU_ACQUISITION_ENVIRONMENT")
    if environment not in {"STAGING", "PRODUCTION"}:
        raise RuntimeConfigurationError("WRONG_ENVIRONMENT")
    path = Path(_required(source, "KIVOU_ACQUISITION_RUNTIME_CONFIG"))
    deployment = _deployment(path)
    if environment == "PRODUCTION":
        return _load_production(source, path, deployment)
    return _load_staging(source, path, deployment)


__all__ = ["RuntimeConfigurationError", "load_runtime_config"]
