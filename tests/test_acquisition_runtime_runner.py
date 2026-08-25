from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeCycleSnapshot,
    RuntimeCycleStatus,
    RuntimeLeaseResult,
    RuntimeProposal,
    RuntimeRunRequest,
    RuntimeRunStatus,
    RuntimeStageStatus,
)
from signals.acquisition_runtime.runner import AcquisitionRuntimeRunner

NOW = dt.datetime(2026, 8, 25, 12, tzinfo=dt.UTC)
DEFAULT_CYCLE = RuntimeCycleSnapshot(
    cycle_ref="cycle-001",
    opportunity_key="opportunity-001",
    status=RuntimeCycleStatus.PENDING,
    next_stage=AcquisitionRuntimeStage.SIGNAL_SEED,
    spent_cost=Decimal("0"),
    started_at=NOW,
)


@dataclass
class FakeStore:
    lease: RuntimeLeaseResult = field(
        default_factory=lambda: RuntimeLeaseResult(owned=True, reclaimed=False)
    )
    cycle: RuntimeCycleSnapshot = field(default_factory=lambda: DEFAULT_CYCLE)
    events: list[tuple[object, ...]] = field(default_factory=list)
    proposals: dict[AcquisitionRuntimeStage, RuntimeProposal | None] = field(
        default_factory=dict
    )

    def acquire_lease(self, owner_ref, *, acquired_at, lease_seconds):
        self.events.append(("lease", owner_ref, acquired_at, lease_seconds))
        return self.lease

    def resume_or_create_cycle(self, *, opportunity_keys, config_fingerprint, at):
        self.events.append(("cycle", opportunity_keys, config_fingerprint, at))
        return self.cycle

    def begin_stage(self, cycle_ref, stage, *, at):
        self.events.append(("begin", cycle_ref, stage, at))

    def finish_stage(self, cycle_ref, stage, result, *, at, proposal=None):
        self.proposals[stage] = proposal
        self.events.append(("finish", cycle_ref, stage, result.status, at))

    def heartbeat_lease(self, owner_ref, *, at, lease_seconds):
        self.events.append(("heartbeat", owner_ref, at, lease_seconds))

    def finish_cycle(self, cycle_ref, status, *, at, reason_code=None):
        self.events.append(("finish_cycle", cycle_ref, status, at, reason_code))

    def release_lease(self, owner_ref, *, at):
        self.events.append(("release", owner_ref, at))


@dataclass
class FakeSupervisor:
    proposals: dict[AcquisitionRuntimeStage, RuntimeProposal]
    calls: list[AcquisitionRuntimeStage] = field(default_factory=list)

    def propose(self, stage, cycle, *, remaining_cost, at):
        del cycle, remaining_cost, at
        self.calls.append(stage)
        return self.proposals[stage]


@dataclass
class FakeRegistry:
    outcomes: dict[AcquisitionRuntimeStage, RuntimeActionResult]
    calls: list[tuple[AcquisitionRuntimeStage, str, bool]] = field(default_factory=list)

    def execute(self, stage, proposal, cycle, *, allow_qa_provider_mutations, at):
        del cycle, at
        self.calls.append(
            (stage, proposal.command, allow_qa_provider_mutations)
        )
        return self.outcomes[stage]


def _proposal(
    stage: AcquisitionRuntimeStage,
    *,
    command: str | None = None,
    cost: Decimal = Decimal("0.25"),
) -> RuntimeProposal:
    return RuntimeProposal(
        plan_ref=f"plan-{stage.value.lower()}",
        action_index=0,
        command=command or stage.command,
        target_ref="runtime-target-001",
        argument_fingerprint="a" * 64,
        estimated_cost=cost,
        reason_codes=("QA_RUNTIME_STEP",),
        evidence_refs=("evidence-001",),
    )


def _runner(
    store,
    *,
    outcomes=None,
    proposals=None,
    maximum_cost="5",
    maximum_wall_seconds=900,
    clock=lambda: NOW,
):
    active_stages = tuple(AcquisitionRuntimeStage)
    outcomes = outcomes or {
        stage: RuntimeActionResult(
            status=RuntimeStageStatus.SUCCEEDED,
            result_refs=(f"result-{stage.value.lower()}",),
            observed_cost=Decimal("0.10"),
            reason_codes=("STEP_COMPLETE",),
        )
        for stage in active_stages
    }
    proposals = proposals or {stage: _proposal(stage) for stage in active_stages}
    return AcquisitionRuntimeRunner(
        store=store,
        supervisor=FakeSupervisor(proposals),
        registry=FakeRegistry(outcomes),
        allowed_opportunity_keys=("opportunity-001",),
        config_fingerprint="f" * 64,
        maximum_cycle_cost=Decimal(maximum_cost),
        maximum_wall_seconds=maximum_wall_seconds,
        lease_seconds=1200,
        clock=clock,
    )


