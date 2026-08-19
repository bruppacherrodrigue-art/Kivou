from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from signals.acquisition.contracts import (
    MAX_EVENT_PAYLOAD_BYTES,
    STATE_MACHINE_VERSION,
    AcquisitionEvent,
    AcquisitionOpportunity,
    AcquisitionState,
    ActorType,
    Decision,
    EventType,
)

NOW = dt.datetime(2026, 8, 19, 12, tzinfo=dt.UTC)


def event_input(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "event_id": "evt-1",
        "acquisition_opportunity_id": "acq-1",
        "stream_sequence": 1,
        "event_type": EventType.OPPORTUNITY_CREATED,
        "schema_version": 1,
        "state_machine_version": STATE_MACHINE_VERSION,
        "occurred_at": NOW,
        "recorded_at": NOW,
        "actor_type": ActorType.SYSTEM,
        "actor_ref": "ingestion-runtime",
        "idempotency_key": "create-1",
        "semantic_fingerprint": "a" * 64,
        "reason_codes": ("source_signal_selected",),
        "evidence_refs": ("signal:s1",),
        "policy_version": None,
        "skill_version": None,
        "supervisor_version": None,
        "confidence": Decimal("0.75"),
        "estimated_cost": Decimal("0.010000"),
        "payload": {"identity_key": "signal:s1", "signal_ref": "s1"},
    }
    values.update(overrides)
    return values


def opportunity_input(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "acquisition_opportunity_id": "acq-1",
        "identity_key": "signal:s1",
        "state": AcquisitionState.DISCOVERED,
        "stream_version": 1,
        "state_machine_version": STATE_MACHINE_VERSION,
        "signal_ref": "s1",
        "supplier_ref": None,
        "contact_ref": None,
        "campaign_ref": None,
        "decision": None,
        "reason_codes": (),
        "confidence": None,
        "evidence_refs": (),
        "next_action": None,
        "next_review_at": None,
        "retry_count": 0,
        "retry_at": None,
        "last_error_category": None,
        "policy_version": None,
        "skill_version": None,
        "supervisor_version": None,
        "estimated_cost": None,
        "last_event_id": "evt-1",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return values


def test_event_and_projection_preserve_the_explicit_state_machine_version() -> None:
    event = AcquisitionEvent.model_validate(event_input())
    opportunity = AcquisitionOpportunity.model_validate(opportunity_input())

    assert event.state_machine_version == "acquisition-state-v1"
    assert opportunity.state_machine_version == "acquisition-state-v1"


@pytest.mark.parametrize("confidence", [Decimal("-0.01"), Decimal("1.01")])
def test_confidence_must_stay_between_zero_and_one(confidence: Decimal) -> None:
    with pytest.raises(ValidationError, match="confidence"):
        AcquisitionEvent.model_validate(event_input(confidence=confidence))


def test_estimated_cost_cannot_be_negative() -> None:
    with pytest.raises(ValidationError, match="estimated_cost"):
        AcquisitionEvent.model_validate(event_input(estimated_cost=Decimal("-0.01")))


@pytest.mark.parametrize(
    "payload",
    [
        {"password": "value"},
        {"nested": {"access_token": "value"}},
        {"list": [{"private-key": "value"}]},
        {"clientSecret": "value"},
    ],
)
def test_event_payload_rejects_credential_keys_recursively(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="prohibited payload key"):
        AcquisitionEvent.model_validate(event_input(payload=payload))


@pytest.mark.parametrize(
    "payload",
    [
        {"chain_of_thought": "private"},
        {"nested": {"reasoning-trace": "private"}},
        {"list": [{"scratchpad": "private"}]},
        {"internalReasoning": "private"},
    ],
)
def test_event_payload_rejects_hidden_reasoning_recursively(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="hidden reasoning"):
        AcquisitionEvent.model_validate(event_input(payload=payload))


def test_event_payload_must_be_finite_json() -> None:
    with pytest.raises(ValidationError, match="finite JSON"):
        AcquisitionEvent.model_validate(event_input(payload={"score": float("nan")}))


def test_event_payload_has_a_serialized_size_limit() -> None:
    payload = {"body": "x" * MAX_EVENT_PAYLOAD_BYTES}

    with pytest.raises(ValidationError, match="payload exceeds"):
        AcquisitionEvent.model_validate(event_input(payload=payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reason_codes", tuple(f"reason-{index}" for index in range(51))),
        ("evidence_refs", tuple(f"evidence-{index}" for index in range(101))),
        ("reason_codes", ("x" * 101,)),
        ("evidence_refs", ("x" * 101,)),
    ],
)
def test_reason_and_evidence_metadata_are_bounded(field: str, value: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        AcquisitionEvent.model_validate(event_input(**{field: value}))


@pytest.mark.parametrize("field", ["occurred_at", "recorded_at"])
def test_event_datetimes_must_be_timezone_aware(field: str) -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        AcquisitionEvent.model_validate(
            event_input(**{field: NOW.replace(tzinfo=None)})
        )


def test_projection_datetimes_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        AcquisitionOpportunity.model_validate(
            opportunity_input(created_at=NOW.replace(tzinfo=None))
        )


def test_contracts_are_immutable_and_reject_unknown_fields() -> None:
    event = AcquisitionEvent.model_validate(event_input())

    with pytest.raises(ValidationError):
        AcquisitionEvent.model_validate(event_input(unexpected="value"))
    with pytest.raises(ValidationError):
        event.payload = {}  # type: ignore[misc]


def test_approved_vocabulary_is_exact() -> None:
    assert {item.value for item in Decision} == {
        "SEND",
        "HOLD",
        "ENRICH",
        "NO_SEND",
        "REVIEW",
    }
    assert AcquisitionState.DISCOVERED.value == "DISCOVERED"
    assert AcquisitionState.CHURNED.value == "CHURNED"
    assert ActorType.HERMES.value == "HERMES"
    assert EventType.SUPERVISOR_PLAN_OBSERVED.value == "SUPERVISOR_PLAN_OBSERVED"
