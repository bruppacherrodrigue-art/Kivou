"""Pure, deterministic acquisition policy evaluation."""

from __future__ import annotations

import datetime as dt

from signals.policy.contracts import (
    POLICY_VERSION,
    ApprovalGrant,
    ApprovalPurpose,
    ApprovalRef,
    AutonomyMode,
    ComplianceState,
    EvidenceStatus,
    PolicyDecision,
    PolicyRequest,
    PolicySnapshot,
    PolicyStatus,
    approval_binding_fingerprint,
)
from signals.policy.registry import COMMAND_POLICIES, RiskClass, TargetScope


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _grant_matches(
    grant: ApprovalGrant,
    purpose: ApprovalPurpose,
    request: PolicyRequest,
    snapshot: PolicySnapshot,
    evaluated_at: dt.datetime,
) -> bool:
    return (
        grant.purpose is purpose
        and grant.command == request.command
        and grant.target_ref == request.target_ref
        and grant.acquisition_opportunity_id == request.acquisition_opportunity_id
        and grant.action_fingerprint == request.action_fingerprint
        and grant.scope_fingerprint == request.scope.fingerprint()
        and grant.policy_version == snapshot.policy_version
        and grant.policy_snapshot_id == snapshot.policy_snapshot_id
        and grant.control_revision == snapshot.control_revision
        and grant.issued_at <= evaluated_at < grant.expires_at
        and grant.consumed_at is None
        and grant.one_shot
    )


def _find_grant(
    purpose: ApprovalPurpose,
    request: PolicyRequest,
    snapshot: PolicySnapshot,
    evaluated_at: dt.datetime,
) -> ApprovalGrant | None:
    return next(
        (
            grant
            for grant in request.approval_grants
            if _grant_matches(grant, purpose, request, snapshot, evaluated_at)
        ),
        None,
    )


def _known_boundaries(
    request: PolicyRequest,
    snapshot: PolicySnapshot,
    used_grants: list[ApprovalGrant],
    *,
    requires_evidence: bool,
    requires_compliance: bool,
    uses_budget: bool,
    uses_operational: bool,
) -> dt.datetime | None:
    values = [
        value
        for value in (
            snapshot.expires_at,
            snapshot.budget.period_end if uses_budget else None,
            request.evidence.valid_until if requires_evidence else None,
            request.compliance.valid_until if requires_compliance else None,
            request.operational.valid_until if uses_operational else None,
            *(grant.expires_at for grant in used_grants),
        )
        if value is not None
    ]
    return min(values) if values else None


