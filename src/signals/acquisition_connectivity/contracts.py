"""Deployment-only contracts for the acquisition SHADOW connectivity boundary."""

from __future__ import annotations

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


class ConnectivityFailure(RuntimeError):
    """One bounded error category; never carries provider/configuration values."""

    def __init__(
        self,
        code: ConnectivityErrorCode,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(f"acquisition connectivity failure: {code.value}")
        self.code = code
        self.retry_after_seconds = (
            retry_after_seconds
            if retry_after_seconds is not None and 0 <= retry_after_seconds <= 86_400
            else None
        )


class _DeploymentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ShadowMailboxBinding(_DeploymentModel):
    mailbox_ref: OpaqueRef
    provider_account_id: ProviderAccountEmail = Field(repr=False)


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


class AcquisitionConnectivityConfig(_DeploymentModel):
    environment: Literal["STAGING"]
    shadow_config_path: Path
    apollo_api_key: SecretStr = Field(repr=False)
    instantly_api_key: SecretStr = Field(repr=False)
    hermes_python: Path
    hermes_home: Path
    hermes_cwd: Path
    deployment: ShadowConnectivityDocument = Field(repr=False)

