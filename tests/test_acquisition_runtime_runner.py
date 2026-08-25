from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeCapabilityEvidence,
    RuntimeCycleSnapshot,
    RuntimeCycleStatus,
    RuntimeHermesIdentityEvidence,
    RuntimeLeaseResult,
    RuntimeProposal,
    RuntimeRunRequest,
    RuntimeRunStatus,
    RuntimeStageDependency,
    RuntimeStageReservation,
    RuntimeStageSnapshot,
    RuntimeStageStatus,
    expected_runtime_registry_identity,
)
from signals.acquisition_runtime.runner import AcquisitionRuntimeRunner
from signals.acquisition_runtime.supervisor import KIVOU_STAGE_COSTS
from signals.supervisor.pin import load_hermes_pin

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
        default_factory=lambda: RuntimeLeaseResult(
            owned=True,
            reclaimed=False,
            fencing_token=1,
        )
    )
    cycle: RuntimeCycleSnapshot = field(default_factory=lambda: DEFAULT_CYCLE)
    events: list[tuple[object, ...]] = field(default_factory=list)
    proposals: dict[AcquisitionRuntimeStage, RuntimeProposal | None] = field(
        default_factory=dict
    )
    reservations: dict[
        tuple[AcquisitionRuntimeStage, int],
        tuple[Decimal, RuntimeProposal | None],
    ] = field(default_factory=dict)
    finished_results: list[RuntimeActionResult] = field(default_factory=list)

    def acquire_lease(self, owner_ref, *, acquired_at, lease_seconds):
        self.events.append(("lease", owner_ref, acquired_at, lease_seconds))
        return self.lease

    def execution_guard(self, owner_ref, *, fencing_token, lease_seconds):
        store = self

        class Guard:
            @contextmanager
            def protect(self):
                assert owner_ref == "runtime-owner-001" and fencing_token == 1
                store.events.append(("guard", owner_ref, lease_seconds))
                yield NOW

        return Guard()

    def resume_or_create_cycle(
        self,
        *,
        owner_ref,
        fencing_token,
        opportunity_keys,
        config_fingerprint,
        at,
    ):
        assert owner_ref == "runtime-owner-001" and fencing_token == 1
        self.events.append(("cycle", opportunity_keys, config_fingerprint, at))
        return self.cycle

    def begin_stage(
        self, cycle_ref, stage, *, owner_ref, fencing_token, at
    ):
        assert owner_ref == "runtime-owner-001" and fencing_token == 1
        self.events.append(("begin", cycle_ref, stage, at))
        return RuntimeStageSnapshot(
            cycle_ref=cycle_ref,
            stage=stage,
            status=RuntimeStageStatus.RUNNING,
            attempt_count=1,
            result_refs=("prior-result-001",),
        )

    def finish_stage(
        self,
        cycle_ref,
        stage,
        result,
        *,
        owner_ref,
        fencing_token,
        at,
        proposal=None,
    ):
        assert owner_ref == "runtime-owner-001" and fencing_token == 1
        self.proposals[stage] = proposal
        self.finished_results.append(result)
        self.events.append(("finish", cycle_ref, stage, result.status, at))

    def reserve_stage_cost(
        self,
        cycle_ref,
        stage,
        stage_snapshot,
        reserved_cost,
        *,
        maximum_cycle_cost,
        owner_ref,
        fencing_token,
        at,
    ):
        assert owner_ref == "runtime-owner-001" and fencing_token == 1
        key = (stage, stage_snapshot.attempt_count)
        existing = self.reservations.get(key)
        reserved_total = sum(
            (value[0] for value in self.reservations.values()),
            start=Decimal("0"),
        )
        base_cost = self.cycle.spent_cost - reserved_total
        total_before = base_cost + sum(
            (value[0] for current, value in self.reservations.items() if current != key),
            start=Decimal("0"),
        )
        accepted = total_before + reserved_cost <= maximum_cycle_cost
        if accepted and existing is None:
            self.reservations[key] = (reserved_cost, None)
        total = total_before + (reserved_cost if accepted else Decimal("0"))
        self.cycle = self.cycle.model_copy(update={"spent_cost": total})
        self.events.append(
            (
                "reserve",
                cycle_ref,
                stage,
                stage_snapshot.attempt_count,
                reserved_cost,
                at,
            )
        )
        return RuntimeStageReservation(
            accepted=accepted,
            created=accepted and existing is None,
            reserved_cost=reserved_cost,
            total_cycle_cost=total,
            proposal=existing[1] if existing is not None else None,
        )

    def bind_stage_proposal(
        self,
        cycle_ref,
        stage,
        stage_snapshot,
        proposal,
        *,
        owner_ref,
        fencing_token,
        at,
    ):
        assert owner_ref == "runtime-owner-001" and fencing_token == 1
        key = (stage, stage_snapshot.attempt_count)
        reserved, existing = self.reservations[key]
        assert reserved == proposal.estimated_cost
        assert existing is None or existing == proposal
        self.reservations[key] = (reserved, proposal)
        self.events.append(("bind_plan", cycle_ref, stage, proposal.plan_ref, at))
        return proposal

    def heartbeat_lease(
        self, owner_ref, *, fencing_token, at, lease_seconds
    ):
        assert owner_ref == "runtime-owner-001" and fencing_token == 1
        self.events.append(("heartbeat", owner_ref, at, lease_seconds))

    def finish_cycle(
        self,
        cycle_ref,
        status,
        *,
        owner_ref,
        fencing_token,
        at,
        reason_code=None,
    ):
        assert owner_ref == "runtime-owner-001" and fencing_token == 1
        self.events.append(("finish_cycle", cycle_ref, status, at, reason_code))

    def release_lease(self, owner_ref, *, fencing_token, at):
        assert owner_ref == "runtime-owner-001" and fencing_token == 1
        self.events.append(("release", owner_ref, at))

    def record_runtime_observation(
        self, owner_ref, capability, *, fencing_token, at
    ):
        assert owner_ref == "runtime-owner-001" and fencing_token == 1
        self.events.append(
            ("observe_runtime", owner_ref, capability.fingerprint, at)
        )

    def record_cycle_observation(
        self, owner_ref, cycle_ref, *, fencing_token, at
    ):
        assert owner_ref == "runtime-owner-001" and fencing_token == 1
        self.events.append(("observe_cycle", owner_ref, cycle_ref, at))


