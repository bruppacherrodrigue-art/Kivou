"""Closed Hermes proposal boundary for the acquisition runtime."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from signals.acquisition_runtime.contracts import (
    ACQUISITION_RUNTIME_SCHEMA_VERSION,
    AcquisitionRuntimeStage,
    RuntimeCycleSnapshot,
    RuntimeProposal,
    require_aware,
)
from signals.supervisor.contracts import (
    BudgetEnvelope,
    KivouAnalysis,
    OpportunitySummary,
    ProposedAction,
    PublicFacts,
    SupervisorContext,
    SupervisorPlan,
)
from signals.supervisor.pin import HermesPin, load_hermes_pin
from signals.supervisor.profile import PROFILE_VERSION
from signals.supervisor.runtime import (
    HealthState,
    SupervisorHealth,
    SupervisorUnavailable,
    SupervisorValidationError,
    SupervisorVersionMismatch,
)

_STAGE_COSTS: dict[AcquisitionRuntimeStage, Decimal] = {
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
KIVOU_STAGE_COSTS: Mapping[AcquisitionRuntimeStage, Decimal] = MappingProxyType(
    _STAGE_COSTS
)
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class _KivouSupervisor(Protocol):
    def health(self) -> SupervisorHealth: ...

    def plan(self, context: SupervisorContext) -> SupervisorPlan: ...


class _ClosedRegistry(Protocol):
    identity: str
    commands: tuple[str, ...]


class AcquisitionSupervisorIdentity(BaseModel):
    """Safe identity evidence; it contains no callable or provider material."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    native_tools: Literal[0] = 0
    commands: tuple[str, ...] = Field(min_length=11, max_length=11)


class AcquisitionHermesSupervisor:
    """Translate one Hermes advisory action into one Kivou-owned proposal."""

    def __init__(
        self,
        supervisor: _KivouSupervisor,
        *,
        registry: _ClosedRegistry,
        pin: HermesPin | None = None,
    ) -> None:
        commands = tuple(stage.command for stage in AcquisitionRuntimeStage)
        if tuple(registry.commands) != commands:
            raise ValueError("runtime registry requires the complete closed runtime command set")
        if not _FINGERPRINT_PATTERN.fullmatch(registry.identity):
            raise ValueError("runtime registry identity must be a SHA-256 fingerprint")
        self._supervisor = supervisor
        self._pin = pin or load_hermes_pin()
        self.identity = AcquisitionSupervisorIdentity(
            registry_identity=registry.identity,
            commands=commands,
        )

    def propose(
        self,
        stage: AcquisitionRuntimeStage,
        cycle: RuntimeCycleSnapshot,
        *,
        remaining_cost: Decimal,
        at: dt.datetime,
    ) -> RuntimeProposal:
        observed_at = require_aware(at)
        if not 1 <= len(cycle.cycle_ref) <= 100:
            raise SupervisorValidationError(
                "runtime cycle reference exceeds the closed supervisor contract"
            )
        if cycle.next_stage is not stage:
            raise SupervisorValidationError("runtime stage and cycle checkpoint mismatch")
        if not remaining_cost.is_finite() or remaining_cost < 0:
            raise SupervisorValidationError("runtime remaining cost is invalid")
        self._require_closed_hermes()

        argument_fingerprint = self._argument_fingerprint(stage, cycle)
        stage_cost = KIVOU_STAGE_COSTS[stage]
        context = SupervisorContext(
            current_time=observed_at,
            runtime_mode="SHADOW",
            policy_version=ACQUISITION_RUNTIME_SCHEMA_VERSION,
            budget=BudgetEnvelope(
                currency="CHF",
                maximum_cycle_cost=min(stage_cost, remaining_cost),
            ),
            available_commands=(stage.command,),
            opportunities=(
                OpportunitySummary(
                    object_ref=cycle.cycle_ref,
                    public_facts=PublicFacts(
                        source="KIVOU_RUNTIME",
                        evidence_refs=(argument_fingerprint,),
                    ),
                    kivou_analysis=KivouAnalysis(
                        opportunity_key=cycle.cycle_ref,
                        decision="REVIEW",
                        reason_codes=("BOUNDED_RUNTIME_STAGE",),
                    ),
                ),
            ),
            recent_outcomes=(),
        )
        plan = self._supervisor.plan(context)
        action = self._validate_plan(
            plan,
            stage=stage,
            cycle_ref=cycle.cycle_ref,
            maximum_model_cost=min(stage_cost, remaining_cost),
        )
        return RuntimeProposal(
            plan_ref=plan.plan_id,
            action_index=0,
            command=action.command,
            target_ref=cycle.cycle_ref,
            argument_fingerprint=argument_fingerprint,
            estimated_cost=stage_cost,
            reason_codes=("HERMES_CLOSED_PROPOSAL",),
            evidence_refs=(argument_fingerprint,),
        )

    def _require_closed_hermes(self) -> None:
        health = self._supervisor.health()
        if health.state is not HealthState.AVAILABLE:
            raise SupervisorUnavailable("Hermes runtime is unavailable")
        if (
            health.hermes_version != self._pin.version
            or health.source_commit != self._pin.commit
        ):
            raise SupervisorVersionMismatch("Hermes runtime version mismatch")
        if health.executable_tools != ():
            raise SupervisorVersionMismatch("Hermes runtime exposed executable tools")

    def _validate_plan(
        self,
        plan: SupervisorPlan,
        *,
        stage: AcquisitionRuntimeStage,
        cycle_ref: str,
        maximum_model_cost: Decimal,
    ) -> ProposedAction:
        if plan.supervisor_version != f"hermes-agent-{self._pin.version}":
            raise SupervisorVersionMismatch("Hermes supervisor version mismatch")
        if plan.skill_version != PROFILE_VERSION:
            raise SupervisorVersionMismatch("Hermes supervisor skill mismatch")
        if len(plan.proposed_actions) != 1:
            raise SupervisorValidationError(
                "Hermes runtime plan must contain exactly one action"
            )
        action = plan.proposed_actions[0]
        if action.command != stage.command:
            raise SupervisorValidationError("Hermes runtime command mismatch")
        if action.target_ref != cycle_ref:
            raise SupervisorValidationError("Hermes runtime target mismatch")
        if plan.estimated_cost != action.estimated_cost:
            raise SupervisorValidationError("Hermes plan and action cost mismatch")
        if (
            plan.estimated_cost > maximum_model_cost
            or action.estimated_cost > maximum_model_cost
        ):
            raise SupervisorValidationError("Hermes runtime cost exceeds Kivou budget")
        return action

    def _argument_fingerprint(
        self,
        stage: AcquisitionRuntimeStage,
        cycle: RuntimeCycleSnapshot,
    ) -> str:
        material = json.dumps(
            {
                "cycle_ref": cycle.cycle_ref,
                "kind": "acquisition-runtime-hermes-action-v1",
                "opportunity_key": cycle.opportunity_key,
                "registry_identity": self.identity.registry_identity,
                "stage": stage.value,
                "command": stage.command,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


__all__ = [
    "KIVOU_STAGE_COSTS",
    "AcquisitionHermesSupervisor",
    "AcquisitionSupervisorIdentity",
]
