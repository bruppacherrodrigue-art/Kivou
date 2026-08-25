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
    RuntimeHealthObservation,
    RuntimeLeaseResult,
    RuntimeProposal,
    RuntimeRunRequest,
    RuntimeRunResult,
    RuntimeRunStatus,
    RuntimeStageSnapshot,
    RuntimeStageStatus,
    require_aware,
)
from signals.acquisition_runtime.events import emit_acquisition_runtime_event


class RuntimeCycleStore(Protocol):
    def acquire_lease(
        self, owner_ref: str, *, acquired_at: dt.datetime, lease_seconds: int
    ) -> RuntimeLeaseResult: ...

    def resume_or_create_cycle(
        self,
        *,
        opportunity_keys: tuple[str, ...],
        config_fingerprint: str,
        at: dt.datetime,
    ) -> RuntimeCycleSnapshot: ...

    def record_runtime_observation(
        self,
        owner_ref: str,
        capability: RuntimeCapabilityEvidence,
        *,
        at: dt.datetime,
    ) -> RuntimeHealthObservation: ...

    def record_cycle_observation(
        self,
        owner_ref: str,
        cycle_ref: str,
        *,
        at: dt.datetime,
    ) -> RuntimeHealthObservation: ...

    def begin_stage(
        self, cycle_ref: str, stage: AcquisitionRuntimeStage, *, at: dt.datetime
    ) -> RuntimeStageSnapshot: ...

    def finish_stage(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        result: RuntimeActionResult,
        *,
        at: dt.datetime,
        proposal: RuntimeProposal | None = None,
    ) -> None: ...

    def heartbeat_lease(
        self, owner_ref: str, *, at: dt.datetime, lease_seconds: int
    ) -> None: ...

    def finish_cycle(
        self,
        cycle_ref: str,
        status: RuntimeCycleStatus,
        *,
        at: dt.datetime,
        reason_code: str | None = None,
    ) -> None: ...

    def release_lease(self, owner_ref: str, *, at: dt.datetime) -> None: ...


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
                at=now,
            )
            cycle = self.store.resume_or_create_cycle(
                opportunity_keys=self._opportunities,
                config_fingerprint=self._config_fingerprint,
                at=now,
            )
            self.store.record_cycle_observation(
                request.owner_ref,
                cycle.cycle_ref,
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
                    cycle.cycle_ref, RuntimeCycleStatus.SUCCEEDED, at=now
                )
                self.store.record_cycle_observation(
                    request.owner_ref,
                    cycle.cycle_ref,
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
                        at=now,
                        reason_code="CYCLE_TIME_BUDGET_REACHED",
                    )
                    self.store.record_cycle_observation(
                        request.owner_ref,
                        cycle.cycle_ref,
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
                    cycle.cycle_ref, current_stage, at=now
                )
                current_attempt = stage_snapshot.attempt_count
                self.store.record_cycle_observation(
                    request.owner_ref,
                    cycle.cycle_ref,
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
                    proposal, action_result = self._execute_stage(
                        current_stage,
                        cycle,
                        stage_snapshot=stage_snapshot,
                        remaining_cost=self._maximum_cost - spent,
                        request=request,
                        at=now,
                    )
                self.store.finish_stage(
                    cycle.cycle_ref,
                    current_stage,
                    action_result,
                    proposal=proposal,
                    at=now,
                )
                self.store.heartbeat_lease(
                    request.owner_ref,
                    at=now,
                    lease_seconds=self._lease_seconds,
                )
                self._emit_stage(
                    cycle.cycle_ref,
                    current_stage,
                    stage_snapshot.attempt_count,
                    action_result,
                )
                if action_result.status is RuntimeStageStatus.SUCCEEDED:
                    spent += max(
                        action_result.reserved_cost,
                        action_result.observed_cost,
                    )
                    continue
                stopped = self._stop_result(
                    cycle.cycle_ref, current_stage, action_result, at=now
                )
                self.store.record_cycle_observation(
                    request.owner_ref,
                    cycle.cycle_ref,
                    at=now,
                )
                self._emit_cycle(
                    cycle.cycle_ref,
                    stopped.status,
                    stopped.reason_code or "CYCLE_STOPPED",
                )
                return stopped
            self.store.finish_cycle(
                cycle.cycle_ref, RuntimeCycleStatus.SUCCEEDED, at=now
            )
            self.store.record_cycle_observation(
                request.owner_ref,
                cycle.cycle_ref,
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
                cycle.cycle_ref, current_stage, cancelled, at=now
            )
            self.store.finish_cycle(
                cycle.cycle_ref,
                RuntimeCycleStatus.CANCELLED,
                at=now,
                reason_code="CURRENT_RUN_INTERRUPTED",
            )
            self.store.record_cycle_observation(
                request.owner_ref,
                cycle.cycle_ref,
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
                        cycle.cycle_ref, current_stage, failed, at=now
                    )
                self.store.finish_cycle(
                    cycle.cycle_ref,
                    RuntimeCycleStatus.FAILED,
                    at=now,
                    reason_code="CURRENT_RUN_TECHNICAL_FAILURE",
                )
                self.store.record_cycle_observation(
                    request.owner_ref,
                    cycle.cycle_ref,
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
            self.store.release_lease(request.owner_ref, at=now)
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
        remaining_cost: Decimal,
        request: RuntimeRunRequest,
        at: dt.datetime,
    ) -> tuple[RuntimeProposal, RuntimeActionResult]:
        proposal = self.supervisor.propose(
            stage, cycle, remaining_cost=remaining_cost, at=at
        )
        if proposal.command != stage.command:
            return (
                proposal,
                RuntimeActionResult(
                    status=RuntimeStageStatus.BLOCKED,
                    reason_codes=("SUPERVISOR_ACTION_MISMATCH",),
                ),
            )
        if proposal.estimated_cost > remaining_cost:
            return (
                proposal,
                RuntimeActionResult(
                    status=RuntimeStageStatus.BLOCKED,
                    reason_codes=("CYCLE_BUDGET_EXCEEDED",),
                ),
            )
        result = self.registry.execute(
            stage,
            proposal,
            cycle,
            stage_snapshot=stage_snapshot,
            allow_qa_provider_mutations=request.allow_qa_provider_mutations,
            at=at,
        )
        if result.observed_cost > remaining_cost:
            return (
                proposal,
                result.model_copy(
                    update={
                        "status": RuntimeStageStatus.FAILED,
                        "reserved_cost": proposal.estimated_cost,
                        "reason_codes": ("OBSERVED_CYCLE_COST_EXCEEDED",),
                    }
                ),
            )
        return (
            proposal,
            result.model_copy(update={"reserved_cost": proposal.estimated_cost}),
        )

    def _stop_result(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        action_result: RuntimeActionResult,
        *,
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
            cycle_ref, cycle_status, at=at, reason_code=reason
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
