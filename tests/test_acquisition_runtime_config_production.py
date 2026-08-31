from __future__ import annotations

import json

import pytest

from signals.acquisition_runtime.config import (
    RuntimeConfigurationError,
    load_runtime_config,
)
from signals.acquisition_runtime.contracts import (
    ACQUISITION_PRODUCTION_SCHEMA_VERSION,
    ACQUISITION_RUNTIME_SCHEMA_VERSION,
)

DOCUMENT = {
    "schema_version": ACQUISITION_PRODUCTION_SCHEMA_VERSION,
    "mode": "SHADOW",
    "qa_scope": {"country": "FR", "language": "fr", "wedge": "construction"},
    "limits": {
        "maximum_cycle_cost": "10.00",
        "maximum_suppliers": 1,
        "maximum_contacts": 1,
        "maximum_provider_operations": 4,
        "maximum_wall_seconds": 900,
        "lease_seconds": 1200,
    },
}


def _write(tmp_path, document: dict[str, object]):
    path = tmp_path / "acquisition-production.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _environment(path, **updates: str) -> dict[str, str]:
    value = {
        "KIVOU_ACQUISITION_ENVIRONMENT": "PRODUCTION",
        "KIVOU_ACQUISITION_RUNTIME_CONFIG": str(path),
    }
    value.update(updates)
    return value


def test_production_configuration_loads_without_any_recipient(tmp_path) -> None:
    path = _write(tmp_path, DOCUMENT)
    config = load_runtime_config(_environment(path))
    assert config.environment == "PRODUCTION"
    assert config.qa_recipient is None
    assert config.qa_recipient_hmac_key is None
    assert config.deployment.is_production is True


@pytest.mark.parametrize(
    "name",
    ["KIVOU_ACQUISITION_QA_RECIPIENT", "KIVOU_ACQUISITION_QA_RECIPIENT_KEY"],
)
def test_production_refuses_to_start_when_a_fallback_recipient_is_present(
    tmp_path, name: str
) -> None:
    path = _write(tmp_path, DOCUMENT)
    with pytest.raises(RuntimeConfigurationError) as error:
        load_runtime_config(_environment(path, **{name: "someone@example.com"}))
    assert error.value.code == "PRODUCTION_FORBIDS_FALLBACK_RECIPIENT"


def test_production_rejects_a_staging_shaped_document(tmp_path) -> None:
    # A staging-shaped deployment must carry its full QA binding to validate at
    # all (contracts.bindings_match_schema); a bare schema_version swap on the
    # production DOCUMENT is not a valid staging document, so this fixture adds
    # the complete staging binding to reach the loader's own schema check.
    path = _write(
        tmp_path,
        {
            **DOCUMENT,
            "schema_version": ACQUISITION_RUNTIME_SCHEMA_VERSION,
            "qa_only": True,
            "allowed_opportunity_keys": ["opportunity-qa-001"],
            "qa_recipient_identity_hmac": "a" * 64,
            "qa_recipient_key_version": "qa-recipient-key-v1",
            "qa_provider_mutations_capable": True,
        },
    )
    with pytest.raises(RuntimeConfigurationError) as error:
        load_runtime_config(_environment(path))
    assert error.value.code == "WRONG_DEPLOYMENT_SCHEMA"


def test_staging_rejects_a_production_shaped_document(tmp_path) -> None:
    path = _write(tmp_path, DOCUMENT)
    with pytest.raises(RuntimeConfigurationError) as error:
        load_runtime_config(
            {
                "KIVOU_ACQUISITION_ENVIRONMENT": "STAGING",
                "KIVOU_ACQUISITION_RUNTIME_CONFIG": str(path),
                "KIVOU_ACQUISITION_QA_RECIPIENT": "qa@example.com",
                "KIVOU_ACQUISITION_QA_RECIPIENT_KEY": "key",
            }
        )
    assert error.value.code == "WRONG_DEPLOYMENT_SCHEMA"


def test_an_unknown_environment_is_still_refused(tmp_path) -> None:
    path = _write(tmp_path, DOCUMENT)
    with pytest.raises(RuntimeConfigurationError) as error:
        load_runtime_config(_environment(path, KIVOU_ACQUISITION_ENVIRONMENT="UNCONFIGURED"))
    assert error.value.code == "WRONG_ENVIRONMENT"
