from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError, SecretStr

from signals.acquisition_runtime.contracts import (
    ACQUISITION_PRODUCTION_SCHEMA_VERSION,
    ACQUISITION_RUNTIME_SCHEMA_VERSION,
    AcquisitionRuntimeDeployment,
    AcquisitionRuntimeConfig,
)

LIMITS = {
    "maximum_cycle_cost": "10.00",
    "maximum_suppliers": 1,
    "maximum_contacts": 1,
    "maximum_provider_operations": 4,
    "maximum_wall_seconds": 900,
    "lease_seconds": 1200,
}
SCOPE = {"country": "FR", "language": "fr", "wedge": "construction"}


def _production_document(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": ACQUISITION_PRODUCTION_SCHEMA_VERSION,
        "mode": "SHADOW",
        "qa_scope": SCOPE,
        "limits": LIMITS,
    }
    value.update(updates)
    return value


def test_production_deployment_omits_every_qa_binding() -> None:
    deployment = AcquisitionRuntimeDeployment.model_validate(_production_document())
    assert deployment.schema_version == ACQUISITION_PRODUCTION_SCHEMA_VERSION
    assert deployment.qa_only is False
    assert deployment.qa_recipient_identity_hmac is None
    assert deployment.qa_recipient_key_version is None
    assert deployment.qa_provider_mutations_capable is False
    assert deployment.allowed_opportunity_keys == ()


@pytest.mark.parametrize(
    "field, value",
    [
        ("qa_recipient_identity_hmac", "0" * 64),
        ("qa_recipient_key_version", "qa-recipient-key-v1"),
        ("qa_only", True),
        ("qa_provider_mutations_capable", True),
        ("allowed_opportunity_keys", ["opportunity-001"]),
    ],
)
def test_production_deployment_rejects_any_qa_binding(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        AcquisitionRuntimeDeployment.model_validate(
            _production_document(**{field: value})
        )


def test_staging_deployment_still_requires_its_qa_binding() -> None:
    with pytest.raises(ValidationError):
        AcquisitionRuntimeDeployment.model_validate(
            {
                "schema_version": ACQUISITION_RUNTIME_SCHEMA_VERSION,
                "mode": "SHADOW",
                "qa_scope": SCOPE,
                "limits": LIMITS,
            }
        )


def _staging_deployment(**updates: object) -> dict[str, object]:
    """Helper to create a valid staging deployment."""
    value: dict[str, object] = {
        "schema_version": ACQUISITION_RUNTIME_SCHEMA_VERSION,
        "mode": "SHADOW",
        "qa_only": True,
        "qa_scope": SCOPE,
        "qa_recipient_identity_hmac": "0" * 64,
        "qa_recipient_key_version": "qa-recipient-key-v1",
        "qa_provider_mutations_capable": True,
        "allowed_opportunity_keys": ["opportunity-001"],
        "limits": LIMITS,
    }
    value.update(updates)
    return value


def test_production_config_rejects_qa_recipient() -> None:
    """Production config must not have qa_recipient."""
    deployment = AcquisitionRuntimeDeployment.model_validate(_production_document())
    with pytest.raises(ValidationError) as exc_info:
        AcquisitionRuntimeConfig(
            environment="PRODUCTION",
            deployment_path=Path("/tmp/deployment.json"),
            deployment=deployment,
            qa_recipient=SecretStr("user@example.com"),
            qa_recipient_hmac_key=None,
        )
    assert "production runtime forbids a fallback recipient" in str(exc_info.value)


def test_production_config_rejects_qa_recipient_hmac_key() -> None:
    """Production config must not have qa_recipient_hmac_key."""
    deployment = AcquisitionRuntimeDeployment.model_validate(_production_document())
    with pytest.raises(ValidationError) as exc_info:
        AcquisitionRuntimeConfig(
            environment="PRODUCTION",
            deployment_path=Path("/tmp/deployment.json"),
            deployment=deployment,
            qa_recipient=None,
            qa_recipient_hmac_key=SecretStr("hmac-key-value"),
        )
    assert "production runtime forbids a fallback recipient" in str(exc_info.value)


def test_staging_config_rejects_missing_qa_recipient() -> None:
    """Staging config must have both qa_recipient and qa_recipient_hmac_key."""
    deployment = AcquisitionRuntimeDeployment.model_validate(_staging_deployment())
    with pytest.raises(ValidationError) as exc_info:
        AcquisitionRuntimeConfig(
            environment="STAGING",
            deployment_path=Path("/tmp/deployment.json"),
            deployment=deployment,
            qa_recipient=None,
            qa_recipient_hmac_key=SecretStr("hmac-key-value"),
        )
    assert "staging runtime requires its QA recipient binding" in str(exc_info.value)


def test_staging_config_rejects_missing_qa_recipient_hmac_key() -> None:
    """Staging config must have both qa_recipient and qa_recipient_hmac_key."""
    deployment = AcquisitionRuntimeDeployment.model_validate(_staging_deployment())
    with pytest.raises(ValidationError) as exc_info:
        AcquisitionRuntimeConfig(
            environment="STAGING",
            deployment_path=Path("/tmp/deployment.json"),
            deployment=deployment,
            qa_recipient=SecretStr("user@example.com"),
            qa_recipient_hmac_key=None,
        )
    assert "staging runtime requires its QA recipient binding" in str(exc_info.value)


def test_normalized_qa_recipient_raises_on_production_config() -> None:
    """Calling normalized_qa_recipient() on production config must raise."""
    deployment = AcquisitionRuntimeDeployment.model_validate(_production_document())
    config = AcquisitionRuntimeConfig(
        environment="PRODUCTION",
        deployment_path=Path("/tmp/deployment.json"),
        deployment=deployment,
        qa_recipient=None,
        qa_recipient_hmac_key=None,
    )
    with pytest.raises(ValueError) as exc_info:
        config.normalized_qa_recipient()
    assert "runtime has no QA recipient" in str(exc_info.value)


def test_production_config_requires_production_deployment() -> None:
    """Production environment requires production deployment schema."""
    staging_deployment = AcquisitionRuntimeDeployment.model_validate(
        _staging_deployment()
    )
    with pytest.raises(ValidationError) as exc_info:
        AcquisitionRuntimeConfig(
            environment="PRODUCTION",
            deployment_path=Path("/tmp/deployment.json"),
            deployment=staging_deployment,
            qa_recipient=None,
            qa_recipient_hmac_key=None,
        )
    assert "production environment requires production deployment schema" in str(
        exc_info.value
    )


def test_staging_config_forbids_production_deployment() -> None:
    """Staging environment forbids production deployment schema."""
    production_deployment = AcquisitionRuntimeDeployment.model_validate(
        _production_document()
    )
    with pytest.raises(ValidationError) as exc_info:
        AcquisitionRuntimeConfig(
            environment="STAGING",
            deployment_path=Path("/tmp/deployment.json"),
            deployment=production_deployment,
            qa_recipient=SecretStr("user@example.com"),
            qa_recipient_hmac_key=SecretStr("hmac-key"),
        )
    assert "staging environment forbids production deployment schema" in str(
        exc_info.value
    )
