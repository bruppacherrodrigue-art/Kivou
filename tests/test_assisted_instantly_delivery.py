from __future__ import annotations

import datetime as dt

import pytest

from signals.prospection_actions.delivery import AssistedInstantlyDelivery
from signals.prospection_actions.service import DeliveryPermit, DeliveryTarget

NOW = dt.datetime(2026, 9, 11, 8, tzinfo=dt.UTC)


class Provider:
    def __init__(self) -> None:
        self.calls = []

    def create_assisted_campaign(self, *, name, provider_account_id, execution_date):
        self.calls.append(("create_campaign", name, provider_account_id, execution_date))
        return type("Campaign", (), {"provider_campaign_id": "campaign-1"})()

    def create_lead_or_batch(
        self, *, provider_campaign_id, leads, verify_leads_on_import=False
    ):
        self.calls.append(
            ("create_lead", provider_campaign_id, leads, verify_leads_on_import)
        )
        return {"id": f"lead-{len(self.calls)}", "verification_status": 1}

    def get_lead(self, provider_lead_id):
        self.calls.append(("get_lead", provider_lead_id))
        return {"id": provider_lead_id, "verification_status": 1}

    def activate_campaign(self, provider_campaign_id):
        self.calls.append(("activate", provider_campaign_id))


def target(target_id: str) -> DeliveryTarget:
    return DeliveryTarget(
        target_id=target_id,
        email=f"{target_id}@example.fr",
        company_name="Entreprise Exemple",
        director_name=None,
        subject="Signal marché public",
        text="Bonjour,\n\nTexte final.",
        html="<p>Bonjour,</p><p>Texte final.</p>",
    )


def test_assisted_delivery_creates_one_step_campaign_and_audits_request_cost() -> None:
    provider = Provider()
    delivery = AssistedInstantlyDelivery(
        provider=provider, provider_account_id="rodrigue@kivou.eu"
    )
    targets = (target("one"), target("two"))
    permit = DeliveryPermit(
        request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
        target_ids=frozenset({"one", "two"}),
        issued_at=NOW,
    )

    result = delivery.deliver(permit=permit, targets=targets, at=NOW)

    assert [call[0] for call in provider.calls] == [
        "create_campaign",
        "create_lead",
        "create_lead",
        "activate",
    ]
    assert all(item.status == "sent" for item in result)
    assert sum(item.instantly_request_count for item in result) == 4
    assert sum(item.instantly_credit_units for item in result) == 2
    leads = [call[2][0] for call in provider.calls if call[0] == "create_lead"]
    assert all(call[3] is True for call in provider.calls if call[0] == "create_lead")
    assert leads[0]["custom_variables"] == {
        "kivou_subject": "Signal marché public",
        "kivou_envelope": "<p>Bonjour,</p><p>Texte final.</p>",
    }


def test_assisted_delivery_refuses_any_target_outside_permit_before_provider() -> None:
    provider = Provider()
    delivery = AssistedInstantlyDelivery(
        provider=provider, provider_account_id="rodrigue@kivou.eu"
    )

    with pytest.raises(PermissionError, match="permit"):
        delivery.deliver(
            permit=DeliveryPermit(
                request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
                target_ids=frozenset({"one"}),
                issued_at=NOW,
            ),
            targets=(target("one"), target("two")),
            at=NOW,
        )

    assert provider.calls == []


def test_assisted_delivery_does_not_activate_an_invalid_import_and_audits_it() -> None:
    class InvalidProvider(Provider):
        def create_lead_or_batch(
            self, *, provider_campaign_id, leads, verify_leads_on_import=False
        ):
            self.calls.append(
                ("create_lead", provider_campaign_id, leads, verify_leads_on_import)
            )
            return {"id": "lead-invalid", "verification_status": -1}

    provider = InvalidProvider()
    delivery = AssistedInstantlyDelivery(
        provider=provider, provider_account_id="rodrigue@kivou.eu"
    )
    permit = DeliveryPermit(
        request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
        target_ids=frozenset({"one"}),
        issued_at=NOW,
    )

    result = delivery.deliver(permit=permit, targets=(target("one"),), at=NOW)

    assert result[0].status == "failed"
    assert result[0].error == "instantly_email_verification_invalid"
    assert all(call[0] != "activate" for call in provider.calls)


def test_assisted_delivery_waits_for_import_verification_before_activation() -> None:
    class PendingProvider(Provider):
        def create_lead_or_batch(
            self, *, provider_campaign_id, leads, verify_leads_on_import=False
        ):
            self.calls.append(
                ("create_lead", provider_campaign_id, leads, verify_leads_on_import)
            )
            return {"id": "lead-pending", "verification_status": 12}

    provider = PendingProvider()
    delivery = AssistedInstantlyDelivery(
        provider=provider, provider_account_id="rodrigue@kivou.eu"
    )
    permit = DeliveryPermit(
        request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
        target_ids=frozenset({"one"}),
        issued_at=NOW,
    )

    result = delivery.deliver(permit=permit, targets=(target("one"),), at=NOW)

    assert result[0].status == "sent"
    assert [call[0] for call in provider.calls] == [
        "create_campaign",
        "create_lead",
        "get_lead",
        "activate",
    ]
