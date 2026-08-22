from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from signals.acquisition.contracts import (
    STATE_MACHINE_VERSION,
    AcquisitionEvent,
    AcquisitionOpportunity,
    AcquisitionState,
    ActorType,
    Decision,
    EventType,
    InvalidTransition,
    UnsupportedStateMachineVersion,
)
from signals.acquisition.state import DECISION_STATES, TRANSITIONS, reduce_event, replay

NOW = dt.datetime(2026, 8, 19, 12, tzinfo=dt.UTC)


def event(
    event_type: EventType,
    *,
    sequence: int,
    payload: dict[str, object] | None = None,
    state_machine_version: str = STATE_MACHINE_VERSION,
    reason_codes: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
    confidence: Decimal | None = None,
) -> AcquisitionEvent:
    return AcquisitionEvent(
        event_id=f"evt-{sequence}",
        acquisition_opportunity_id="acq-1",
        stream_sequence=sequence,
        event_type=event_type,
        state_machine_version=state_machine_version,
        occurred_at=NOW + dt.timedelta(minutes=sequence),
        recorded_at=NOW + dt.timedelta(minutes=sequence),
        actor_type=ActorType.SYSTEM,
        idempotency_key=f"idem-{sequence}",
        semantic_fingerprint=f"{sequence:064x}",
        reason_codes=reason_codes,
        evidence_refs=evidence_refs,
        confidence=confidence,
        payload={} if payload is None else payload,
    )


def created(*, state_machine_version: str = STATE_MACHINE_VERSION) -> AcquisitionEvent:
    return event(
        EventType.OPPORTUNITY_CREATED,
        sequence=1,
        state_machine_version=state_machine_version,
        payload={
            "identity_key": "signal:s1",
            "signal_ref": "s1",
            "supplier_ref": None,
            "contact_ref": None,
            "campaign_ref": None,
        },
    )


def projection(state: AcquisitionState, *, version: int = 1) -> AcquisitionOpportunity:
    return AcquisitionOpportunity(
        acquisition_opportunity_id="acq-1",
        identity_key="signal:s1",
        state=state,
        stream_version=version,
        state_machine_version=STATE_MACHINE_VERSION,
        signal_ref="s1",
        last_event_id=f"evt-{version}",
        created_at=NOW,
        updated_at=NOW,
    )


def transition(target: AcquisitionState, *, sequence: int = 2) -> AcquisitionEvent:
    return event(
        EventType.STATE_TRANSITIONED,
        sequence=sequence,
        payload={"target_state": target.value},
    )


def outcome(target: AcquisitionState, *, sequence: int) -> AcquisitionEvent:
    return event(
        EventType.OUTCOME_RECORDED,
        sequence=sequence,
        payload={"outcome_state": target.value},
    )


def test_created_event_builds_the_initial_projection() -> None:
    result = replay((created(),))

    assert result.identity_key == "signal:s1"
    assert result.state == AcquisitionState.DISCOVERED
    assert result.stream_version == 1
    assert result.state_machine_version == STATE_MACHINE_VERSION
    assert result.last_event_id == "evt-1"


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source, targets in {
            AcquisitionState.DISCOVERED: {AcquisitionState.ENRICHING},
            AcquisitionState.ENRICHING: {AcquisitionState.READY_FOR_DECISION},
            AcquisitionState.READY_FOR_DECISION: {
                AcquisitionState.ENRICHING,
                AcquisitionState.HOLD,
                AcquisitionState.NO_SEND,
                AcquisitionState.REVIEW,
                AcquisitionState.SEND,
            },
            AcquisitionState.HOLD: {
                AcquisitionState.ENRICHING,
                AcquisitionState.READY_FOR_DECISION,
                AcquisitionState.REVIEW,
                AcquisitionState.NO_SEND,
            },
            AcquisitionState.REVIEW: {
                AcquisitionState.ENRICHING,
                AcquisitionState.HOLD,
                AcquisitionState.READY_FOR_DECISION,
                AcquisitionState.NO_SEND,
                AcquisitionState.SEND,
            },
            AcquisitionState.SEND: {AcquisitionState.QUEUED},
            AcquisitionState.QUEUED: {AcquisitionState.SENT},
        }.items()
        for target in targets
    ],
)
def test_approved_pre_send_transition_matrix(
    source: AcquisitionState, target: AcquisitionState
) -> None:
    current = projection(source)
    change = transition(target)
    if target == AcquisitionState.HOLD:
        change = change.model_copy(
            update={
                "reason_codes": ("awaiting_evidence",),
                "payload": {
                    "target_state": target.value,
                    "next_review_at": (NOW + dt.timedelta(days=1)).isoformat(),
                },
            }
        )

    assert reduce_event(current, change).state == target


