from __future__ import annotations

import datetime as dt
import hashlib
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
import sqlalchemy as sa
from test_acquisition_runtime_health import capability

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeCycleStatus,
    RuntimeProposal,
    RuntimeRunRequest,
    RuntimeRunStatus,
    RuntimeStageStatus,
)
from signals.acquisition_runtime.runner import AcquisitionRuntimeRunner
from signals.acquisition_runtime.store import (
    AcquisitionRuntimeConflict,
    AcquisitionRuntimeStore,
)
from signals.persistence.schema import (
    METADATA,
    acquisition_runtime_cycle,
    acquisition_runtime_lease,
    acquisition_runtime_observation,
    acquisition_runtime_stage,
    acquisition_runtime_stage_attempt,
)

NOW = dt.datetime(2026, 8, 25, 12, tzinfo=dt.UTC)


def _engine(tmp_path) -> sa.Engine:
    engine = sa.create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'runtime.sqlite'}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    METADATA.create_all(
        engine,
        tables=[
            acquisition_runtime_lease,
            acquisition_runtime_cycle,
            acquisition_runtime_observation,
            acquisition_runtime_stage,
            acquisition_runtime_stage_attempt,
        ],
    )
    return engine


def _fence(store: AcquisitionRuntimeStore) -> dict[str, object]:
    lease = store.acquire_lease(
        "test-owner",
        acquired_at=NOW,
        lease_seconds=7_200,
    )
    assert lease.fencing_token is not None
    return {
        "owner_ref": "test-owner",
        "fencing_token": lease.fencing_token,
    }


def test_runtime_schema_is_bounded_and_contains_no_recipient_or_payload_fields() -> None:
    assert {column.name for column in acquisition_runtime_lease.c} == {
        "lease_name",
        "owner_ref",
        "acquired_at",
        "heartbeat_at",
        "expires_at",
        "generation",
    }
    assert {column.name for column in acquisition_runtime_cycle.c} == {
        "cycle_ref",
        "opportunity_key",
        "config_fingerprint",
        "status",
        "next_stage",
        "spent_cost",
        "last_reason_code",
        "started_at",
        "updated_at",
        "completed_at",
    }
    assert {column.name for column in acquisition_runtime_stage.c} == {
        "cycle_ref",
        "stage",
        "status",
        "attempt_count",
        "plan_ref",
        "command",
        "argument_fingerprint",
        "result_refs",
        "reserved_cost",
        "observed_cost",
        "reason_codes",
        "retry_at",
        "started_at",
        "completed_at",
        "updated_at",
    }
    assert {column.name for column in acquisition_runtime_stage_attempt.c} == {
        "cycle_ref",
        "stage",
        "attempt_count",
        "status",
        "reserved_cost",
        "observed_cost",
        "retry_at",
        "completed_at",
    }
    names = {
        column.name
        for table in (
            acquisition_runtime_lease,
            acquisition_runtime_cycle,
            acquisition_runtime_stage,
            acquisition_runtime_stage_attempt,
        )
        for column in table.c
    }
    assert not names & {
        "email",
        "recipient",
        "payload",
        "content",
        "provider_payload",
        "provider_secret",
    }


def test_sequential_lease_contention_and_expired_reclaim(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))

    first = store.acquire_lease("owner-a", acquired_at=NOW, lease_seconds=120)
    blocked = store.acquire_lease(
        "owner-b", acquired_at=NOW + dt.timedelta(seconds=1), lease_seconds=120
    )
    reclaimed = store.acquire_lease(
        "owner-b", acquired_at=NOW + dt.timedelta(seconds=121), lease_seconds=120
    )

    assert first.owned is True and first.reclaimed is False
    assert blocked.owned is False and blocked.reclaimed is False
    assert reclaimed.owned is True and reclaimed.reclaimed is True
    assert first.fencing_token == 1
    assert blocked.fencing_token is None
    assert reclaimed.fencing_token == 2


