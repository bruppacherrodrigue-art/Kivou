from __future__ import annotations

from test_policy_gateway import NOW, request, snapshot

from signals.policy.contracts import (
    EvidenceReadiness,
    EvidenceStatus,
    OperationalReadiness,
    PolicyStatus,
)
from signals.policy.evaluator import evaluate_policy
from signals.policy.registry import COMMAND_POLICIES, TargetScope


def _request(**overrides):
    values = {
        "target_ref": "acquisition-opportunity:ao-1",
        "acquisition_opportunity_id": "ao-1",
        "expected_opportunity_version": 2,
        "evidence": EvidenceReadiness(
            status=EvidenceStatus.READY,
            claims=("SUPPLIER", "CONTACT_SEARCH_PROFILE"),
            assessment_version="contact-search-evidence-v1",
            observed_at=NOW,
        ),
    }
    values.update(overrides)
    return request("find_decision_makers", **values)


def test_find_decision_makers_has_provider_relevant_opportunity_policy() -> None:
    profile = COMMAND_POLICIES["find_decision_makers"]

    assert profile.target_scope is TargetScope.OPPORTUNITY
    assert profile.required_evidence == ("SUPPLIER", "CONTACT_SEARCH_PROFILE")
    assert profile.uses_budget is True
    assert profile.uses_provider_quota is True
    assert profile.requires_control_plane is True
    assert profile.uses_send_controls is False
    assert profile.requires_compliance is False
    assert evaluate_policy(_request(), snapshot(), NOW).status is PolicyStatus.APPROVED


def test_provider_quota_and_control_plane_fail_closed_without_send_controls() -> None:
    unavailable = _request(
        operational=OperationalReadiness(
            runtime_revision="runtime-1",
            provider_quota="UNKNOWN",
            provider_control_plane="UNAVAILABLE",
            mailbox_quota="READY",
            send_window="OPEN",
        )
    )
    decision = evaluate_policy(unavailable, snapshot(), NOW)
    assert decision.status is PolicyStatus.RATE_LIMITED
    assert "provider_quota_unavailable" in decision.reason_codes
    assert "provider_control_plane_unavailable" in decision.reason_codes

    send_state_irrelevant = _request(
        operational=OperationalReadiness(
            runtime_revision="runtime-1",
            provider_quota="READY",
            provider_control_plane="AVAILABLE",
            mailbox_quota="EXHAUSTED",
            send_window="CLOSED",
        )
    )
    assert evaluate_policy(send_state_irrelevant, snapshot(), NOW).status is PolicyStatus.APPROVED
