"""Opportunity-scoped, non-executing audit of validated SPEC-017 plans."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from signals.acquisition.contracts import SupervisorAuditMappingError
from signals.acquisition.store import AcquisitionStore, MutationResult
from signals.supervisor.contracts import ProposedAction, SupervisorPlan


@dataclass(frozen=True)
class SupervisorAuditResult:
    recorded: bool
    mutation: MutationResult | None = None


def _safe_action(action: ProposedAction) -> dict[str, object]:
    return {
        "command": action.command,
        "target_ref": action.target_ref,
        "reason_codes": list(action.reason_codes),
        "evidence_refs": list(action.evidence_refs),
        "estimated_cost": str(action.estimated_cost),
    }


def _unique(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def record_supervisor_plan(
    store: AcquisitionStore,
    acquisition_opportunity_id: str,
    plan: SupervisorPlan,
    *,
    expected_version: int,
    idempotency_key: str,
) -> SupervisorAuditResult:
    """Audit selected intents; this function deliberately has no executor boundary."""
    selected: list[ProposedAction] = []
    for action in plan.proposed_actions:
        matches = store.resolve_target_ref(action.target_ref)
        if not matches:
            raise SupervisorAuditMappingError(f"unknown target_ref: {action.target_ref}")
        if len(matches) != 1:
            raise SupervisorAuditMappingError(f"ambiguous target_ref: {action.target_ref}")
        if matches[0] == acquisition_opportunity_id:
            selected.append(action)

    if not selected:
        return SupervisorAuditResult(recorded=False)

    evidence_refs = _unique(
        [reference for action in selected for reference in action.evidence_refs]
    )
    selected_cost = sum(
        (action.estimated_cost for action in selected),
        start=Decimal("0"),
    )
    payload = {
        "plan_id": plan.plan_id,
        "objective": plan.objective,
        "priority": plan.priority,
        "next_review_at": plan.next_review_at.isoformat(),
        "plan_estimated_cost": str(plan.estimated_cost),
        "actions": [_safe_action(action) for action in selected],
    }
    mutation = store.record_supervisor_plan_observed(
        acquisition_opportunity_id,
        payload=payload,
        reason_codes=plan.reason_codes,
        evidence_refs=evidence_refs,
        confidence=plan.confidence,
        estimated_cost=selected_cost,
        supervisor_version=plan.supervisor_version,
        skill_version=plan.skill_version,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        occurred_at=plan.created_at,
    )
    return SupervisorAuditResult(recorded=True, mutation=mutation)
