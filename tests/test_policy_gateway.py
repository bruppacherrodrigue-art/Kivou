from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from signals.policy.contracts import (
    POLICY_VERSION,
    ApprovalGrant,
    ApprovalPurpose,
    AutonomyMode,
    BudgetEnvelope,
    ComplianceAssessment,
    ComplianceState,
    EvidenceReadiness,
    EvidenceStatus,
    OperationalReadiness,
    PolicyRequest,
    PolicySnapshot,
    PolicyStatus,
    Scope,
)
from signals.policy.evaluator import evaluate_policy
from signals.policy.registry import COMMAND_POLICIES, RiskClass, TargetScope
from signals.supervisor.registry import ALLOWED_COMMANDS, ALLOWED_NEXT_ACTIONS

NOW = dt.datetime(2026, 8, 20, 8, tzinfo=dt.UTC)


def snapshot(**overrides: object) -> PolicySnapshot:
    values: dict[str, object] = {
        "policy_snapshot_id": "snapshot-1",
        "control_revision": 1,
        "policy_version": POLICY_VERSION,
        "captured_at": NOW,
        "autonomy_mode": AutonomyMode.AUTONOMOUS_CAPPED,
        "shadow_target_mode": None,
        "read_only": False,
        "kill_switch": False,
        "allowed_commands": tuple(sorted(ALLOWED_COMMANDS)),
        "allowed_countries": ("CH",),
        "allowed_languages": ("fr",),
        "allowed_wedges": ("construction",),
        "budget": BudgetEnvelope(
            period_start=NOW - dt.timedelta(hours=1),
            period_end=NOW + dt.timedelta(hours=12),
            currency="CHF",
            cost_cap=Decimal("100"),
            cost_used=Decimal("10"),
            volume_cap=100,
            volume_used=10,
        ),
        "runtime_revision": "runtime-1",
        "expires_at": NOW + dt.timedelta(hours=6),
    }
    values.update(overrides)
    return PolicySnapshot.model_validate(values)


def request(command: str = "evaluate_opportunity", **overrides: object) -> PolicyRequest:
    values: dict[str, object] = {
        "evaluation_id": "eval-1",
        "request_id": "request-1",
        "command": command,
        "target_ref": "target-1",
        "acquisition_opportunity_id": "opp-1",
        "expected_opportunity_version": 1,
        "actor_type": "HERMES",
        "actor_ref": "kivou-acquisition-supervisor",
        "canonical_arguments": "{}",
        "action_fingerprint": "a" * 64,
        "scope": Scope(country="CH", language="fr", wedge="construction"),
        "proposed_cost": Decimal("1"),
        "currency": "CHF",
        "proposed_volume": 1,
        "reason_codes": ("qualified",),
        "evidence_refs": ("evidence-1",),
        "evidence": EvidenceReadiness(
            status=EvidenceStatus.READY,
            claims=(
                "SIGNAL",
                "PUBLIC_OPPORTUNITY",
                "PUBLIC_EVIDENCE",
                "ACQUISITION_PROSPECT_PREBUILD",
                "ACQUISITION_DECISION",
                "DECISION_INPUT",
                "FIT_DECISION",
                "RECENT_SIGNAL",
                "VERIFIED_CONTACT",
                "SUPPLIER",
                "PERSONALIZATION_ARTIFACT",
                "COMPLIANCE_ASSESSMENT",
                "CAMPAIGN_PLAN",
                "MAILBOX_READINESS",
                "SEND_WINDOW",
            ),
            assessment_version="evidence-v1",
            observed_at=NOW,
        ),
        "compliance": ComplianceAssessment(
            state=ComplianceState.ALLOWED,
            assessment_version="compliance-v1",
            observed_at=NOW,
        ),
        "operational": OperationalReadiness(runtime_revision="runtime-1"),
        "expected_policy_version": POLICY_VERSION,
        "approval_grants": (),
    }
    values.update(overrides)
    return PolicyRequest.model_validate(values)


