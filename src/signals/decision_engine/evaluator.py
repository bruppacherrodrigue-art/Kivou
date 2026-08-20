"""Pure ordered rule matrix for decision-policy-v1."""

from __future__ import annotations

from signals.acquisition.contracts import Decision
from signals.decision_engine.contracts import (
    AcquisitionDecisionInput,
    AcquisitionDecisionProposal,
    DecisionPolicyConfig,
    RecencyBasis,
)
from signals.decision_engine.policy import semantic_fingerprint
from signals.supplier_discovery.contracts import SupplierIdentityStatus


def _outcome(
    decision_input: AcquisitionDecisionInput,
    policy_config: DecisionPolicyConfig,
) -> tuple[Decision, tuple[str, ...], str | None]:
    if (
        decision_input.profile_supplier_identity_status
        != decision_input.current_supplier_identity_status
    ):
        return Decision.REVIEW, ("SUPPLIER_IDENTITY_CHANGED_SINCE_RESEARCH",), (
            "request_human_review"
        )
    if decision_input.current_supplier_identity_status is SupplierIdentityStatus.DOMAIN_CONFLICT:
        return Decision.REVIEW, ("SUPPLIER_DOMAIN_CONFLICT",), "request_human_review"
    if decision_input.recency_basis is RecencyBasis.UNRESOLVED:
        return Decision.REVIEW, ("RECENCY_UNRESOLVED",), "request_human_review"
    if decision_input.public_timing_inconsistent:
        return Decision.REVIEW, ("PUBLIC_TIMING_INCONSISTENT",), "request_human_review"
    if decision_input.age_days is None:
        raise ValueError("resolved recency must have age_days")
    if decision_input.age_days > policy_config.max_send_age_days:
        return Decision.NO_SEND, ("SIGNAL_OUTSIDE_ACQUISITION_WINDOW",), None

    reasons = [
        "SIGNAL_WITHIN_ACQUISITION_WINDOW",
        "SUPPLIER_IDENTITY_ACCEPTABLE",
        "VERIFIED_COMMERCIAL_CONTACT",
        "ACQUISITION_PREBUILD_AVAILABLE",
    ]
    if decision_input.recency_basis is RecencyBasis.CONTRACT_NOTIFICATION_DATE:
        reasons.append("RECENCY_NOTIFICATION_FALLBACK")
    elif decision_input.recency_basis is RecencyBasis.PUBLICATION_DATE:
        reasons.append("RECENCY_PUBLICATION_FALLBACK")
    return Decision.SEND, tuple(reasons), "prepare_campaign"


def evaluate_decision(
    decision_input: AcquisitionDecisionInput,
    policy_config: DecisionPolicyConfig,
) -> AcquisitionDecisionProposal:
    """Evaluate one immutable input without I/O, clocks, randomness, or hidden state."""

    if decision_input.decision_policy_config_fingerprint != policy_config.config_fingerprint:
        raise ValueError("decision input and policy configuration do not match")
    decision, reasons, next_action = _outcome(decision_input, policy_config)
    evidence = (
        f"contract-award:{decision_input.representative_award_key}",
        f"source-event:{decision_input.source_event_key}",
        f"acquisition-company-profile:{decision_input.acquisition_opportunity_id}",
        f"acquisition-supplier:{decision_input.supplier_ref}",
        f"acquisition-contact:{decision_input.contact_ref}",
    )
    values = {
        "proposed_decision": decision,
        "reason_codes": reasons,
        "evidence_refs": evidence,
        "next_action": next_action,
        "next_review_at": None,
        "decision_input_fingerprint": decision_input.decision_input_fingerprint,
        "decision_policy_version": policy_config.policy_version,
        "confidence": None,
    }
    return AcquisitionDecisionProposal(
        **values,
        proposal_fingerprint=semantic_fingerprint(values),
    )
