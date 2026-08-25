"""One bounded, durable acquisition cycle over injected Kivou actions."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeCapabilityEvidence,
    RuntimeCycleSnapshot,
    RuntimeCycleStatus,
    RuntimeDependencyState,
    RuntimeHealthObservation,
    RuntimeLeaseResult,
    RuntimeProposal,
    RuntimeRunRequest,
    RuntimeRunResult,
    RuntimeRunStatus,
    RuntimeStageReservation,
    RuntimeStageSnapshot,
    RuntimeStageStatus,
    require_aware,
)
from signals.acquisition_runtime.events import emit_acquisition_runtime_event
from signals.acquisition_runtime.registry import RuntimeExecutionGuard
from signals.acquisition_runtime.supervisor import KIVOU_STAGE_COSTS


class RuntimeCycleStore(Protocol):
    def acquire_lease(
        self, owner_ref: str, *, acquired_at: dt.datetime, lease_seconds: int
    ) -> RuntimeLeaseResult: ...

    def execution_guard(
        self,
        owner_ref: str,
        *,
        fencing_token: int,
        lease_seconds: int,
    ) -> RuntimeExecutionGuard: ...

    def resume_or_create_cycle(
        self,
        *,
        owner_ref: str,
        fencing_token: int,
        opportunity_keys: tuple[str, ...],
        config_fingerprint: str,
        at: dt.datetime,
    ) -> RuntimeCycleSnapshot: ...

    def record_runtime_observation(
        self,
        owner_ref: str,
        capability: RuntimeCapabilityEvidence,
        *,
        fencing_token: int,
        at: dt.datetime,
    ) -> RuntimeHealthObservation: ...

    def record_cycle_observation(
        self,
        owner_ref: str,
        cycle_ref: str,
        *,
        fencing_token: int,
        at: dt.datetime,
    ) -> RuntimeHealthObservation: ...

    def begin_stage(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        *,
        owner_ref: str,
        fencing_token: int,
        at: dt.datetime,
    ) -> RuntimeStageSnapshot: ...

    def finish_stage(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        result: RuntimeActionResult,
        *,
        owner_ref: str,
        fencing_token: int,
        at: dt.datetime,
        proposal: RuntimeProposal | None = None,
    ) -> None: ...

    def reserve_stage_cost(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        stage_snapshot: RuntimeStageSnapshot,
        reserved_cost: Decimal,
        *,
        maximum_cycle_cost: Decimal,
        owner_ref: str,
        fencing_token: int,
        at: dt.datetime,
    ) -> RuntimeStageReservation: ...

    def bind_stage_proposal(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        stage_snapshot: RuntimeStageSnapshot,
        proposal: RuntimeProposal,
        *,
        owner_ref: str,
        fencing_token: int,
        at: dt.datetime,
    ) -> RuntimeProposal: ...

    def heartbeat_lease(
        self,
        owner_ref: str,
        *,
        fencing_token: int,
        at: dt.datetime,
        lease_seconds: int,
    ) -> None: ...

    def finish_cycle(
        self,
        cycle_ref: str,
        status: RuntimeCycleStatus,
        *,
        owner_ref: str,
        fencing_token: int,
        at: dt.datetime,
        reason_code: str | None = None,
    ) -> None: ...

    def release_lease(
        self,
        owner_ref: str,
        *,
        fencing_token: int,
        at: dt.datetime,
    ) -> None: ...


class RuntimeSupervisor(Protocol):
    def propose(
        self,
        stage: AcquisitionRuntimeStage,
        cycle: RuntimeCycleSnapshot,
        *,
        remaining_cost: Decimal,
        at: dt.datetime,
    ) -> RuntimeProposal: ...


class RuntimeActionRegistry(Protocol):
    def execute(
        self,
        stage: AcquisitionRuntimeStage,
        proposal: RuntimeProposal,
        cycle: RuntimeCycleSnapshot,
        *,
        stage_snapshot: RuntimeStageSnapshot,
        allow_qa_provider_mutations: bool,
        guard: RuntimeExecutionGuard,
        at: dt.datetime,
    ) -> RuntimeActionResult: ...


class AcquisitionRuntimeRunner:
    def __init__(
        self,
        *,
        store: RuntimeCycleStore,
        supervisor: RuntimeSupervisor,
        registry: RuntimeActionRegistry,
        allowed_opportunity_keys: tuple[str, ...],
        config_fingerprint: str,
        maximum_cycle_cost: Decimal,
        maximum_wall_seconds: int,
        lease_seconds: int,
        runtime_capability: RuntimeCapabilityEvidence,
        clock: Callable[[], dt.datetime],
        event_sink: Callable[..., None] = emit_acquisition_runtime_event,
    ) -> None:
        self.store = store
        self.supervisor = supervisor
        self.registry = registry
        self._opportunities = allowed_opportunity_keys
        self._config_fingerprint = config_fingerprint
        self._maximum_cost = maximum_cycle_cost
        self._maximum_wall = dt.timedelta(seconds=maximum_wall_seconds)
        self._lease_seconds = lease_seconds
        self._runtime_capability = runtime_capability
        self._clock = clock
        self._event = event_sink

    def run_once(self, request: RuntimeRunRequest) -> RuntimeRunResult:
        now = self._now()
        started_at = now
        lease = self.store.acquire_lease(
            request.owner_ref,
            acquired_at=now,
            lease_seconds=self._lease_seconds,
        )
        if not lease.owned:
            self._event(
                action="lease",
                status="already_running",
                code="LEASE_HELD",
            )
            return RuntimeRunResult(status=RuntimeRunStatus.ALREADY_RUNNING)
        assert lease.fencing_token is not None
        fencing_token = lease.fencing_token
        execution_guard = self.store.execution_guard(
            request.owner_ref,
            fencing_token=fencing_token,
            lease_seconds=self._lease_seconds,
        )
        self._event(
            action="lease",
            status="started",
            code="LEASE_ACQUIRED",
        )

        cycle: RuntimeCycleSnapshot | None = None
        current_stage: AcquisitionRuntimeStage | None = None
        current_attempt = 0
        try:
            self.store.record_runtime_observation(
                request.owner_ref,
                self._runtime_capability,
                fencing_token=fencing_token,
                at=now,
            )
            unavailable = next(
                (
                    dependency
                    for dependency in self._runtime_capability.dependencies
                    if dependency.status is RuntimeDependencyState.NOT_READY
                ),
                None,
            )
            if unavailable is not None:
                reason = unavailable.reason_codes[0]
                self._event(
                    action="cycle",
                    status="blocked",
                    code=reason,
                    stage=unavailable.stage.value,
                )
                return RuntimeRunResult(
                    status=RuntimeRunStatus.BLOCKED,
                    stage=unavailable.stage,
                    reason_code=reason,
                )
            cycle = self.store.resume_or_create_cycle(
                owner_ref=request.owner_ref,
                fencing_token=fencing_token,
                opportunity_keys=self._opportunities,
                config_fingerprint=self._config_fingerprint,
                at=now,
            )
            self.store.record_cycle_observation(
                request.owner_ref,
                cycle.cycle_ref,
                fencing_token=fencing_token,
                at=now,
            )
            self._event(
                action="cycle",
                status="started",
                code="CYCLE_RESUMED",
                cycle_ref=cycle.cycle_ref,
            )
            if cycle.next_stage is None:
                if cycle.status is RuntimeCycleStatus.SUPPRESSED:
                    self._emit_cycle(
                        cycle.cycle_ref,
                        RuntimeRunStatus.SUPPRESSED,
                        "CYCLE_SUPPRESSED",
                    )
                    return RuntimeRunResult(
                        status=RuntimeRunStatus.SUPPRESSED,
                        cycle_ref=cycle.cycle_ref,
                    )
                if cycle.status is RuntimeCycleStatus.SUCCEEDED:
                    self._emit_cycle(
                        cycle.cycle_ref,
                        RuntimeRunStatus.COMPLETED,
                        "CYCLE_SUCCEEDED",
                    )
                    return RuntimeRunResult(
                        status=RuntimeRunStatus.COMPLETED,
                        cycle_ref=cycle.cycle_ref,
                    )
                self.store.finish_cycle(
                    cycle.cycle_ref,
                    RuntimeCycleStatus.SUCCEEDED,
                    owner_ref=request.owner_ref,
                    fencing_token=fencing_token,
                    at=now,
                )
                self.store.record_cycle_observation(
                    request.owner_ref,
                    cycle.cycle_ref,
                    fencing_token=fencing_token,
                    at=now,
                )
                self._emit_cycle(
                    cycle.cycle_ref,
                    RuntimeRunStatus.COMPLETED,
                    "CYCLE_SUCCEEDED",
                )
                return RuntimeRunResult(
                    status=RuntimeRunStatus.COMPLETED,
                    cycle_ref=cycle.cycle_ref,
                )
            stages = tuple(AcquisitionRuntimeStage)
            start = stages.index(cycle.next_stage)
            spent = cycle.spent_cost
            for current_stage in stages[start:]:
                current_attempt = 0
                now = self._now()
                if now - started_at >= self._maximum_wall:
                    self.store.finish_cycle(
                        cycle.cycle_ref,
                        RuntimeCycleStatus.WAITING,
                        owner_ref=request.owner_ref,
                        fencing_token=fencing_token,
                        at=now,
                        reason_code="CYCLE_TIME_BUDGET_REACHED",
                    )
                    self.store.record_cycle_observation(
                        request.owner_ref,
                        cycle.cycle_ref,
                        fencing_token=fencing_token,
                        at=now,
                    )
                    self._emit_cycle(
                        cycle.cycle_ref,
                        RuntimeRunStatus.WAITING,
                        "CYCLE_TIME_BUDGET_REACHED",
                    )
                    return RuntimeRunResult(
                        status=RuntimeRunStatus.WAITING,
                        cycle_ref=cycle.cycle_ref,
                        stage=current_stage,
                        reason_code="CYCLE_TIME_BUDGET_REACHED",
                    )
                stage_snapshot = self.store.begin_stage(
                    cycle.cycle_ref,
                    current_stage,
                    owner_ref=request.owner_ref,
                    fencing_token=fencing_token,
                    at=now,
                )
                current_attempt = stage_snapshot.attempt_count
                if (
                    stage_snapshot.status is RuntimeStageStatus.WAITING
                    and stage_snapshot.retry_at is not None
                    and stage_snapshot.retry_at > now
                ):
                    self.store.record_cycle_observation(
                        request.owner_ref,
                        cycle.cycle_ref,
                        fencing_token=fencing_token,
                        at=now,
                    )
                    self._emit_cycle(
                        cycle.cycle_ref,
                        RuntimeRunStatus.WAITING,
                        "STAGE_RETRY_NOT_DUE",
                    )
                    return RuntimeRunResult(
                        status=RuntimeRunStatus.WAITING,
                        cycle_ref=cycle.cycle_ref,
                        stage=current_stage,
                        reason_code="STAGE_RETRY_NOT_DUE",
                    )
                self.store.record_cycle_observation(
                    request.owner_ref,
                    cycle.cycle_ref,
                    fencing_token=fencing_token,
                    at=now,
                )
                self._event(
                    action="stage",
                    status="started",
                    code="STAGE_STARTED",
                    cycle_ref=cycle.cycle_ref,
                    stage=current_stage.value,
                    attempt=stage_snapshot.attempt_count,
                )
                proposal: RuntimeProposal | None = None
                if (
                    current_stage is AcquisitionRuntimeStage.PROVIDER_HANDOFF
                    and not request.allow_qa_provider_mutations
                ):
                    action_result = RuntimeActionResult(
                        status=RuntimeStageStatus.WAITING,
                        reason_codes=("QA_PROVIDER_MUTATION_NOT_AUTHORIZED",),
                    )
                else:
                    stage_cycle = cycle.model_copy(
                        update={
                            "status": RuntimeCycleStatus.RUNNING,
                            "next_stage": current_stage,
                            "spent_cost": spent,
                        }
                    )
                    proposal, action_result, spent = self._execute_stage(
                        current_stage,
                        stage_cycle,
                        stage_snapshot=stage_snapshot,
                        request=request,
                        execution_guard=execution_guard,
                        fencing_token=fencing_token,
                        at=now,
                    )
                checkpoint_at = self._now()
                self.store.heartbeat_lease(
                    request.owner_ref,
                    fencing_token=fencing_token,
                    at=checkpoint_at,
                    lease_seconds=self._lease_seconds,
                )
                self.store.finish_stage(
                    cycle.cycle_ref,
                    current_stage,
                    action_result,
                    owner_ref=request.owner_ref,
                    fencing_token=fencing_token,
                    proposal=proposal,
                    at=checkpoint_at,
                )
                now = checkpoint_at
                self._emit_stage(
                    cycle.cycle_ref,
                    current_stage,
                    stage_snapshot.attempt_count,
                    action_result,
                )
                if action_result.status is RuntimeStageStatus.SUCCEEDED:
                    continue
                stopped = self._stop_result(
                    cycle.cycle_ref,
                    current_stage,
                    action_result,
                    owner_ref=request.owner_ref,
                    fencing_token=fencing_token,
                    at=now,
                )
                self.store.record_cycle_observation(
                    request.owner_ref,
                    cycle.cycle_ref,
                    fencing_token=fencing_token,
                    at=now,
                )
                self._emit_cycle(
                    cycle.cycle_ref,
                    stopped.status,
                    stopped.reason_code or "CYCLE_STOPPED",
                )
                return stopped
            self.store.finish_cycle(
                cycle.cycle_ref,
                RuntimeCycleStatus.SUCCEEDED,
                owner_ref=request.owner_ref,
                fencing_token=fencing_token,
                at=now,
            )
            self.store.record_cycle_observation(
                request.owner_ref,
                cycle.cycle_ref,
                fencing_token=fencing_token,
                at=now,
            )
            self._emit_cycle(
                cycle.cycle_ref,
                RuntimeRunStatus.COMPLETED,
                "CYCLE_SUCCEEDED",
            )
            return RuntimeRunResult(
                status=RuntimeRunStatus.COMPLETED,
                cycle_ref=cycle.cycle_ref,
            )
        except InterruptedError:
            if cycle is None or current_stage is None:
                raise
            cancelled = RuntimeActionResult(
                status=RuntimeStageStatus.CANCELLED,
                reason_codes=("CURRENT_RUN_INTERRUPTED",),
            )
            self.store.finish_stage(
                cycle.cycle_ref,
                current_stage,
                cancelled,
                owner_ref=request.owner_ref,
                fencing_token=fencing_token,
                at=now,
            )
            self.store.finish_cycle(
                cycle.cycle_ref,
                RuntimeCycleStatus.CANCELLED,
                owner_ref=request.owner_ref,
                fencing_token=fencing_token,
                at=now,
                reason_code="CURRENT_RUN_INTERRUPTED",
            )
            self.store.record_cycle_observation(
                request.owner_ref,
                cycle.cycle_ref,
                fencing_token=fencing_token,
                at=now,
            )
            self._emit_stage(
                cycle.cycle_ref,
                current_stage,
                current_attempt,
                cancelled,
            )
            self._emit_cycle(
                cycle.cycle_ref,
                RuntimeRunStatus.CANCELLED,
                "CURRENT_RUN_INTERRUPTED",
            )
            return RuntimeRunResult(
                status=RuntimeRunStatus.CANCELLED,
                cycle_ref=cycle.cycle_ref,
                stage=current_stage,
                reason_code="CURRENT_RUN_INTERRUPTED",
            )
        except Exception:  # noqa: BLE001 - provider/configuration detail is private
            if cycle is not None:
                failed = RuntimeActionResult(
                    status=RuntimeStageStatus.FAILED,
                    reason_codes=("CURRENT_RUN_TECHNICAL_FAILURE",),
                )
                if current_stage is not None and current_attempt > 0:
                    self.store.finish_stage(
                        cycle.cycle_ref,
                        current_stage,
                        failed,
                        owner_ref=request.owner_ref,
                        fencing_token=fencing_token,
                        at=now,
                    )
                self.store.finish_cycle(
                    cycle.cycle_ref,
                    RuntimeCycleStatus.FAILED,
                    owner_ref=request.owner_ref,
                    fencing_token=fencing_token,
                    at=now,
                    reason_code="CURRENT_RUN_TECHNICAL_FAILURE",
                )
                self.store.record_cycle_observation(
                    request.owner_ref,
                    cycle.cycle_ref,
                    fencing_token=fencing_token,
                    at=now,
                )
                if current_stage is not None and current_attempt > 0:
                    self._emit_stage(
                        cycle.cycle_ref,
                        current_stage,
                        current_attempt,
                        failed,
                    )
                self._emit_cycle(
                    cycle.cycle_ref,
                    RuntimeRunStatus.FAILED,
                    "CURRENT_RUN_TECHNICAL_FAILURE",
                )
                return RuntimeRunResult(
                    status=RuntimeRunStatus.FAILED,
                    cycle_ref=cycle.cycle_ref,
                    stage=current_stage,
                    reason_code="CURRENT_RUN_TECHNICAL_FAILURE",
                )
            self._event(
                action="cycle",
                status="failed",
                code="CURRENT_RUN_TECHNICAL_FAILURE",
            )
            return RuntimeRunResult(
                status=RuntimeRunStatus.FAILED,
                reason_code="CURRENT_RUN_TECHNICAL_FAILURE",
            )
        finally:
            self.store.release_lease(
                request.owner_ref,
                fencing_token=fencing_token,
                at=now,
            )
            self._event(
                action="lease",
                status="released",
                code="LEASE_RELEASED",
            )

    def _execute_stage(
        self,
        stage: AcquisitionRuntimeStage,
        cycle: RuntimeCycleSnapshot,
        *,
        stage_snapshot: RuntimeStageSnapshot,
        request: RuntimeRunRequest,
        execution_guard: RuntimeExecutionGuard,
        fencing_token: int,
        at: dt.datetime,
    ) -> tuple[RuntimeProposal | None, RuntimeActionResult, Decimal]:
        envelope = KIVOU_STAGE_COSTS[stage]
        reservation = self.store.reserve_stage_cost(
            cycle.cycle_ref,
            stage,
            stage_snapshot,
            envelope,
            maximum_cycle_cost=self._maximum_cost,
            owner_ref=request.owner_ref,
            fencing_token=fencing_token,
            at=at,
        )
        if not reservation.accepted:
            return (
                None,
                RuntimeActionResult(
                    status=RuntimeStageStatus.BLOCKED,
                    reason_codes=("CYCLE_BUDGET_EXCEEDED",),
                ),
                reservation.total_cycle_cost,
            )
        remaining_before_current = (
            self._maximum_cost
            - reservation.total_cycle_cost
            + reservation.reserved_cost
        )
        proposal = reservation.proposal
        if proposal is None:
            proposal = self.supervisor.propose(
                stage,
                cycle.model_copy(
                    update={"spent_cost": reservation.total_cycle_cost}
                ),
                remaining_cost=remaining_before_current,
                at=at,
            )
            proposal = self.store.bind_stage_proposal(
                cycle.cycle_ref,
                stage,
                stage_snapshot,
                proposal,
                owner_ref=request.owner_ref,
                fencing_token=fencing_token,
                at=at,
            )
        if proposal.command != stage.command:
            return (
                proposal,
                RuntimeActionResult(
                    status=RuntimeStageStatus.BLOCKED,
                    reason_codes=("SUPERVISOR_ACTION_MISMATCH",),
                ),
                reservation.total_cycle_cost,
            )
        if proposal.estimated_cost != envelope:
            return (
                proposal,
                RuntimeActionResult(
                    status=RuntimeStageStatus.BLOCKED,
                    reason_codes=("CYCLE_BUDGET_EXCEEDED",),
                ),
                reservation.total_cycle_cost,
            )
        result = self.registry.execute(
            stage,
            proposal,
            cycle,
            stage_snapshot=stage_snapshot,
            allow_qa_provider_mutations=request.allow_qa_provider_mutations,
            guard=execution_guard,
            at=at,
        )
        if result.observed_cost > remaining_before_current:
            return (
                proposal,
                result.model_copy(
                    update={
                        "status": RuntimeStageStatus.FAILED,
                        "reserved_cost": proposal.estimated_cost,
                        "reason_codes": ("OBSERVED_CYCLE_COST_EXCEEDED",),
                    }
                ),
                reservation.total_cycle_cost,
            )
        return (
            proposal,
            result.model_copy(update={"reserved_cost": proposal.estimated_cost}),
            max(
                reservation.total_cycle_cost,
                reservation.total_cycle_cost
                - reservation.reserved_cost
                + result.observed_cost,
            ),
        )

    def _stop_result(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        action_result: RuntimeActionResult,
        *,
        owner_ref: str,
        fencing_token: int,
        at: dt.datetime,
    ) -> RuntimeRunResult:
        mappings = {
            RuntimeStageStatus.WAITING: (
                RuntimeCycleStatus.WAITING,
                RuntimeRunStatus.WAITING,
            ),
            RuntimeStageStatus.BLOCKED: (
                RuntimeCycleStatus.BLOCKED,
                RuntimeRunStatus.BLOCKED,
            ),
            RuntimeStageStatus.FAILED: (
                RuntimeCycleStatus.FAILED,
                RuntimeRunStatus.FAILED,
            ),
            RuntimeStageStatus.SUPPRESSED: (
                RuntimeCycleStatus.SUPPRESSED,
                RuntimeRunStatus.SUPPRESSED,
            ),
            RuntimeStageStatus.CANCELLED: (
                RuntimeCycleStatus.CANCELLED,
                RuntimeRunStatus.CANCELLED,
            ),
        }
        cycle_status, run_status = mappings[action_result.status]
        reason = action_result.reason_codes[0]
        self.store.finish_cycle(
            cycle_ref,
            cycle_status,
            owner_ref=owner_ref,
            fencing_token=fencing_token,
            at=at,
            reason_code=reason,
        )
        return RuntimeRunResult(
            status=run_status,
            cycle_ref=cycle_ref,
            stage=stage,
            reason_code=reason,
        )

    def _now(self) -> dt.datetime:
        return require_aware(self._clock())

    def _emit_stage(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        attempt: int,
        result: RuntimeActionResult,
    ) -> None:
        status = result.status.value.casefold()
        code = (
            result.reason_codes[0]
            if result.reason_codes
            else "STAGE_SUCCEEDED"
        )
        self._event(
            action="stage",
            status=status,
            code=code,
            cycle_ref=cycle_ref,
            stage=stage.value,
            attempt=attempt,
        )

    def _emit_cycle(
        self,
        cycle_ref: str,
        status: RuntimeRunStatus,
        code: str,
    ) -> None:
        normalized = (
            "succeeded"
            if status is RuntimeRunStatus.COMPLETED
            else status.value.casefold()
        )
        self._event(
            action="cycle",
            status=normalized,
            code=code,
            cycle_ref=cycle_ref,
        )


__all__ = ["AcquisitionRuntimeRunner"]