def grant(purpose: ApprovalPurpose, req: PolicyRequest, snap: PolicySnapshot) -> ApprovalGrant:
    return ApprovalGrant(
        approval_id=f"approval-{purpose.value.lower()}",
        purpose=purpose,
        command=req.command,
        target_ref=req.target_ref,
        acquisition_opportunity_id=req.acquisition_opportunity_id,
        action_fingerprint=req.action_fingerprint,
        policy_version=snap.policy_version,
        policy_snapshot_id=snap.policy_snapshot_id,
        control_revision=snap.control_revision,
        scope_fingerprint=req.scope.fingerprint(),
        issued_at=NOW - dt.timedelta(minutes=1),
        expires_at=NOW + dt.timedelta(minutes=30),
        approved_by_actor_ref="human-supervisor",
    )


def test_registry_covers_all_supervisor_commands_without_callables() -> None:
    assert set(COMMAND_POLICIES) == set(ALLOWED_COMMANDS)
    assert {
        command for command, profile in COMMAND_POLICIES.items() if profile.requires_compliance
    } == {"schedule_campaign"}
    assert all(
        not callable(value)
        for profile in COMMAND_POLICIES.values()
        for value in vars(profile).values()
    )


def test_assess_compliance_is_a_real_preparatory_command_without_circular_gate() -> None:
    policy = COMMAND_POLICIES["assess_campaign_compliance"]

    assert "assess_campaign_compliance" in ALLOWED_COMMANDS
    assert policy.risk_class.value == "PREPARATORY"
    assert policy.target_scope.value == "OPPORTUNITY"
    assert policy.required_evidence == (
        "ACQUISITION_DECISION",
        "PUBLIC_EVIDENCE",
        "VERIFIED_CONTACT",
        "ACQUISITION_PROSPECT_PREBUILD",
        "PERSONALIZATION_ARTIFACT",
        "COMPLIANCE_INPUT",
    )
    assert policy.uses_budget is False
    assert policy.uses_volume is False
    assert policy.uses_provider_quota is False
    assert policy.uses_send_controls is False
    assert policy.requires_control_plane is False
    assert policy.requires_compliance is False
    assert ALLOWED_NEXT_ACTIONS == ALLOWED_COMMANDS


def test_schedule_campaign_policy_is_exact_spec026_commercial_gate() -> None:
    policy = COMMAND_POLICIES["schedule_campaign"]

    assert policy.risk_class is RiskClass.COMMERCIAL_MUTATION
    assert policy.target_scope is TargetScope.OPPORTUNITY
    assert policy.required_evidence == (
        "ACQUISITION_DECISION",
        "PUBLIC_EVIDENCE",
        "VERIFIED_CONTACT",
        "ACQUISITION_PROSPECT_PREBUILD",
        "PERSONALIZATION_ARTIFACT",
        "COMPLIANCE_ASSESSMENT",
        "CAMPAIGN_PLAN",
        "MAILBOX_READINESS",
        "SEND_WINDOW",
    )
    assert policy.uses_budget is True
    assert policy.uses_volume is True
    assert policy.uses_provider_quota is True
    assert policy.uses_send_controls is True
    assert policy.requires_control_plane is True
    assert policy.requires_compliance is True
    assert "FIT_DECISION" not in policy.required_evidence
    assert "RECENT_SIGNAL" not in policy.required_evidence


def test_assisted_assessment_command_is_not_action_approval_gated() -> None:
    decision = evaluate_policy(
        request(
            "assess_campaign_compliance",
            evidence=EvidenceReadiness(
                status=EvidenceStatus.READY,
                claims=COMMAND_POLICIES[
                    "assess_campaign_compliance"
                ].required_evidence,
                assessment_version="compliance-evidence-v1",
                observed_at=NOW,
            ),
            compliance=ComplianceAssessment(
                state=ComplianceState.UNKNOWN,
                assessment_version="policy-compliance-pending-v1",
                observed_at=NOW,
            ),
            proposed_cost=Decimal("0"),
            proposed_volume=0,
        ),
        snapshot(autonomy_mode=AutonomyMode.ASSISTED),
        NOW,
    )

    assert decision.status is PolicyStatus.APPROVED
    assert decision.executable is True


@pytest.mark.parametrize("value", ["", "x" * 65, "run;rm", "$(id)", "bad\ncommand"])
def test_malformed_command_is_contract_error(value: str) -> None:
    with pytest.raises(ValidationError):
        request(value)