def test_expired_owner_cannot_mutate_after_fenced_lease_reclaim(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    original = store.acquire_lease(
        "owner-a",
        acquired_at=NOW,
        lease_seconds=120,
    )
    assert original.fencing_token is not None
    cycle = store.resume_or_create_cycle(
        owner_ref="owner-a",
        fencing_token=original.fencing_token,
        opportunity_keys=("signal-001",),
        config_fingerprint="6" * 64,
        at=NOW,
    )
    reclaimed_at = NOW + dt.timedelta(seconds=121)
    current = store.acquire_lease(
        "owner-b",
        acquired_at=reclaimed_at,
        lease_seconds=120,
    )
    assert current.fencing_token is not None

    with pytest.raises(AcquisitionRuntimeConflict):
        store.begin_stage(
            cycle.cycle_ref,
            AcquisitionRuntimeStage.SIGNAL_SEED,
            owner_ref="owner-a",
            fencing_token=original.fencing_token,
            at=reclaimed_at,
        )

    snapshot = store.begin_stage(
        cycle.cycle_ref,
        AcquisitionRuntimeStage.SIGNAL_SEED,
        owner_ref="owner-b",
        fencing_token=current.fencing_token,
        at=reclaimed_at,
    )
    assert snapshot.status is RuntimeStageStatus.RUNNING


def test_concurrent_lease_acquisition_has_exactly_one_owner(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))

    def acquire(owner: str):
        return owner, store.acquire_lease(owner, acquired_at=NOW, lease_seconds=120)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(acquire, ("owner-a", "owner-b")))

    assert sum(result.owned for _, result in outcomes) == 1
    winner = next(owner for owner, result in outcomes if result.owned)
    with store.engine.connect() as connection:
        row = connection.execute(sa.select(acquisition_runtime_lease)).mappings().one()
    assert row["owner_ref"] == winner


def test_cycle_creation_is_deterministic_and_replay_safe(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    fence = _fence(store)

    first = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("signal-001",), config_fingerprint="a" * 64, at=NOW
    )
    replay = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("signal-001",),
        config_fingerprint="a" * 64,
        at=NOW + dt.timedelta(seconds=1),
    )

    assert replay == first
    assert first.next_stage is AcquisitionRuntimeStage.SIGNAL_SEED
    with store.engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_runtime_cycle)) == 1
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_runtime_stage)) == len(AcquisitionRuntimeStage)


def test_stage_checkpoint_advances_and_cost_is_reserved_durably(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    fence = _fence(store)
    cycle = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("signal-001",), config_fingerprint="b" * 64, at=NOW
    )
    first = AcquisitionRuntimeStage.SIGNAL_SEED
    result = RuntimeActionResult(
        status=RuntimeStageStatus.SUCCEEDED,
        result_refs=("seed-001",),
        reserved_cost=Decimal("0.25"),
        observed_cost=Decimal("0.10"),
        reason_codes=("STEP_COMPLETE",),
    )
    proposal = RuntimeProposal(
        plan_ref="plan-seed-001",
        action_index=0,
        command=first.command,
        target_ref="signal-001",
        argument_fingerprint="e" * 64,
        estimated_cost=Decimal("0.25"),
        reason_codes=("QA_RUNTIME_STEP",),
    )

    store.begin_stage(cycle.cycle_ref, first, **fence, at=NOW)
    store.finish_stage(
        cycle.cycle_ref,
        first,
        result,
        **fence,
        proposal=proposal,
        at=NOW,
    )
    resumed = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("signal-001",), config_fingerprint="b" * 64, at=NOW
    )

    assert resumed.next_stage is AcquisitionRuntimeStage.SUPPLIER_DISCOVERY
    assert resumed.spent_cost == Decimal("0.25")
    with store.engine.connect() as connection:
        row = connection.execute(
            sa.select(acquisition_runtime_stage).where(
                acquisition_runtime_stage.c.cycle_ref == cycle.cycle_ref,
                acquisition_runtime_stage.c.stage == first.value,
            )
        ).mappings().one()
    assert row["result_refs"] == ["seed-001"]
    assert row["reason_codes"] == ["STEP_COMPLETE"]
    assert row["plan_ref"] == "plan-seed-001"
    assert row["command"] == first.command
    assert row["argument_fingerprint"] == "e" * 64
    assert row["attempt_count"] == 1


