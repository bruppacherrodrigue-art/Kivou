"""Small, resumable Instantly operations used by the prospect-send worker."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
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

    def list_campaigns(self, *, search: str, starting_after: str | None = None) -> object: ...

    def get_campaign(self, provider_campaign_id: str) -> object: ...

    def get_campaign_status(self, provider_campaign_id: str) -> object: ...

    def list_leads(
        self, *, provider_campaign_id: str, starting_after: str | None = None
    ) -> object: ...

    def activate_campaign(self, provider_campaign_id: str) -> object: ...


_VERIFICATION_ERRORS = {
    -1: "instantly_email_invalid",
    -2: "instantly_email_risky",
    -3: "instantly_email_catch_all",
    -4: "instantly_email_job_change",
}
MAX_RECONCILIATION_PAGES = 20


class ReconciliationRequired(RuntimeError):
    """Remote identity is ambiguous; a worker must never guess a mutation."""


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

    def find_campaign(
        self,
        request: Mapping[str, object],
        *,
        at: dt.datetime,
        before_read: Callable[[str | None], None] | None = None,
    ) -> str | None:
        name = self._campaign_name(request, at=at)
        matches = []
        for items in self._pages(
            lambda **cursor: self._provider.list_campaigns(search=name, **cursor),
            before_read=before_read,
        ):
            for item in items:
                if not getattr(item, "name", None) or not getattr(
                    item, "provider_campaign_id", None
                ):
                    raise ReconciliationRequired("reconciliation_required: malformed campaigns")
                if item.name == name:
                    matches.append(item)
            if len(matches) > 1:
                raise ReconciliationRequired("reconciliation_required: multiple campaigns")
        return str(matches[0].provider_campaign_id) if matches else None

    def find_lead(
        self,
        campaign_id: str,
        email: str,
        *,
        before_read: Callable[[str | None], None] | None = None,
    ) -> str | None:
        matches = []
        for items in self._pages(
            lambda **cursor: self._provider.list_leads(provider_campaign_id=campaign_id, **cursor),
            before_read=before_read,
        ):
            for item in items:
                if (
                    not isinstance(item, dict)
                    or not item.get("id")
                    or not isinstance(item.get("email"), str)
                ):
                    raise ReconciliationRequired("reconciliation_required: malformed leads")
                if item.get("campaign_id", item.get("campaign")) != campaign_id or (
                    "campaign" in item and item["campaign"] != campaign_id
                ):
                    raise ReconciliationRequired("reconciliation_required: lead campaign mismatch")
                if item["email"].casefold() == email.casefold():
                    matches.append(item)
            if len(matches) > 1:
                raise ReconciliationRequired("reconciliation_required: multiple leads")
        return str(matches[0]["id"]) if matches else None

    @staticmethod
    def _pages(fetch, *, before_read):
        cursor = None
        seen = set()
        for _ in range(MAX_RECONCILIATION_PAGES):
            if before_read is not None:
                before_read(cursor)
            try:
                response = fetch(**({"starting_after": cursor} if cursor is not None else {}))
            except Exception as error:
                raise ReconciliationRequired(
                    "reconciliation_required: provider read failed"
                ) from error
            if isinstance(response, tuple):
                items, following = response, None
            elif isinstance(response, dict):
                if "next_starting_after" not in response or not isinstance(
                    response.get("items"), list
                ):
                    raise ReconciliationRequired("reconciliation_required: malformed pagination")
                items, following = response["items"], response["next_starting_after"]
            else:
                items = getattr(response, "items", None)
                following = getattr(response, "next_starting_after", None)
                if not isinstance(items, tuple):
                    raise ReconciliationRequired("reconciliation_required: malformed pagination")
            if following is not None and (
                not isinstance(following, str)
                or not 1 <= len(following) <= 512
                or following in seen
            ):
                raise ReconciliationRequired("reconciliation_required: malformed pagination")
            yield items
            if following is None:
                return
            seen.add(following)
            cursor = following
        raise ReconciliationRequired("reconciliation_required: pagination limit")

    def campaign_active(self, campaign_id: str) -> bool:
        """Active or completed proves activation; a paused campaign still needs resume."""
        read_status = getattr(self._provider, "get_campaign_status", self._provider.get_campaign)
        campaign = read_status(campaign_id)
        return str(getattr(campaign, "status", "")).casefold() in {"active", "1", "completed", "3"}

    @staticmethod
    def _campaign_name(request: Mapping[str, object], *, at: dt.datetime) -> str:
        request_day = request.get("request_day") or at.astimezone(dt.UTC).date()
        return f"Kivou assisted {request_day} {str(request['request_id'])[:8]}"


__all__ = [
    "AssistedInstantlyDelivery",
    "AssistedInstantlyProvider",
    "ReconciliationRequired",
    "Verification",
]
