from __future__ import annotations

from pathlib import Path

from signals.acquisition.contracts import EventType
from signals.acquisition.state import STATE_MACHINE_VERSION
from signals.persistence.schema import METADATA
from signals.supervisor.registry import ALLOWED_COMMANDS


def test_cockpit_adds_no_truth_table_migration_state_or_duplicate_command() -> None:
    root = Path(__file__).parents[1]
    migrations = root / "src/signals/persistence/migrations/versions"

    assert STATE_MACHINE_VERSION == "acquisition-state-v1"
    assert tuple(item.value for item in EventType) == (
        "OPPORTUNITY_CREATED",
        "STATE_TRANSITIONED",
        "DECISION_RECORDED",
        "NEXT_ACTION_SET",
        "RETRY_SCHEDULED",
        "SUPERVISOR_PLAN_OBSERVED",
        "POLICY_EVALUATED",
        "CONTACT_SELECTED",
        "OUTCOME_RECORDED",
    )
    assert "generate_weekly_report" in ALLOWED_COMMANDS
    assert not {
        "get_dashboard",
        "build_cockpit",
        "generate_cockpit",
        "send_weekly_report",
    }.intersection(ALLOWED_COMMANDS)
    assert "acquisition_commercial_cockpit" not in METADATA.tables
    assert not tuple(migrations.glob("0021*"))


def test_cockpit_package_has_no_network_provider_mutation_or_pii_contract() -> None:
    root = Path(__file__).parents[1]
    package = root / "src/signals/cockpit"
    text = "\n".join(path.read_text() for path in package.glob("*.py")).casefold()
    for forbidden in (
        "import httpx",
        "import requests",
        "import stripe",
        "openrouter",
        "openai",
        "apollo",
        "instantly",
        "send_email",
        "activate_campaign",
        "reallocate_volume",
    ):
        assert forbidden not in text
    for pii in (
        "lead_email",
        "signup_email",
        "person_name",
        "company_name",
        "stripe_id",
        "provider_lead_id",
        "response_text",
        "user_agent",
        "raw_ip",
    ):
        assert pii not in text