@dataclass
class FakeSupervisor:
    proposals: dict[AcquisitionRuntimeStage, RuntimeProposal]
    calls: list[AcquisitionRuntimeStage] = field(default_factory=list)
    events: list[tuple[object, ...]] | None = None

    def propose(self, stage, cycle, *, remaining_cost, at):
        del cycle, remaining_cost, at
        self.calls.append(stage)
        if self.events is not None:
            self.events.append(("propose", stage))
        return self.proposals[stage]


@dataclass
class FakeRegistry:
    outcomes: dict[AcquisitionRuntimeStage, RuntimeActionResult]
    calls: list[tuple[AcquisitionRuntimeStage, str, bool]] = field(default_factory=list)
    stage_snapshots: list[RuntimeStageSnapshot | None] = field(default_factory=list)

    def execute(
        self,
        stage,
        proposal,
        cycle,
        *,
        stage_snapshot=None,
        allow_qa_provider_mutations,
        guard,
        at,
    ):
        del cycle, at
        assert guard is not None
        self.stage_snapshots.append(stage_snapshot)
        self.calls.append(
            (stage, proposal.command, allow_qa_provider_mutations)
        )
        return self.outcomes[stage]


def _proposal(
    stage: AcquisitionRuntimeStage,
    *,
    command: str | None = None,
    cost: Decimal | None = None,
) -> RuntimeProposal:
    return RuntimeProposal(
        plan_ref=f"plan-{stage.value.lower()}",
        action_index=0,
        command=command or stage.command,
        target_ref="runtime-target-001",
        argument_fingerprint="a" * 64,
        estimated_cost=(KIVOU_STAGE_COSTS[stage] if cost is None else cost),
        reason_codes=("QA_RUNTIME_STEP",),
        evidence_refs=("evidence-001",),
    )


def _capability() -> RuntimeCapabilityEvidence:
    pin = load_hermes_pin()
    return RuntimeCapabilityEvidence(
        environment="STAGING",
        mode="SHADOW",
        qa_only=True,
        hermes=RuntimeHermesIdentityEvidence(
            repository=pin.repository,
            tag=pin.tag,
            commit=pin.commit,
            version=pin.version,
            python_contract=pin.python,
        ),
        registry_identity=expected_runtime_registry_identity(),
        native_tools=0,
        commands=tuple(stage.command for stage in AcquisitionRuntimeStage),
        dependencies=tuple(
            RuntimeStageDependency(stage=stage, status="READY")
            for stage in AcquisitionRuntimeStage
        ),
    )