def test_approval_grants_are_bounded_and_shadow_target_is_strict() -> None:
    req = request()
    snap = snapshot()
    with pytest.raises(ValidationError):
        request(approval_grants=tuple(grant(ApprovalPurpose.ACTION, req, snap) for _ in range(5)))
    with pytest.raises(ValidationError):
        snapshot(autonomy_mode=AutonomyMode.SHADOW, shadow_target_mode=AutonomyMode.SHADOW)
    with pytest.raises(ValidationError):
        snapshot(autonomy_mode=AutonomyMode.ASSISTED, shadow_target_mode=AutonomyMode.ASSISTED)


def test_evaluation_id_is_bounded_for_acquisition_event_idempotency() -> None:
    with pytest.raises(ValidationError):
        request(evaluation_id="e" * 65)


def test_known_command_is_approved_and_unknown_symbolic_command_is_denied() -> None:
    assert evaluate_policy(request(), snapshot(), NOW).status is PolicyStatus.APPROVED
    decision = evaluate_policy(request("unknown_symbolic_command"), snapshot(), NOW)
    assert decision.status is PolicyStatus.DENIED
    assert decision.reason_codes[0] == "unknown_command"


def test_shadow_is_never_executable_and_reports_counterfactual() -> None:
    snap = snapshot(
        autonomy_mode=AutonomyMode.SHADOW, shadow_target_mode=AutonomyMode.AUTONOMOUS_CAPPED
    )
    decision = evaluate_policy(request(), snap, NOW)
    assert decision.status is PolicyStatus.DENIED
    assert decision.counterfactual_status is PolicyStatus.APPROVED
    assert decision.executable is False
    assert decision.allowed is False


def test_read_only_and_kill_switch_block_positive_mutation_but_allow_safe_actions() -> None:
    read_only = snapshot(read_only=True)
    assert (
        evaluate_policy(request("schedule_campaign"), read_only, NOW).status is PolicyStatus.DENIED
    )
    killed = snapshot(kill_switch=True)
    assert (
        evaluate_policy(request("schedule_campaign"), killed, NOW).reason_codes[0]
        == "kill_switch_active"
    )
    for command in ("pause_campaign", "request_human_review", "generate_weekly_report"):
        req = request(command, acquisition_opportunity_id=None, expected_opportunity_version=None)
        assert evaluate_policy(req, killed, NOW).status is PolicyStatus.APPROVED


def test_compliance_and_action_approvals_are_independent() -> None:
    snap = snapshot(autonomy_mode=AutonomyMode.ASSISTED)
    base = request(
        "schedule_campaign",
        compliance=ComplianceAssessment(
            state=ComplianceState.REVIEW_REQUIRED,
            assessment_version="compliance-v1",
            observed_at=NOW,
        ),
    )
    compliance = grant(ApprovalPurpose.COMPLIANCE_REVIEW, base, snap)
    action = grant(ApprovalPurpose.ACTION, base, snap)
    assert (
        evaluate_policy(
            base.model_copy(update={"approval_grants": (compliance,)}), snap, NOW
        ).status
        is PolicyStatus.APPROVAL_REQUIRED
    )
    assert (
        evaluate_policy(base.model_copy(update={"approval_grants": (action,)}), snap, NOW).status
        is PolicyStatus.APPROVAL_REQUIRED
    )
    approved = evaluate_policy(
        base.model_copy(update={"approval_grants": (compliance, action)}), snap, NOW
    )
    assert approved.status is PolicyStatus.APPROVED
    assert {
        (approval.approval_id, approval.purpose.value)
        for approval in approved.approval_refs
    } == {
        (compliance.approval_id, ApprovalPurpose.COMPLIANCE_REVIEW.value),
        (action.approval_id, ApprovalPurpose.ACTION.value),
    }
    assert all(len(approval.binding_fingerprint) == 64 for approval in approved.approval_refs)


def test_no_approval_required_produces_empty_approval_refs() -> None:
    decision = evaluate_policy(request(), snapshot(), NOW)
    assert decision.status is PolicyStatus.APPROVED
    assert decision.approval_refs == ()


