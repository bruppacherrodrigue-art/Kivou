from __future__ import annotations

import datetime as dt

from signals.acquisition.contracts import (
    STATE_MACHINE_VERSION,
    AcquisitionEvent,
    AcquisitionOpportunity,
    AcquisitionState,
    ActorType,
    EventType,
)
from signals.acquisition.state import reduce_event

NOW = dt.datetime(2026, 8, 20, tzinfo=dt.UTC)


def test_policy_evaluated_is_backward_compatible_state_neutral_audit() -> None:
    before = AcquisitionOpportunity(
        acquisition_opportunity_id="opp-1",
        identity_key="identity-1",
        state=AcquisitionState.READY_FOR_DECISION,
        stream_version=2,
        state_machine_version=STATE_MACHINE_VERSION,
        signal_ref="signal-1",
        last_event_id="event-2",
        created_at=NOW,
        updated_at=NOW,
    )
    audit = AcquisitionEvent(
        event_id="event-3",
        acquisition_opportunity_id="opp-1",
        stream_sequence=3,
        event_type=EventType.POLICY_EVALUATED,
        state_machine_version=STATE_MACHINE_VERSION,
        occurred_at=NOW,
        recorded_at=NOW,
        actor_type=ActorType.SYSTEM,
        idempotency_key="policy_evaluation:eval-1",
        semantic_fingerprint="a" * 64,
        payload={"evaluation_id": "eval-1", "status": "DENIED"},
    )
    after = reduce_event(before, audit)
    assert after.state == before.state
    assert after.decision == before.decision
    assert after.retry_count == before.retry_count
    assert after.signal_ref == before.signal_ref
    assert after.stream_version == before.stream_version + 1