def _runner(
    store,
    *,
    outcomes=None,
    proposals=None,
    maximum_cost="10",
    maximum_wall_seconds=900,
    clock=lambda: NOW,
    event_sink=None,
    runtime_capability=None,
):
    active_stages = tuple(AcquisitionRuntimeStage)
    outcomes = outcomes or {
        stage: RuntimeActionResult(
            status=RuntimeStageStatus.SUCCEEDED,
            result_refs=(f"result-{stage.value.lower()}",),
            observed_cost=(
                Decimal("0.10")
                if KIVOU_STAGE_COSTS[stage] > 0
                else Decimal("0")
            ),
            reason_codes=("STEP_COMPLETE",),
        )
        for stage in active_stages
    }
    proposals = proposals or {stage: _proposal(stage) for stage in active_stages}
    arguments = {
        "store": store,
        "supervisor": FakeSupervisor(proposals, events=store.events),
        "registry": FakeRegistry(outcomes),
        "allowed_opportunity_keys": ("opportunity-001",),
        "config_fingerprint": "f" * 64,
        "maximum_cycle_cost": Decimal(maximum_cost),
        "maximum_wall_seconds": maximum_wall_seconds,
        "lease_seconds": 1200,
        "runtime_capability": runtime_capability or _capability(),
        "clock": clock,
    }
    if event_sink is not None:
        arguments["event_sink"] = event_sink
    return AcquisitionRuntimeRunner(
        **arguments,
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


def test_not_ready_dependency_is_observed_then_blocks_before_cycle_or_action() -> None:
    capability = _capability().model_copy(
        update={
            "dependencies": tuple(
                RuntimeStageDependency(
                    stage=stage,
                    status=(
                        "NOT_READY"
                        if stage is AcquisitionRuntimeStage.COMPANY_RESEARCH
                        else "READY"
                    ),
                    reason_codes=(
                        ("APOLLO_DEPENDENCY_NOT_READY",)
                        if stage is AcquisitionRuntimeStage.COMPANY_RESEARCH
                        else ()
                    ),
                )
                for stage in AcquisitionRuntimeStage
            )
        }
    )
    store = FakeStore()

    result = _runner(store, runtime_capability=capability).run_once(_request())

    assert result.status is RuntimeRunStatus.BLOCKED
    assert result.stage is AcquisitionRuntimeStage.COMPANY_RESEARCH
    assert result.reason_code == "APOLLO_DEPENDENCY_NOT_READY"
    assert result.exit_code == 1
    assert not any(event[0] == "cycle" for event in store.events)
    assert not any(event[0] == "begin" for event in store.events)


def test_runtime_events_follow_their_durable_transitions() -> None:
    stage = AcquisitionRuntimeStage.CONTACT_DISCOVERY
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": stage})
    )

    def capture(**payload):
        store.events.append(("runtime_event", payload))

    runner = _runner(
        store,
        outcomes={
            stage: RuntimeActionResult(
                status=RuntimeStageStatus.WAITING,
                reason_codes=("PROVIDER_RETRY_DUE",),
            )
        },
        proposals={stage: _proposal(stage)},
        event_sink=capture,
    )

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.WAITING
    emitted = [event[1] for event in store.events if event[0] == "runtime_event"]
    assert emitted == [
        {
            "action": "lease",
            "status": "started",
            "code": "LEASE_ACQUIRED",
        },
        {
            "action": "cycle",
            "status": "started",
            "code": "CYCLE_RESUMED",
            "cycle_ref": "cycle-001",
        },
        {
            "action": "stage",
            "status": "started",
            "code": "STAGE_STARTED",
            "cycle_ref": "cycle-001",
            "stage": stage.value,
            "attempt": 1,
        },
        {
            "action": "stage",
            "status": "waiting",
            "code": "PROVIDER_RETRY_DUE",
            "cycle_ref": "cycle-001",
            "stage": stage.value,
            "attempt": 1,
        },
        {
            "action": "cycle",
            "status": "waiting",
            "code": "PROVIDER_RETRY_DUE",
            "cycle_ref": "cycle-001",
        },
        {
            "action": "lease",
            "status": "released",
            "code": "LEASE_RELEASED",
        },
    ]
    finish_index = next(
        index for index, event in enumerate(store.events) if event[0] == "finish"
    )
    waiting_event_index = next(
        index
        for index, event in enumerate(store.events)
        if event[0] == "runtime_event" and event[1]["status"] == "waiting"
    )
    assert finish_index < waiting_event_index


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
    assert names[0:4] == [
        "lease",
        "observe_runtime",
        "cycle",
        "observe_cycle",
    ]
    for stage in AcquisitionRuntimeStage:
        begin = store.events.index(next(e for e in store.events if e[:3] == ("begin", "cycle-001", stage)))
        finish = store.events.index(next(e for e in store.events if e[:3] == ("finish", "cycle-001", stage)))
        observed_running = store.events.index(
            next(
                e
                for e in store.events[begin + 1 :]
                if e[:3] == ("observe_cycle", "runtime-owner-001", "cycle-001")
            ),
            begin + 1,
        )
        assert begin < observed_running < finish
        following = list(AcquisitionRuntimeStage)
        index = following.index(stage)
        if index + 1 < len(following):
            next_stage = following[index + 1]
            next_begin = store.events.index(
                next(e for e in store.events if e[:3] == ("begin", "cycle-001", next_stage))
            )
            assert finish < next_begin
    assert names[-3:] == ["finish_cycle", "observe_cycle", "release"]
    assert all(store.proposals[stage] is not None for stage in AcquisitionRuntimeStage)


