"""Closed contracts for the bounded Acquisition Engine runtime."""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

ACQUISITION_RUNTIME_SCHEMA_VERSION = "acquisition-runtime-v1"

OpaqueRef = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$",
    ),
]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
MachineCode = Annotated[
    str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9_:-]{0,99}$")
]
CommandName = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")
]


class RuntimeExecutionMode(StrEnum):
    SHADOW = "SHADOW"


class AcquisitionRuntimeStage(StrEnum):
    SIGNAL_SEED = "SIGNAL_SEED"
    SUPPLIER_DISCOVERY = "SUPPLIER_DISCOVERY"
    CONTACT_DISCOVERY = "CONTACT_DISCOVERY"
    COMPANY_RESEARCH = "COMPANY_RESEARCH"
    DECISION = "DECISION"
    PERSONALIZATION = "PERSONALIZATION"
    COMPLIANCE = "COMPLIANCE"
    CAMPAIGN = "CAMPAIGN"
    PROVIDER_HANDOFF = "PROVIDER_HANDOFF"
    RESPONSE = "RESPONSE"
    ATTRIBUTION_CONVERSION = "ATTRIBUTION_CONVERSION"

    @property
    def command(self) -> str:
        return _STAGE_COMMANDS[self]


_STAGE_COMMANDS: dict[AcquisitionRuntimeStage, str] = {
    AcquisitionRuntimeStage.SIGNAL_SEED: "resolve_signal_seed",
    AcquisitionRuntimeStage.SUPPLIER_DISCOVERY: "discover_suppliers",
    AcquisitionRuntimeStage.CONTACT_DISCOVERY: "find_decision_makers",
    AcquisitionRuntimeStage.COMPANY_RESEARCH: "enrich_company",
    AcquisitionRuntimeStage.DECISION: "evaluate_opportunity",
    AcquisitionRuntimeStage.PERSONALIZATION: "prepare_campaign",
    AcquisitionRuntimeStage.COMPLIANCE: "assess_campaign_compliance",
    AcquisitionRuntimeStage.CAMPAIGN: "schedule_campaign",
    AcquisitionRuntimeStage.PROVIDER_HANDOFF: "execute_provider_operations",
    AcquisitionRuntimeStage.RESPONSE: "classify_response",
    AcquisitionRuntimeStage.ATTRIBUTION_CONVERSION: "reconcile_conversion",
}


class RuntimeStageStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"
    CANCELLED = "CANCELLED"


class RuntimeCycleStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"
    CANCELLED = "CANCELLED"


class RuntimeRunStatus(StrEnum):
    ALREADY_RUNNING = "ALREADY_RUNNING"
    COMPLETED = "COMPLETED"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"
    CANCELLED = "CANCELLED"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AcquisitionRuntimeLimits(_FrozenModel):
    maximum_cycle_cost: Decimal = Field(gt=0, le=Decimal("50"))
    maximum_suppliers: Literal[1] = 1
    maximum_contacts: Literal[1] = 1
    maximum_provider_operations: int = Field(ge=1, le=4)
    maximum_wall_seconds: int = Field(ge=60, le=1200)
    lease_seconds: int = Field(ge=120, le=1500)

    @model_validator(mode="after")
    def lease_outlives_cycle(self) -> AcquisitionRuntimeLimits:
        if self.lease_seconds <= self.maximum_wall_seconds:
            raise ValueError("runtime lease must outlive the cycle wall-clock bound")
        return self


class AcquisitionRuntimeDeployment(_FrozenModel):
    schema_version: Literal["acquisition-runtime-v1"] = (
        ACQUISITION_RUNTIME_SCHEMA_VERSION
    )
    mode: Literal[RuntimeExecutionMode.SHADOW] = RuntimeExecutionMode.SHADOW
    qa_only: Literal[True]
    allowed_opportunity_keys: tuple[OpaqueRef, ...] = Field(min_length=1, max_length=8)
    qa_recipient_identity_hmac: Fingerprint = Field(repr=False)
    qa_recipient_key_version: OpaqueRef
    qa_provider_mutations_capable: Literal[True]
    limits: AcquisitionRuntimeLimits

    @model_validator(mode="after")
    def unique_opportunities(self) -> AcquisitionRuntimeDeployment:
        if len(self.allowed_opportunity_keys) != len(set(self.allowed_opportunity_keys)):
            raise ValueError("runtime opportunity allowlist must be unique")
        return self


