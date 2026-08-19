from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command

from signals.acquisition.contracts import (
    AcquisitionIdentityConflict,
    AcquisitionState,
    Decision,
    IdempotencyConflict,
    InvalidTransition,
    OpportunityConcurrencyConflict,
    ProjectionVerification,
)
from signals.acquisition.store import AcquisitionStore
from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import acquisition_event, acquisition_opportunity

NOW = dt.datetime(2026, 8, 19, 12, tzinfo=dt.UTC)


@pytest.fixture
def engine(tmp_path):
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'acquisition.db'}")
    command.upgrade(alembic_config(value), "head")
    return value


@pytest.fixture
def store(engine):
    opportunity_ids = iter(["opp-1", "opp-2", "opp-3"])
    event_ids = iter(f"event-{index}" for index in range(1, 30))
    return AcquisitionStore(
        engine,
        clock=lambda: NOW,
        opportunity_id_factory=lambda: next(opportunity_ids),
        event_id_factory=lambda: next(event_ids),
    )


def test_creation_is_atomic_and_persists_event_and_projection(engine, store):
    result = store.create_opportunity(
        identity_key="signal:sig-1:supplier:pending",
        signal_ref="sig-1",
        idempotency_key="create-1",
        reason_codes=("source_signal",),
        evidence_refs=("evidence-1",),
        confidence=Decimal("0.70"),
        estimated_cost=Decimal("1.25"),
    )

    assert result.replayed is False
    assert result.projection.state == AcquisitionState.DISCOVERED
    assert result.projection.stream_version == 1
    assert result.event.stream_sequence == 1
    assert store.get_opportunity("opp-1") == result.projection
    assert store.list_events("opp-1") == [result.event]
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_event)) == 1
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_opportunity)
        ) == 1


def test_creation_idempotency_and_immutable_identity(store):
    first = store.create_opportunity(
        identity_key="identity-1",
        signal_ref="signal-1",
        idempotency_key="create-1",
    )
    replayed = store.create_opportunity(
        identity_key="identity-1",
        signal_ref="signal-1",
        idempotency_key="create-1",
    )

    assert replayed.replayed is True
    assert replayed.projection == first.projection
    assert len(store.list_events("opp-1")) == 1

    with pytest.raises(IdempotencyConflict):
        store.create_opportunity(
            identity_key="identity-1",
            signal_ref="different-signal",
            idempotency_key="create-1",
        )
    with pytest.raises(AcquisitionIdentityConflict):
        store.create_opportunity(
            identity_key="identity-1",
            signal_ref="signal-1",
            idempotency_key="different-create-key",
        )


def test_idempotency_is_scoped_to_one_opportunity(store):
    first = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="shared"
    )
    second = store.create_opportunity(
        identity_key="identity-2", signal_ref="signal-2", idempotency_key="shared"
    )

    transitioned_first = store.transition_state(
        first.projection.acquisition_opportunity_id,
        target_state=AcquisitionState.ENRICHING,
        expected_version=1,
        idempotency_key="transition-shared",
    )
    transitioned_second = store.transition_state(
        second.projection.acquisition_opportunity_id,
        target_state=AcquisitionState.ENRICHING,
        expected_version=1,
        idempotency_key="transition-shared",
    )

    assert transitioned_first.projection.stream_version == 2
    assert transitioned_second.projection.stream_version == 2


def test_same_scoped_key_replays_same_semantics_and_rejects_different(store):
    created = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create"
    )
    opportunity_id = created.projection.acquisition_opportunity_id
    first = store.transition_state(
        opportunity_id,
        target_state=AcquisitionState.ENRICHING,
        expected_version=1,
        idempotency_key="transition-1",
    )
    replayed = store.transition_state(
        opportunity_id,
        target_state=AcquisitionState.ENRICHING,
        expected_version=1,
        idempotency_key="transition-1",
    )

    assert replayed.replayed is True
    assert replayed.event == first.event
    assert len(store.list_events(opportunity_id)) == 2

    with pytest.raises(IdempotencyConflict):
        store.transition_state(
            opportunity_id,
            target_state=AcquisitionState.READY_FOR_DECISION,
            expected_version=2,
            idempotency_key="transition-1",
        )


