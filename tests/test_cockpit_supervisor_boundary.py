from __future__ import annotations

from decimal import Decimal

import pytest
from test_policy_gateway import request

from signals.policy.mapper import map_proposed_action
from signals.policy.registry import COMMAND_POLICIES, RiskClass, TargetScope
from signals.supervisor.contracts import ProposedAction


def _action(*, target: str = "global:commercial-cockpit-v1", arguments=None):
    return ProposedAction(
        command="generate_weekly_report",
        target_ref=target,
        arguments={} if arguments is None else arguments,
        reason_codes=("WEEKLY_COCKPIT",),
        evidence_refs=(),
        estimated_cost=Decimal("0"),
    )


def test_generate_weekly_report_policy_remains_pure_read_only_global() -> None:
    profile = COMMAND_POLICIES["generate_weekly_report"]
    assert profile.risk_class is RiskClass.READ_ONLY
    assert profile.target_scope is TargetScope.GLOBAL
    assert profile.required_evidence == ()
    assert profile.uses_budget is False
    assert profile.uses_volume is False
    assert profile.uses_provider_quota is False
    assert profile.uses_send_controls is False
    assert profile.requires_compliance is False


def test_hermes_can_request_only_the_frozen_target_with_empty_arguments() -> None:
    trusted = request(
        "generate_weekly_report",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
    ).model_dump(mode="python")
    for key in (
        "command",
        "target_ref",
        "canonical_arguments",
        "action_fingerprint",
        "reason_codes",
        "evidence_refs",
        "proposed_cost",
    ):
        trusted.pop(key)
    mapped = map_proposed_action(_action(), **trusted)
    assert mapped.command == "generate_weekly_report"
    assert mapped.target_ref == "global:commercial-cockpit-v1"
    assert mapped.canonical_arguments == "{}"

    for action in (
        _action(target="global:anything-else"),
        _action(arguments={"week_offset": 1}),
        _action(arguments={"country": "CH"}),
    ):
        with pytest.raises(ValueError):
            map_proposed_action(action, **trusted)