def test_direct_discovered_to_ready_for_decision_is_rejected() -> None:
    with pytest.raises(InvalidTransition, match="DISCOVERED.*READY_FOR_DECISION"):
        reduce_event(projection(AcquisitionState.DISCOVERED), transition(AcquisitionState.READY_FOR_DECISION))


@pytest.mark.parametrize(
    ("decision", "target"),
    [
        (Decision.ENRICH, AcquisitionState.ENRICHING),
        (Decision.HOLD, AcquisitionState.HOLD),
        (Decision.NO_SEND, AcquisitionState.NO_SEND),
        (Decision.REVIEW, AcquisitionState.REVIEW),
        (Decision.SEND, AcquisitionState.SEND),
    ],
)
def test_decision_mapping_is_recorded_without_deciding(
    decision: Decision, target: AcquisitionState
) -> None:
    payload: dict[str, object] = {"decision": decision.value}
    reasons = ("approved_decision",)
    if decision == Decision.HOLD:
        payload["next_review_at"] = (NOW + dt.timedelta(days=2)).isoformat()
    decision_event = event(
        EventType.DECISION_RECORDED,
        sequence=2,
        payload=payload,
        reason_codes=reasons,
        confidence=Decimal("0.8"),
    )

    result = reduce_event(projection(AcquisitionState.READY_FOR_DECISION), decision_event)

    assert DECISION_STATES[decision] == target
    assert result.decision == decision
    assert result.state == target
    assert result.confidence == Decimal("0.8")


@pytest.mark.parametrize(
    ("decision", "next_action"),
    (
        (Decision.SEND, "prepare_campaign"),
        (Decision.REVIEW, "request_human_review"),
        (Decision.NO_SEND, None),
    ),
)
def test_spec023_decision_payload_updates_state_and_next_action_atomically(
    decision: Decision, next_action: str | None
) -> None:
    current = projection(AcquisitionState.READY_FOR_DECISION).model_copy(
        update={"next_action": "evaluate_opportunity"}
    )
    change = event(
        EventType.DECISION_RECORDED,
        sequence=2,
        payload={"decision": decision.value, "next_action": next_action},
        reason_codes=("bounded_reason",),
        evidence_refs=("contract-award:award-1",),
    )

    result = reduce_event(current, change)

    assert result.state is DECISION_STATES[decision]
    assert result.next_action == next_action
    assert result.confidence is None


def test_historical_decision_payload_preserves_previous_next_action_semantics() -> None:
    current = projection(AcquisitionState.READY_FOR_DECISION).model_copy(
        update={"next_action": "evaluate_opportunity"}
    )
    historical = event(
        EventType.DECISION_RECORDED,
        sequence=2,
        payload={"decision": Decision.NO_SEND.value},
        reason_codes=("historical",),
    )

    assert reduce_event(current, historical).next_action == "evaluate_opportunity"


def test_send_to_queued_can_bind_campaign_ref_without_new_event_type() -> None:
    current = projection(AcquisitionState.SEND).model_copy(
        update={"decision": Decision.SEND, "next_action": "schedule_campaign"}
    )
    queued = event(
        EventType.STATE_TRANSITIONED,
        sequence=2,
        payload={"target_state": "QUEUED", "campaign_ref": "campaign-ref-1"},
        reason_codes=("CAMPAIGN_MEMBER_QUEUED",),
    )

    result = reduce_event(current, queued)

    assert result.state is AcquisitionState.QUEUED
    assert result.campaign_ref == "campaign-ref-1"
    assert len(EventType) == 9


def test_historical_queued_transition_without_campaign_ref_replays_unchanged() -> None:
    current = projection(AcquisitionState.SEND)
    assert reduce_event(current, transition(AcquisitionState.QUEUED)).campaign_ref is None


def test_campaign_ref_cannot_bind_outside_send_to_queued_or_replace_existing() -> None:
    wrong_transition = event(
        EventType.STATE_TRANSITIONED,
        sequence=2,
        payload={"target_state": "ENRICHING", "campaign_ref": "campaign-ref-1"},
    )
    with pytest.raises(InvalidTransition, match="campaign_ref"):
        reduce_event(projection(AcquisitionState.DISCOVERED), wrong_transition)

    replacement = event(
        EventType.STATE_TRANSITIONED,
        sequence=2,
        payload={"target_state": "QUEUED", "campaign_ref": "campaign-ref-2"},
    )
    with pytest.raises(InvalidTransition, match="campaign_ref"):
        reduce_event(
            projection(AcquisitionState.SEND).model_copy(
                update={"campaign_ref": "campaign-ref-1"}
            ),
            replacement,
        )


