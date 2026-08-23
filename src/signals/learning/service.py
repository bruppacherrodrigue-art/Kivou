"""Pure snapshot construction for the versioned learning loop."""

from __future__ import annotations

from signals.learning.contracts import (
    ECONOMIC_FORMULA_VERSION,
    LEARNING_COST_POLICY_VERSION,
    LEARNING_RISK_POLICY_VERSION,
    AllocationUnit,
    LearningAllocationEnvelope,
    LearningCellMetrics,
    LearningSnapshot,
    LearningWindow,
    canonical_fingerprint,
)
from signals.learning.economics import (
    MAX_BOUNCE_RATE,
    MIN_CONTACTED,
    MIN_M1_ELIGIBLE,
    MIN_PAID,
    MIN_RETAINED_M1,
    score_cell,
)


def build_learning_snapshot(
    *,
    window: LearningWindow,
    metrics: tuple[LearningCellMetrics, ...],
    envelope: LearningAllocationEnvelope,
    previous_applied_proposal_ref: str | None,
    current_allocation: dict[str, int] | None = None,
) -> LearningSnapshot:
    ordered_metrics = tuple(sorted(metrics, key=lambda item: item.cell.key))
    scores = tuple(score_cell(item) for item in ordered_metrics)
    resolved = current_allocation or {item.cell.key: item.current_units for item in envelope.cells}
    if set(resolved) != {item.cell.key for item in envelope.cells}:
        raise ValueError("current allocation does not match envelope cells")
    current = tuple(
        AllocationUnit(cell=item.cell, units=resolved[item.cell.key])
        for item in sorted(envelope.cells, key=lambda item: item.cell.key)
    )
    if sum(item.units for item in current) != envelope.total_daily_units:
        raise ValueError("current allocation does not conserve total units")
    formula_fingerprint = canonical_fingerprint(
        "wedge-economic-value:v1",
        {
            "version": ECONOMIC_FORMULA_VERSION,
            "complaint_penalty": 2500,
            "unsubscribe_penalty": 500,
            "bounce_penalty": 250,
            "churn_penalty": 1000,
            "risk_cap": 5000,
        },
    )
    risk_fingerprint = canonical_fingerprint(
        "learning-risk-policy:v1",
        {
            "version": LEARNING_RISK_POLICY_VERSION,
            "max_bounce_rate": str(MAX_BOUNCE_RATE),
            "min_contacted": MIN_CONTACTED,
            "min_paid": MIN_PAID,
            "min_m1_eligible": MIN_M1_ELIGIBLE,
            "min_retained_m1": MIN_RETAINED_M1,
            "complaint_blocks": True,
        },
    )
    cost_fingerprint = canonical_fingerprint(
        "learning-cost-policy:v1",
        {
            "version": LEARNING_COST_POLICY_VERSION,
            "unknown_is_zero": False,
            "provider_and_mailbox_required": True,
        },
    )
    window_identity = window.model_dump(mode="json", exclude={"captured_at"})
    input_fingerprint = canonical_fingerprint(
        "learning-snapshot-input:v1",
        {
            "window": window_identity,
            "metrics": [item.model_dump(mode="json") for item in ordered_metrics],
        },
    )
    current_fingerprint = canonical_fingerprint(
        "learning-allocation-vector:v1",
        [item.model_dump(mode="json") for item in current],
    )
    identity = {
        "window": window_identity,
        "input_fingerprint": input_fingerprint,
        "formula_fingerprint": formula_fingerprint,
        "risk_policy_fingerprint": risk_fingerprint,
        "cost_policy_fingerprint": cost_fingerprint,
        "allocation_envelope_fingerprint": envelope.fingerprint,
        "current_allocation_fingerprint": current_fingerprint,
        "previous_applied_proposal_ref": previous_applied_proposal_ref,
    }
    return LearningSnapshot(
        snapshot_ref=canonical_fingerprint("learning-snapshot:v1", identity),
        window=window,
        formula_fingerprint=formula_fingerprint,
        risk_policy_fingerprint=risk_fingerprint,
        cost_policy_fingerprint=cost_fingerprint,
        input_fingerprint=input_fingerprint,
        cell_metrics=ordered_metrics,
        economic_scores=scores,
        allocation_envelope_fingerprint=envelope.fingerprint,
        current_allocation=current,
        current_allocation_fingerprint=current_fingerprint,
        previous_applied_proposal_ref=previous_applied_proposal_ref,
        created_at=window.captured_at,
    )


__all__ = ["build_learning_snapshot"]
