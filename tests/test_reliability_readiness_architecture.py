from __future__ import annotations

import datetime as dt

from signals.acquisition.contracts import STATE_MACHINE_VERSION, AcquisitionState, EventType
from signals.operations.contracts import GateStatus
from signals.operations.evidence import (
    ClosedLoopIntegrityFacts,
    ShadowEvidenceFacts,
    evaluate_closed_loop_integrity,
    evaluate_shadow_evidence,
)
from signals.persistence.schema import (
    acquisition_conversion_event,
    acquisition_conversion_journey,
    acquisition_provider_event,
    acquisition_response_evaluation,
)
from signals.policy.registry import COMMAND_POLICIES
from signals.supervisor.registry import ALLOWED_COMMANDS

NOW = dt.datetime(2026, 8, 23, 12, tzinfo=dt.UTC)


def test_h_c_every_hermes_command_has_one_policy_profile_and_no_scale_alias() -> None:
    assert set(ALLOWED_COMMANDS) == set(COMMAND_POLICIES)
    assert "reallocate_volume" in ALLOWED_COMMANDS
    assert not {
        "optimize_wedge",
        "scale_campaign",
        "increase_volume",
        "apply_learning",
    }.intersection(ALLOWED_COMMANDS)


def test_h_d_never_invents_missing_human_review_truth() -> None:
    insufficient = evaluate_shadow_evidence(
        ShadowEvidenceFacts(
            observed_at=NOW,
            shadow_decision_count=10,
            human_review_count=0,
            agreement_count=0,
            disagreement_count=0,
            outcome_refs=(),
        )
    )
    assert insufficient.status is GateStatus.INSUFFICIENT_EVIDENCE
    assert "HUMAN_REVIEW_TRUTH_UNAVAILABLE" in insufficient.reason_codes

    ready = evaluate_shadow_evidence(
        ShadowEvidenceFacts(
            observed_at=NOW,
            shadow_decision_count=10,
            human_review_count=10,
            agreement_count=8,
            disagreement_count=2,
            outcome_refs=("outcome-ref-1",),
        )
    )
    assert ready.status is GateStatus.READY


def test_h_f_checks_orphans_not_impossible_hundred_percent_conversion() -> None:
    no_outcomes = evaluate_closed_loop_integrity(
        ClosedLoopIntegrityFacts(
            observed_at=NOW,
            sent_member_count=100,
            response_count=0,
            click_count=0,
            journey_count=0,
            conversion_event_count=0,
            orphan_response_count=0,
            orphan_click_count=0,
            orphan_journey_count=0,
            orphan_conversion_event_count=0,
        )
    )
    assert no_outcomes.status is GateStatus.READY

    orphaned = evaluate_closed_loop_integrity(
        ClosedLoopIntegrityFacts(
            observed_at=NOW,
            sent_member_count=1,
            response_count=1,
            click_count=0,
            journey_count=0,
            conversion_event_count=0,
            orphan_response_count=1,
            orphan_click_count=0,
            orphan_journey_count=0,
            orphan_conversion_event_count=0,
        )
    )
    assert orphaned.status is GateStatus.NOT_READY


def test_closed_loop_tables_keep_exact_identity_foreign_keys() -> None:
    response_fks = {
        fk.parent.name: fk.target_fullname.rsplit(".", 1)[0]
        for fk in acquisition_response_evaluation.foreign_keys
    }
    journey_fks = {
        fk.parent.name: fk.target_fullname.rsplit(".", 1)[0]
        for fk in acquisition_conversion_journey.foreign_keys
    }
    conversion_fks = {
        fk.parent.name: fk.target_fullname.rsplit(".", 1)[0]
        for fk in acquisition_conversion_event.foreign_keys
    }
    provider_fks = {
        fk.parent.name: fk.target_fullname.rsplit(".", 1)[0]
        for fk in acquisition_provider_event.foreign_keys
    }
    assert response_fks["provider_event_ref"] == "acquisition_provider_event"
    assert response_fks["member_ref"] == "acquisition_campaign_member"
    assert journey_fks["member_ref"] == "acquisition_campaign_member"
    assert conversion_fks["journey_ref"] == "acquisition_conversion_journey"
    assert provider_fks["member_ref"] == "acquisition_campaign_member"


def test_state_machine_and_event_type_are_frozen() -> None:
    assert STATE_MACHINE_VERSION == "acquisition-state-v1"
    assert {item.value for item in AcquisitionState} == {
        "DISCOVERED",
        "ENRICHING",
        "READY_FOR_DECISION",
        "HOLD",
        "NO_SEND",
        "REVIEW",
        "SEND",
        "QUEUED",
        "SENT",
        "REPLIED",
        "ACTIVATED",
        "PAID",
        "RETAINED",
        "CHURNED",
    }
    assert {item.value for item in EventType} == {
        "OPPORTUNITY_CREATED",
        "STATE_TRANSITIONED",
        "DECISION_RECORDED",
        "NEXT_ACTION_SET",
        "RETRY_SCHEDULED",
        "SUPERVISOR_PLAN_OBSERVED",
        "POLICY_EVALUATED",
        "CONTACT_SELECTED",
        "OUTCOME_RECORDED",
    }
