"""One bounded, durable acquisition cycle over injected Kivou actions."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeCycleSnapshot,
    RuntimeCycleStatus,
    RuntimeLeaseResult,
    RuntimeProposal,
    RuntimeRunRequest,
    RuntimeRunResult,
    RuntimeRunStatus,
    RuntimeStageSnapshot,
    RuntimeStageStatus,
    require_aware,
)


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
        clock: Callable[[], dt.datetime],
    ) -> None:
        self.store = store
        self.supervisor = supervisor
        self.registry = registry
        self._opportunities = allowed_opportunity_keys
        self._config_fingerprint = config_fingerprint
        self._maximum_cost = maximum_cycle_cost
        self._maximum_wall = dt.timedelta(seconds=maximum_wall_seconds)
        self._lease_seconds = lease_seconds
        self._clock = clock

    def run_once(self, request: RuntimeRunRequest) -> RuntimeRunResult:
        now = self._now()
        started_at = now
        lease = self.store.acquire_lease(
            request.owner_ref,
            acquired_at=now,
            lease_seconds=self._lease_seconds,
        )
        if not lease.owned:
            return RuntimeRunResult(status=RuntimeRunStatus.ALREADY_RUNNING)

        cycle: RuntimeCycleSnapshot | None = None
        current_stage: AcquisitionRuntimeStage | None = None
        try:
            cycle = self.store.resume_or_create_cycle(
                opportunity_keys=self._opportunities,
                config_fingerprint=self._config_fingerprint,
                at=now,
            )
            if cycle.next_stage is None:
                if cycle.status is RuntimeCycleStatus.SUPPRESSED:
                    return RuntimeRunResult(
                        status=RuntimeRunStatus.SUPPRESSED,
                        cycle_ref=cycle.cycle_ref,
                    )
                if cycle.status is RuntimeCycleStatus.SUCCEEDED:
                    return RuntimeRunResult(
                        status=RuntimeRunStatus.COMPLETED,
                        cycle_ref=cycle.cycle_ref,
                    )
                self.store.finish_cycle(
                    cycle.cycle_ref, RuntimeCycleStatus.SUCCEEDED, at=now
                )
                return RuntimeRunResult(
                    status=RuntimeRunStatus.COMPLETED,
                    cycle_ref=cycle.cycle_ref,
                )
            stages = tuple(AcquisitionRuntimeStage)
            start = stages.index(cycle.next_stage)
            spent = cycle.spent_cost
            for current_stage in stages[start:]:
                now = self._now()
                if now - started_at >= self._maximum_wall:
                    self.store.finish_cycle(
                        cycle.cycle_ref,
                        RuntimeCycleStatus.WAITING,
                        at=now,
                        reason_code="CYCLE_TIME_BUDGET_REACHED",
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
                if action_result.status is RuntimeStageStatus.SUCCEEDED:
                    spent += max(
                        action_result.reserved_cost,
                        action_result.observed_cost,
                    )
                    continue
                return self._stop_result(
                    cycle.cycle_ref, current_stage, action_result, at=now
                )
            self.store.finish_cycle(
                cycle.cycle_ref, RuntimeCycleStatus.SUCCEEDED, at=now
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
            return RuntimeRunResult(
                status=RuntimeRunStatus.CANCELLED,
                cycle_ref=cycle.cycle_ref,
                stage=current_stage,
                reason_code="CURRENT_RUN_INTERRUPTED",
            )
        except Exception:  # noqa: BLE001 - provider/configuration detail is private
            if cycle is not None and current_stage is not None:
                failed = RuntimeActionResult(
                    status=RuntimeStageStatus.FAILED,
                    reason_codes=("CURRENT_RUN_TECHNICAL_FAILURE",),
                )
                self.store.finish_stage(
                    cycle.cycle_ref, current_stage, failed, at=now
                )
                self.store.finish_cycle(
                    cycle.cycle_ref,
                    RuntimeCycleStatus.FAILED,
                    at=now,
                    reason_code="CURRENT_RUN_TECHNICAL_FAILURE",
                )
                return RuntimeRunResult(
                    status=RuntimeRunStatus.FAILED,
                    cycle_ref=cycle.cycle_ref,
                    stage=current_stage,
                    reason_code="CURRENT_RUN_TECHNICAL_FAILURE",
                )
            return RuntimeRunResult(
                status=RuntimeRunStatus.FAILED,
                reason_code="CURRENT_RUN_TECHNICAL_FAILURE",
            )
        finally:
            self.store.release_lease(request.owner_ref, at=now)

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


__all__ = ["AcquisitionRuntimeRunner"]
