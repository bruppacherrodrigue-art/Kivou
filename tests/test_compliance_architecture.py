from __future__ import annotations

import ast
from pathlib import Path

from signals.acquisition.contracts import STATE_MACHINE_VERSION, EventType
from signals.compliance.contracts import ComplianceAuthorizationInput
from signals.persistence.schema import (
    acquisition_compliance_assessment,
    acquisition_contact_suppression,
)

PACKAGE = Path("src/signals/compliance")


def test_compliance_package_has_no_external_or_customer_runtime_dependencies() -> None:
    forbidden = (
        "signals.instantly",
        "signals.smtp",
        "signals.apollo",
        "signals.openrouter",
        "signals.llm",
        "signals.crawler",
        "signals.billing",
        "signals.stripe",
        "signals.matching",
        "signals.target_icp",
        "signals.customer",
    )
    imports = set()
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)

    assert not any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for imported in imports
        for prefix in forbidden
    )


def test_compliance_tables_exclude_contact_pii_copy_and_provider_secrets() -> None:
    forbidden = {
        "business_email",
        "first_name",
        "last_name",
        "display_name",
        "subject",
        "greeting",
        "body",
        "cta",
        "hmac_secret",
        "key_bytes",
        "raw_apollo_payload",
        "provider",
        "model",
    }

    assert forbidden.isdisjoint(column.name for column in acquisition_contact_suppression.columns)
    assert forbidden.isdisjoint(column.name for column in acquisition_compliance_assessment.columns)


def test_spec025_keeps_the_existing_state_machine_and_event_vocabulary() -> None:
    assert STATE_MACHINE_VERSION == "acquisition-state-v1"
    assert not any("COMPLIANCE" in event_type.value for event_type in EventType)
    assert "compliance" not in ComplianceAuthorizationInput.model_fields