def evaluate_policy(
    request: PolicyRequest,
    snapshot: PolicySnapshot,
    evaluated_at: dt.datetime,
) -> PolicyDecision:
    """Evaluate immutable inputs without I/O, clocks, randomness, or side effects."""
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")

    reasons: list[str] = []
    used_grants: list[ApprovalGrant] = []
    primary: PolicyStatus | None = None
    profile = COMMAND_POLICIES.get(request.command)
    effective_mode = (
        snapshot.shadow_target_mode
        if snapshot.autonomy_mode is AutonomyMode.SHADOW
        else snapshot.autonomy_mode
    )

    safe_under_hard_stop = bool(
        profile
        and profile.risk_class
        in {
            RiskClass.READ_ONLY,
            RiskClass.PREPARATORY,
            RiskClass.RISK_REDUCTION,
            RiskClass.HUMAN_REVIEW,
        }
    )
    positive_mutation = bool(profile and profile.risk_class is RiskClass.COMMERCIAL_MUTATION)
    if snapshot.kill_switch and not safe_under_hard_stop:
        primary = PolicyStatus.DENIED
        reasons.append("kill_switch_active")
    elif snapshot.kill_switch:
        reasons.append("kill_switch_active_safe_exception")
    if snapshot.read_only and positive_mutation:
        primary = primary or PolicyStatus.DENIED
        reasons.append("read_only_mutation_blocked")

    if (
        snapshot.policy_version != POLICY_VERSION
        or request.expected_policy_version != snapshot.policy_version
    ):
        primary = primary or PolicyStatus.DENIED
        reasons.append("unsupported_policy_version")
    if profile is None:
        primary = primary or PolicyStatus.DENIED
        reasons.append("unknown_command")
    else:
        if request.command not in snapshot.allowed_commands:
            primary = primary or PolicyStatus.DENIED
            reasons.append("command_not_allowed")
        if (
            profile.target_scope is TargetScope.OPPORTUNITY
            and request.acquisition_opportunity_id is None
        ):
            primary = primary or PolicyStatus.DENIED
            reasons.append("opportunity_required")
        if (
            profile.target_scope is TargetScope.GLOBAL
            and request.acquisition_opportunity_id is not None
        ):
            primary = primary or PolicyStatus.DENIED
            reasons.append("global_command_scope_mismatch")
        if request.scope.country and request.scope.country not in snapshot.allowed_countries:
            primary = primary or PolicyStatus.DENIED
            reasons.append("country_not_allowed")
        if request.scope.language and request.scope.language not in snapshot.allowed_languages:
            primary = primary or PolicyStatus.DENIED
            reasons.append("language_not_allowed")
        if request.scope.wedge and request.scope.wedge not in snapshot.allowed_wedges:
            primary = primary or PolicyStatus.DENIED
            reasons.append("wedge_not_allowed")
        if (
            request.command == "reallocate_volume"
            and effective_mode is not AutonomyMode.ADAPTIVE_SCALE
        ):
            primary = primary or PolicyStatus.DENIED
            reasons.append("adaptive_scale_required")

    if profile is not None:
        if profile.requires_compliance:
            compliance = request.compliance
            if compliance.observed_at > evaluated_at:
                primary = primary or PolicyStatus.COMPLIANCE_BLOCKED
                reasons.append("compliance_assessment_future_dated")
            elif compliance.valid_until is not None and evaluated_at >= compliance.valid_until:
                primary = primary or PolicyStatus.COMPLIANCE_BLOCKED
                reasons.append("compliance_assessment_expired")
            elif compliance.state is ComplianceState.BLOCKED:
                primary = primary or PolicyStatus.COMPLIANCE_BLOCKED
                reasons.append("compliance_blocked")
            elif compliance.state is ComplianceState.UNKNOWN:
                primary = primary or PolicyStatus.COMPLIANCE_BLOCKED
                reasons.append("compliance_state_unknown")
            elif compliance.state is ComplianceState.REVIEW_REQUIRED:
                compliance_grant = _find_grant(
                    ApprovalPurpose.COMPLIANCE_REVIEW, request, snapshot, evaluated_at
                )
                if compliance_grant is None:
                    primary = primary or PolicyStatus.APPROVAL_REQUIRED
                    reasons.append("compliance_review_approval_required")
                else:
                    used_grants.append(compliance_grant)

        if profile.required_evidence:
            evidence = request.evidence
            claims = set(evidence.claims)
            if evidence.observed_at > evaluated_at:
                primary = primary or PolicyStatus.INSUFFICIENT_EVIDENCE
                reasons.append("evidence_future_dated")
            elif evidence.valid_until is not None and evaluated_at >= evidence.valid_until:
                primary = primary or PolicyStatus.INSUFFICIENT_EVIDENCE
                reasons.append("evidence_expired")
            elif evidence.status is not EvidenceStatus.READY or any(
                item not in claims for item in profile.required_evidence
            ):
                primary = primary or PolicyStatus.INSUFFICIENT_EVIDENCE
                reasons.append("insufficient_evidence")

        budget = snapshot.budget
        cost_remaining = budget.cost_cap - budget.cost_used
        volume_remaining = budget.volume_cap - budget.volume_used
        if profile.uses_budget and request.currency != budget.currency:
            primary = primary or PolicyStatus.BUDGET_EXCEEDED
            reasons.append("currency_mismatch")
        if profile.uses_budget and request.proposed_cost > cost_remaining:
            primary = primary or PolicyStatus.BUDGET_EXCEEDED
            reasons.append("daily_cost_cap_exceeded")
        if profile.uses_volume and request.proposed_volume > volume_remaining:
            primary = primary or PolicyStatus.BUDGET_EXCEEDED
            reasons.append("daily_volume_cap_exceeded")

        op = request.operational
        uses_operational = profile.uses_send_controls or profile.requires_control_plane
        if (
            uses_operational
            and op.valid_until is not None
            and evaluated_at >= op.valid_until
        ):
            primary = primary or PolicyStatus.RATE_LIMITED
            reasons.append("operational_readiness_expired")
        else:
            if profile.uses_send_controls:
                if op.provider_quota != "READY":
                    primary = primary or PolicyStatus.RATE_LIMITED
                    reasons.append("provider_quota_unavailable")
                if op.mailbox_quota != "READY":
                    primary = primary or PolicyStatus.RATE_LIMITED
                    reasons.append("mailbox_quota_unavailable")
                if op.send_window != "OPEN":
                    primary = primary or PolicyStatus.RATE_LIMITED
                    reasons.append("send_window_unavailable")
            if profile.requires_control_plane and op.provider_control_plane != "AVAILABLE":
                primary = primary or PolicyStatus.RATE_LIMITED
                reasons.append("provider_control_plane_unavailable")

        action_required = bool(
            profile.risk_class is RiskClass.COMMERCIAL_MUTATION
            and effective_mode is AutonomyMode.ASSISTED
        )
        if action_required:
            action_grant = _find_grant(ApprovalPurpose.ACTION, request, snapshot, evaluated_at)
            if action_grant is None:
                primary = primary or PolicyStatus.APPROVAL_REQUIRED
                reasons.append("action_approval_required")
            else:
                used_grants.append(action_grant)
    else:
        cost_remaining = snapshot.budget.cost_cap - snapshot.budget.cost_used
        volume_remaining = snapshot.budget.volume_cap - snapshot.budget.volume_used
        uses_operational = False

    status = primary or PolicyStatus.APPROVED
    counterfactual = None
    if snapshot.autonomy_mode is AutonomyMode.SHADOW:
        counterfactual = status
        if status is PolicyStatus.APPROVED:
            status = PolicyStatus.DENIED
            reasons.append("shadow_mode_execution_blocked")

    executable = (
        status is PolicyStatus.APPROVED and snapshot.autonomy_mode is not AutonomyMode.SHADOW
    )
    return PolicyDecision(
        evaluation_id=request.evaluation_id,
        request_id=request.request_id,
        status=status,
        counterfactual_status=counterfactual,
        executable=executable,
        command=request.command,
        target_ref=request.target_ref,
        acquisition_opportunity_id=request.acquisition_opportunity_id,
        action_fingerprint=request.action_fingerprint,
        reason_codes=_dedupe(reasons or ["policy_envelope_satisfied"]),
        policy_version=snapshot.policy_version,
        policy_snapshot_id=snapshot.policy_snapshot_id,
        control_revision=snapshot.control_revision,
        runtime_revision=request.operational.runtime_revision,
        evaluated_at=evaluated_at,
        valid_until=_known_boundaries(
            request,
            snapshot,
            used_grants,
            requires_evidence=bool(profile and profile.required_evidence),
            requires_compliance=bool(profile and profile.requires_compliance),
            uses_budget=bool(profile and (profile.uses_budget or profile.uses_volume)),
            uses_operational=uses_operational,
        ),
        requires_revalidation=True,
        currency=request.currency,
        estimated_cost=request.proposed_cost,
        proposed_volume=request.proposed_volume,
        cost_remaining=cost_remaining,
        volume_remaining=volume_remaining,
        retry_after=request.operational.retry_after
        if status is PolicyStatus.RATE_LIMITED
        else None,
        approval_refs=tuple(
            sorted(
                (
                    ApprovalRef(
                        approval_id=grant.approval_id,
                        purpose=grant.purpose,
                        binding_fingerprint=approval_binding_fingerprint(grant),
                    )
                    for grant in used_grants
                ),
                key=lambda item: (item.purpose.value, item.approval_id, item.binding_fingerprint),
            )
        ),
        evidence_refs=request.evidence_refs,
    )