def test_runner_passes_durable_stage_attempt_to_the_action_registry() -> None:
    stage = AcquisitionRuntimeStage.SIGNAL_SEED
    store = FakeStore()
    runner = _runner(
        store,
        outcomes={
            stage: RuntimeActionResult(
                status=RuntimeStageStatus.WAITING,
                reason_codes=("CHECKPOINT_REQUIRED",),
            )
        },
        proposals={stage: _proposal(stage)},
    )

    runner.run_once(_request())

    assert runner.registry.stage_snapshots[0] == RuntimeStageSnapshot(
        cycle_ref="cycle-001",
        stage=stage,
        status=RuntimeStageStatus.RUNNING,
        attempt_count=1,
        result_refs=("prior-result-001",),
    )


def test_cost_envelope_is_durable_before_hermes_is_called() -> None:
    stage = AcquisitionRuntimeStage.CONTACT_DISCOVERY
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": stage})
    )
    runner = _runner(
        store,
        outcomes={
            stage: RuntimeActionResult(
                status=RuntimeStageStatus.WAITING,
                reason_codes=("CHECKPOINT_REQUIRED",),
            )
        },
        proposals={stage: _proposal(stage)},
    )

    runner.run_once(_request())

    reserve_index = next(
        index for index, event in enumerate(store.events) if event[0] == "reserve"
    )
    propose_index = next(
        index for index, event in enumerate(store.events) if event[0] == "propose"
    )
    assert reserve_index < propose_index
    assert store.events[reserve_index][4] == Decimal("6")


def test_replay_uses_persisted_plan_without_calling_hermes_again() -> None:
    stage = AcquisitionRuntimeStage.CONTACT_DISCOVERY
    proposal = _proposal(stage)
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(
            update={"next_stage": stage, "spent_cost": Decimal("6")}
        ),
        reservations={(stage, 1): (Decimal("6"), proposal)},
    )
    runner = _runner(
        store,
        outcomes={
            stage: RuntimeActionResult(
                status=RuntimeStageStatus.WAITING,
                reason_codes=("CHECKPOINT_REQUIRED",),
            )
        },
        proposals={stage: proposal},
    )

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.WAITING
    assert runner.supervisor.calls == []
    assert runner.registry.calls == [(stage, stage.command, False)]
    assert store.cycle.spent_cost == Decimal("6")


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
            update={"next_stage": stage, "spent_cost": Decimal("9.90")}
        )
    )
    runner = _runner(
        store,
        outcomes={stage: RuntimeActionResult(status=RuntimeStageStatus.SUCCEEDED)},
        proposals={stage: _proposal(stage)},
    )

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.BLOCKED
    assert result.reason_code == "CYCLE_BUDGET_EXCEEDED"
    assert runner.registry.calls == []


