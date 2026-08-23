from __future__ import annotations

from pathlib import Path

from signals.acquisition.contracts import EventType
from signals.acquisition.state import STATE_MACHINE_VERSION
from signals.persistence.schema import (
    acquisition_allocation_proposal,
    acquisition_learning_snapshot,
)
from signals.supervisor.registry import ALLOWED_COMMANDS


def test_learning_adds_no_state_or_event_and_keeps_one_allocation_command() -> None:
    assert STATE_MACHINE_VERSION == "acquisition-state-v1"
    assert not any("LEARNING" in item.value or "REALLOC" in item.value for item in EventType)
    assert "reallocate_volume" in ALLOWED_COMMANDS
    assert not {
        "optimize_wedge",
        "scale_campaign",
        "increase_volume",
        "apply_learning",
    }.intersection(ALLOWED_COMMANDS)


def test_learning_tables_and_package_exclude_pii_network_and_dashboard_authority() -> None:
    forbidden_columns = {
        "email",
        "name",
        "contact",
        "account",
        "stripe",
        "provider",
        "reply",
        "body",
        "phone",
    }
    for table in (acquisition_learning_snapshot, acquisition_allocation_proposal):
        assert not any(
            marker in column.name.casefold() for marker in forbidden_columns for column in table.c
        )

    root = Path(__file__).parents[1]
    package_text = "\n".join(
        path.read_text() for path in (root / "src/signals/learning").glob("*.py")
    ).casefold()
    for forbidden_import in (
        "import httpx",
        "import requests",
        "import stripe",
        "openrouter",
        "openai",
        "instantly",
        "apollo",
    ):
        assert forbidden_import not in package_text
    api_text = "\n".join(path.read_text() for path in (root / "src/signals/api").glob("*.py"))
    assert "LearningLoopWorker" not in api_text
    assert not (root / "frontend/src/pages/LearningDashboard.tsx").exists()