def _request(*, mutations=False):
    return RuntimeRunRequest(
        owner_ref="runtime-owner-001",
        allow_qa_provider_mutations=mutations,
    )


def test_normal_lease_contention_is_clean_already_running_without_cycle_work() -> None:
    store = FakeStore(lease=RuntimeLeaseResult(owned=False, reclaimed=False))
    runner = _runner(store)

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.ALREADY_RUNNING
    assert result.exit_code == 0
    assert [event[0] for event in store.events] == ["lease"]


def test_terminal_suppressed_cycle_is_not_reclassified_as_success() -> None:
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(
            update={
                "status": RuntimeCycleStatus.SUPPRESSED,
                "next_stage": None,
            }
        )
    )
    runner = _runner(store)

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.SUPPRESSED
    assert result.exit_code == 0
    assert not any(event[0] == "finish_cycle" for event in store.events)
    assert store.events[-1][0] == "release"


def test_full_cycle_checkpoints_each_stage_before_the_next_action() -> None:
    store = FakeStore()
    runner = _runner(store)

    result = runner.run_once(_request(mutations=True))

    assert result.status is RuntimeRunStatus.COMPLETED
    assert result.exit_code == 0
    names = [event[0] for event in store.events]
    assert names[0:2] == ["lease", "cycle"]
    for stage in AcquisitionRuntimeStage:
        begin = store.events.index(next(e for e in store.events if e[:3] == ("begin", "cycle-001", stage)))
        finish = store.events.index(next(e for e in store.events if e[:3] == ("finish", "cycle-001", stage)))
        assert begin < finish
        following = list(AcquisitionRuntimeStage)
        index = following.index(stage)
        if index + 1 < len(following):
            next_stage = following[index + 1]
            next_begin = store.events.index(
                next(e for e in store.events if e[:3] == ("begin", "cycle-001", next_stage))
            )
            assert finish < next_begin
    assert names[-2:] == ["finish_cycle", "release"]
    assert all(store.proposals[stage] is not None for stage in AcquisitionRuntimeStage)


def test_waiting_result_is_durable_and_current_run_exits_cleanly() -> None:
    stage = AcquisitionRuntimeStage.CONTACT_DISCOVERY
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": stage})
    )
    waiting = RuntimeActionResult(
        status=RuntimeStageStatus.WAITING,
        reason_codes=("HUMAN_APPROVAL_REQUIRED",),
    )
    runner = _runner(store, outcomes={stage: waiting}, proposals={stage: _proposal(stage)})

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.WAITING
    assert result.exit_code == 0
    assert result.stage is stage
    assert ("finish_cycle", "cycle-001", RuntimeCycleStatus.WAITING, NOW, "HUMAN_APPROVAL_REQUIRED") in store.events
    assert store.events[-1][0] == "release"


def test_provider_handoff_without_manual_flag_never_reaches_registry() -> None:
    stage = AcquisitionRuntimeStage.PROVIDER_HANDOFF
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": stage})
    )
    runner = _runner(
        store,
        outcomes={stage: RuntimeActionResult(status=RuntimeStageStatus.SUCCEEDED)},
        proposals={stage: _proposal(stage)},
    )

    result = runner.run_once(_request(mutations=False))

    assert result.status is RuntimeRunStatus.WAITING
    assert result.reason_code == "QA_PROVIDER_MUTATION_NOT_AUTHORIZED"
    assert runner.registry.calls == []


def test_unknown_or_stage_mismatched_supervisor_action_is_blocked() -> None:
    stage = AcquisitionRuntimeStage.DECISION
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": stage})
    )
    runner = _runner(
        store,
        outcomes={stage: RuntimeActionResult(status=RuntimeStageStatus.SUCCEEDED)},
        proposals={stage: _proposal(stage, command="pause_campaign")},
    )

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.BLOCKED
    assert result.exit_code == 1
    assert result.reason_code == "SUPERVISOR_ACTION_MISMATCH"
    assert runner.registry.calls == []


def test_proposal_cannot_exceed_remaining_cycle_budget() -> None:
    stage = AcquisitionRuntimeStage.SUPPLIER_DISCOVERY
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(
            update={"next_stage": stage, "spent_cost": Decimal("4.90")}
        )
    )
    runner = _runner(
        store,
        outcomes={stage: RuntimeActionResult(status=RuntimeStageStatus.SUCCEEDED)},
        proposals={stage: _proposal(stage, cost=Decimal("0.11"))},
    )

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.BLOCKED
    assert result.reason_code == "CYCLE_BUDGET_EXCEEDED"
    assert runner.registry.calls == []


