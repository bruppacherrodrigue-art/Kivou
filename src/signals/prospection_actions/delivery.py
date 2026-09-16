"""Small, resumable Instantly operations used by the prospect-send worker."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from signals.prospection_actions.service import DeliveryTarget


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

    def list_campaigns(self, *, search: str) -> tuple[object, ...]: ...

    def get_campaign(self, provider_campaign_id: str) -> object: ...

    def list_leads(self, *, provider_campaign_id: str) -> object: ...

    def activate_campaign(self, provider_campaign_id: str) -> object: ...


_VERIFICATION_ERRORS = {
    -1: "instantly_email_invalid",
    -2: "instantly_email_risky",
    -3: "instantly_email_catch_all",
    -4: "instantly_email_job_change",
}


@dataclass(frozen=True)
class Verification:
    status: str
    verification_status: int | None
    error_code: str | None = None


def _verification_status(response: object) -> int | None:
    value = response.get("verification_status") if isinstance(response, dict) else None
    return value if type(value) is int else None


class AssistedInstantlyDelivery:
    def __init__(self, *, provider: AssistedInstantlyProvider, provider_account_id: str) -> None:
        if not provider_account_id.strip():
            raise ValueError("assisted Instantly mailbox is required")
        self._provider = provider
        self._provider_account_id = provider_account_id.strip().casefold()

    def ensure_campaign(self, request: Mapping[str, object], *, at: dt.datetime) -> str:
        campaign = self._provider.create_assisted_campaign(
            name=self._campaign_name(request, at=at),
            provider_account_id=self._provider_account_id,
            execution_date=at.astimezone(dt.UTC).date(),
        )
        campaign_id = getattr(campaign, "provider_campaign_id", None)
        if not campaign_id:
            raise RuntimeError("Instantly did not return a campaign id")
        return str(campaign_id)

    def import_target(self, campaign_id: str, target: DeliveryTarget) -> str:
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
        return str(lead_id)

    def verification(self, instantly_id: str) -> Verification:
        """Read a lead exactly once; scheduling is deliberately the worker's job."""
        status = _verification_status(self._provider.get_lead(instantly_id))
        if status == 1:
            return Verification(status="accepted", verification_status=status)
        error_code = _VERIFICATION_ERRORS.get(status)
        if error_code is not None:
            return Verification(status="failed", verification_status=status, error_code=error_code)
        return Verification(status="pending", verification_status=status)

    def activate(self, campaign_id: str) -> None:
        self._provider.activate_campaign(campaign_id)

    def find_campaign(self, request: Mapping[str, object], *, at: dt.datetime) -> str | None:
        name = self._campaign_name(request, at=at)
        matches = [
            item
            for item in self._provider.list_campaigns(search=name)
            if getattr(item, "name", None) == name and getattr(item, "provider_campaign_id", None)
        ]
        return str(matches[0].provider_campaign_id) if len(matches) == 1 else None

    def find_lead(self, campaign_id: str, email: str) -> str | None:
        response = self._provider.list_leads(provider_campaign_id=campaign_id)
        items = response.get("items", []) if isinstance(response, dict) else []
        matches = [
            item
            for item in items
            if isinstance(item, dict)
            and str(item.get("email", "")).casefold() == email.casefold()
            and item.get("id")
        ]
        return str(matches[0]["id"]) if len(matches) == 1 else None

    def campaign_active(self, campaign_id: str) -> bool:
        campaign = self._provider.get_campaign(campaign_id)
        return str(getattr(campaign, "status", "")).casefold() in {"active", "1"}

    @staticmethod
    def _campaign_name(request: Mapping[str, object], *, at: dt.datetime) -> str:
        request_day = request.get("request_day") or at.astimezone(dt.UTC).date()
        return f"Kivou assisted {request_day} {str(request['request_id'])[:8]}"


__all__ = ["AssistedInstantlyDelivery", "AssistedInstantlyProvider", "Verification"]
