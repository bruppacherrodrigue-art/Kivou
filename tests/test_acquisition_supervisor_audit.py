from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from alembic import command

from signals.acquisition.contracts import (
    AcquisitionState,
    EventType,
    SupervisorAuditMappingError,
)
from signals.acquisition.store import AcquisitionStore
from signals.acquisition.supervisor_audit import record_supervisor_plan
from signals.persistence.database import alembic_config, create_database_engine
from signals.supervisor.contracts import ProposedAction, SupervisorPlan

NOW = dt.datetime(2026, 8, 19, 12, tzinfo=dt.UTC)


@pytest.fixture
def store(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'audit.db'}")
    command.upgrade(alembic_config(engine), "head")
    opportunity_ids = iter(["opp-1", "opp-2", "identity-collision"])
    event_ids = iter(f"event-{index}" for index in range(1, 20))
    return AcquisitionStore(
        engine,
        clock=lambda: NOW,
        opportunity_id_factory=lambda: next(opportunity_ids),
        event_id_factory=lambda: next(event_ids),
    )


def action(target_ref: str, command_name: str = "enrich_company") -> ProposedAction:
    return ProposedAction(
        command=command_name,
        target_ref=target_ref,
        arguments={"unpersisted_input": "must-not-be-audited"},
        reason_codes=("candidate_requires_enrichment",),
        evidence_refs=("evidence-1",),
        estimated_cost=Decimal("0.20"),
    )


def plan(*actions: ProposedAction) -> SupervisorPlan:
    return SupervisorPlan(
        plan_id="plan-1",
        created_at=NOW,
        objective="Evaluate bounded acquisition opportunities",
        priority=2,
        proposed_actions=actions,
        reason_codes=("bounded_shadow_cycle",),
        confidence=Decimal("0.75"),
        estimated_cost=Decimal("0.40"),
        next_review_at=NOW + dt.timedelta(hours=2),
        supervisor_version="hermes-0.20.4",
        skill_version="kivou-acquisition-supervisor-v1",
    )


def test_plan_audit_stores_only_actions_for_selected_opportunity_and_never_executes(store):
    first = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create-1"
    ).projection
    second = store.create_opportunity(
        identity_key="identity-2", signal_ref="signal-2", idempotency_key="create-2"
    ).projection
    result = record_supervisor_plan(
        store,
        first.acquisition_opportunity_id,
        plan(action(first.identity_key), action(second.acquisition_opportunity_id)),
        expected_version=1,
        idempotency_key="observe-plan-1",
    )

    assert result.recorded is True
    assert result.mutation is not None
    assert result.mutation.event.event_type == EventType.SUPERVISOR_PLAN_OBSERVED
    assert result.mutation.projection.state == AcquisitionState.DISCOVERED
    assert result.mutation.event.payload["actions"] == [
        {
            "command": "enrich_company",
            "target_ref": "identity-1",
            "reason_codes": ["candidate_requires_enrichment"],
            "evidence_refs": ["evidence-1"],
            "estimated_cost": "0.20",
        }
    ]
    assert "arguments" not in result.mutation.event.payload["actions"][0]
    assert not hasattr(result, "executed_actions")
    assert len(store.list_events(first.acquisition_opportunity_id)) == 2
    assert len(store.list_events(second.acquisition_opportunity_id)) == 1


def test_plan_with_zero_actions_for_selected_opportunity_writes_no_event(store):
    first = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create-1"
    ).projection
    second = store.create_opportunity(
        identity_key="identity-2", signal_ref="signal-2", idempotency_key="create-2"
    ).projection

    result = record_supervisor_plan(
        store,
        first.acquisition_opportunity_id,
        plan(action(second.identity_key)),
        expected_version=1,
        idempotency_key="observe-plan-1",
    )

    assert result.recorded is False
    assert result.mutation is None
    assert store.get_opportunity(first.acquisition_opportunity_id).stream_version == 1


def test_unknown_or_ambiguous_plan_target_rejects_the_entire_audit(store):
    first = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create-1"
    ).projection

    with pytest.raises(SupervisorAuditMappingError, match="unknown"):
        record_supervisor_plan(
            store,
            first.acquisition_opportunity_id,
            plan(action("missing-opportunity")),
            expected_version=1,
            idempotency_key="unknown",
        )
    assert len(store.list_events(first.acquisition_opportunity_id)) == 1

    store.create_opportunity(
        identity_key="opp-1", signal_ref="signal-2", idempotency_key="create-2"
    )
    with pytest.raises(SupervisorAuditMappingError, match="ambiguous"):
        record_supervisor_plan(
            store,
            first.acquisition_opportunity_id,
            plan(action("opp-1")),
            expected_version=1,
            idempotency_key="ambiguous",
        )
    assert len(store.list_events(first.acquisition_opportunity_id)) == 1


def test_plan_audit_is_idempotent_and_does_not_require_hermes_runtime(store):
    first = store.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create-1"
    ).projection
    observed = plan(action(first.acquisition_opportunity_id))

    first_result = record_supervisor_plan(
        store,
        first.acquisition_opportunity_id,
        observed,
        expected_version=1,
        idempotency_key="observe-plan-1",
    )
    replayed = record_supervisor_plan(
        store,
        first.acquisition_opportunity_id,
        observed,
        expected_version=1,
        idempotency_key="observe-plan-1",
    )

    assert first_result.recorded is True
    assert replayed.mutation is not None and replayed.mutation.replayed is True
    assert len(store.list_events(first.acquisition_opportunity_id)) == 2
