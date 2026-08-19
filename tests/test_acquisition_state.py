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
