from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from pydantic import ValidationError

from signals.acquisition_runtime.config import (
    RuntimeConfigurationError,
    load_runtime_config,
)
from signals.acquisition_runtime.contracts import (
    ACQUISITION_RUNTIME_SCHEMA_VERSION,
    AcquisitionRuntimeConfig,
    AcquisitionRuntimeDeployment,
    AcquisitionRuntimeLimits,
    AcquisitionRuntimeStage,
    RuntimeExecutionMode,
    RuntimeStageStatus,
)

QA_RECIPIENT = "qa-controlled@example.com"
QA_KEY = "synthetic-test-hmac-key"


def _recipient_hmac(address: str = QA_RECIPIENT, key: str = QA_KEY) -> str:
    return hmac.new(
        key.encode(), address.strip().casefold().encode(), hashlib.sha256
    ).hexdigest()


def _document(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": ACQUISITION_RUNTIME_SCHEMA_VERSION,
        "mode": "SHADOW",
        "qa_only": True,
        "allowed_opportunity_keys": ["opportunity-qa-001"],
        "qa_recipient_identity_hmac": _recipient_hmac(),
        "qa_recipient_key_version": "qa-recipient-key-v1",
        "qa_provider_mutations_capable": True,
        "limits": {
            "maximum_cycle_cost": "5.00",
            "maximum_suppliers": 1,
            "maximum_contacts": 1,
            "maximum_provider_operations": 4,
            "maximum_wall_seconds": 900,
            "lease_seconds": 1200,
        },
    }
    value.update(updates)
    return value


def _environment(path) -> dict[str, str]:
    return {
        "KIVOU_ACQUISITION_ENVIRONMENT": "STAGING",
        "KIVOU_ACQUISITION_RUNTIME_CONFIG": str(path),
        "KIVOU_ACQUISITION_QA_RECIPIENT": QA_RECIPIENT,
        "KIVOU_ACQUISITION_QA_RECIPIENT_KEY": QA_KEY,
    }


def test_runtime_contract_has_one_closed_ordered_stage_catalog() -> None:
    assert tuple(AcquisitionRuntimeStage) == (
        AcquisitionRuntimeStage.SIGNAL_SEED,
        AcquisitionRuntimeStage.SUPPLIER_DISCOVERY,
        AcquisitionRuntimeStage.CONTACT_DISCOVERY,
        AcquisitionRuntimeStage.COMPANY_RESEARCH,
        AcquisitionRuntimeStage.DECISION,
        AcquisitionRuntimeStage.PERSONALIZATION,
        AcquisitionRuntimeStage.COMPLIANCE,
        AcquisitionRuntimeStage.CAMPAIGN,
        AcquisitionRuntimeStage.PROVIDER_HANDOFF,
        AcquisitionRuntimeStage.RESPONSE,
        AcquisitionRuntimeStage.ATTRIBUTION_CONVERSION,
    )
    assert set(RuntimeStageStatus) == {
        RuntimeStageStatus.PENDING,
        RuntimeStageStatus.RUNNING,
        RuntimeStageStatus.WAITING,
        RuntimeStageStatus.SUCCEEDED,
        RuntimeStageStatus.BLOCKED,
        RuntimeStageStatus.FAILED,
        RuntimeStageStatus.SUPPRESSED,
        RuntimeStageStatus.CANCELLED,
    }


def test_loads_strict_staging_shadow_config_and_redacts_recipient(tmp_path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(_document()))

    config = load_runtime_config(_environment(path))

    assert config.environment == "STAGING"
    assert config.deployment.mode is RuntimeExecutionMode.SHADOW
    assert config.deployment.allowed_opportunity_keys == ("opportunity-qa-001",)
    assert config.qa_recipient.get_secret_value() == QA_RECIPIENT
    assert config.deployment.limits.maximum_cycle_cost == 5
    rendered = repr(config)
    assert QA_RECIPIENT not in rendered
    assert QA_KEY not in rendered
    assert "qa_recipient=" not in rendered
    assert "qa_recipient_hmac_key=" not in rendered


@pytest.mark.parametrize(
    "missing",
    [
        "KIVOU_ACQUISITION_ENVIRONMENT",
        "KIVOU_ACQUISITION_RUNTIME_CONFIG",
        "KIVOU_ACQUISITION_QA_RECIPIENT",
        "KIVOU_ACQUISITION_QA_RECIPIENT_KEY",
    ],
)
def test_missing_required_runtime_configuration_fails_closed_without_values(
    tmp_path, missing
) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(_document()))
    environment = _environment(path)
    environment.pop(missing)

    with pytest.raises(RuntimeConfigurationError) as error:
        load_runtime_config(environment)

    assert error.value.code == "NOT_CONFIGURED"
    assert QA_RECIPIENT not in str(error.value)
    assert QA_KEY not in str(error.value)


@pytest.mark.parametrize("environment", ["PRODUCTION", "production", "LOCAL", ""])
def test_runtime_is_staging_only(environment, tmp_path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(_document()))
    values = _environment(path)
    values["KIVOU_ACQUISITION_ENVIRONMENT"] = environment

    with pytest.raises(RuntimeConfigurationError) as error:
        load_runtime_config(values)

    assert error.value.code in {"NOT_CONFIGURED", "WRONG_ENVIRONMENT"}


def test_document_never_contains_the_qa_address_or_hmac_key() -> None:
    raw = _document()
    encoded = json.dumps(raw)

    assert QA_RECIPIENT not in encoded
    assert QA_KEY not in encoded
    with pytest.raises(ValidationError):
        AcquisitionRuntimeDeployment.model_validate(
            {**raw, "qa_recipient": QA_RECIPIENT}
        )


def test_recipient_hmac_must_match_the_separate_secret_binding(tmp_path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(_document(qa_recipient_identity_hmac="f" * 64))
    )

    with pytest.raises(RuntimeConfigurationError) as error:
        load_runtime_config(_environment(path))

    assert error.value.code == "QA_RECIPIENT_BINDING_MISMATCH"
    assert QA_RECIPIENT not in str(error.value)


@pytest.mark.parametrize(
    "opportunity_key",
    ["name@example.test", "https://example.test/1", "contains whitespace", ""],
)
def test_opportunity_allowlist_accepts_only_opaque_keys(opportunity_key) -> None:
    with pytest.raises(ValidationError):
        AcquisitionRuntimeDeployment.model_validate(
            _document(allowed_opportunity_keys=[opportunity_key])
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("maximum_cycle_cost", "50.01"),
        ("maximum_suppliers", 2),
        ("maximum_contacts", 2),
        ("maximum_provider_operations", 5),
        ("maximum_wall_seconds", 1801),
        ("lease_seconds", 1800),
    ],
)
def test_runtime_limits_are_small_and_lease_outlives_wall_clock(field, value) -> None:
    payload = _document()["limits"]
    assert isinstance(payload, dict)
    limits = {**payload, field: value}

    with pytest.raises(ValidationError):
        AcquisitionRuntimeLimits.model_validate(limits)


def test_deployment_is_shadow_qa_only_and_provider_capability_is_explicit() -> None:
    for update in (
        {"mode": "ASSISTED"},
        {"qa_only": False},
        {"qa_provider_mutations_capable": False},
    ):
        with pytest.raises(ValidationError):
            AcquisitionRuntimeDeployment.model_validate(_document(**update))


def test_runtime_config_secret_fields_are_not_serialized() -> None:
    assert set(AcquisitionRuntimeConfig.model_fields) == {
        "environment",
        "deployment_path",
        "deployment",
        "qa_recipient",
        "qa_recipient_hmac_key",
    }
