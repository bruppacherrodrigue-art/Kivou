"""Deployment-only contracts for the acquisition SHADOW connectivity boundary."""

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
    model_validator,
)

SHADOW_CONNECTIVITY_SCHEMA_VERSION = "acquisition-shadow-connectivity-v1"

OpaqueRef = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$",
    ),
]
ProviderAccountEmail = Annotated[EmailStr, Field(max_length=320)]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class ConnectivityErrorCode(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    WRONG_ENVIRONMENT = "WRONG_ENVIRONMENT"
    POLICY_NOT_SHADOW = "POLICY_NOT_SHADOW"
    READ_ONLY_REQUIRED = "READ_ONLY_REQUIRED"
    KILL_SWITCH_REQUIRED = "KILL_SWITCH_REQUIRED"
    AUTONOMOUS_VOLUME_REQUIRED = "AUTONOMOUS_VOLUME_REQUIRED"
    OPERATIONAL_AMBIGUITY = "OPERATIONAL_AMBIGUITY"
    AUTH = "AUTH"
    PERMISSION = "PERMISSION"
    PLAN_REQUIRED = "PLAN_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    SERVER_ERROR = "SERVER_ERROR"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    WORKSPACE_MISMATCH = "WORKSPACE_MISMATCH"
    MAILBOX_NOT_READY = "MAILBOX_NOT_READY"
    HERMES_VERSION_MISMATCH = "HERMES_VERSION_MISMATCH"
    HERMES_TOOLS_EXPOSED = "HERMES_TOOLS_EXPOSED"
    HERMES_PLAN_INVALID = "HERMES_PLAN_INVALID"
    LOCAL_MUTATION_DETECTED = "LOCAL_MUTATION_DETECTED"


class _DeploymentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ShadowMailboxBinding(_DeploymentModel):
    mailbox_ref: OpaqueRef
    provider_account_id: ProviderAccountEmail = Field(repr=False)
    managed_airmail_sending_gap_minutes: int | None = Field(
        default=None, strict=True, ge=1, le=1_440
    )


class ShadowConnectivityDocument(_DeploymentModel):
    schema_version: Literal["acquisition-shadow-connectivity-v1"] = (
        SHADOW_CONNECTIVITY_SCHEMA_VERSION
    )
    instantly_workspace_ref: OpaqueRef
    mailboxes: tuple[ShadowMailboxBinding, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def unique_bindings(self) -> ShadowConnectivityDocument:
        mailbox_refs = tuple(item.mailbox_ref for item in self.mailboxes)
        provider_accounts = tuple(str(item.provider_account_id).casefold() for item in self.mailboxes)
        if len(set(mailbox_refs)) != 3 or len(set(provider_accounts)) != 3:
            raise ValueError("shadow mailbox bindings must be unique")
        return self


class ApolloIdentityEvidence(_DeploymentModel):
    auth: Literal["READY"] = "READY"
    acting_profile: Literal["BOUND"] = "BOUND"
    acting_profile_fingerprint: Fingerprint = Field(repr=False)


class InstantlyConnectivityEvidence(_DeploymentModel):
    workspace: Literal["BOUND"] = "BOUND"
    mailboxes_ready: Literal[3] = 3
    mailboxes_total: Literal[3] = 3


class ShadowPreflightEvidence(_DeploymentModel):
    environment: Literal["STAGING"] = "STAGING"
    policy: Literal["SHADOW"] = "SHADOW"
    read_only: Literal[True] = True
    kill_switch: Literal[True] = True
    autonomous_live_volume_cap: Literal[0] = 0
    policy_control_revision: int = Field(ge=0)
    policy_version: OpaqueRef


class HermesConnectivityEvidence(_DeploymentModel):
    state: Literal["AVAILABLE"] = "AVAILABLE"
    version: Literal["0.20.4"] = "0.20.4"
    executable_tools: Literal[0] = 0
    model: Literal["anthropic/claude-sonnet-4.6"] = "anthropic/claude-sonnet-4.6"
    tag: Literal["v2026.8.18"] = "v2026.8.18"
    commit: Literal["e624e9fde561e1add9388384012b295fde669ade"] = (
        "e624e9fde561e1add9388384012b295fde669ade"
    )


class ShadowPlanEvidence(_DeploymentModel):
    status: Literal["advisory"] = "advisory"
    plan_id: OpaqueRef
    actions: int = Field(ge=0, le=10)
    estimated_cost: Decimal = Field(ge=0, le=Decimal("1"))
    next_review_at: dt.datetime

    @model_validator(mode="after")
    def aware_review_time(self) -> ShadowPlanEvidence:
        if self.next_review_at.tzinfo is None or self.next_review_at.utcoffset() is None:
            raise ValueError("next review time must be timezone-aware")
        return self


class AcquisitionMutationDelta(_DeploymentModel):
    campaigns: int
    members: int
    provider_operations: int
    provider_events: int

    @property
    def detected(self) -> bool:
        return any(self.model_dump().values())


class AcquisitionShadowSmokeResult(_DeploymentModel):
    deployed_sha: GitSha
    preflight: ShadowPreflightEvidence
    apollo: ApolloIdentityEvidence
    instantly: InstantlyConnectivityEvidence
    hermes: HermesConnectivityEvidence
    shadow_plan: ShadowPlanEvidence
    mutation_delta: AcquisitionMutationDelta


class AcquisitionShadowSmokePartial(_DeploymentModel):
    deployed_sha: GitSha
    preflight: ShadowPreflightEvidence
    failed_component: Literal["apollo", "instantly", "hermes", "postcondition"]
    apollo: ApolloIdentityEvidence | None = None
    instantly: InstantlyConnectivityEvidence | None = None
    hermes: HermesConnectivityEvidence | None = None
    shadow_plan: ShadowPlanEvidence | None = None
    mutation_delta: AcquisitionMutationDelta | None = None


class ConnectivityFailure(RuntimeError):
    """One bounded error category; never carries provider/configuration values."""

    def __init__(
        self,
        code: ConnectivityErrorCode,
        *,
        retry_after_seconds: int | None = None,
        partial: AcquisitionShadowSmokePartial | None = None,
    ) -> None:
        super().__init__(f"acquisition connectivity failure: {code.value}")
        self.code = code
        self.retry_after_seconds = (
            retry_after_seconds
            if retry_after_seconds is not None and 0 <= retry_after_seconds <= 86_400
            else None
        )
        self.partial = partial


class AcquisitionConnectivityConfig(_DeploymentModel):
    environment: Literal["STAGING"]
    shadow_config_path: Path
    apollo_api_key: SecretStr = Field(repr=False)
    instantly_api_key: SecretStr = Field(repr=False)
    hermes_python: Path
    hermes_home: Path
    hermes_cwd: Path
    deployment: ShadowConnectivityDocument = Field(repr=False)