class AcquisitionRuntimeConfig(_FrozenModel):
    environment: Literal["STAGING"]
    deployment_path: Path
    deployment: AcquisitionRuntimeDeployment = Field(repr=False)
    qa_recipient: SecretStr = Field(repr=False)
    qa_recipient_hmac_key: SecretStr = Field(repr=False)

    def normalized_qa_recipient(self) -> str:
        return str(
            TypeAdapter(EmailStr).validate_python(
                self.qa_recipient.get_secret_value()
            )
        ).casefold()


class RuntimeLeaseResult(_FrozenModel):
    owned: bool
    reclaimed: bool

    @model_validator(mode="after")
    def reclaimed_requires_ownership(self) -> RuntimeLeaseResult:
        if self.reclaimed and not self.owned:
            raise ValueError("only an acquired runtime lease can be reclaimed")
        return self


class RuntimeCycleSnapshot(_FrozenModel):
    cycle_ref: OpaqueRef
    opportunity_key: OpaqueRef
    status: RuntimeCycleStatus
    next_stage: AcquisitionRuntimeStage | None
    spent_cost: Decimal = Field(ge=0, le=Decimal("50"))
    started_at: dt.datetime

    @model_validator(mode="after")
    def aware_start(self) -> RuntimeCycleSnapshot:
        require_aware(self.started_at)
        return self


class RuntimeStageSnapshot(_FrozenModel):
    cycle_ref: OpaqueRef
    stage: AcquisitionRuntimeStage
    status: RuntimeStageStatus
    attempt_count: int = Field(ge=1)
    result_refs: tuple[OpaqueRef, ...] = Field(default=(), max_length=16)

    @property
    def attempt_ref(self) -> str:
        material = (
            "acquisition-runtime-attempt-v1\0"
            f"{self.cycle_ref}\0{self.stage.value}\0{self.attempt_count}"
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


class RuntimeRunRequest(_FrozenModel):
    owner_ref: OpaqueRef
    allow_qa_provider_mutations: bool = False


class RuntimeProposal(_FrozenModel):
    plan_ref: OpaqueRef
    action_index: int = Field(ge=0, le=9)
    command: CommandName
    target_ref: OpaqueRef
    argument_fingerprint: Fingerprint
    estimated_cost: Decimal = Field(ge=0, le=Decimal("50"))
    reason_codes: tuple[MachineCode, ...] = Field(min_length=1, max_length=16)
    evidence_refs: tuple[OpaqueRef, ...] = Field(default=(), max_length=16)


class RuntimeActionResult(_FrozenModel):
    status: RuntimeStageStatus
    result_refs: tuple[OpaqueRef, ...] = Field(default=(), max_length=16)
    reserved_cost: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("50"))
    observed_cost: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("50"))
    reason_codes: tuple[MachineCode, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def terminal_or_waiting(self) -> RuntimeActionResult:
        if self.status in {RuntimeStageStatus.PENDING, RuntimeStageStatus.RUNNING}:
            raise ValueError("an action result must checkpoint a bounded disposition")
        if self.status is not RuntimeStageStatus.SUCCEEDED and not self.reason_codes:
            raise ValueError("non-success runtime results require a machine reason")
        return self


class RuntimeRunResult(_FrozenModel):
    status: RuntimeRunStatus
    cycle_ref: OpaqueRef | None = None
    stage: AcquisitionRuntimeStage | None = None
    reason_code: MachineCode | None = None

    @property
    def exit_code(self) -> int:
        return (
            0
            if self.status
            in {
                RuntimeRunStatus.ALREADY_RUNNING,
                RuntimeRunStatus.COMPLETED,
                RuntimeRunStatus.WAITING,
                RuntimeRunStatus.SUPPRESSED,
            }
            else 1
        )


def require_aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("runtime timestamp must be timezone-aware")
    return value.astimezone(dt.UTC)


__all__ = [
    "ACQUISITION_RUNTIME_SCHEMA_VERSION",
    "AcquisitionRuntimeConfig",
    "AcquisitionRuntimeDeployment",
    "AcquisitionRuntimeLimits",
    "AcquisitionRuntimeStage",
    "RuntimeActionResult",
    "RuntimeCycleSnapshot",
    "RuntimeCycleStatus",
    "RuntimeExecutionMode",
    "RuntimeLeaseResult",
    "RuntimeProposal",
    "RuntimeRunRequest",
    "RuntimeRunResult",
    "RuntimeRunStatus",
    "RuntimeStageSnapshot",
    "RuntimeStageStatus",
    "require_aware",
]
