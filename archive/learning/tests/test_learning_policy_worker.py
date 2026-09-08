from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from test_policy_gateway import NOW, request, snapshot

from signals.learning.policy import LearningPolicyFacts, build_reallocate_policy_request
from signals.policy.contracts import (
    AutonomyMode,
    AvailabilityState,
    OperationalReadiness,
    PolicyStatus,
    ReadinessState,
    WindowState,
)
from signals.policy.evaluator import evaluate_policy
from signals.policy.mapper import map_proposed_action
from signals.policy.registry import COMMAND_POLICIES, RiskClass, TargetScope
from signals.supervisor.contracts import ProposedAction


def _facts() -> LearningPolicyFacts:
    return LearningPolicyFacts(
        proposal_ref="a" * 64,
        snapshot_ref="b" * 64,
        snapshot_input_fingerprint="c" * 64,
        formula_version="wedge-economic-value-v1",
        formula_fingerprint="d" * 64,
        risk_policy_version="learning-risk-policy-v1",
        risk_policy_fingerprint="e" * 64,
        allocation_envelope_version="learning-allocation-envelope-v1",
        allocation_envelope_fingerprint="f" * 64,
        current_allocation_fingerprint="1" * 64,
        proposed_allocation_fingerprint="2" * 64,
        total_daily_units=5,
        delta_units=1,
        candidate_version="learning-candidate-generation-v1",
        window_start=NOW - dt.timedelta(days=60),
        window_end=NOW,
        observed_at=NOW,
        policy_snapshot_id="snapshot-1",
        control_revision=4,
    )


def test_reallocate_policy_profile_is_internal_plan_mutation_only() -> None:
    profile = COMMAND_POLICIES["reallocate_volume"]

    assert profile.risk_class is RiskClass.COMMERCIAL_MUTATION
    assert profile.target_scope is TargetScope.GLOBAL
    assert profile.required_evidence == (
        "LEARNING_SNAPSHOT",
        "ALLOCATION_ENVELOPE",
        "CONVERSION_RETENTION",
    )
    assert profile.uses_budget is False
    assert profile.uses_volume is False
    assert profile.uses_provider_quota is False
    assert profile.uses_send_controls is False
    assert profile.requires_control_plane is True
    assert profile.requires_compliance is False


def test_mapper_accepts_only_global_target_and_opaque_proposal_ref() -> None:
    trusted = request(
        "reallocate_volume",
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
    action = ProposedAction(
        command="reallocate_volume",
        target_ref="global:acquisition-allocation-v1",
        arguments={"proposal_ref": "a" * 64},
        reason_codes=("LEARNING_SELECTION",),
        evidence_refs=("proposal:" + "a" * 64,),
        estimated_cost=Decimal(0),
    )

    mapped = map_proposed_action(action, **trusted)

    assert mapped.canonical_arguments == '{"proposal_ref":"' + "a" * 64 + '"}'
    with pytest.raises(ValueError):
        map_proposed_action(
            action.model_copy(update={"arguments": {"allocation": {"CH:x": 5}}}),
            **trusted,
        )


def test_learning_policy_request_binds_safe_facts_but_arguments_are_proposal_only() -> None:
    value = build_reallocate_policy_request(
        _facts(),
        operational=OperationalReadiness(runtime_revision="runtime-1"),
        currency="CHF",
    )

    assert value.target_ref == "global:acquisition-allocation-v1"
    assert value.canonical_arguments == '{"proposal_ref":"' + "a" * 64 + '"}'
    assert value.acquisition_opportunity_id is None
    assert value.proposed_cost == 0
    assert value.proposed_volume == 0
    assert value.evidence.claims == (
        "LEARNING_SNAPSHOT",
        "ALLOCATION_ENVELOPE",
        "CONVERSION_RETENTION",
    )


@pytest.mark.parametrize(
    ("mode", "expected", "executable"),
    [
        (AutonomyMode.SHADOW, PolicyStatus.DENIED, False),
        (AutonomyMode.ASSISTED, PolicyStatus.DENIED, False),
        (AutonomyMode.AUTONOMOUS_CAPPED, PolicyStatus.DENIED, False),
        (AutonomyMode.ADAPTIVE_SCALE, PolicyStatus.APPROVED, True),
    ],
)
def test_only_adaptive_scale_can_execute_reallocation(mode, expected, executable) -> None:
    policy_request = build_reallocate_policy_request(
        _facts(),
        operational=OperationalReadiness(runtime_revision="runtime-1"),
        currency="CHF",
    )
    control = snapshot(
        autonomy_mode=mode,
        shadow_target_mode=(AutonomyMode.ADAPTIVE_SCALE if mode is AutonomyMode.SHADOW else None),
    )

    decision = evaluate_policy(policy_request, control, NOW)

    assert decision.status is expected
    assert decision.executable is executable
    if mode is AutonomyMode.SHADOW:
        assert decision.counterfactual_status is PolicyStatus.APPROVED


@pytest.mark.parametrize("change", [{"kill_switch": True}, {"read_only": True}])
def test_live_hard_stops_block_adaptive_reallocation(change) -> None:
    policy_request = build_reallocate_policy_request(
        _facts(),
        operational=OperationalReadiness(runtime_revision="runtime-1"),
        currency="CHF",
    )

    decision = evaluate_policy(
        policy_request,
        snapshot(autonomy_mode=AutonomyMode.ADAPTIVE_SCALE, **change),
        NOW,
    )

    assert decision.status is PolicyStatus.DENIED
    assert decision.executable is False


def test_reallocation_does_not_consume_provider_quota_or_require_send_window() -> None:
    policy_request = build_reallocate_policy_request(
        _facts(),
        operational=OperationalReadiness(
            runtime_revision="runtime-1",
            provider_quota=ReadinessState.EXHAUSTED,
            mailbox_quota=ReadinessState.EXHAUSTED,
            send_window=WindowState.CLOSED,
            provider_control_plane=AvailabilityState.AVAILABLE,
        ),
        currency="CHF",
    )

    decision = evaluate_policy(
        policy_request,
        snapshot(autonomy_mode=AutonomyMode.ADAPTIVE_SCALE),
        NOW,
    )

    assert decision.status is PolicyStatus.APPROVED
    assert decision.proposed_volume == 0
    assert decision.estimated_cost == 0
