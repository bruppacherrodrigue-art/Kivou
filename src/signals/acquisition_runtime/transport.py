"""Staging-only transport binding that never mutates discovered contact truth."""

from __future__ import annotations

from pydantic import EmailStr, TypeAdapter

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeConfig,
    RuntimeExecutionMode,
)
from signals.compliance.suppression import SuppressionIdentityKeyring


class StagingQaRecipientOverride:
    """Resolve provider transport to the separately bound controlled address."""

    __slots__ = (
        "_recipient",
        "binding_fingerprint",
        "key_version",
        "transport_key_version",
        "transport_recipient_identity",
    )

    def __init__(
        self,
        config: AcquisitionRuntimeConfig,
        *,
        transport_keyring: SuppressionIdentityKeyring,
    ) -> None:
        deployment = config.deployment
        if (
            config.environment != "STAGING"
            or deployment.mode is not RuntimeExecutionMode.SHADOW
            or deployment.qa_only is not True
            or deployment.qa_provider_mutations_capable is not True
        ):
            raise ValueError("recipient override requires a staging QA runtime")
        self._recipient = config.normalized_qa_recipient()
        self.binding_fingerprint = deployment.qa_recipient_identity_hmac
        self.key_version = deployment.qa_recipient_key_version
        self.transport_key_version = transport_keyring.current_key_version
        self.transport_recipient_identity = transport_keyring.identities_for_email(
            self._recipient
        )[self.transport_key_version]

    def resolve(self, discovered_email: str) -> str:
        TypeAdapter(EmailStr).validate_python(discovered_email)
        return self._recipient

    def __repr__(self) -> str:
        return "StagingQaRecipientOverride(configured=True)"


__all__ = ["StagingQaRecipientOverride"]
