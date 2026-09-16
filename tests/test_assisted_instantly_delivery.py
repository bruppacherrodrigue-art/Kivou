from __future__ import annotations

import datetime as dt

import pytest

from signals.prospection_actions.delivery import AssistedInstantlyDelivery
from signals.prospection_actions.service import DeliveryTarget

NOW = dt.datetime(2026, 9, 11, 8, tzinfo=dt.UTC)


class Provider:
    def __init__(self, verification_status: int = 1) -> None:
        self.verification_status = verification_status
        self.calls: list[tuple[object, ...]] = []

    def create_assisted_campaign(self, *, name, provider_account_id, execution_date):
        self.calls.append(("create_campaign", name, provider_account_id, execution_date))
        return type("Campaign", (), {"provider_campaign_id": "campaign-1"})()

    def create_lead_or_batch(self, *, provider_campaign_id, leads, verify_leads_on_import=False):
        self.calls.append(("create_lead", provider_campaign_id, leads, verify_leads_on_import))
        return {"id": "lead-1", "verification_status": self.verification_status}

    def get_lead(self, provider_lead_id):
        self.calls.append(("get_lead", provider_lead_id))
        return {"id": provider_lead_id, "verification_status": self.verification_status}

    def activate_campaign(self, provider_campaign_id):
        self.calls.append(("activate", provider_campaign_id))


def target() -> DeliveryTarget:
    return DeliveryTarget(
        target_id="one",
        email="one@example.fr",
        company_name="Entreprise Exemple",
        director_name=None,
        subject="Signal marché public",
        text="Bonjour,\n\nTexte final.",
        html="<p>Bonjour,</p><p>Texte final.</p>",
    )


def test_incremental_delivery_creates_campaign_and_imports_one_target() -> None:
    provider = Provider()
    delivery = AssistedInstantlyDelivery(provider=provider, provider_account_id="rodrigue@kivou.eu")

    campaign_id = delivery.ensure_campaign({"request_id": "request-12345678"}, at=NOW)
    lead_id = delivery.import_target(campaign_id, target())

    assert campaign_id == "campaign-1"
    assert lead_id == "lead-1"
    assert [call[0] for call in provider.calls] == ["create_campaign", "create_lead"]
    assert provider.calls[1][2][0]["custom_variables"] == {
        "kivou_subject": "Signal marché public",
        "kivou_envelope": "<p>Bonjour,</p><p>Texte final.</p>",
    }


def test_verification_performs_exactly_one_read_and_reports_pending() -> None:
    provider = Provider(verification_status=12)
    delivery = AssistedInstantlyDelivery(provider=provider, provider_account_id="rodrigue@kivou.eu")

    result = delivery.verification("lead-1")

    assert result.status == "pending"
    assert result.error_code is None
    assert [call[0] for call in provider.calls] == ["get_lead"]


@pytest.mark.parametrize(
    ("verification_status", "error_code"),
    [
        (-1, "instantly_email_invalid"),
        (-2, "instantly_email_risky"),
        (-3, "instantly_email_catch_all"),
        (-4, "instantly_email_job_change"),
    ],
)
def test_verification_exposes_terminal_public_codes(verification_status, error_code) -> None:
    provider = Provider(verification_status=verification_status)
    delivery = AssistedInstantlyDelivery(provider=provider, provider_account_id="rodrigue@kivou.eu")

    result = delivery.verification("lead-1")

    assert result.status == "failed"
    assert result.error_code == error_code


def test_incremental_delivery_activates_only_when_requested() -> None:
    provider = Provider()
    delivery = AssistedInstantlyDelivery(provider=provider, provider_account_id="rodrigue@kivou.eu")

    delivery.activate("campaign-1")

    assert provider.calls == [("activate", "campaign-1")]