@pytest.mark.parametrize("state", [ComplianceState.BLOCKED, ComplianceState.UNKNOWN])
def test_blocked_or_unknown_compliance_cannot_be_overridden(state: ComplianceState) -> None:
    snap = snapshot(autonomy_mode=AutonomyMode.ASSISTED)
    base = request(
        "schedule_campaign",
        compliance=ComplianceAssessment(
            state=state, assessment_version="compliance-v1", observed_at=NOW
        ),
    )
    grants = (
        grant(ApprovalPurpose.COMPLIANCE_REVIEW, base, snap),
        grant(ApprovalPurpose.ACTION, base, snap),
    )
    assert (
        evaluate_policy(base.model_copy(update={"approval_grants": grants}), snap, NOW).status
        is PolicyStatus.COMPLIANCE_BLOCKED
    )


def test_wrong_target_expired_and_old_policy_approvals_do_not_bind() -> None:
    snap = snapshot(autonomy_mode=AutonomyMode.ASSISTED)
    req = request("schedule_campaign")
    valid = grant(ApprovalPurpose.ACTION, req, snap)
    for invalid in (
        valid.model_copy(update={"target_ref": "other"}),
        valid.model_copy(update={"expires_at": NOW}),
        valid.model_copy(update={"control_revision": 99}),
    ):
        assert (
            evaluate_policy(
                req.model_copy(update={"approval_grants": (invalid,)}), snap, NOW
            ).status
            is PolicyStatus.APPROVAL_REQUIRED
        )


def test_evidence_budget_compliance_and_rate_gates_have_deterministic_precedence() -> None:
    missing = request(
        evidence=request().evidence.model_copy(update={"status": EvidenceStatus.INSUFFICIENT})
    )
    assert evaluate_policy(missing, snapshot(), NOW).status is PolicyStatus.INSUFFICIENT_EVIDENCE
    discovery_evidence = request().evidence.model_copy(
        update={
            "claims": (
                "PUBLIC_OPPORTUNITY",
                "PUBLIC_EVIDENCE",
                "SUPPLIER_SEARCH_PROFILE",
            )
        }
    )
    over = request(
        "discover_suppliers",
        target_ref="procurement-opportunity:public-1",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
        evidence=discovery_evidence,
        proposed_cost=Decimal("91"),
    )
    assert evaluate_policy(over, snapshot(), NOW).status is PolicyStatus.BUDGET_EXCEEDED
    exact = request(
        "discover_suppliers",
        target_ref="procurement-opportunity:public-1",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
        evidence=discovery_evidence,
        proposed_cost=Decimal("90"),
        proposed_volume=90,
    )
    assert evaluate_policy(exact, snapshot(), NOW).status is PolicyStatus.APPROVED
    rate = request(
        "schedule_campaign",
        operational=OperationalReadiness(
            runtime_revision="runtime-1",
            provider_quota="EXHAUSTED",
            retry_after=NOW + dt.timedelta(hours=1),
        ),
    )
    result = evaluate_policy(rate, snapshot(), NOW)
    assert result.status is PolicyStatus.RATE_LIMITED
    assert result.retry_after == NOW + dt.timedelta(hours=1)
    blocked = request(
        "schedule_campaign",
        compliance=request().compliance.model_copy(update={"state": ComplianceState.BLOCKED}),
        proposed_cost=Decimal("100"),
    )
    result = evaluate_policy(blocked, snapshot(kill_switch=True), NOW)
    assert result.reason_codes[:3] == (
        "kill_switch_active",
        "compliance_blocked",
        "daily_cost_cap_exceeded",
    )


def test_valid_until_is_earliest_authoritative_boundary_or_none() -> None:
    result = evaluate_policy(request(), snapshot(), NOW)
    assert result.valid_until == NOW + dt.timedelta(hours=6)
    no_bounds = snapshot(
        expires_at=None, budget=snapshot().budget.model_copy(update={"period_end": None})
    )
    result = evaluate_policy(request(), no_bounds, NOW)
    assert result.valid_until is None
    assert result.requires_revalidation is True


def test_invalid_money_and_naive_dates_are_rejected() -> None:
    for cost in (Decimal("-1"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValidationError):
            request(proposed_cost=cost)
    with pytest.raises(ValidationError):
        snapshot(captured_at=dt.datetime(2026, 8, 20))  # noqa: DTZ001