def test_explicit_occurrence_time_is_part_of_idempotent_event_semantics(store):
    created = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create"
    )
    opportunity_id = created.projection.acquisition_opportunity_id
    first_time = NOW - dt.timedelta(hours=2)
    store.transition_state(
        opportunity_id,
        target_state=AcquisitionState.ENRICHING,
        expected_version=1,
        idempotency_key="transition-1",
        occurred_at=first_time,
    )

    with pytest.raises(IdempotencyConflict):
        store.transition_state(
            opportunity_id,
            target_state=AcquisitionState.ENRICHING,
            expected_version=1,
            idempotency_key="transition-1",
            occurred_at=first_time + dt.timedelta(minutes=1),
        )


def test_optimistic_concurrency_fails_without_creating_an_event(store):
    created = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create"
    )
    opportunity_id = created.projection.acquisition_opportunity_id
    store.transition_state(
        opportunity_id,
        target_state=AcquisitionState.ENRICHING,
        expected_version=1,
        idempotency_key="worker-a",
    )

    with pytest.raises(OpportunityConcurrencyConflict):
        store.transition_state(
            opportunity_id,
            target_state=AcquisitionState.ENRICHING,
            expected_version=1,
            idempotency_key="worker-b",
        )

    assert store.get_opportunity(opportunity_id).stream_version == 2
    assert [event.stream_sequence for event in store.list_events(opportunity_id)] == [1, 2]


def test_decision_and_hold_metadata_are_persisted(store):
    created = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create"
    )
    opportunity_id = created.projection.acquisition_opportunity_id
    store.transition_state(
        opportunity_id,
        target_state=AcquisitionState.ENRICHING,
        expected_version=1,
        idempotency_key="enrich",
    )
    store.transition_state(
        opportunity_id,
        target_state=AcquisitionState.READY_FOR_DECISION,
        expected_version=2,
        idempotency_key="ready",
    )
    review_at = NOW + dt.timedelta(days=2)
    result = store.record_decision(
        opportunity_id,
        decision=Decision.HOLD,
        reason_codes=("awaiting_evidence",),
        evidence_refs=("evidence-1",),
        confidence=Decimal("0.55"),
        policy_version="policy-v1",
        skill_version="skill-v1",
        estimated_cost=Decimal("0.50"),
        next_review_at=review_at,
        expected_version=3,
        idempotency_key="decision-hold",
    )

    assert result.projection.state == AcquisitionState.HOLD
    assert result.projection.decision == Decision.HOLD
    assert result.projection.next_review_at == review_at
    assert result.projection.reason_codes == ("awaiting_evidence",)


def test_restart_reloads_version_and_continues_sequence(engine, store):
    created = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create"
    )
    opportunity_id = created.projection.acquisition_opportunity_id
    store.transition_state(
        opportunity_id,
        target_state=AcquisitionState.ENRICHING,
        expected_version=1,
        idempotency_key="enrich",
    )

    restarted = AcquisitionStore(
        engine,
        clock=lambda: NOW + dt.timedelta(minutes=5),
        event_id_factory=lambda: "event-after-restart",
    )
    result = restarted.transition_state(
        opportunity_id,
        target_state=AcquisitionState.READY_FOR_DECISION,
        expected_version=2,
        idempotency_key="ready",
    )

    assert result.projection.stream_version == 3
    assert result.event.stream_sequence == 3
    assert restarted.get_opportunity(opportunity_id).state == AcquisitionState.READY_FOR_DECISION


def test_failed_invalid_transition_rolls_back_event_and_projection(store):
    created = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create"
    )
    opportunity_id = created.projection.acquisition_opportunity_id

    with pytest.raises(InvalidTransition):
        store.transition_state(
            opportunity_id,
            target_state=AcquisitionState.SEND,
            expected_version=1,
            idempotency_key="invalid",
        )

    assert store.get_opportunity(opportunity_id).stream_version == 1
    assert len(store.list_events(opportunity_id)) == 1


