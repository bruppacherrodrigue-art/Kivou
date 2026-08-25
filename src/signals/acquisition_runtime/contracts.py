"""Closed contracts for the bounded Acquisition Engine runtime."""

from __future__ import annotations

import datetime as dt
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


class RuntimeStageStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
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
    "RuntimeExecutionMode",
    "RuntimeStageStatus",
    "require_aware",
]