def test_success_reserves_the_greater_of_estimated_and_observed_cycle_cost() -> None:
    first = AcquisitionRuntimeStage.SUPPLIER_DISCOVERY
    second = AcquisitionRuntimeStage.CONTACT_DISCOVERY
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": first})
    )
    runner = _runner(
        store,
        outcomes={
            first: RuntimeActionResult(
                status=RuntimeStageStatus.SUCCEEDED,
                observed_cost=Decimal("0.10"),
            ),
            second: RuntimeActionResult(status=RuntimeStageStatus.SUCCEEDED),
        },
        proposals={
            first: _proposal(first, cost=Decimal("3")),
            second: _proposal(second, cost=Decimal("3")),
        },
        maximum_cost="5",
    )

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.BLOCKED
    assert result.stage is second
    assert runner.registry.calls == [(first, first.command, False)]


def test_observed_cost_overrun_is_a_current_execution_failure() -> None:
    stage = AcquisitionRuntimeStage.SUPPLIER_DISCOVERY
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": stage})
    )
    runner = _runner(
        store,
        outcomes={
            stage: RuntimeActionResult(
                status=RuntimeStageStatus.SUCCEEDED,
                observed_cost=Decimal("5.01"),
            )
        },
        proposals={stage: _proposal(stage, cost=Decimal("1"))},
        maximum_cost="5",
    )

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.FAILED
    assert result.reason_code == "OBSERVED_CYCLE_COST_EXCEEDED"
    assert (
        "finish",
        "cycle-001",
        stage,
        RuntimeStageStatus.FAILED,
        NOW,
    ) in store.events


def test_current_execution_failure_is_nonzero_but_history_is_not_replayed() -> None:
    stage = AcquisitionRuntimeStage.COMPANY_RESEARCH
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": stage})
    )
    failure = RuntimeActionResult(
        status=RuntimeStageStatus.FAILED,
        reason_codes=("PROVIDER_TIMEOUT",),
    )
    runner = _runner(store, outcomes={stage: failure}, proposals={stage: _proposal(stage)})

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.FAILED
    assert result.exit_code == 1
    assert result.reason_code == "PROVIDER_TIMEOUT"
    assert store.events[-1][0] == "release"


def test_suppressed_eligibility_is_terminal_without_provider_failure() -> None:
    stage = AcquisitionRuntimeStage.COMPLIANCE
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": stage})
    )
    suppressed = RuntimeActionResult(
        status=RuntimeStageStatus.SUPPRESSED,
        reason_codes=("QA_ELIGIBILITY_REVOKED",),
    )
    runner = _runner(
        store,
        outcomes={stage: suppressed},
        proposals={stage: _proposal(stage)},
    )

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.SUPPRESSED
    assert result.exit_code == 0
    assert result.reason_code == "QA_ELIGIBILITY_REVOKED"


def test_interruption_cancels_current_stage_and_always_releases_lease() -> None:
    stage = AcquisitionRuntimeStage.PERSONALIZATION
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": stage})
    )

    class InterruptingRegistry(FakeRegistry):
        def execute(self, *args, **kwargs):
            raise InterruptedError

    runner = _runner(store, outcomes={}, proposals={stage: _proposal(stage)})
    runner.registry = InterruptingRegistry({})

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.CANCELLED
    assert result.exit_code == 1
    assert ("finish", "cycle-001", stage, RuntimeStageStatus.CANCELLED, NOW) in store.events
    assert store.events[-1][0] == "release"


def test_technical_exception_terminalizes_current_run_without_exception_text() -> None:
    stage = AcquisitionRuntimeStage.PERSONALIZATION
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": stage})
    )

    class FailingRegistry(FakeRegistry):
        def execute(self, *args, **kwargs):
            raise RuntimeError("private-provider-detail")

    runner = _runner(store, outcomes={}, proposals={stage: _proposal(stage)})
    runner.registry = FailingRegistry({})

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.FAILED
    assert result.reason_code == "CURRENT_RUN_TECHNICAL_FAILURE"
    assert "private-provider-detail" not in repr(result)
    assert ("finish", "cycle-001", stage, RuntimeStageStatus.FAILED, NOW) in store.events
    assert store.events[-1][0] == "release"


def test_wall_clock_budget_stops_before_starting_another_stage() -> None:
    first = AcquisitionRuntimeStage.SIGNAL_SEED
    second = AcquisitionRuntimeStage.SUPPLIER_DISCOVERY
    times = iter((NOW, NOW, NOW + dt.timedelta(seconds=61)))
    store = FakeStore()
    runner = _runner(
        store,
        outcomes={
            first: RuntimeActionResult(status=RuntimeStageStatus.SUCCEEDED),
        },
        proposals={first: _proposal(first)},
        maximum_wall_seconds=60,
        clock=lambda: next(times),
    )

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.WAITING
    assert result.stage is second
    assert result.reason_code == "CYCLE_TIME_BUDGET_REACHED"
    assert not any(event[:3] == ("begin", "cycle-001", second) for event in store.events)
    assert store.events[-1][0] == "release"