def test_next_action_set_can_explicitly_clear_with_a_reason() -> None:
    current = projection(AcquisitionState.SEND).model_copy(
        update={"next_action": "assess_campaign_compliance"}
    )
    clear = event(
        EventType.NEXT_ACTION_SET,
        sequence=2,
        payload={"next_action": None},
        reason_codes=("COMPLIANCE_HARD_BLOCK",),
    )

    result = reduce_event(current, clear)

    assert result.state is AcquisitionState.SEND
    assert result.next_action is None
    assert result.reason_codes == ("COMPLIANCE_HARD_BLOCK",)


def test_next_action_set_rejects_an_unexplained_clear() -> None:
    current = projection(AcquisitionState.SEND).model_copy(
        update={"next_action": "assess_campaign_compliance"}
    )
    clear = event(EventType.NEXT_ACTION_SET, sequence=2, payload={"next_action": None})

    with pytest.raises(InvalidTransition, match="reason"):
        reduce_event(current, clear)


def test_next_action_set_requires_an_explicit_next_action_key() -> None:
    current = projection(AcquisitionState.SEND).model_copy(
        update={"next_action": "assess_campaign_compliance"}
    )
    malformed = event(
        EventType.NEXT_ACTION_SET,
        sequence=2,
        payload={},
        reason_codes=("COMPLIANCE_HARD_BLOCK",),
    )

    with pytest.raises(InvalidTransition, match="next_action"):
        reduce_event(current, malformed)


def test_next_action_set_keeps_existing_string_validation() -> None:
    current = projection(AcquisitionState.SEND)
    valid = event(
        EventType.NEXT_ACTION_SET,
        sequence=2,
        payload={"next_action": "assess_campaign_compliance"},
    )
    unknown = event(
        EventType.NEXT_ACTION_SET,
        sequence=2,
        payload={"next_action": "invented_compliance_action"},
    )

    assert reduce_event(current, valid).next_action == "assess_campaign_compliance"
    with pytest.raises(InvalidTransition, match="unknown next_action"):
        reduce_event(current, unknown)


@pytest.mark.parametrize(
    "payload",
    (
        {"decision": "SEND", "next_action": "request_human_review"},
        {"decision": "REVIEW", "next_action": None},
        {"decision": "NO_SEND", "next_action": "prepare_campaign"},
        {"decision": "HOLD", "next_action": None},
        {"decision": "ENRICH", "next_action": "enrich_company"},
        {"decision": "SEND", "next_action": "prepare_campaign", "score": 100},
        {
            "decision": "SEND",
            "next_action": "prepare_campaign",
            "next_review_at": (NOW + dt.timedelta(days=1)).isoformat(),
        },
    ),
)
def test_spec023_decision_payload_fails_closed(payload: dict[str, object]) -> None:
    change = event(
        EventType.DECISION_RECORDED,
        sequence=2,
        payload=payload,
        reason_codes=("bounded_reason",),
        evidence_refs=("contract-award:award-1",),
    )

    with pytest.raises(InvalidTransition):
        reduce_event(projection(AcquisitionState.READY_FOR_DECISION), change)


@pytest.mark.parametrize(
    ("reason_codes", "evidence_refs", "confidence"),
    (
        ((), ("contract-award:award-1",), None),
        (("bounded_reason",), (), None),
        (("bounded_reason",), ("contract-award:award-1",), Decimal("0.9")),
    ),
)
def test_spec023_decision_requires_structured_evidence_without_fake_confidence(
    reason_codes: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    confidence: Decimal | None,
) -> None:
    change = event(
        EventType.DECISION_RECORDED,
        sequence=2,
        payload={"decision": "SEND", "next_action": "prepare_campaign"},
        reason_codes=reason_codes,
        evidence_refs=evidence_refs,
        confidence=confidence,
    )

    with pytest.raises(InvalidTransition):
        reduce_event(projection(AcquisitionState.READY_FOR_DECISION), change)


