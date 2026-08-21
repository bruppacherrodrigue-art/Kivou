from __future__ import annotations

from signals.policy.registry import COMMAND_POLICIES
from signals.supervisor.registry import ALLOWED_COMMANDS, ALLOWED_NEXT_ACTIONS


def test_spec025_promotes_personalization_handoff_to_compliance_command() -> None:
    assert "assess_campaign_compliance" in ALLOWED_NEXT_ACTIONS
    assert "assess_campaign_compliance" in ALLOWED_COMMANDS
    assert "assess_campaign_compliance" in COMMAND_POLICIES
