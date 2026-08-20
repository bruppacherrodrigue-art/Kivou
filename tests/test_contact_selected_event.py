from __future__ import annotations

import datetime as dt

import pytest

from signals.acquisition.contracts import (
    AcquisitionEvent,
    AcquisitionState,
    ActorType,
    EventType,
    InvalidTransition,
)
from signals.acquisition.state import reduce_event, replay

NOW = dt.datetime(2026, 8, 20, 11, tzinfo=dt.UTC)


def _event(
    event_type: EventType,
    sequence: int,
    payload: dict[str, object],
) -> AcquisitionEvent:
    return AcquisitionEvent(
        event_id=f"evt-{sequence}",
        acquisition_opportunity_id="ao-1",
        stream_sequence=sequence,
        event_type=event_type,
        occurred_at=NOW + dt.timedelta(minutes=sequence),
        recorded_at=NOW + dt.timedelta(minutes=sequence),
        actor_type=ActorType.SYSTEM,
        actor_ref="kivou-contact-discovery",
        idempotency_key=f"idem-{sequence}",
        semantic_fingerprint=f"{sequence:064x}",
        payload=payload,
    )


def _created(*, supplier_ref: str | None = "supplier-1") -> AcquisitionEvent:
    return _event(
        EventType.OPPORTUNITY_CREATED,
        1,
        {
            "identity_key": "seed:supplier-1",
            "signal_ref": "procurement-opportunity:opp-1",
            "supplier_ref": supplier_ref,
            "contact_ref": None,
            "campaign_ref": None,
        },
    )


def _selected(sequence: int = 2, *, supplier_ref: str = "supplier-1") -> AcquisitionEvent:
    return _event(
        EventType.CONTACT_SELECTED,
        sequence,
        {"contact_ref": "contact-1", "supplier_ref": supplier_ref},
    )


def test_contact_selected_mutates_only_contact_and_common_stream_metadata() -> None:
    current = replay((_created(),))

    result = reduce_event(current, _selected())

    assert result.contact_ref == "contact-1"
    assert result.stream_version == 2
    assert result.last_event_id == "evt-2"
    assert result.state == AcquisitionState.DISCOVERED
    assert result.supplier_ref == "supplier-1"
    assert result.campaign_ref is None
    assert result.decision is None
    assert result.retry_count == 0
    assert result.next_action is None


@pytest.mark.parametrize(
    ("current_events", "selection", "message"),
    [
        (
            (
                _created(),
                _event(
                    EventType.STATE_TRANSITIONED,
                    2,
                    {"target_state": AcquisitionState.ENRICHING.value},
                ),
            ),
            _selected(3),
            "DISCOVERED",
        ),
        ((_created(supplier_ref=None),), _selected(), "supplier_ref"),
        ((_created(),), _selected(supplier_ref="supplier-2"), "supplier_ref"),
    ],
)
def test_contact_selected_rejects_invalid_source_or_supplier(
    current_events: tuple[AcquisitionEvent, ...],
    selection: AcquisitionEvent,
    message: str,
) -> None:
    with pytest.raises(InvalidTransition, match=message):
        reduce_event(replay(current_events), selection)


def test_contact_selected_cannot_replace_existing_contact() -> None:
    selected = replay((_created(), _selected()))
    replacement = _event(
        EventType.CONTACT_SELECTED,
        3,
        {"contact_ref": "contact-2", "supplier_ref": "supplier-1"},
    )

    with pytest.raises(InvalidTransition, match="contact_ref"):
        reduce_event(selected, replacement)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "contact_ref": "contact-1",
            "supplier_ref": "supplier-1",
            "business_email": "must-not-enter-event@example.test",
        },
        {"contact_ref": "x" * 257, "supplier_ref": "supplier-1"},
        {"contact_ref": "contact-1", "supplier_ref": "x" * 257},
    ],
)
def test_contact_selected_accepts_only_two_bounded_reference_fields(payload) -> None:
    event = _event(EventType.CONTACT_SELECTED, 2, payload)

    with pytest.raises(InvalidTransition):
        reduce_event(replay((_created(),)), event)


def test_pre_spec021_stream_replays_to_identical_historical_projection() -> None:
    old_stream = (
        _created(),
        _event(EventType.NEXT_ACTION_SET, 2, {"next_action": "find_decision_makers"}),
    )

    projection = replay(old_stream)

    assert projection.model_dump(mode="json") == {
        "acquisition_opportunity_id": "ao-1",
        "identity_key": "seed:supplier-1",
        "state": "DISCOVERED",
        "stream_version": 2,
        "state_machine_version": "acquisition-state-v1",
        "signal_ref": "procurement-opportunity:opp-1",
        "supplier_ref": "supplier-1",
        "contact_ref": None,
        "campaign_ref": None,
        "decision": None,
        "reason_codes": [],
        "confidence": None,
        "evidence_refs": [],
        "next_action": "find_decision_makers",
        "next_review_at": None,
        "retry_count": 0,
        "retry_at": None,
        "last_error_category": None,
        "policy_version": None,
        "skill_version": None,
        "supervisor_version": None,
        "estimated_cost": None,
        "last_event_id": "evt-2",
        "created_at": "2026-08-20T11:01:00Z",
        "updated_at": "2026-08-20T11:02:00Z",
    }