def test_durably_exhausted_retry_budget_blocks_before_supervisor_or_registry() -> None:
    stage = AcquisitionRuntimeStage.SUPPLIER_DISCOVERY
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(
            update={"next_stage": stage, "spent_cost": Decimal("5")}
        )
    )
    runner = _runner(store, maximum_cost="5")

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.BLOCKED
    assert result.reason_code == "CYCLE_BUDGET_EXCEEDED"
    assert runner.supervisor.calls == []
    assert runner.registry.calls == []


def test_retry_before_durable_deadline_skips_hermes_registry_and_new_cost() -> None:
    stage = AcquisitionRuntimeStage.SUPPLIER_DISCOVERY

    @dataclass
    class DeferredStore(FakeStore):
        def begin_stage(
            self,
            cycle_ref,
            selected_stage,
            *,
            owner_ref,
            fencing_token,
            at,
        ):
            assert owner_ref == "runtime-owner-001" and fencing_token == 1
            self.events.append(("begin", cycle_ref, selected_stage, at))
            return RuntimeStageSnapshot(
                cycle_ref=cycle_ref,
                stage=selected_stage,
                status=RuntimeStageStatus.WAITING,
                attempt_count=1,
                retry_at=NOW + dt.timedelta(minutes=5),
            )

    store = DeferredStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": stage})
    )
    runner = _runner(store)

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.WAITING
    assert result.reason_code == "STAGE_RETRY_NOT_DUE"
    assert runner.supervisor.calls == []
    assert runner.registry.calls == []
    assert not any(event[0] == "reserve" for event in store.events)


def test_cumulative_durable_envelopes_block_before_next_expensive_stage() -> None:
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
            first: _proposal(first),
            second: _proposal(second),
        },
        maximum_cost="3",
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
        proposals={stage: _proposal(stage, cost=Decimal("2"))},
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


def test_failure_before_stage_ownership_does_not_invent_a_stage_transition() -> None:
    class BeginFailureStore(FakeStore):
        def begin_stage(
            self,
            cycle_ref,
            stage,
            *,
            owner_ref,
            fencing_token,
            at,
        ):
            assert owner_ref == "runtime-owner-001" and fencing_token == 1
            self.events.append(("begin_failed", cycle_ref, stage, at))
            raise RuntimeError("private-provider-marker")

    store = BeginFailureStore()
    runner = _runner(store)

    result = runner.run_once(_request())

    assert result.status is RuntimeRunStatus.FAILED
    assert result.reason_code == "CURRENT_RUN_TECHNICAL_FAILURE"
    assert not any(event[0] == "finish" for event in store.events)
    assert any(event[0] == "finish_cycle" for event in store.events)
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


def test_interruption_checkpoints_same_attempt_waiting_and_always_releases_lease() -> None:
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
    assert ("finish", "cycle-001", stage, RuntimeStageStatus.WAITING, NOW) in store.events
    checkpoint = store.finished_results[-1]
    assert checkpoint.retry_at == NOW + dt.timedelta(minutes=1)
    assert checkpoint.replay_same_attempt is True
    assert store.events[-1][0] == "release"


def test_interrupted_provider_stage_reuses_attempt_proposal_and_reservation() -> None:
    stage = AcquisitionRuntimeStage.ATTRIBUTION_CONVERSION
    store = FakeStore(
        cycle=DEFAULT_CYCLE.model_copy(update={"next_stage": stage})
    )

    class InterruptingRegistry(FakeRegistry):
        def execute(self, *args, **kwargs):
            super().execute(*args, **kwargs)
            raise InterruptedError

    first = _runner(store, outcomes={}, proposals={stage: _proposal(stage)})
    first.registry = InterruptingRegistry(
        {stage: RuntimeActionResult(status=RuntimeStageStatus.SUCCEEDED)}
    )

    interrupted = first.run_once(_request())
    assert interrupted.status is RuntimeRunStatus.CANCELLED

    completed = _runner(
        store,
        outcomes={stage: RuntimeActionResult(status=RuntimeStageStatus.SUCCEEDED)},
        proposals={stage: _proposal(stage)},
        clock=lambda: NOW + dt.timedelta(minutes=2),
    )
    result = completed.run_once(_request())

    assert result.status is RuntimeRunStatus.COMPLETED
    assert tuple(store.reservations) == ((stage, 1),)
    assert completed.supervisor.calls == []
    assert completed.registry.stage_snapshots[-1].attempt_count == 1


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
    times = iter(
        (
            NOW,
            NOW,
            NOW + dt.timedelta(seconds=61),
            NOW + dt.timedelta(seconds=61),
        )
    )
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
