"""Kivou-owned v1 economic score and fail-closed evidence gates."""

from __future__ import annotations

from decimal import Decimal

from signals.learning.contracts import EconomicScore, EconomicScoreStatus, LearningCellMetrics

MAX_BOUNCE_RATE = Decimal("0.05")
MIN_CONTACTED = 50
MIN_PAID = 2
MIN_M1_ELIGIBLE = 2
MIN_RETAINED_M1 = 1


def score_cell(metrics: LearningCellMetrics) -> EconomicScore:
    contacted = Decimal(metrics.contacted_count)
    retained = Decimal(metrics.retained_mrr_minor_units) / contacted if contacted else Decimal(0)
    cost = Decimal(metrics.known_variable_cost_minor_units) / contacted if contacted else Decimal(0)
    risk_numerator = (
        2500 * metrics.complaint_count
        + 500 * metrics.unsubscribe_count
        + 250 * metrics.bounce_count
        + 1000 * metrics.churn_count
    )
    risk = min(Decimal(5000), Decimal(risk_numerator) / contacted) if contacted else Decimal(0)
    reasons: list[str] = []
    bounce_rate = Decimal(metrics.bounce_count) / contacted if contacted else None
    if (
        metrics.complaint_count > 0
        or metrics.conversion_identity_ambiguous
        or (bounce_rate is not None and bounce_rate > MAX_BOUNCE_RATE)
    ):
        status = EconomicScoreStatus.RISK_BLOCKED
        reasons.append("LEARNING_RISK_BLOCKED")
    elif not metrics.mrr_complete:
        status = EconomicScoreStatus.MRR_INCOMPLETE
        reasons.append("MRR_INCOMPLETE")
    elif not metrics.cost_complete or metrics.cost_currency != metrics.currency:
        status = EconomicScoreStatus.COST_INCOMPLETE
        reasons.append(
            "COST_INCOMPLETE"
            if not metrics.cost_complete
            else "COST_CURRENCY_MISMATCH"
        )
    elif (
        metrics.contacted_count < MIN_CONTACTED
        or metrics.paid_count < MIN_PAID
        or metrics.m1_eligible_count < MIN_M1_ELIGIBLE
        or metrics.retained_m1_count < MIN_RETAINED_M1
    ):
        status = EconomicScoreStatus.INSUFFICIENT_EVIDENCE
        reasons.append("INSUFFICIENT_EVIDENCE")
    else:
        status = EconomicScoreStatus.READY
        reasons.append("ECONOMIC_SCORE_READY")
    return EconomicScore(
        cell=metrics.cell,
        status=status,
        currency=metrics.currency,
        score=retained - cost - risk,
        retained_mrr_per_contact=retained,
        cost_per_contact=cost,
        risk_penalty_per_contact=risk,
        reason_codes=tuple(reasons),
    )


__all__ = [
    "MAX_BOUNCE_RATE",
    "MIN_CONTACTED",
    "MIN_M1_ELIGIBLE",
    "MIN_PAID",
    "MIN_RETAINED_M1",
    "score_cell",
]
