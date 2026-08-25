"""Typed boundary from the orchestrator to the existing acquisition domains."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    MachineCode,
    OpaqueRef,
    RuntimeActionResult,
    RuntimeStageStatus,
)
from signals.acquisition_runtime.registry import (
    AcquisitionActionContext,
    AcquisitionActionHandler,
)


class KivouDomainDisposition(StrEnum):
    COMPLETE = "COMPLETE"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    SUPPRESSED = "SUPPRESSED"
    FAILED = "FAILED"


_RUNTIME_STATUS = {
    KivouDomainDisposition.COMPLETE: RuntimeStageStatus.SUCCEEDED,
    KivouDomainDisposition.WAITING: RuntimeStageStatus.WAITING,
    KivouDomainDisposition.BLOCKED: RuntimeStageStatus.BLOCKED,
    KivouDomainDisposition.SUPPRESSED: RuntimeStageStatus.SUPPRESSED,
    KivouDomainDisposition.FAILED: RuntimeStageStatus.FAILED,
}


class KivouDomainOutcome(BaseModel):
    """Only bounded, opaque domain evidence may cross into runtime state."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    disposition: KivouDomainDisposition
    result_refs: tuple[OpaqueRef, ...] = Field(default=(), max_length=16)
    reserved_cost: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("50"))
    observed_cost: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("50"))
    reason_codes: tuple[MachineCode, ...] = Field(default=(), max_length=16)
    retry_at: dt.datetime | None = None

    @model_validator(mode="after")
    def require_machine_reason_for_non_complete(self) -> KivouDomainOutcome:
        if (
            self.disposition is not KivouDomainDisposition.COMPLETE
            and not self.reason_codes
        ):
            raise ValueError("non-complete domain outcome requires a machine reason")
        if self.retry_at is not None:
            if self.retry_at.tzinfo is None or self.retry_at.utcoffset() is None:
                raise ValueError("domain retry_at must be timezone-aware")
            if self.disposition is not KivouDomainDisposition.WAITING:
                raise ValueError("only a waiting domain outcome can carry retry_at")
        return self

    def to_runtime_result(self) -> RuntimeActionResult:
        return RuntimeActionResult(
            status=_RUNTIME_STATUS[self.disposition],
            result_refs=self.result_refs,
            reserved_cost=self.reserved_cost,
            observed_cost=self.observed_cost,
            reason_codes=self.reason_codes,
            retry_at=self.retry_at,
        )


class KivouDomainActions(Protocol):
    """The closed set of existing domain operations composed by run-once."""

    def resolve_signal_seed(
        self, context: AcquisitionActionContext
    ) -> KivouDomainOutcome: ...

    def discover_supplier(
        self, context: AcquisitionActionContext
    ) -> KivouDomainOutcome: ...

    def discover_contact(
        self, context: AcquisitionActionContext
    ) -> KivouDomainOutcome: ...

    def research_company(
        self, context: AcquisitionActionContext
    ) -> KivouDomainOutcome: ...

    def decide(self, context: AcquisitionActionContext) -> KivouDomainOutcome: ...

    def personalize(self, context: AcquisitionActionContext) -> KivouDomainOutcome: ...

    def assess_compliance(
        self, context: AcquisitionActionContext
    ) -> KivouDomainOutcome: ...

    def plan_campaign(
        self, context: AcquisitionActionContext
    ) -> KivouDomainOutcome: ...

    def handoff_provider(
        self, context: AcquisitionActionContext
    ) -> KivouDomainOutcome: ...

    def observe_response(
        self, context: AcquisitionActionContext
    ) -> KivouDomainOutcome: ...

    def reconcile_conversion(
        self, context: AcquisitionActionContext
    ) -> KivouDomainOutcome: ...


DomainAction = Callable[[AcquisitionActionContext], KivouDomainOutcome]


def _runtime_handler(action: DomainAction) -> AcquisitionActionHandler:
    def execute(context: AcquisitionActionContext) -> RuntimeActionResult:
        return action(context).to_runtime_result()

    return execute


def build_kivou_stage_handlers(
    actions: KivouDomainActions,
) -> Mapping[AcquisitionRuntimeStage, AcquisitionActionHandler]:
    """Bind every stage explicitly; no dynamic imports or arbitrary dispatch."""

    return {
        AcquisitionRuntimeStage.SIGNAL_SEED: _runtime_handler(
            actions.resolve_signal_seed
        ),
        AcquisitionRuntimeStage.SUPPLIER_DISCOVERY: _runtime_handler(
            actions.discover_supplier
        ),
        AcquisitionRuntimeStage.CONTACT_DISCOVERY: _runtime_handler(
            actions.discover_contact
        ),
        AcquisitionRuntimeStage.COMPANY_RESEARCH: _runtime_handler(
            actions.research_company
        ),
        AcquisitionRuntimeStage.DECISION: _runtime_handler(actions.decide),
        AcquisitionRuntimeStage.PERSONALIZATION: _runtime_handler(
            actions.personalize
        ),
        AcquisitionRuntimeStage.COMPLIANCE: _runtime_handler(
            actions.assess_compliance
        ),
        AcquisitionRuntimeStage.CAMPAIGN: _runtime_handler(actions.plan_campaign),
        AcquisitionRuntimeStage.PROVIDER_HANDOFF: _runtime_handler(
            actions.handoff_provider
        ),
        AcquisitionRuntimeStage.RESPONSE: _runtime_handler(
            actions.observe_response
        ),
        AcquisitionRuntimeStage.ATTRIBUTION_CONVERSION: _runtime_handler(
            actions.reconcile_conversion
        ),
    }


__all__ = [
    "KivouDomainActions",
    "KivouDomainDisposition",
    "KivouDomainOutcome",
    "build_kivou_stage_handlers",
]
