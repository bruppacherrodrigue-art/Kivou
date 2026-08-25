from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeCycleSnapshot,
    RuntimeCycleStatus,
)
from signals.acquisition_runtime.registry import AcquisitionActionRegistry
from signals.acquisition_runtime.supervisor import (
    KIVOU_STAGE_COSTS,
    AcquisitionHermesSupervisor,
)
from signals.policy.registry import COMMAND_POLICIES, RiskClass, TargetScope
from signals.supervisor.contracts import ProposedAction, SupervisorPlan
from signals.supervisor.pin import load_hermes_pin
from signals.supervisor.profile import PROFILE_VERSION
from signals.supervisor.registry import ALLOWED_COMMANDS
from signals.supervisor.runtime import (
    HealthState,
    SupervisorHealth,
    SupervisorUnavailable,
    SupervisorValidationError,
    SupervisorVersionMismatch,
)

NOW = dt.datetime(2026, 8, 25, 12, tzinfo=dt.UTC)
PIN = load_hermes_pin()
CYCLE = RuntimeCycleSnapshot(
    cycle_ref="cycle-runtime-001",
    opportunity_key="opportunity-001",
    status=RuntimeCycleStatus.RUNNING,
    next_stage=AcquisitionRuntimeStage.SUPPLIER_DISCOVERY,
    spent_cost=Decimal("0"),
    started_at=NOW,
)


@dataclass
class ClosedRegistry:
    identity: str = "a" * 64
    commands: tuple[str, ...] = tuple(stage.command for stage in AcquisitionRuntimeStage)


@dataclass
class FakeSupervisor:
    response: SupervisorPlan
    runtime_health: SupervisorHealth = field(
        default_factory=lambda: SupervisorHealth(
            state=HealthState.AVAILABLE,
            hermes_version=PIN.version,
            source_commit=PIN.commit,
            executable_tools=(),
        )
    )
    contexts: list[object] = field(default_factory=list)

    def health(self) -> SupervisorHealth:
        return self.runtime_health

    def plan(self, context):
        self.contexts.append(context)
        return self.response


def _plan(
    *,
    command: str = AcquisitionRuntimeStage.SUPPLIER_DISCOVERY.command,
    target_ref: str = CYCLE.cycle_ref,
    action_cost: str = "0.25",
    plan_cost: str | None = None,
    actions: int = 1,
    supervisor_version: str | None = None,
    skill_version: str = PROFILE_VERSION,
) -> SupervisorPlan:
    proposed = tuple(
        ProposedAction(
            command=command,
            target_ref=target_ref,
            arguments={"model_payload": "must-not-cross-the-boundary"},
            reason_codes=("MODEL_REASON",),
            evidence_refs=("model-evidence",),
            estimated_cost=Decimal(action_cost),
        )
        for _ in range(actions)
    )
    return SupervisorPlan(
        plan_id="hermes-plan-001",
        created_at=NOW,
        objective="Bounded action",
        priority=1,
        proposed_actions=proposed,
        reason_codes=("MODEL_PLAN",),
        confidence=Decimal("0.8"),
        estimated_cost=Decimal(plan_cost if plan_cost is not None else action_cost) * actions,
        next_review_at=NOW + dt.timedelta(minutes=5),
        supervisor_version=supervisor_version or f"hermes-agent-{PIN.version}",
        skill_version=skill_version,
    )


def test_supervisor_command_allowlist_covers_the_closed_runtime_registry() -> None:
    assert {stage.command for stage in AcquisitionRuntimeStage}.issubset(ALLOWED_COMMANDS)


def test_new_runtime_commands_have_closed_fail_safe_policy_profiles() -> None:
    seed = COMMAND_POLICIES[AcquisitionRuntimeStage.SIGNAL_SEED.command]
    assert seed.risk_class is RiskClass.READ_ONLY
    assert seed.target_scope is TargetScope.EITHER

    provider = COMMAND_POLICIES[AcquisitionRuntimeStage.PROVIDER_HANDOFF.command]
    assert provider.risk_class is RiskClass.COMMERCIAL_MUTATION
    assert provider.target_scope is TargetScope.OPPORTUNITY
    assert provider.uses_budget is True
    assert provider.uses_volume is True
    assert provider.uses_provider_quota is True
    assert provider.uses_send_controls is True
    assert provider.requires_control_plane is True
    assert provider.requires_compliance is True

    conversion = COMMAND_POLICIES[
        AcquisitionRuntimeStage.ATTRIBUTION_CONVERSION.command
    ]
    assert conversion.risk_class is RiskClass.PREPARATORY
    assert conversion.target_scope is TargetScope.OPPORTUNITY


