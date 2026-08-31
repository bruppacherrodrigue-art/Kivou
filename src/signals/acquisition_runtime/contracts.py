"""Closed contracts for the bounded Acquisition Engine runtime."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
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
ACQUISITION_PRODUCTION_SCHEMA_VERSION = "acquisition-production-v1"

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
BoundedRuntimeText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=256,
        pattern=r"^[^\s\x00-\x1f]+$",
    ),
]
CommitFingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class RuntimeExecutionMode(StrEnum):
    SHADOW = "SHADOW"


class RuntimeDependencyState(StrEnum):
    READY = "READY"
    NOT_READY = "NOT_READY"


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


class RuntimeHermesIdentityEvidence(_FrozenModel):
    repository: BoundedRuntimeText
    tag: BoundedRuntimeText
    commit: CommitFingerprint
    version: BoundedRuntimeText
    python_contract: BoundedRuntimeText


class RuntimeStageDependency(_FrozenModel):
    stage: AcquisitionRuntimeStage
    status: RuntimeDependencyState
    reason_codes: tuple[MachineCode, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def reason_matches_status(self) -> RuntimeStageDependency:
        if self.status is RuntimeDependencyState.NOT_READY and not self.reason_codes:
            raise ValueError("unavailable runtime dependencies require a reason")
        if self.status is RuntimeDependencyState.READY and self.reason_codes:
            raise ValueError("ready runtime dependencies have no failure reason")
        return self


class RuntimeCapabilityEvidence(_FrozenModel):
    environment: Literal["STAGING", "PRODUCTION"]
    mode: Literal[RuntimeExecutionMode.SHADOW] = RuntimeExecutionMode.SHADOW
    qa_only: bool
    hermes: RuntimeHermesIdentityEvidence
    registry_identity: Fingerprint
    native_tools: Literal[0] = 0
    commands: tuple[CommandName, ...] = Field(min_length=11, max_length=11)
    dependencies: tuple[RuntimeStageDependency, ...] = Field(
        min_length=11,
        max_length=11,
    )

    @model_validator(mode="after")
    def closed_registry_and_dependencies(self) -> RuntimeCapabilityEvidence:
        expected_stages = tuple(AcquisitionRuntimeStage)
        if self.commands != tuple(stage.command for stage in expected_stages):
            raise ValueError("runtime command registry identity drifted")
        if tuple(item.stage for item in self.dependencies) != expected_stages:
            raise ValueError("runtime dependencies must cover every stage exactly once")
        return self

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class RuntimeHealthObservation(_FrozenModel):
    capability: RuntimeCapabilityEvidence
    observed_at: dt.datetime
    heartbeat_at: dt.datetime
    last_cycle_ref: OpaqueRef | None = None
    last_cycle_status: RuntimeCycleStatus | None = None
    last_cycle_at: dt.datetime | None = None

    @model_validator(mode="after")
    def coherent_timeline(self) -> RuntimeHealthObservation:
        observed_at = require_aware(self.observed_at)
        heartbeat_at = require_aware(self.heartbeat_at)
        if heartbeat_at < observed_at:
            raise ValueError("runtime heartbeat cannot predate its observation")
        cycle_fields = (
            self.last_cycle_ref,
            self.last_cycle_status,
            self.last_cycle_at,
        )
        if any(item is None for item in cycle_fields) and any(
            item is not None for item in cycle_fields
        ):
            raise ValueError("runtime cycle observation must be complete")
        if self.last_cycle_at is not None:
            last_cycle_at = require_aware(self.last_cycle_at)
            if last_cycle_at > heartbeat_at:
                raise ValueError("runtime cycle observation cannot follow heartbeat")
        return self


def expected_runtime_registry_identity() -> str:
    canonical = json.dumps(
        [
            {"stage": stage.value, "command": stage.command}
            for stage in AcquisitionRuntimeStage
        ],
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


class RuntimeQaScope(_FrozenModel):
    """Exact operator-owned scope; no runtime heuristic may derive it."""

    country: Literal["CH", "FR"]
    language: Literal["fr", "en"]
    wedge: OpaqueRef


class AcquisitionRuntimeDeployment(_FrozenModel):
    schema_version: Literal[
        "acquisition-runtime-v1", "acquisition-production-v1"
    ] = ACQUISITION_RUNTIME_SCHEMA_VERSION
    mode: Literal[RuntimeExecutionMode.SHADOW] = RuntimeExecutionMode.SHADOW
    qa_only: bool = False
    allowed_opportunity_keys: tuple[OpaqueRef, ...] = Field(
        default=(), max_length=8
    )
    qa_scope: RuntimeQaScope
    qa_recipient_identity_hmac: Fingerprint | None = Field(default=None, repr=False)
    qa_recipient_key_version: OpaqueRef | None = None
    qa_provider_mutations_capable: bool = False
    limits: AcquisitionRuntimeLimits

    @property
    def is_production(self) -> bool:
        return self.schema_version == ACQUISITION_PRODUCTION_SCHEMA_VERSION

    @model_validator(mode="after")
    def bindings_match_schema(self) -> AcquisitionRuntimeDeployment:
        if len(self.allowed_opportunity_keys) != len(
            set(self.allowed_opportunity_keys)
        ):
            raise ValueError("runtime opportunity allowlist must be unique")
        qa_bindings = (
            self.qa_recipient_identity_hmac,
            self.qa_recipient_key_version,
        )
        if self.is_production:
            if (
                any(item is not None for item in qa_bindings)
                or self.qa_only
                or self.qa_provider_mutations_capable
                or self.allowed_opportunity_keys
            ):
                raise ValueError("production runtime forbids every QA binding")
            return self
        if (
            any(item is None for item in qa_bindings)
            or not self.qa_only
            or not self.qa_provider_mutations_capable
            or not self.allowed_opportunity_keys
        ):
            raise ValueError("staging runtime requires its complete QA binding")
        return self


class AcquisitionRuntimeConfig(_FrozenModel):
    environment: Literal["STAGING", "PRODUCTION"]
    deployment_path: Path
    deployment: AcquisitionRuntimeDeployment = Field(repr=False)
    qa_recipient: SecretStr | None = Field(default=None, repr=False)
    qa_recipient_hmac_key: SecretStr | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def recipient_matches_environment(self) -> AcquisitionRuntimeConfig:
        has_recipient = (
            self.qa_recipient is not None or self.qa_recipient_hmac_key is not None
        )
        if self.environment == "PRODUCTION" and has_recipient:
            raise ValueError("production runtime forbids a fallback recipient")
        if self.environment == "STAGING" and not (
            self.qa_recipient is not None and self.qa_recipient_hmac_key is not None
        ):
            raise ValueError("staging runtime requires its QA recipient binding")
        return self

    def normalized_qa_recipient(self) -> str:
        if self.qa_recipient is None:
            raise ValueError("runtime has no QA recipient")
        return str(
            TypeAdapter(EmailStr).validate_python(
                self.qa_recipient.get_secret_value()
            )
        ).strip().casefold()


class RuntimeLeaseResult(_FrozenModel):
    owned: bool
    reclaimed: bool
    fencing_token: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def reclaimed_requires_ownership(self) -> RuntimeLeaseResult:
        if self.reclaimed and not self.owned:
            raise ValueError("only an acquired runtime lease can be reclaimed")
        if self.owned != (self.fencing_token is not None):
            raise ValueError("owned runtime leases require exactly one fencing token")
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
    retry_at: dt.datetime | None = None
    replay_same_attempt: bool = False

    @model_validator(mode="after")
    def valid_retry_checkpoint(self) -> RuntimeStageSnapshot:
        if self.retry_at is not None:
            require_aware(self.retry_at)
            if self.status is not RuntimeStageStatus.WAITING:
                raise ValueError("only a waiting runtime stage can carry retry_at")
        if self.replay_same_attempt and (
            self.status is not RuntimeStageStatus.WAITING or self.retry_at is None
        ):
            raise ValueError(
                "same-attempt replay requires one bounded waiting deadline"
            )
        return self

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


class RuntimeStageReservation(_FrozenModel):
    accepted: bool
    created: bool
    reserved_cost: Decimal = Field(ge=0, le=Decimal("50"))
    total_cycle_cost: Decimal = Field(ge=0, le=Decimal("50"))
    proposal: RuntimeProposal | None = None

    @model_validator(mode="after")
    def coherent_reservation(self) -> RuntimeStageReservation:
        if self.created and not self.accepted:
            raise ValueError("a rejected reservation cannot be created")
        if self.proposal is not None:
            if not self.accepted:
                raise ValueError("a rejected reservation cannot carry a proposal")
            if self.proposal.estimated_cost != self.reserved_cost:
                raise ValueError("proposal cost must equal its durable reservation")
        return self


class RuntimeActionResult(_FrozenModel):
    status: RuntimeStageStatus
    result_refs: tuple[OpaqueRef, ...] = Field(default=(), max_length=16)
    reserved_cost: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("50"))
    observed_cost: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("50"))
    reason_codes: tuple[MachineCode, ...] = Field(default=(), max_length=16)
    retry_at: dt.datetime | None = None
    replay_same_attempt: bool = False

    @model_validator(mode="after")
    def terminal_or_waiting(self) -> RuntimeActionResult:
        if self.status in {RuntimeStageStatus.PENDING, RuntimeStageStatus.RUNNING}:
            raise ValueError("an action result must checkpoint a bounded disposition")
        if self.status is not RuntimeStageStatus.SUCCEEDED and not self.reason_codes:
            raise ValueError("non-success runtime results require a machine reason")
        if self.retry_at is not None:
            require_aware(self.retry_at)
            if self.status is not RuntimeStageStatus.WAITING:
                raise ValueError("only a waiting runtime result can carry retry_at")
        if self.replay_same_attempt and (
            self.status is not RuntimeStageStatus.WAITING or self.retry_at is None
        ):
            raise ValueError(
                "same-attempt replay requires one bounded waiting deadline"
            )
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
    "ACQUISITION_PRODUCTION_SCHEMA_VERSION",
    "ACQUISITION_RUNTIME_SCHEMA_VERSION",
    "AcquisitionRuntimeConfig",
    "AcquisitionRuntimeDeployment",
    "AcquisitionRuntimeLimits",
    "AcquisitionRuntimeStage",
    "RuntimeActionResult",
    "RuntimeCapabilityEvidence",
    "RuntimeCycleSnapshot",
    "RuntimeCycleStatus",
    "RuntimeDependencyState",
    "RuntimeExecutionMode",
    "RuntimeHealthObservation",
    "RuntimeHermesIdentityEvidence",
    "RuntimeLeaseResult",
    "RuntimeProposal",
    "RuntimeQaScope",
    "RuntimeRunRequest",
    "RuntimeRunResult",
    "RuntimeRunStatus",
    "RuntimeStageDependency",
    "RuntimeStageSnapshot",
    "RuntimeStageStatus",
    "expected_runtime_registry_identity",
    "require_aware",
]
