from __future__ import annotations

import pytest
from pydantic import ValidationError

from signals.acquisition_runtime.contracts import (
    ACQUISITION_PRODUCTION_SCHEMA_VERSION,
    ACQUISITION_RUNTIME_SCHEMA_VERSION,
    AcquisitionRuntimeDeployment,
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