def test_interrupted_running_stage_resumes_without_duplicate_cycle(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    fence = _fence(store)
    cycle = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("signal-001",), config_fingerprint="c" * 64, at=NOW
    )
    stage = AcquisitionRuntimeStage.SIGNAL_SEED
    store.begin_stage(cycle.cycle_ref, stage, **fence, at=NOW)

    resumed = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("signal-001",),
        config_fingerprint="c" * 64,
        at=NOW + dt.timedelta(minutes=30),
    )
    store.begin_stage(
        cycle.cycle_ref,
        stage,
        **fence,
        at=NOW + dt.timedelta(minutes=30),
    )

    assert resumed.cycle_ref == cycle.cycle_ref
    assert resumed.next_stage is stage
    with store.engine.connect() as connection:
        row = connection.execute(
            sa.select(acquisition_runtime_stage).where(
                acquisition_runtime_stage.c.cycle_ref == cycle.cycle_ref,
                acquisition_runtime_stage.c.stage == stage.value,
            )
        ).mappings().one()
    assert row["attempt_count"] == 1


def test_running_stage_restart_reuses_same_deterministic_attempt_identity(
    tmp_path,
) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    fence = _fence(store)
    cycle = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("signal-001",), config_fingerprint="e" * 64, at=NOW
    )
    stage = AcquisitionRuntimeStage.SIGNAL_SEED

    first = store.begin_stage(cycle.cycle_ref, stage, **fence, at=NOW)
    restarted = store.begin_stage(
        cycle.cycle_ref,
        stage,
        **fence,
        at=NOW + dt.timedelta(minutes=30),
    )

    assert first.status is RuntimeStageStatus.RUNNING
    assert first.attempt_count == 1
    assert restarted == first
    assert restarted.attempt_ref == first.attempt_ref
    material = (
        "acquisition-runtime-attempt-v1\0"
        f"{cycle.cycle_ref}\0{stage.value}\0{first.attempt_count}"
    )
    assert restarted.attempt_ref == hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()


def test_new_attempt_preserves_partial_result_references_for_resume(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    fence = _fence(store)
    cycle = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("signal-001",), config_fingerprint="f" * 64, at=NOW
    )
    stage = AcquisitionRuntimeStage.SUPPLIER_DISCOVERY
    first = store.begin_stage(cycle.cycle_ref, stage, **fence, at=NOW)
    store.finish_stage(
        cycle.cycle_ref,
        stage,
        RuntimeActionResult(
            status=RuntimeStageStatus.WAITING,
            result_refs=("supplier-run-001",),
            reason_codes=("PROVIDER_RETRY_DUE",),
            retry_at=NOW + dt.timedelta(minutes=15),
        ),
        **fence,
        at=NOW,
    )

    deferred = store.begin_stage(
        cycle.cycle_ref,
        stage,
        **fence,
        at=NOW + dt.timedelta(minutes=5),
    )
    resumed = store.begin_stage(
        cycle.cycle_ref,
        stage,
        **fence,
        at=NOW + dt.timedelta(minutes=30),
    )

    assert deferred.status is RuntimeStageStatus.WAITING
    assert deferred.attempt_count == 1
    assert deferred.retry_at == NOW + dt.timedelta(minutes=15)
    assert resumed.status is RuntimeStageStatus.RUNNING
    assert resumed.attempt_count == 2
    assert resumed.attempt_ref != first.attempt_ref
    assert resumed.result_refs == ("supplier-run-001",)