@pytest.mark.parametrize(
    ("reason_codes", "next_review_at"),
    [
        ((), (NOW + dt.timedelta(days=1)).isoformat()),
        (("awaiting_data",), None),
    ],
)
def test_hold_requires_reasons_and_a_review_time(
    reason_codes: tuple[str, ...], next_review_at: str | None
) -> None:
    payload = {"decision": Decision.HOLD.value, "next_review_at": next_review_at}
    hold = event(
        EventType.DECISION_RECORDED,
        sequence=2,
        payload=payload,
        reason_codes=reason_codes,
    )

    with pytest.raises(InvalidTransition, match="HOLD"):
        reduce_event(projection(AcquisitionState.READY_FOR_DECISION), hold)


def test_no_send_cannot_reenter_the_send_workflow() -> None:
    with pytest.raises(InvalidTransition, match="NO_SEND"):
        reduce_event(projection(AcquisitionState.NO_SEND), transition(AcquisitionState.SEND))


def test_sent_can_advance_directly_to_activated_and_late_reply_does_not_regress() -> None:
    activated = reduce_event(
        projection(AcquisitionState.SENT), outcome(AcquisitionState.ACTIVATED, sequence=2)
    )
    late_reply = reduce_event(
        activated, outcome(AcquisitionState.REPLIED, sequence=3)
    )

    assert activated.state == AcquisitionState.ACTIVATED
    assert late_reply.state == AcquisitionState.ACTIVATED
    assert late_reply.stream_version == 3
    assert late_reply.last_event_id == "evt-3"


def test_activated_can_advance_to_paid() -> None:
    result = reduce_event(
        projection(AcquisitionState.ACTIVATED), outcome(AcquisitionState.PAID, sequence=2)
    )
    assert result.state == AcquisitionState.PAID


def test_churned_rejects_a_new_forward_transition() -> None:
    with pytest.raises(InvalidTransition, match="CHURNED"):
        reduce_event(projection(AcquisitionState.CHURNED), transition(AcquisitionState.SEND))


def test_state_neutral_audit_advances_only_stream_metadata() -> None:
    current = projection(AcquisitionState.NO_SEND)
    audit = event(
        EventType.SUPERVISOR_PLAN_OBSERVED,
        sequence=2,
        payload={"plan_id": "plan-1", "actions": []},
    )

    result = reduce_event(current, audit)

    assert result.state == AcquisitionState.NO_SEND
    assert result.stream_version == 2
    assert result.last_event_id == "evt-2"


def test_next_action_and_retry_metadata_reduce_deterministically() -> None:
    current = projection(AcquisitionState.ENRICHING)
    action = event(
        EventType.NEXT_ACTION_SET,
        sequence=2,
        payload={"next_action": "enrich_company"},
    )
    retry_at = NOW + dt.timedelta(hours=2)
    retry = event(
        EventType.RETRY_SCHEDULED,
        sequence=3,
        payload={
            "retry_at": retry_at.isoformat(),
            "error_category": "provider_timeout",
        },
        reason_codes=("transient_provider_failure",),
    )

    with_action = reduce_event(current, action)
    result = reduce_event(with_action, retry)

    assert with_action.next_action == "enrich_company"
    assert result.state == AcquisitionState.ENRICHING
    assert result.retry_count == 1
    assert result.retry_at == retry_at
    assert result.last_error_category == "provider_timeout"


def test_unknown_next_action_fails_closed() -> None:
    unknown = event(
        EventType.NEXT_ACTION_SET,
        sequence=2,
        payload={"next_action": "run_arbitrary_shell"},
    )

    with pytest.raises(InvalidTransition, match="unknown next_action"):
        reduce_event(projection(AcquisitionState.DISCOVERED), unknown)


def test_replay_rejects_an_unknown_historical_reducer_version() -> None:
    with pytest.raises(UnsupportedStateMachineVersion, match="unknown-reducer"):
        replay((created(state_machine_version="unknown-reducer"),))


def test_replay_requires_contiguous_sequence_numbers() -> None:
    gap = transition(AcquisitionState.ENRICHING, sequence=3)

    with pytest.raises(InvalidTransition, match="sequence"):
        replay((created(), gap))


def test_reducer_does_not_mutate_the_input_projection() -> None:
    current = projection(AcquisitionState.DISCOVERED)

    result = reduce_event(current, transition(AcquisitionState.ENRICHING))

    assert current.state == AcquisitionState.DISCOVERED
    assert current.stream_version == 1
    assert result.state == AcquisitionState.ENRICHING
    assert TRANSITIONS[AcquisitionState.DISCOVERED] == frozenset(
        {AcquisitionState.ENRICHING}
    )
