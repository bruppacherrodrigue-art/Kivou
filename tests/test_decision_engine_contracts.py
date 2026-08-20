from __future__ import annotations

import pytest
from pydantic import ValidationError

from signals.acquisition.contracts import Decision
from signals.decision_engine.contracts import AcquisitionDecisionProposal
from signals.decision_engine.policy import (
    DECISION_POLICY_V1,
    decision_policy_config_fingerprint,
)


def test_decision_policy_v1_is_frozen_and_callable_free() -> None:
    policy = DECISION_POLICY_V1

    assert policy.policy_version == "decision-policy-v1"
    assert policy.recency_version == "acquisition-recency-v1"
    assert policy.max_send_age_days == 60
    assert policy.future_date_tolerance_days == 0
    assert policy.award_publication_tolerance_days == 1
    assert policy.hold_enabled is False
    assert policy.enrich_enabled is False
    assert policy.reason_code_version == "decision-reasons-v1"
    assert policy.config_fingerprint == decision_policy_config_fingerprint(policy)
    assert len(policy.config_fingerprint) == 64


def test_policy_fingerprint_is_deterministic_and_changes_with_semantics() -> None:
    policy = DECISION_POLICY_V1

    assert decision_policy_config_fingerprint(policy) == decision_policy_config_fingerprint(
        policy.model_copy()
    )
    changed = policy.model_copy(
        update={"max_send_age_days": 61, "config_fingerprint": "0" * 64}
    )
    assert decision_policy_config_fingerprint(changed) != policy.config_fingerprint


@pytest.mark.parametrize("decision", (Decision.HOLD, Decision.ENRICH))
def test_v1_proposal_contract_rejects_reserved_decisions(decision: Decision) -> None:
    with pytest.raises(ValidationError):
        AcquisitionDecisionProposal(
            proposed_decision=decision,
            reason_codes=("reserved",),
            evidence_refs=("contract-award:award-1",),
            next_action=None,
            decision_input_fingerprint="a" * 64,
            proposal_fingerprint="b" * 64,
        )