def test_next_action_and_retry_survive_restart(engine, store):
    created = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create"
    )
    opportunity_id = created.projection.acquisition_opportunity_id
    store.set_next_action(
        opportunity_id,
        next_action="enrich_company",
        expected_version=1,
        idempotency_key="next-action",
    )
    retry_at = NOW + dt.timedelta(hours=2)
    store.schedule_retry(
        opportunity_id,
        retry_at=retry_at,
        error_category="provider_timeout",
        reason_codes=("transient_provider_failure",),
        expected_version=2,
        idempotency_key="retry-1",
    )

    restarted = AcquisitionStore(engine)
    projection = restarted.get_opportunity(opportunity_id)
    assert projection.next_action == "enrich_company"
    assert projection.retry_count == 1
    assert projection.retry_at == retry_at
    assert projection.last_error_category == "provider_timeout"


def test_out_of_order_outcome_is_audited_without_projection_regression(store):
    created = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create"
    )
    opportunity_id = created.projection.acquisition_opportunity_id
    version = 1
    for index, target in enumerate(
        (
            AcquisitionState.ENRICHING,
            AcquisitionState.READY_FOR_DECISION,
        ),
        start=1,
    ):
        result = store.transition_state(
            opportunity_id,
            target_state=target,
            expected_version=version,
            idempotency_key=f"pre-{index}",
        )
        version = result.projection.stream_version
    result = store.record_decision(
        opportunity_id,
        decision=Decision.SEND,
        reason_codes=("approved",),
        evidence_refs=("evidence-1",),
        confidence=Decimal("0.8"),
        policy_version="policy-v1",
        skill_version="skill-v1",
        estimated_cost=Decimal("0"),
        expected_version=version,
        idempotency_key="send",
    )
    version = result.projection.stream_version
    for target in (AcquisitionState.QUEUED, AcquisitionState.SENT):
        result = store.transition_state(
            opportunity_id,
            target_state=target,
            expected_version=version,
            idempotency_key=f"state-{target.value.lower()}",
        )
        version = result.projection.stream_version

    activated = store.record_outcome(
        opportunity_id,
        outcome_state=AcquisitionState.ACTIVATED,
        expected_version=version,
        idempotency_key="activated",
    )
    late_reply = store.record_outcome(
        opportunity_id,
        outcome_state=AcquisitionState.REPLIED,
        expected_version=activated.projection.stream_version,
        idempotency_key="late-replied",
    )
    paid = store.record_outcome(
        opportunity_id,
        outcome_state=AcquisitionState.PAID,
        expected_version=late_reply.projection.stream_version,
        idempotency_key="paid",
    )

    assert activated.projection.state == AcquisitionState.ACTIVATED
    assert late_reply.projection.state == AcquisitionState.ACTIVATED
    assert paid.projection.state == AcquisitionState.PAID
    assert [event.event_type.value for event in store.list_events(opportunity_id)][-3:] == [
        "OUTCOME_RECORDED",
        "OUTCOME_RECORDED",
        "OUTCOME_RECORDED",
    ]


def test_verify_and_explicit_rebuild_restore_projection_without_touching_events(
    engine, store
):
    created = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create"
    )
    opportunity_id = created.projection.acquisition_opportunity_id
    store.transition_state(
        opportunity_id,
        target_state=AcquisitionState.ENRICHING,
        expected_version=1,
        idempotency_key="enrich",
    )
    original_events = store.list_events(opportunity_id)
    assert store.verify_projection(opportunity_id) == ProjectionVerification.MATCH

    with engine.begin() as connection:
        connection.execute(
            sa.update(acquisition_opportunity)
            .where(
                acquisition_opportunity.c.acquisition_opportunity_id == opportunity_id
            )
            .values(
                state=AcquisitionState.REVIEW.value,
                stream_version=99,
                next_action="prepare_campaign",
            )
        )

    assert store.verify_projection(opportunity_id) == ProjectionVerification.MISMATCH
    rebuilt = store.rebuild_projection(opportunity_id)

    assert rebuilt.state == AcquisitionState.ENRICHING
    assert rebuilt.stream_version == 2
    assert rebuilt.next_action is None
    assert store.verify_projection(opportunity_id) == ProjectionVerification.MATCH
    assert store.list_events(opportunity_id) == original_events


def test_event_store_exposes_no_event_update_or_delete_api(store):
    assert not hasattr(store, "update_event")
    assert not hasattr(store, "delete_event")