def test_allowed_hermes_plan_becomes_one_fingerprinted_kivou_action() -> None:
    hermes = FakeSupervisor(_plan())
    adapter = AcquisitionHermesSupervisor(hermes, registry=ClosedRegistry())

    proposal = adapter.propose(
        AcquisitionRuntimeStage.SUPPLIER_DISCOVERY,
        CYCLE,
        remaining_cost=Decimal("5"),
        at=NOW,
    )

    assert proposal.plan_ref == "hermes-plan-001"
    assert proposal.action_index == 0
    assert proposal.command == AcquisitionRuntimeStage.SUPPLIER_DISCOVERY.command
    assert proposal.target_ref == CYCLE.cycle_ref
    assert proposal.estimated_cost == Decimal("1")
    assert len(proposal.argument_fingerprint) == 64
    assert proposal.reason_codes == ("HERMES_CLOSED_PROPOSAL",)
    assert proposal.evidence_refs == (proposal.argument_fingerprint,)
    assert "model_payload" not in proposal.model_dump_json()

    assert len(hermes.contexts) == 1
    context = hermes.contexts[0]
    assert context.available_commands == (
        AcquisitionRuntimeStage.SUPPLIER_DISCOVERY.command,
    )
    assert context.budget.maximum_cycle_cost == Decimal("1")
    assert len(context.opportunities) == 1
    assert context.opportunities[0].object_ref == CYCLE.cycle_ref
    assert context.opportunities[0].kivou_analysis.opportunity_key == CYCLE.cycle_ref
    assert context.opportunities[0].public_facts.evidence_refs == (
        proposal.argument_fingerprint,
    )
    assert context.recent_outcomes == ()
    serialized = context.model_dump_json()
    assert "shell" not in serialized
    assert "mcp" not in serialized.casefold()
    assert "native_tool" not in serialized

    identity = adapter.identity
    assert identity.registry_identity == "a" * 64
    assert identity.native_tools == 0
    assert identity.commands == tuple(stage.command for stage in AcquisitionRuntimeStage)
    assert len(identity.commands) == 11


def test_stage_costs_are_kivou_owned_deterministic_and_bounded() -> None:
    assert set(KIVOU_STAGE_COSTS) == set(AcquisitionRuntimeStage)
    assert KIVOU_STAGE_COSTS == {
        AcquisitionRuntimeStage.SIGNAL_SEED: Decimal("0"),
        AcquisitionRuntimeStage.SUPPLIER_DISCOVERY: Decimal("1"),
        AcquisitionRuntimeStage.CONTACT_DISCOVERY: Decimal("3"),
        AcquisitionRuntimeStage.COMPANY_RESEARCH: Decimal("1"),
        AcquisitionRuntimeStage.DECISION: Decimal("0"),
        AcquisitionRuntimeStage.PERSONALIZATION: Decimal("0"),
        AcquisitionRuntimeStage.COMPLIANCE: Decimal("0"),
        AcquisitionRuntimeStage.CAMPAIGN: Decimal("0"),
        AcquisitionRuntimeStage.PROVIDER_HANDOFF: Decimal("0"),
        AcquisitionRuntimeStage.RESPONSE: Decimal("0"),
        AcquisitionRuntimeStage.ATTRIBUTION_CONVERSION: Decimal("0"),
    }
    assert sum(KIVOU_STAGE_COSTS.values(), start=Decimal("0")) == Decimal("5")


