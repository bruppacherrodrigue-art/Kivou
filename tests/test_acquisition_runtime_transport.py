from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from signals.acquisition_runtime.config import load_runtime_config
from signals.acquisition_runtime.transport import StagingQaRecipientOverride
from signals.compliance.suppression import SuppressionIdentityKeyring

QA_RECIPIENT = "qa-controlled@example.com"
QA_KEY = "synthetic-test-hmac-key"


def _transport_keyring() -> SuppressionIdentityKeyring:
    return SuppressionIdentityKeyring(
        current_key_version="suppression-key-v1",
        keys={"suppression-key-v1": b"synthetic-suppression-key"},
    )


def _config(tmp_path):
    binding = hmac.new(
        QA_KEY.encode(), QA_RECIPIENT.encode(), hashlib.sha256
    ).hexdigest()
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "acquisition-runtime-v1",
                "mode": "SHADOW",
                "qa_only": True,
                "allowed_opportunity_keys": ["signal-qa-001"],
                "qa_recipient_identity_hmac": binding,
                "qa_recipient_key_version": "qa-recipient-key-v1",
                "qa_provider_mutations_capable": True,
                "limits": {
                    "maximum_cycle_cost": "5",
                    "maximum_suppliers": 1,
                    "maximum_contacts": 1,
                    "maximum_provider_operations": 4,
                    "maximum_wall_seconds": 900,
                    "lease_seconds": 1200,
                },
            }
        )
    )
    return load_runtime_config(
        {
            "KIVOU_ACQUISITION_ENVIRONMENT": "STAGING",
            "KIVOU_ACQUISITION_RUNTIME_CONFIG": str(path),
            "KIVOU_ACQUISITION_QA_RECIPIENT": QA_RECIPIENT,
            "KIVOU_ACQUISITION_QA_RECIPIENT_KEY": QA_KEY,
        }
    )


def test_verified_staging_override_replaces_only_transport_recipient(tmp_path) -> None:
    config = _config(tmp_path)
    override = StagingQaRecipientOverride(
        config, transport_keyring=_transport_keyring()
    )

    assert override.resolve("discovered-prospect@example.net") == QA_RECIPIENT
    assert override.binding_fingerprint == config.deployment.qa_recipient_identity_hmac
    assert override.key_version == "qa-recipient-key-v1"
    assert override.transport_key_version == "suppression-key-v1"
    assert override.transport_recipient_identity == _transport_keyring().identities_for_email(
        QA_RECIPIENT
    )["suppression-key-v1"]


def test_override_repr_never_contains_recipient_or_hmac_key(tmp_path) -> None:
    override = StagingQaRecipientOverride(
        _config(tmp_path), transport_keyring=_transport_keyring()
    )

    rendered = repr(override)

    assert QA_RECIPIENT not in rendered
    assert QA_KEY not in rendered
    assert "configured" in rendered


def test_override_rechecks_staging_qa_contract_even_after_unsafe_model_copy(
    tmp_path,
) -> None:
    config = _config(tmp_path)
    unsafe = config.model_copy(update={"environment": "PRODUCTION"})

    with pytest.raises(ValueError, match="staging QA runtime"):
        StagingQaRecipientOverride(
            unsafe, transport_keyring=_transport_keyring()
        )
