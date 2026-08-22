"""Pure, version-selected Acquisition Opportunity state reduction."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable
from typing import Any

from signals.acquisition.contracts import (
    STATE_MACHINE_VERSION,
    AcquisitionEvent,
    AcquisitionOpportunity,
    AcquisitionState,
    Decision,
    EventType,
    InvalidTransition,
    UnsupportedStateMachineVersion,
)
from signals.supervisor.registry import ALLOWED_NEXT_ACTIONS

TRANSITIONS: dict[AcquisitionState, frozenset[AcquisitionState]] = {
    AcquisitionState.DISCOVERED: frozenset({AcquisitionState.ENRICHING}),
    AcquisitionState.ENRICHING: frozenset({AcquisitionState.READY_FOR_DECISION}),
    AcquisitionState.READY_FOR_DECISION: frozenset(
        {
            AcquisitionState.ENRICHING,
            AcquisitionState.HOLD,
            AcquisitionState.NO_SEND,
            AcquisitionState.REVIEW,
            AcquisitionState.SEND,
        }
    ),
    AcquisitionState.HOLD: frozenset(
        {
            AcquisitionState.ENRICHING,
            AcquisitionState.READY_FOR_DECISION,
            AcquisitionState.REVIEW,
            AcquisitionState.NO_SEND,
        }
    ),
    AcquisitionState.REVIEW: frozenset(
        {
            AcquisitionState.ENRICHING,
            AcquisitionState.HOLD,
            AcquisitionState.READY_FOR_DECISION,
            AcquisitionState.NO_SEND,
            AcquisitionState.SEND,
        }
    ),
    AcquisitionState.SEND: frozenset({AcquisitionState.QUEUED}),
    AcquisitionState.QUEUED: frozenset({AcquisitionState.SENT}),
}

DECISION_STATES: dict[Decision, AcquisitionState] = {
    Decision.ENRICH: AcquisitionState.ENRICHING,
    Decision.HOLD: AcquisitionState.HOLD,
    Decision.NO_SEND: AcquisitionState.NO_SEND,
    Decision.REVIEW: AcquisitionState.REVIEW,
    Decision.SEND: AcquisitionState.SEND,
}

_OUTCOME_RANK: dict[AcquisitionState, int] = {
    AcquisitionState.SEND: 0,
    AcquisitionState.QUEUED: 1,
    AcquisitionState.SENT: 2,
    AcquisitionState.REPLIED: 3,
    AcquisitionState.ACTIVATED: 4,
    AcquisitionState.PAID: 5,
    AcquisitionState.RETAINED: 6,
    AcquisitionState.CHURNED: 7,
}


def _datetime_payload(payload: dict[str, Any], key: str) -> dt.datetime | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidTransition(f"{key} must be an ISO-8601 datetime")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidTransition(f"{key} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidTransition(f"{key} must be timezone-aware")
    return parsed


def _common_updates(event: AcquisitionEvent) -> dict[str, object]:
    updates: dict[str, object] = {
        "stream_version": event.stream_sequence,
        "state_machine_version": event.state_machine_version,
        "last_event_id": event.event_id,
        "updated_at": event.recorded_at,
    }
    for field in (
        "policy_version",
        "skill_version",
        "supervisor_version",
        "estimated_cost",
    ):
        value = getattr(event, field)
        if value is not None:
            updates[field] = value
    return updates


def _require_transition(source: AcquisitionState, target: AcquisitionState) -> None:
    if target not in TRANSITIONS.get(source, frozenset()):
        raise InvalidTransition(f"invalid transition: {source.value} -> {target.value}")


def _require_hold_metadata(event: AcquisitionEvent, next_review_at: dt.datetime | None) -> None:
    if not event.reason_codes or next_review_at is None:
        raise InvalidTransition("HOLD requires reason codes and next_review_at")


def _created(event: AcquisitionEvent) -> AcquisitionOpportunity:
    if event.stream_sequence != 1:
        raise InvalidTransition("OPPORTUNITY_CREATED must have sequence 1")
    identity_key = event.payload.get("identity_key")
    signal_ref = event.payload.get("signal_ref")
    if not isinstance(identity_key, str) or not isinstance(signal_ref, str):
        raise InvalidTransition("OPPORTUNITY_CREATED requires identity_key and signal_ref")
    return AcquisitionOpportunity(
        acquisition_opportunity_id=event.acquisition_opportunity_id,
        identity_key=identity_key,
        state=AcquisitionState.DISCOVERED,
        stream_version=1,
        state_machine_version=event.state_machine_version,
        signal_ref=signal_ref,
        supplier_ref=event.payload.get("supplier_ref"),
        contact_ref=event.payload.get("contact_ref"),
        campaign_ref=event.payload.get("campaign_ref"),
        reason_codes=event.reason_codes,
        confidence=event.confidence,
        evidence_refs=event.evidence_refs,
        policy_version=event.policy_version,
        skill_version=event.skill_version,
        supervisor_version=event.supervisor_version,
        estimated_cost=event.estimated_cost,
        last_event_id=event.event_id,
        created_at=event.recorded_at,
        updated_at=event.recorded_at,
    )


def _transitioned(
    current: AcquisitionOpportunity, event: AcquisitionEvent
) -> AcquisitionOpportunity:
    try:
        target = AcquisitionState(event.payload.get("target_state"))
    except (TypeError, ValueError) as exc:
        raise InvalidTransition("STATE_TRANSITIONED requires a known target_state") from exc
    _require_transition(current.state, target)
    next_review_at = _datetime_payload(event.payload, "next_review_at")
    if target == AcquisitionState.HOLD:
        _require_hold_metadata(event, next_review_at)
    if "campaign_ref" in event.payload:
        campaign_ref = event.payload.get("campaign_ref")
        if (
            current.state is not AcquisitionState.SEND
            or target is not AcquisitionState.QUEUED
            or current.campaign_ref is not None
            or not isinstance(campaign_ref, str)
            or not 1 <= len(campaign_ref) <= 256
            or campaign_ref.strip() != campaign_ref
            or not event.reason_codes
        ):
            raise InvalidTransition(
                "campaign_ref may bind once on a reasoned SEND -> QUEUED transition"
            )
    updates = _common_updates(event)
    updates["state"] = target
    if event.reason_codes:
        updates["reason_codes"] = event.reason_codes
    if event.evidence_refs:
        updates["evidence_refs"] = event.evidence_refs
    if event.confidence is not None:
        updates["confidence"] = event.confidence
    if next_review_at is not None:
        updates["next_review_at"] = next_review_at
    if "campaign_ref" in event.payload:
        updates["campaign_ref"] = event.payload["campaign_ref"]
    return current.model_copy(update=updates)


def _decision_recorded(
    current: AcquisitionOpportunity, event: AcquisitionEvent
) -> AcquisitionOpportunity:
    try:
        decision = Decision(event.payload.get("decision"))
    except (TypeError, ValueError) as exc:
        raise InvalidTransition("DECISION_RECORDED requires a known decision") from exc
    target = DECISION_STATES[decision]
    _require_transition(current.state, target)
    is_spec023 = "next_action" in event.payload
    if is_spec023:
        allowed_keys = {"decision", "next_action", "next_review_at"}
        if set(event.payload) - allowed_keys:
            raise InvalidTransition("SPEC-023 DECISION_RECORDED has unexpected payload keys")
        expected_actions = {
            Decision.SEND: "prepare_campaign",
            Decision.REVIEW: "request_human_review",
            Decision.NO_SEND: None,
        }
        if decision not in expected_actions:
            raise InvalidTransition("decision-policy-v1 cannot emit HOLD or ENRICH")
        if event.payload.get("next_action") != expected_actions[decision]:
            raise InvalidTransition("decision-policy-v1 next_action does not match decision")
        if event.payload.get("next_review_at") is not None:
            raise InvalidTransition("decision-policy-v1 cannot schedule a review")
        if not event.reason_codes or not event.evidence_refs:
            raise InvalidTransition("SPEC-023 decision requires reasons and evidence")
        if event.confidence is not None:
            raise InvalidTransition("decision-policy-v1 has no numeric confidence")
    next_review_at = _datetime_payload(event.payload, "next_review_at")
    if decision == Decision.HOLD:
        _require_hold_metadata(event, next_review_at)
    updates = _common_updates(event)
    updates.update(
        {
            "decision": decision,
            "state": target,
            "reason_codes": event.reason_codes,
            "evidence_refs": event.evidence_refs,
            "confidence": event.confidence,
            "next_review_at": next_review_at,
        }
    )
    if is_spec023:
        updates["next_action"] = event.payload.get("next_action")
    return current.model_copy(update=updates)


def _outcome_recorded(
    current: AcquisitionOpportunity, event: AcquisitionEvent
) -> AcquisitionOpportunity:
    try:
        target = AcquisitionState(event.payload.get("outcome_state"))
    except (TypeError, ValueError) as exc:
        raise InvalidTransition("OUTCOME_RECORDED requires a known outcome_state") from exc
    if current.state not in _OUTCOME_RANK or target not in _OUTCOME_RANK:
        raise InvalidTransition(
            f"invalid outcome transition: {current.state.value} -> {target.value}"
        )
    updates = _common_updates(event)
    if _OUTCOME_RANK[target] > _OUTCOME_RANK[current.state]:
        updates["state"] = target
    if event.reason_codes:
        updates["reason_codes"] = event.reason_codes
    if event.evidence_refs:
        updates["evidence_refs"] = event.evidence_refs
    return current.model_copy(update=updates)


def _next_action_set(
    current: AcquisitionOpportunity, event: AcquisitionEvent
) -> AcquisitionOpportunity:
    if "next_action" not in event.payload:
        raise InvalidTransition("next_action is required")
    next_action = event.payload.get("next_action")
    if next_action is None:
        if not event.reason_codes:
            raise InvalidTransition("clearing next_action requires a reason")
    elif not isinstance(next_action, str) or next_action not in ALLOWED_NEXT_ACTIONS:
        raise InvalidTransition("unknown next_action")
    updates = _common_updates(event)
    updates["next_action"] = next_action
    if next_action is None:
        updates["reason_codes"] = event.reason_codes
    return current.model_copy(update=updates)


def _retry_scheduled(
    current: AcquisitionOpportunity, event: AcquisitionEvent
) -> AcquisitionOpportunity:
    retry_at = _datetime_payload(event.payload, "retry_at")
    error_category = event.payload.get("error_category")
    if retry_at is None or not isinstance(error_category, str) or not error_category.strip():
        raise InvalidTransition("RETRY_SCHEDULED requires retry_at and error_category")
    updates = _common_updates(event)
    updates.update(
        {
            "retry_count": current.retry_count + 1,
            "retry_at": retry_at,
            "last_error_category": error_category,
        }
    )
    if event.reason_codes:
        updates["reason_codes"] = event.reason_codes
    return current.model_copy(update=updates)


def _contact_selected(
    current: AcquisitionOpportunity, event: AcquisitionEvent
) -> AcquisitionOpportunity:
    if set(event.payload) != {"contact_ref", "supplier_ref"}:
        raise InvalidTransition("CONTACT_SELECTED accepts only reference fields")
    contact_ref = event.payload.get("contact_ref")
    supplier_ref = event.payload.get("supplier_ref")
    if current.state is not AcquisitionState.DISCOVERED:
        raise InvalidTransition("CONTACT_SELECTED requires DISCOVERED state")
    if (
        not current.supplier_ref
        or not isinstance(supplier_ref, str)
        or not 1 <= len(supplier_ref) <= 256
        or supplier_ref.strip() != supplier_ref
    ):
        raise InvalidTransition("CONTACT_SELECTED requires supplier_ref")
    if supplier_ref != current.supplier_ref:
        raise InvalidTransition("CONTACT_SELECTED supplier_ref mismatch")
    if current.contact_ref is not None:
        raise InvalidTransition("CONTACT_SELECTED cannot replace contact_ref")
    if (
        not isinstance(contact_ref, str)
        or not 1 <= len(contact_ref) <= 256
        or contact_ref.strip() != contact_ref
    ):
        raise InvalidTransition("CONTACT_SELECTED requires contact_ref")
    updates = _common_updates(event)
    updates["contact_ref"] = contact_ref
    return current.model_copy(update=updates)


def _reduce_v1(
    current: AcquisitionOpportunity | None, event: AcquisitionEvent
) -> AcquisitionOpportunity:
    if current is None:
        if event.event_type != EventType.OPPORTUNITY_CREATED:
            raise InvalidTransition("the first event must be OPPORTUNITY_CREATED")
        return _created(event)
    if event.acquisition_opportunity_id != current.acquisition_opportunity_id:
        raise InvalidTransition("event belongs to a different acquisition opportunity")
    if event.stream_sequence != current.stream_version + 1:
        raise InvalidTransition(
            f"event sequence {event.stream_sequence} does not follow {current.stream_version}"
        )
    if event.event_type == EventType.STATE_TRANSITIONED:
        return _transitioned(current, event)
    if event.event_type == EventType.DECISION_RECORDED:
        return _decision_recorded(current, event)
    if event.event_type == EventType.OUTCOME_RECORDED:
        return _outcome_recorded(current, event)
    if event.event_type == EventType.NEXT_ACTION_SET:
        return _next_action_set(current, event)
    if event.event_type == EventType.RETRY_SCHEDULED:
        return _retry_scheduled(current, event)
    if event.event_type == EventType.CONTACT_SELECTED:
        return _contact_selected(current, event)
    if event.event_type in {
        EventType.SUPERVISOR_PLAN_OBSERVED,
        EventType.POLICY_EVALUATED,
    }:
        return current.model_copy(update=_common_updates(event))
    raise InvalidTransition(f"unsupported event type: {event.event_type.value}")


Reducer = Callable[[AcquisitionOpportunity | None, AcquisitionEvent], AcquisitionOpportunity]
REDUCERS: dict[str, Reducer] = {STATE_MACHINE_VERSION: _reduce_v1}


def reduce_event(
    current: AcquisitionOpportunity | None, event: AcquisitionEvent
) -> AcquisitionOpportunity:
    reducer = REDUCERS.get(event.state_machine_version)
    if reducer is None:
        raise UnsupportedStateMachineVersion(event.state_machine_version)
    return reducer(current, event)


def replay(events: Iterable[AcquisitionEvent]) -> AcquisitionOpportunity:
    current: AcquisitionOpportunity | None = None
    for event in events:
        current = reduce_event(current, event)
    if current is None:
        raise InvalidTransition("cannot replay an empty acquisition event stream")
    return current