def test_retry_attempt_costs_are_immutable_and_cumulative(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    fence = _fence(store)
    cycle = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("signal-001",), config_fingerprint="7" * 64, at=NOW
    )
    stage = AcquisitionRuntimeStage.SUPPLIER_DISCOVERY
    store.begin_stage(cycle.cycle_ref, stage, **fence, at=NOW)
    store.finish_stage(
        cycle.cycle_ref,
        stage,
        RuntimeActionResult(
            status=RuntimeStageStatus.WAITING,
            reserved_cost=Decimal("1.25"),
            observed_cost=Decimal("1.00"),
            reason_codes=("PROVIDER_RETRY_DUE",),
        ),
        **fence,
        at=NOW,
    )
    store.begin_stage(
        cycle.cycle_ref,
        stage,
        **fence,
        at=NOW + dt.timedelta(minutes=1),
    )
    store.finish_stage(
        cycle.cycle_ref,
        stage,
        RuntimeActionResult(
            status=RuntimeStageStatus.SUCCEEDED,
            reserved_cost=Decimal("0.75"),
            observed_cost=Decimal("0.50"),
        ),
        **fence,
        at=NOW + dt.timedelta(minutes=1),
    )

    resumed = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("signal-001",),
        config_fingerprint="7" * 64,
        at=NOW + dt.timedelta(minutes=2),
    )
    with store.engine.connect() as connection:
        attempts = connection.execute(
            sa.select(acquisition_runtime_stage_attempt)
            .where(acquisition_runtime_stage_attempt.c.cycle_ref == cycle.cycle_ref)
            .order_by(acquisition_runtime_stage_attempt.c.attempt_count)
        ).mappings().all()

    assert resumed.spent_cost == Decimal("2.00")
    assert [row["attempt_count"] for row in attempts] == [1, 2]
    assert [row["status"] for row in attempts] == ["WAITING", "SUCCEEDED"]


def test_crash_after_business_commit_before_runtime_checkpoint_reuses_attempt(
    tmp_path,
) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    committed_attempts: set[str] = set()
    observed_attempts: list[str] = []

    class SimulatedProcessCrash(BaseException):
        pass

    class Supervisor:
        def propose(self, stage, cycle, *, remaining_cost, at):
            del remaining_cost, at
            return RuntimeProposal(
                plan_ref="plan-crash-resume",
                action_index=0,
                command=stage.command,
                target_ref=cycle.opportunity_key,
                argument_fingerprint="1" * 64,
                estimated_cost=Decimal("0"),
                reason_codes=("QA_RUNTIME_STEP",),
            )

    class Registry:
        def execute(
            self,
            stage,
            proposal,
            cycle,
            *,
            stage_snapshot,
            allow_qa_provider_mutations,
            at,
        ):
            del stage, proposal, cycle, allow_qa_provider_mutations, at
            attempt_ref = stage_snapshot.attempt_ref
            observed_attempts.append(attempt_ref)
            if attempt_ref not in committed_attempts:
                committed_attempts.add(attempt_ref)
                raise SimulatedProcessCrash
            return RuntimeActionResult(
                status=RuntimeStageStatus.WAITING,
                result_refs=(f"committed-{attempt_ref}",),
                reason_codes=("NEXT_STAGE_NOT_DUE",),
            )

    runner = AcquisitionRuntimeRunner(
        store=store,
        supervisor=Supervisor(),
        registry=Registry(),
        allowed_opportunity_keys=("signal-001",),
        config_fingerprint="9" * 64,
        maximum_cycle_cost=Decimal("5"),
        maximum_wall_seconds=900,
        lease_seconds=1200,
        runtime_capability=capability(),
        clock=lambda: NOW,
    )
    request = RuntimeRunRequest(owner_ref="runtime-owner-001")

    with pytest.raises(SimulatedProcessCrash):
        runner.run_once(request)
    resumed = runner.run_once(request)

    assert resumed.status is RuntimeRunStatus.WAITING
    assert len(committed_attempts) == 1
    assert observed_attempts == [observed_attempts[0], observed_attempts[0]]
    with store.engine.connect() as connection:
        row = connection.execute(
            sa.select(acquisition_runtime_stage).where(
                acquisition_runtime_stage.c.stage
                == AcquisitionRuntimeStage.SIGNAL_SEED.value
            )
        ).mappings().one()
    assert row["attempt_count"] == 1
    assert row["result_refs"] == [f"committed-{observed_attempts[0]}"]


def test_suppressed_cycle_is_terminal_and_not_reopened(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    fence = _fence(store)
    cycle = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("signal-001",), config_fingerprint="d" * 64, at=NOW
    )
    store.finish_cycle(
        cycle.cycle_ref,
        RuntimeCycleStatus.SUPPRESSED,
        **fence,
        at=NOW,
        reason_code="QA_ELIGIBILITY_REVOKED",
    )

    replay = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("signal-001",),
        config_fingerprint="d" * 64,
        at=NOW + dt.timedelta(hours=1),
    )

    assert replay.status is RuntimeCycleStatus.SUPPRESSED
    assert replay.next_stage is None
