from __future__ import annotations

import ast
from pathlib import Path

from signals.acquisition.contracts import STATE_MACHINE_VERSION, EventType
from signals.api.config import ApiConfig
from signals.persistence.schema import (
    acquisition_conversion_event,
    acquisition_conversion_journey,
)


def test_conversion_schema_has_no_raw_pii_or_provider_payload_columns() -> None:
    columns = {
        column.name
        for table in (acquisition_conversion_journey, acquisition_conversion_event)
        for column in table.c
    }
    forbidden = {
        "email",
        "lead_email",
        "signup_email",
        "name",
        "company_name",
        "ip",
        "user_agent",
        "raw_token",
        "stripe_id",
        "stripe_payload",
        "payment_method",
        "subject",
        "body",
        "html",
        "campaign_copy",
    }
    assert forbidden.isdisjoint(columns)


def test_conversion_package_has_no_network_or_learning_dashboard_dependency() -> None:
    root = Path(__file__).resolve().parents[1] / "src/signals/conversion"
    forbidden_roots = {
        "httpx",
        "requests",
        "stripe",
        "openai",
        "openrouter",
        "signals.campaigns.instantly",
        "signals.apollo",
        "signals.supervisor",
        "signals.responses.classifier",
    }
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        assert not any(
            imported == forbidden or imported.startswith(f"{forbidden}.")
            for imported in imports
            for forbidden in forbidden_roots
        ), path


def test_state_machine_event_types_and_fail_closed_defaults_are_unchanged() -> None:
    assert STATE_MACHINE_VERSION == "acquisition-state-v1"
    assert "CONVERSION_RECORDED" not in {item.value for item in EventType}
    config = ApiConfig()
    assert config.attribution_hmac_key is None
    assert config.attribution_hmac_key_version is None

