"""Permit-scoped one-message Instantly delivery for Founder-approved targets."""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import Protocol

from signals.prospection_actions.service import (
    DeliveryAttempt,
    DeliveryPermit,
    DeliveryTarget,
)


class AssistedInstantlyProvider(Protocol):
    def create_assisted_campaign(
        self,
        *,
        name: str,
        provider_account_id: str,
        execution_date: dt.date,
    ): ...

    def create_lead_or_batch(
        self,
        *,
        provider_campaign_id: str,
        leads: tuple[dict[str, object], ...],
        verify_leads_on_import: bool = False,
    ) -> object: ...

    def get_lead(self, provider_lead_id: str) -> object: ...

    def activate_campaign(self, provider_campaign_id: str) -> object: ...


@dataclass
class _ImportedLead:
    target: DeliveryTarget
    lead_id: str | None
    verification_status: int | None
    request_count: int
    error: str | None = None


def _verification_status(response: object) -> int | None:
    value = response.get("verification_status") if isinstance(response, dict) else None
    return value if type(value) is int else None


_VERIFICATION_ERRORS = {
    -1: "instantly_email_verification_invalid",
    -2: "instantly_email_verification_risky",
    -3: "instantly_email_verification_catch_all",
    -4: "instantly_email_verification_job_change",
}


class AssistedInstantlyDelivery:
    def __init__(self, *, provider: AssistedInstantlyProvider, provider_account_id: str) -> None:
        if not provider_account_id.strip():
            raise ValueError("assisted Instantly mailbox is required")
        self._provider = provider
        self._provider_account_id = provider_account_id.strip().casefold()

    def deliver(
        self,
        *,
        permit: DeliveryPermit,
        targets: tuple[DeliveryTarget, ...],
        at: dt.datetime,
    ) -> tuple[DeliveryAttempt, ...]:
        target_ids = frozenset(item.target_id for item in targets)
        if not targets or target_ids != permit.target_ids or len(target_ids) != len(targets):
            raise PermissionError("delivery targets exceed the Founder send permit")
        if permit.issued_at != at:
            raise PermissionError("delivery permit is not bound to this send attempt")
        campaign = self._provider.create_assisted_campaign(
            name=f"Kivou assisted {at.astimezone(dt.UTC).date()} {permit.request_id[:8]}",
            provider_account_id=self._provider_account_id,
            execution_date=at.astimezone(dt.UTC).date(),
        )
        campaign_id = str(campaign.provider_campaign_id)
        imported: list[_ImportedLead] = []
        for target in targets:
            try:
                response = self._provider.create_lead_or_batch(
                    provider_campaign_id=campaign_id,
                    verify_leads_on_import=True,
                    leads=(
                        {
                            "email": target.email,
                            "custom_variables": {
                                "kivou_subject": target.subject,
                                "kivou_envelope": target.html,
                            },
                            "skip_if_in_workspace": True,
                        },
                    ),
                )
                lead_id = response.get("id") if isinstance(response, dict) else None
                if not lead_id:
                    raise RuntimeError("Instantly did not return a lead id")
                imported.append(
                    _ImportedLead(target, str(lead_id), _verification_status(response), 1)
                )
            except Exception as error:  # noqa: BLE001 - one lead failure remains isolated
                imported.append(
                    _ImportedLead(target, None, None, 1, str(error)[:1000])
                )
        for poll in range(15):
            pending = [item for item in imported if item.lead_id and item.verification_status in {None, 11, 12}]
            if not pending:
                break
            if poll:
                time.sleep(2)
            for item in pending:
                try:
                    response = self._provider.get_lead(str(item.lead_id))
                    item.request_count += 1
                    item.verification_status = _verification_status(response)
                    item.error = None
                except Exception as error:  # noqa: BLE001 - retry the bounded verification poll
                    item.request_count += 1
                    item.error = str(error)[:1000]
        accepted = [
            DeliveryAttempt(
                target_id=item.target.target_id,
                status="sent" if item.verification_status == 1 and not item.error else "failed",
                instantly_id=item.lead_id,
                provider_campaign_id=campaign_id,
                instantly_credit_units=1 if item.lead_id else 0,
                instantly_request_count=item.request_count,
                error=(
                    item.error
                    or _VERIFICATION_ERRORS.get(item.verification_status)
                    or (
                        None
                        if item.verification_status == 1
                        else "instantly_email_verification_pending"
                    )
                ),
            )
            for item in imported
        ]
        first = accepted[0]
        accepted[0] = DeliveryAttempt(
            **{**first.__dict__, "instantly_request_count": first.instantly_request_count + 1}
        )
        successful = [item for item in accepted if item.status == "sent"]
        if successful:
            self._provider.activate_campaign(campaign_id)
            first = successful[0]
            replacement = DeliveryAttempt(
                target_id=first.target_id,
                status=first.status,
                instantly_id=first.instantly_id,
                provider_campaign_id=first.provider_campaign_id,
                instantly_credit_units=first.instantly_credit_units,
                # Campaign activation is charged to one delivery row; creation was above.
                instantly_request_count=first.instantly_request_count + 1,
                error=first.error,
            )
            accepted[accepted.index(first)] = replacement
        return tuple(accepted)


__all__ = ["AssistedInstantlyDelivery", "AssistedInstantlyProvider"]