@pytest.mark.parametrize(
    ("plan", "message"),
    (
        (_plan(command="run_shell"), "command"),
        (_plan(target_ref="other-cycle"), "target"),
        (_plan(action_cost="1.01"), "cost"),
        (_plan(actions=0), "exactly one"),
        (_plan(actions=2), "exactly one"),
        (_plan(supervisor_version="hermes-agent-other"), "version"),
        (_plan(skill_version="other-skill"), "skill"),
    ),
)
def test_untrusted_hermes_plan_drift_is_rejected(
    plan: SupervisorPlan, message: str
) -> None:
    adapter = AcquisitionHermesSupervisor(FakeSupervisor(plan), registry=ClosedRegistry())

    with pytest.raises((SupervisorValidationError, SupervisorVersionMismatch), match=message):
        adapter.propose(
            AcquisitionRuntimeStage.SUPPLIER_DISCOVERY,
            CYCLE,
            remaining_cost=Decimal("5"),
            at=NOW,
        )


def test_inconsistent_hermes_plan_and_action_cost_is_rejected() -> None:
    adapter = AcquisitionHermesSupervisor(
        FakeSupervisor(_plan(action_cost="0.25", plan_cost="0.20")),
        registry=ClosedRegistry(),
    )

    with pytest.raises(SupervisorValidationError, match="cost"):
        adapter.propose(
            AcquisitionRuntimeStage.SUPPLIER_DISCOVERY,
            CYCLE,
            remaining_cost=Decimal("5"),
            at=NOW,
        )


@pytest.mark.parametrize(
    "health",
    (
        SupervisorHealth(state=HealthState.NOT_CONFIGURED),
        SupervisorHealth(state=HealthState.UNAVAILABLE),
    ),
)
def test_missing_hermes_is_rejected_before_requesting_a_plan(
    health: SupervisorHealth,
) -> None:
    hermes = FakeSupervisor(_plan(), runtime_health=health)
    adapter = AcquisitionHermesSupervisor(hermes, registry=ClosedRegistry())

    with pytest.raises(SupervisorUnavailable, match="unavailable"):
        adapter.propose(
            AcquisitionRuntimeStage.SUPPLIER_DISCOVERY,
            CYCLE,
            remaining_cost=Decimal("5"),
            at=NOW,
        )

    assert hermes.contexts == []


def test_hermes_with_native_tools_is_rejected_before_requesting_a_plan() -> None:
    health = SupervisorHealth(
        state=HealthState.AVAILABLE,
        hermes_version=PIN.version,
        source_commit=PIN.commit,
        executable_tools=("terminal",),
    )
    hermes = FakeSupervisor(_plan(), runtime_health=health)
    adapter = AcquisitionHermesSupervisor(hermes, registry=ClosedRegistry())

    with pytest.raises(SupervisorVersionMismatch, match="tools"):
        adapter.propose(
            AcquisitionRuntimeStage.SUPPLIER_DISCOVERY,
            CYCLE,
            remaining_cost=Decimal("5"),
            at=NOW,
        )

    assert hermes.contexts == []


def test_target_cycle_reference_must_fit_the_closed_supervisor_contract() -> None:
    long_cycle = CYCLE.model_copy(update={"cycle_ref": "c" * 101})
    adapter = AcquisitionHermesSupervisor(FakeSupervisor(_plan()), registry=ClosedRegistry())

    with pytest.raises(SupervisorValidationError, match="cycle reference"):
        adapter.propose(
            AcquisitionRuntimeStage.SUPPLIER_DISCOVERY,
            long_cycle,
            remaining_cost=Decimal("5"),
            at=NOW,
        )


def test_runtime_registry_identity_rejects_command_or_fingerprint_drift() -> None:
    with pytest.raises(ValueError, match="complete closed runtime command set"):
        AcquisitionHermesSupervisor(
            FakeSupervisor(_plan()),
            registry=ClosedRegistry(commands=("run_shell",)),
        )
    with pytest.raises(ValueError, match="registry identity"):
        AcquisitionHermesSupervisor(
            FakeSupervisor(_plan()),
            registry=ClosedRegistry(identity="not-a-fingerprint"),
        )


def test_real_registry_exposes_the_same_closed_identity_surface() -> None:
    def handler(_context):
        raise AssertionError("identity inspection must not execute a handler")

    registry = AcquisitionActionRegistry(
        {stage: handler for stage in AcquisitionRuntimeStage}
    )
    adapter = AcquisitionHermesSupervisor(FakeSupervisor(_plan()), registry=registry)

    assert adapter.identity.registry_identity == registry.identity
    assert adapter.identity.commands == registry.commands
    assert adapter.identity.native_tools == 0
