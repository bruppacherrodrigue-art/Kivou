"""Read-only Instantly smoke orchestration over the existing provider and normalizer."""

from __future__ import annotations

import datetime as dt

from signals.acquisition_connectivity.contracts import (
    ConnectivityErrorCode,
    ConnectivityFailure,
    InstantlyConnectivityEvidence,
    ShadowConnectivityDocument,
)
from signals.campaigns.contracts import MailboxReadinessState
from signals.campaigns.instantly import (
    HttpInstantlyProvider,
    InstantlyErrorCode,
    InstantlyMailboxReadinessSource,
    InstantlyProviderError,
)

_ERROR_MAP = {
    InstantlyErrorCode.AUTH: ConnectivityErrorCode.AUTH,
    InstantlyErrorCode.PERMISSION: ConnectivityErrorCode.PERMISSION,
    InstantlyErrorCode.PLAN_REQUIRED: ConnectivityErrorCode.PLAN_REQUIRED,
    InstantlyErrorCode.RATE_LIMITED: ConnectivityErrorCode.RATE_LIMITED,
    InstantlyErrorCode.TIMEOUT: ConnectivityErrorCode.TIMEOUT,
    InstantlyErrorCode.NETWORK: ConnectivityErrorCode.NETWORK,
    InstantlyErrorCode.SERVER_ERROR: ConnectivityErrorCode.SERVER_ERROR,
    InstantlyErrorCode.CLIENT_CONTRACT_ERROR: ConnectivityErrorCode.MALFORMED_RESPONSE,
    InstantlyErrorCode.MALFORMED_RESPONSE: ConnectivityErrorCode.MALFORMED_RESPONSE,
    InstantlyErrorCode.REMOTE_STATE_CONFLICT: ConnectivityErrorCode.MALFORMED_RESPONSE,
}


class InstantlyConnectivityProbe:
    """Coordinate only current-workspace and account-readiness reads."""

    def __init__(
        self,
        *,
        provider: HttpInstantlyProvider,
        mailbox_readiness: InstantlyMailboxReadinessSource,
    ) -> None:
        self._provider = provider
        self._mailbox_readiness = mailbox_readiness

    def check(
        self,
        deployment: ShadowConnectivityDocument,
        *,
        observed_at: dt.datetime,
    ) -> InstantlyConnectivityEvidence:
        try:
            workspace_ref = self._provider.get_current_workspace_ref()
            if workspace_ref != deployment.instantly_workspace_ref:
                raise ConnectivityFailure(ConnectivityErrorCode.WORKSPACE_MISMATCH)
            readiness = tuple(
                self._mailbox_readiness.get(
                    str(binding.provider_account_id), observed_at=observed_at
                )
                for binding in deployment.mailboxes
            )
        except ConnectivityFailure:
            raise
        except InstantlyProviderError as exc:
            raise ConnectivityFailure(
                _ERROR_MAP[exc.code], retry_after_seconds=exc.retry_after_seconds
            ) from None
        if len(readiness) != 3 or any(
            item.state is not MailboxReadinessState.READY for item in readiness
        ):
            raise ConnectivityFailure(ConnectivityErrorCode.MAILBOX_NOT_READY)
        return InstantlyConnectivityEvidence()
