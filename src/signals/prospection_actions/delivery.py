"""Permit-scoped one-message Instantly delivery for Founder-approved targets."""

from __future__ import annotations

import datetime as dt
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
        self, *, provider_campaign_id: str, leads: tuple[dict[str, object], ...]
    ) -> object: ...

    def activate_campaign(self, provider_campaign_id: str) -> object: ...


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
        accepted: list[DeliveryAttempt] = []
        for target in targets:
            try:
                response = self._provider.create_lead_or_batch(
                    provider_campaign_id=campaign_id,
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
                accepted.append(
                    DeliveryAttempt(
                        target_id=target.target_id,
                        status="sent",
                        instantly_id=str(lead_id),
                        provider_campaign_id=campaign_id,
                        instantly_credit_units=1,
                        instantly_request_count=1,
                    )
                )
            except Exception as error:  # noqa: BLE001 - one lead failure remains isolated
                accepted.append(
                    DeliveryAttempt(
                        target_id=target.target_id,
                        status="failed",
                        instantly_id=None,
                        provider_campaign_id=campaign_id,
                        instantly_credit_units=0,
                        instantly_request_count=1,
                        error=str(error)[:1000],
                    )
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
                # Campaign creation and activation are charged to one delivery row.
                instantly_request_count=first.instantly_request_count + 2,
                error=first.error,
            )
            accepted[accepted.index(first)] = replacement
        return tuple(accepted)


__all__ = ["AssistedInstantlyDelivery", "AssistedInstantlyProvider"]
