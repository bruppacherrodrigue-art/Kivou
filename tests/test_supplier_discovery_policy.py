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


def _discovery_request(**overrides):
    values = {
        "target_ref": "procurement-opportunity:public-1",
        "acquisition_opportunity_id": None,
        "expected_opportunity_version": None,
        "evidence": EvidenceReadiness(
            status=EvidenceStatus.READY,
            claims=("PUBLIC_OPPORTUNITY", "PUBLIC_EVIDENCE", "SUPPLIER_SEARCH_PROFILE"),
            assessment_version="supplier-search-evidence-v1",
            observed_at=NOW,
        ),
    }
    values.update(overrides)
    return request("discover_suppliers", **values)


def test_discover_suppliers_uses_pre_opportunity_signal_scope() -> None:
    profile = COMMAND_POLICIES["discover_suppliers"]

    assert profile.target_scope is TargetScope.SIGNAL
    assert profile.uses_provider_quota is True
    assert profile.uses_send_controls is False
    assert profile.requires_control_plane is True
    assert profile.requires_compliance is False
    assert evaluate_policy(_discovery_request(), snapshot(), NOW).status is PolicyStatus.APPROVED


def test_signal_scope_rejects_non_public_seed_reference() -> None:
    decision = evaluate_policy(
        _discovery_request(target_ref="customer-signal:private-1"), snapshot(), NOW
    )
    assert decision.status is PolicyStatus.DENIED
    assert "signal_target_invalid" in decision.reason_codes


def test_discovery_provider_quota_fails_closed_without_mailbox_or_send_window_gate() -> None:
    unknown = _discovery_request(
        operational=OperationalReadiness(runtime_revision="runtime-1", provider_quota="UNKNOWN")
    )
    assert evaluate_policy(unknown, snapshot(), NOW).status is PolicyStatus.RATE_LIMITED
    assert "provider_quota_unavailable" in evaluate_policy(
        unknown, snapshot(), NOW
    ).reason_codes

    mailbox_irrelevant = _discovery_request(
        operational=OperationalReadiness(
            runtime_revision="runtime-1",
            provider_quota="READY",
            mailbox_quota="EXHAUSTED",
            send_window="CLOSED",
        )
    )
    assert (
        evaluate_policy(mailbox_irrelevant, snapshot(), NOW).status
        is PolicyStatus.APPROVED
    )
