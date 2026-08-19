from __future__ import annotations

import datetime as dt
from decimal import Decimal

from alembic import command

from signals.acquisition.contracts import AcquisitionState, ProjectionVerification
from signals.acquisition.state import replay
from signals.acquisition.store import AcquisitionStore
from signals.persistence.database import alembic_config, create_database_engine

NOW = dt.datetime(2026, 8, 19, 12, tzinfo=dt.UTC)


def test_one_hundred_event_stream_loads_replays_and_verifies(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'replay.db'}")
    command.upgrade(alembic_config(engine), "head")
    store = AcquisitionStore(engine, clock=lambda: NOW)
    created = store.create_opportunity(
        identity_key="identity-100-events",
        signal_ref="signal-1",
        idempotency_key="create",
    )
    opportunity_id = created.projection.acquisition_opportunity_id

    for sequence in range(2, 101):
        store.record_supervisor_plan_observed(
            opportunity_id,
            payload={
                "plan_id": f"plan-{sequence}",
                "objective": "deterministic replay measurement",
                "priority": 3,
                "next_review_at": NOW.isoformat(),
                "plan_estimated_cost": "0",
                "actions": [
                    {
                        "command": "evaluate_opportunity",
                        "target_ref": opportunity_id,
                        "reason_codes": ["replay_fixture"],
                        "evidence_refs": [],
                        "estimated_cost": "0",
                    }
                ],
            },
            reason_codes=("replay_fixture",),
            evidence_refs=(),
            confidence=Decimal("1"),
            estimated_cost=Decimal("0"),
            supervisor_version="fake-supervisor-v1",
            skill_version="fixture-skill-v1",
            expected_version=sequence - 1,
            idempotency_key=f"audit-{sequence}",
            occurred_at=NOW,
        )

    events = store.list_events(opportunity_id)
    rebuilt = replay(events)

    assert len(events) == 100
    assert rebuilt.state == AcquisitionState.DISCOVERED
    assert rebuilt.stream_version == 100
    assert rebuilt == store.get_opportunity(opportunity_id)
    assert store.verify_projection(opportunity_id) == ProjectionVerification.MATCH


def test_hermes_failure_does_not_affect_event_store(monkeypatch, tmp_path) -> None:
    from signals.supervisor.hermes import HermesSupervisorAdapter

    def unavailable(*args, **kwargs):
        raise RuntimeError("Hermes unavailable")

    monkeypatch.setattr(HermesSupervisorAdapter, "plan", unavailable)
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'isolated.db'}")
    command.upgrade(alembic_config(engine), "head")
    store = AcquisitionStore(engine, clock=lambda: NOW)

    created = store.create_opportunity(
        identity_key="identity-without-hermes",
        signal_ref="signal-1",
        idempotency_key="create",
    )

    assert created.projection.state == AcquisitionState.DISCOVERED
    assert store.verify_projection(created.projection.acquisition_opportunity_id) == (
        ProjectionVerification.MATCH
    )
