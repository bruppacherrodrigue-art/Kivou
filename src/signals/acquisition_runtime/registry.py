"""Closed Kivou-owned executable registry for acquisition runtime stages."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeCycleSnapshot,
    RuntimeProposal,
    RuntimeStageSnapshot,
    RuntimeStageStatus,
    require_aware,
)


class AcquisitionRegistryConfigurationError(RuntimeError):
    """The local executable registry is incomplete or has unknown stages."""


class RuntimeExecutionGuard(Protocol):
    """Hold the durable runtime fence across one business side effect."""

    def protect(self) -> AbstractContextManager[dt.datetime]: ...


@dataclass(frozen=True)
class AcquisitionActionContext:
    stage: AcquisitionRuntimeStage
    proposal: RuntimeProposal
    cycle: RuntimeCycleSnapshot
    stage_snapshot: RuntimeStageSnapshot
    allow_qa_provider_mutations: bool
    guard: RuntimeExecutionGuard
    at: dt.datetime


AcquisitionActionHandler = Callable[[AcquisitionActionContext], RuntimeActionResult]


class AcquisitionActionRegistry:
    """Dispatch exact, typed Kivou actions; never arbitrary tools or callables."""

    def __init__(
        self,
        handlers: Mapping[AcquisitionRuntimeStage, AcquisitionActionHandler],
    ) -> None:
        if set(handlers) != set(AcquisitionRuntimeStage):
            raise AcquisitionRegistryConfigurationError(
                "runtime registry requires the complete closed stage set"
            )
        self._handlers = dict(handlers)
        self.commands = tuple(stage.command for stage in AcquisitionRuntimeStage)
        canonical = json.dumps(
            [
                {"stage": stage.value, "command": stage.command}
                for stage in AcquisitionRuntimeStage
            ],
            separators=(",", ":"),
            sort_keys=True,
        )
        self.identity = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def execute(
        self,
        stage: AcquisitionRuntimeStage,
        proposal: RuntimeProposal,
        cycle: RuntimeCycleSnapshot,
        *,
        stage_snapshot: RuntimeStageSnapshot,
        allow_qa_provider_mutations: bool,
        guard: RuntimeExecutionGuard | None,
        at: dt.datetime,
    ) -> RuntimeActionResult:
        observed_at = require_aware(at)
        if proposal.command != stage.command:
            return RuntimeActionResult(
                status=RuntimeStageStatus.BLOCKED,
                reason_codes=("REGISTRY_COMMAND_MISMATCH",),
            )
        if proposal.target_ref != cycle.cycle_ref:
            return RuntimeActionResult(
                status=RuntimeStageStatus.BLOCKED,
                reason_codes=("REGISTRY_TARGET_MISMATCH",),
            )
        if (
            stage is AcquisitionRuntimeStage.PROVIDER_HANDOFF
            and not allow_qa_provider_mutations
        ):
            return RuntimeActionResult(
                status=RuntimeStageStatus.WAITING,
                reason_codes=("QA_PROVIDER_MUTATION_NOT_AUTHORIZED",),
            )
        if guard is None:
            return RuntimeActionResult(
                status=RuntimeStageStatus.BLOCKED,
                reason_codes=("RUNTIME_FENCE_MISSING",),
            )
        return self._handlers[stage](
            AcquisitionActionContext(
                stage=stage,
                proposal=proposal,
                cycle=cycle,
                stage_snapshot=stage_snapshot,
                allow_qa_provider_mutations=allow_qa_provider_mutations,
                guard=guard,
                at=observed_at,
            )
        )


__all__ = [
    "AcquisitionActionContext",
    "AcquisitionActionHandler",
    "AcquisitionActionRegistry",
    "AcquisitionRegistryConfigurationError",
    "RuntimeExecutionGuard",
]
