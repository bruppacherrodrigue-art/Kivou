from __future__ import annotations

import datetime as dt

import pytest
from test_policy_gateway import NOW, grant, request, snapshot

from signals.policy.contracts import (
    ApprovalPurpose,
    ComplianceState,
    EvidenceStatus,
    PolicyStatus,
)
from signals.policy.evaluator import evaluate_policy


def _request_with_states(
    command: str,
    *,
    evidence: EvidenceStatus,
    compliance: ComplianceState,
    currency: str,
):
    pre_opportunity_command = command in {
        "generate_weekly_report",
        "pause_campaign",
        "request_human_review",
        "discover_suppliers",
    }
    base = request(
        command,
        target_ref=(
            "procurement-opportunity:public-1"
            if command == "discover_suppliers"
            else "target-1"
        ),
        acquisition_opportunity_id=None if pre_opportunity_command else "opp-1",
        expected_opportunity_version=None if pre_opportunity_command else 1,
        currency=currency,
    )
    claims = (
        ("PUBLIC_OPPORTUNITY", "PUBLIC_EVIDENCE", "SUPPLIER_SEARCH_PROFILE")
        if command == "discover_suppliers"
        else base.evidence.claims
    )
    return base.model_copy(
        update={
            "evidence": base.evidence.model_copy(
                update={"status": evidence, "claims": claims}
            ),
            "compliance": base.compliance.model_copy(update={"state": compliance}),
        }
    )


@pytest.mark.parametrize(
    ("command", "evidence", "compliance", "currency", "expected"),
    [
        (
            "request_human_review",
            EvidenceStatus.UNKNOWN,
            ComplianceState.UNKNOWN,
            "EUR",
            PolicyStatus.APPROVED,
        ),
        (
            "generate_weekly_report",
            EvidenceStatus.UNKNOWN,
            ComplianceState.BLOCKED,
            "EUR",
            PolicyStatus.APPROVED,
        ),
        (
            "pause_campaign",
            EvidenceStatus.UNKNOWN,
            ComplianceState.BLOCKED,
            "EUR",
            PolicyStatus.APPROVED,
        ),
        (
            "evaluate_opportunity",
            EvidenceStatus.UNKNOWN,
            ComplianceState.ALLOWED,
            "CHF",
            PolicyStatus.INSUFFICIENT_EVIDENCE,
        ),
        (
            "discover_suppliers",
            EvidenceStatus.READY,
            ComplianceState.ALLOWED,
            "EUR",
            PolicyStatus.BUDGET_EXCEEDED,
        ),
        (
            "schedule_campaign",
            EvidenceStatus.READY,
            ComplianceState.UNKNOWN,
            "CHF",
            PolicyStatus.COMPLIANCE_BLOCKED,
        ),
    ],
)
def test_command_relevant_gate_matrix(
    command: str,
    evidence: EvidenceStatus,
    compliance: ComplianceState,
    currency: str,
    expected: PolicyStatus,
) -> None:
    decision = evaluate_policy(
        _request_with_states(
            command, evidence=evidence, compliance=compliance, currency=currency
        ),
        snapshot(),
        NOW,
    )
    assert decision.status is expected


@pytest.mark.parametrize(
    "command", ["pause_campaign", "request_human_review", "generate_weekly_report"]
)
def test_safe_actions_ignore_unrelated_evidence(command: str) -> None:
    req = _request_with_states(
        command,
        evidence=EvidenceStatus.UNKNOWN,
        compliance=ComplianceState.ALLOWED,
        currency="CHF",
    )
    decision = evaluate_policy(req, snapshot(), NOW)
    assert decision.status is PolicyStatus.APPROVED
    assert "insufficient_evidence" not in decision.reason_codes


def test_schedule_campaign_missing_required_claim_is_insufficient_evidence() -> None:
    req = request("schedule_campaign")
    req = req.model_copy(
        update={"evidence": req.evidence.model_copy(update={"claims": ("SIGNAL",)})}
    )
    decision = evaluate_policy(req, snapshot(), NOW)
    assert decision.status is PolicyStatus.INSUFFICIENT_EVIDENCE
    assert "insufficient_evidence" in decision.reason_codes


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"valid_until": NOW}, "evidence_expired"),
        ({"observed_at": NOW + dt.timedelta(seconds=1)}, "evidence_future_dated"),
    ],
)
def test_relevant_evidence_freshness_fails_closed(changes: dict[str, object], reason: str) -> None:
    req = request()
    req = req.model_copy(update={"evidence": req.evidence.model_copy(update=changes)})
    decision = evaluate_policy(req, snapshot(), NOW)
    assert decision.status is PolicyStatus.INSUFFICIENT_EVIDENCE
    assert decision.reason_codes[0] == reason


def test_irrelevant_expired_evidence_does_not_block_reporting() -> None:
    req = request(
        "generate_weekly_report",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
    )
    req = req.model_copy(
        update={
            "evidence": req.evidence.model_copy(
                update={"status": EvidenceStatus.UNKNOWN, "valid_until": NOW}
            )
        }
    )
    decision = evaluate_policy(req, snapshot(), NOW)
    assert decision.status is PolicyStatus.APPROVED
    assert "evidence_expired" not in decision.reason_codes


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"valid_until": NOW}, "compliance_assessment_expired"),
        (
            {"observed_at": NOW + dt.timedelta(seconds=1)},
            "compliance_assessment_future_dated",
        ),
    ],
)
def test_relevant_compliance_freshness_cannot_be_overridden(
    changes: dict[str, object], reason: str
) -> None:
    snap = snapshot()
    req = request("schedule_campaign")
    compliance = req.compliance.model_copy(
        update={"state": ComplianceState.REVIEW_REQUIRED, **changes}
    )
    req = req.model_copy(update={"compliance": compliance})
    approval = grant(ApprovalPurpose.COMPLIANCE_REVIEW, req, snap)
    req = req.model_copy(update={"approval_grants": (approval,)})
    decision = evaluate_policy(req, snap, NOW)
    assert decision.status is PolicyStatus.COMPLIANCE_BLOCKED
    assert decision.reason_codes[0] == reason
    assert decision.approval_refs == ()


def test_irrelevant_compliance_freshness_does_not_block_reporting() -> None:
    req = request(
        "generate_weekly_report",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
    )
    req = req.model_copy(
        update={
            "compliance": req.compliance.model_copy(
                update={"state": ComplianceState.UNKNOWN, "valid_until": NOW}
            )
        }
    )
    assert evaluate_policy(req, snapshot(), NOW).status is PolicyStatus.APPROVED


@pytest.mark.parametrize("command", ["schedule_campaign", "pause_campaign"])
def test_relevant_operational_expiry_fails_closed(command: str) -> None:
    global_command = command == "pause_campaign"
    req = request(
        command,
        acquisition_opportunity_id=None if global_command else "opp-1",
        expected_opportunity_version=None if global_command else 1,
    )
    req = req.model_copy(
        update={"operational": req.operational.model_copy(update={"valid_until": NOW})}
    )
    decision = evaluate_policy(req, snapshot(), NOW)
    assert decision.status is PolicyStatus.RATE_LIMITED
    assert "operational_readiness_expired" in decision.reason_codes
    assert decision.retry_after is None


def test_irrelevant_operational_expiry_does_not_block_reporting() -> None:
    req = request(
        "generate_weekly_report",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
    )
    req = req.model_copy(
        update={"operational": req.operational.model_copy(update={"valid_until": NOW})}
    )
    decision = evaluate_policy(req, snapshot(), NOW)
    assert decision.status is PolicyStatus.APPROVED
    assert "operational_readiness_expired" not in decision.reason_codes
