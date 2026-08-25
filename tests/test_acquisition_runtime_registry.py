from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeCycleSnapshot,
    RuntimeCycleStatus,
    RuntimeProposal,
    RuntimeStageSnapshot,
    RuntimeStageStatus,
)
from signals.acquisition_runtime.registry import (
    AcquisitionActionContext,
    AcquisitionActionRegistry,
    AcquisitionRegistryConfigurationError,
)

NOW = dt.datetime(2026, 8, 25, 12, tzinfo=dt.UTC)
CYCLE = RuntimeCycleSnapshot(
    cycle_ref="cycle-001",
    opportunity_key="signal-001",
    status=RuntimeCycleStatus.RUNNING,
    next_stage=AcquisitionRuntimeStage.SIGNAL_SEED,
    spent_cost=Decimal("0"),
    started_at=NOW,
)
STAGE_SNAPSHOT = RuntimeStageSnapshot(
    cycle_ref=CYCLE.cycle_ref,
    stage=AcquisitionRuntimeStage.SIGNAL_SEED,
    status=RuntimeStageStatus.RUNNING,
    attempt_count=1,
    result_refs=("prior-result-001",),
)


def _proposal(stage: AcquisitionRuntimeStage, **updates) -> RuntimeProposal:
    values = {
        "plan_ref": "plan-001",
        "action_index": 0,
        "command": stage.command,
        "target_ref": "signal-001",
        "argument_fingerprint": "a" * 64,
        "estimated_cost": Decimal("0.25"),
        "reason_codes": ("QA_RUNTIME_STEP",),
        "evidence_refs": ("evidence-001",),
    }
    values.update(updates)
    return RuntimeProposal(**values)


def _handlers(calls: list[AcquisitionActionContext]):
    def handler(context: AcquisitionActionContext) -> RuntimeActionResult:
        calls.append(context)
        return RuntimeActionResult(
            status=RuntimeStageStatus.SUCCEEDED,
            result_refs=(f"result-{context.stage.value.lower()}",),
            observed_cost=Decimal("0.10"),
        )

    return {stage: handler for stage in AcquisitionRuntimeStage}


def test_registry_requires_one_typed_handler_for_every_stage() -> None:
    calls: list[AcquisitionActionContext] = []
    handlers = _handlers(calls)
    handlers.pop(AcquisitionRuntimeStage.RESPONSE)

    with pytest.raises(
        AcquisitionRegistryConfigurationError, match="complete closed stage set"
    ):
        AcquisitionActionRegistry(handlers)


def test_registry_executes_only_the_exact_stage_command_and_target() -> None:
    calls: list[AcquisitionActionContext] = []
    registry = AcquisitionActionRegistry(_handlers(calls))
    stage = AcquisitionRuntimeStage.SUPPLIER_DISCOVERY

    result = registry.execute(
        stage,
        _proposal(stage),
        CYCLE,
        stage_snapshot=STAGE_SNAPSHOT.model_copy(update={"stage": stage}),
        allow_qa_provider_mutations=False,
        at=NOW,
    )

    assert result.status is RuntimeStageStatus.SUCCEEDED
    assert len(calls) == 1
    assert calls[0].stage is stage
    assert calls[0].cycle == CYCLE
    assert calls[0].stage_snapshot.attempt_ref
    assert calls[0].stage_snapshot.result_refs == ("prior-result-001",)
    assert calls[0].allow_qa_provider_mutations is False


@pytest.mark.parametrize(
    ("proposal", "reason"),
    (
        (
            _proposal(
                AcquisitionRuntimeStage.DECISION,
                command="pause_campaign",
            ),
            "REGISTRY_COMMAND_MISMATCH",
        ),
        (
            _proposal(
                AcquisitionRuntimeStage.DECISION,
                target_ref="another-signal",
            ),
            "REGISTRY_TARGET_MISMATCH",
        ),
    ),
)
def test_registry_fails_closed_before_handler(
    proposal: RuntimeProposal, reason: str
) -> None:
    calls: list[AcquisitionActionContext] = []
    registry = AcquisitionActionRegistry(_handlers(calls))

    result = registry.execute(
        AcquisitionRuntimeStage.DECISION,
        proposal,
        CYCLE,
        stage_snapshot=STAGE_SNAPSHOT.model_copy(
            update={"stage": AcquisitionRuntimeStage.DECISION}
        ),
        allow_qa_provider_mutations=False,
        at=NOW,
    )

    assert result.status is RuntimeStageStatus.BLOCKED
    assert result.reason_codes == (reason,)
    assert calls == []


def test_provider_handoff_requires_current_explicit_qa_authorization() -> None:
    calls: list[AcquisitionActionContext] = []
    registry = AcquisitionActionRegistry(_handlers(calls))
    stage = AcquisitionRuntimeStage.PROVIDER_HANDOFF

    result = registry.execute(
        stage,
        _proposal(stage),
        CYCLE,
        stage_snapshot=STAGE_SNAPSHOT.model_copy(update={"stage": stage}),
        allow_qa_provider_mutations=False,
        at=NOW,
    )

    assert result.status is RuntimeStageStatus.WAITING
    assert result.reason_codes == ("QA_PROVIDER_MUTATION_NOT_AUTHORIZED",)
    assert calls == []


def test_registry_identity_is_deterministic_and_contains_no_callable_repr() -> None:
    first = AcquisitionActionRegistry(_handlers([]))
    second = AcquisitionActionRegistry(_handlers([]))

    assert first.identity == second.identity
    assert len(first.identity) == 64
    assert first.commands == tuple(stage.command for stage in AcquisitionRuntimeStage)
    assert "handler" not in repr(first)
