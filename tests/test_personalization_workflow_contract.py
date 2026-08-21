from __future__ import annotations

from signals.policy.registry import COMMAND_POLICIES
from signals.supervisor.registry import ALLOWED_COMMANDS, ALLOWED_NEXT_ACTIONS


def test_personalization_hands_off_to_canonical_compliance_assessment_action() -> None:
    assert "assess_campaign_compliance" in ALLOWED_NEXT_ACTIONS
    assert "assess_campaign_compliance" not in ALLOWED_COMMANDS
    assert "assess_campaign_compliance" not in COMMAND_POLICIES
