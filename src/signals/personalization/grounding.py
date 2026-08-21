"""Fresh, read-only reuse of the frozen SPEC-023 decision evaluator."""

from __future__ import annotations

from signals.acquisition.contracts import Decision
from signals.decision_engine.contracts import (
    AcquisitionDecisionInput,
    AcquisitionDecisionProposal,
)
from signals.decision_engine.evaluator import evaluate_decision
from signals.decision_engine.policy import DECISION_POLICY_V1


class PersonalizationDecisionNoLongerEligible(ValueError):
    """The current pure decision is not SEND, regardless of historical SEND."""


class PersonalizationGroundingInsufficient(ValueError):
    """Current public grounding has no eligible Need Graph output."""


def require_current_send(
    decision_input: AcquisitionDecisionInput,
) -> AcquisitionDecisionProposal:
    """Apply exactly the frozen decision-policy-v1 rules without recording a decision."""
    proposal = evaluate_decision(decision_input, DECISION_POLICY_V1)
    if proposal.proposed_decision is not Decision.SEND:
        raise PersonalizationDecisionNoLongerEligible(
            proposal.proposed_decision.value
        )
    return proposal
