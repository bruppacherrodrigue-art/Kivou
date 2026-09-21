from __future__ import annotations

import datetime as dt
import json
from contextlib import contextmanager

import httpx
import pytest
import sqlalchemy as sa
from test_prospection_actions_service import NOW, TARGET_ID
from test_prospection_send_worker import target_row
from test_prospection_send_worker import worker_fixture as worker_fixture  # noqa: PLC0414
from test_prospection_send_worker_integrity import actions

from signals.campaigns.instantly import HttpInstantlyProvider
from signals.persistence.schema import prospect_send_item, prospect_send_request
from signals.prospection_actions.contracts import (
    ApproveCommand,
    CorrectCommand,
    CorrectionChanges,
    RejectCommand,
    SendCommand,
    SendTarget,
)
from signals.prospection_actions.delivery import AssistedInstantlyDelivery
from signals.prospection_actions.service import ProspectionActionError

OLD_REQUEST = "484be03d-fbe4-46b1-9900-b99b4068fcbd"
# Distinct UUIDs sharing the legacy name prefix must never share a campaign.
NEW_REQUEST = "484be03d-1111-4111-8111-111111111111"


def request_row(engine, request_id=OLD_REQUEST):
    with engine.connect() as connection:
        return dict(
            connection.execute(
                sa.select(prospect_send_request).where(
                    prospect_send_request.c.request_id == request_id
                )
            )
            .mappings()
            .one()
        )


def item_row(engine, request_id=OLD_REQUEST):
    with engine.connect() as connection:
        return dict(
            connection.execute(
                sa.select(prospect_send_item).where(prospect_send_item.c.request_id == request_id)
            )
            .mappings()
            .one()
        )


class Remote:
    """Offline HTTP storage: lead payload and verification belong to its campaign."""

    def __init__(self, verification_status):
        self.verification_status = verification_status
        self.campaigns = {}
        self.leads = {}
        self.calls = []
        self.imports = []
        self.activations = []
        self.campaign_searches = []
        self.before_verification = None

    def handle(self, request):
        path = request.url.path.removeprefix("/api/v2/")
        body = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, path))
        if path == "campaigns" and request.method == "GET":
            self.campaign_searches.append(request.url.params["search"])
            return httpx.Response(
                200,
                json={
                    "items": [
                        c
                        for c in self.campaigns.values()
                        if c["name"] == request.url.params["search"]
                    ],
                    "next_starting_after": None,
                },
            )
        if path == "campaigns" and request.method == "POST":
            campaign = {
                "id": f"campaign-{len(self.campaigns) + 1}",
                "name": body["name"],
                "status": 2,
            }
            self.campaigns[campaign["id"]] = campaign
            return httpx.Response(200, json=campaign)
        if path == "leads/list":
            return httpx.Response(
                200,
                json={
                    "items": [
                        lead for lead in self.leads.values() if lead["campaign"] == body["campaign"]
                    ],
                    "next_starting_after": None,
                },
            )
        if path == "leads" and request.method == "POST":
            self.imports.append(body)
            # Official create-lead contract: this flag skips existing workspace leads.
            if body.get("skip_if_in_workspace") and any(
                lead["email"] == body["email"] for lead in self.leads.values()
            ):
                return httpx.Response(200, json={"status": "skipped"})
            lead = {
                "id": f"lead-{len(self.leads) + 1}",
                "email": body["email"],
                "campaign": body["campaign"],
                "payload": body["custom_variables"],
                "verification_status": self.verification_status,
            }
            self.leads[lead["id"]] = lead
            return httpx.Response(200, json=lead)
        if path.startswith("leads/") and request.method == "GET":
            if self.before_verification:
                callback, self.before_verification = self.before_verification, None
                callback()
            return httpx.Response(200, json=self.leads[path.split("/")[1]])
        if path.endswith("/activate"):
            campaign_id = path.split("/")[1]
            self.activations.append(campaign_id)
            self.campaigns[campaign_id]["status"] = 1
            return httpx.Response(200, json=self.campaigns[campaign_id])
        if path.startswith("campaigns/") and request.method == "GET":
            return httpx.Response(200, json=self.campaigns[path.split("/")[1]])
        pytest.fail(f"unexpected offline HTTP request {request.method} {path}")


@contextmanager
def actual_delivery(worker, verification_status):
    remote = Remote(verification_status)
    with httpx.Client(transport=httpx.MockTransport(remote.handle)) as client:
        worker._delivery = AssistedInstantlyDelivery(
            provider=HttpInstantlyProvider(api_key="synthetic", client=client),
            provider_account_id="sender@example.invalid",
        )
        yield remote


def enqueue_corrected(service, engine):
    target = target_row(engine)
    if target["status"] == "pending_review":
        service.approve(
            ApproveCommand(target_id=TARGET_ID, expected_version=target["version"]),
            actor="reviewer",
        )
        target = target_row(engine)
    service.enqueue_send(
        SendCommand(
            request_id=NEW_REQUEST,
            targets=(SendTarget(target_id=TARGET_ID, expected_version=target["version"]),),
        ),
        actor="reviewer",
    )


def test_invalid_lead_email_correction_imports_new_payload_in_new_request(worker_fixture):
    worker, _provider, engine = worker_fixture(verification_status=-1)
    service = actions(engine)
    with actual_delivery(worker, -1) as remote:
        assert worker.run_once(worker_ref="worker", now=NOW).status == "failed"
        old_item = item_row(engine)
        old_request = request_row(engine)
        service.correct(
            CorrectCommand(
                target_id=TARGET_ID,
                expected_version=target_row(engine)["version"],
                changes=CorrectionChanges(email_address="Corrected@beton-bourbonnais.fr"),
            ),
            actor="reviewer",
        )
        assert target_row(engine)["delivery_error"] is None
        enqueue_corrected(service, engine)
        remote.verification_status = 1
        assert (
            worker.run_once(worker_ref="worker", now=NOW + dt.timedelta(minutes=1)).status
            == "completed"
        )
    assert [body["email"] for body in remote.imports] == [
        "contact@beton-bourbonnais.fr",
        "corrected@beton-bourbonnais.fr",
    ]
    assert [body["campaign"] for body in remote.imports] == ["campaign-1", "campaign-2"]
    assert remote.activations == ["campaign-2"]
    assert OLD_REQUEST in remote.campaigns["campaign-1"]["name"]
    assert NEW_REQUEST in remote.campaigns["campaign-2"]["name"]
    assert ("GET", "leads/lead-2") in remote.calls
    assert item_row(engine) == old_item
    assert request_row(engine) == old_request
    assert target_row(engine)["instantly_credit_units"] == 2


@pytest.mark.parametrize("change", ["email", "director", "regenerate"])
def test_corrected_pending_payload_uses_new_campaign_and_keeps_old_campaign_blocked(
    worker_fixture, change
):
    worker, _provider, engine = worker_fixture(verification_status=12)
    service = actions(engine)
    with actual_delivery(worker, 12) as remote:
        assert worker.run_once(worker_ref="worker", now=NOW).status == "waiting"
        before_target, before_request = target_row(engine), request_row(engine)
        if change == "regenerate":
            assert service.regenerate_pending_mail_v2() == 1
        else:
            service.correct(
                CorrectCommand(
                    target_id=TARGET_ID,
                    expected_version=2,
                    changes=CorrectionChanges(
                        **(
                            {"email_address": "corrected@beton-bourbonnais.fr"}
                            if change == "email"
                            else {"director_name": "Camille Exemple"}
                        )
                    ),
                ),
                actor="reviewer",
            )
        changed = target_row(engine)
        assert changed["instantly_id"] is None
        assert changed["provider_campaign_id"] is None
        assert changed["instantly_credit_units"] == before_target["instantly_credit_units"]
        assert changed["instantly_request_count"] == before_target["instantly_request_count"]
        assert item_row(engine)["instantly_id"] == "lead-1"
        assert request_row(engine) == before_request
        assert (
            worker.run_once(worker_ref="worker", now=NOW + dt.timedelta(minutes=1)).status
            == "waiting"
        )
        assert request_row(engine)["result"]["activation_blocked"] == "target_changed_after_enqueue"
        assert request_row(engine)["provider_campaign_id"] == "campaign-1"
        assert item_row(engine)["status"] == "failed"
        enqueue_corrected(service, engine)
        remote.verification_status = 1
        assert (
            worker.run_once(worker_ref="worker", now=NOW + dt.timedelta(minutes=1)).status
            == "completed"
        )
        sent_target = target_row(engine)
        # The old activation carrier must neither activate nor overwrite the new target.
        assert (
            worker.run_once(worker_ref="worker", now=NOW + dt.timedelta(minutes=2)).status
            == "waiting"
        )
        assert target_row(engine) == sent_target
    assert remote.activations == ["campaign-2"]
    assert [body["campaign"] for body in remote.imports] == ["campaign-1", "campaign-2"]
    assert remote.imports[1]["custom_variables"] == {
        "kivou_subject": changed["mail_subject"],
        "kivou_envelope": changed["mail_html"],
    }
    assert remote.imports[1]["skip_if_in_workspace"] is False
    if change == "director":
        assert remote.imports[1]["custom_variables"] != remote.imports[0]["custom_variables"]
    elif change == "email":
        assert remote.imports[1]["email"] == changed["email_address"]
        assert remote.imports[1]["email"] != remote.imports[0]["email"]
    else:
        assert changed["version"] == before_target["version"] + 1
    assert request_row(engine, NEW_REQUEST)["status"] == "completed"
    assert "reconcile imported lead" in request_row(engine)["error"].lower()


@pytest.mark.parametrize("change", ["correct", "reject", "regenerate"])
def test_actions_clear_reusable_binding_but_keep_old_item_exposure_without_import_receipt(
    worker_fixture, change
):
    worker, _provider, engine = worker_fixture(
        verification_status=12,
        instantly_id="existing-lead",
        provider_campaign_id="existing-campaign",
    )
    service = actions(engine)
    if change == "correct":
        service.correct(
            CorrectCommand(
                target_id=TARGET_ID,
                expected_version=2,
                changes=CorrectionChanges(director_name="Camille Exemple"),
            ),
            actor="reviewer",
        )
    elif change == "reject":
        service.reject(
            RejectCommand(target_id=TARGET_ID, expected_version=2, reason="off_topic"),
            actor="reviewer",
        )
        with pytest.raises(ProspectionActionError, match="seule une cible en attente"):
            service.approve(
                ApproveCommand(target_id=TARGET_ID, expected_version=3), actor="reviewer"
            )
    else:
        service.regenerate_pending_mail_v2()
    assert target_row(engine)["instantly_id"] is None
    assert target_row(engine)["provider_campaign_id"] is None
    assert item_row(engine)["instantly_id"] == "existing-lead"
    with actual_delivery(worker, 12) as remote:
        assert worker.run_once(worker_ref="worker", now=NOW).status == "waiting"
    assert remote.calls == []
    assert request_row(engine)["provider_campaign_id"] == "existing-campaign"
    assert request_row(engine)["result"]["activation_blocked"] == "target_changed_after_enqueue"


def test_reused_binding_is_recorded_before_verification_can_be_corrected(worker_fixture):
    worker, _provider, engine = worker_fixture(
        verification_status=12,
        instantly_id="existing-lead",
        provider_campaign_id="existing-campaign",
    )
    # Actual enqueue leaves the new item unbound; only the target has the reusable ID.
    with engine.begin() as connection:
        connection.execute(sa.update(prospect_send_item).values(instantly_id=None))
    with actual_delivery(worker, 12) as remote:
        remote.campaigns["existing-campaign"] = {
            "id": "existing-campaign",
            "name": "existing",
            "status": 2,
        }
        remote.leads["existing-lead"] = {
            "id": "existing-lead",
            "campaign": "existing-campaign",
            "email": target_row(engine)["email_address"],
            "verification_status": 12,
        }

        def correct_during_get():
            assert item_row(engine)["instantly_id"] == "existing-lead"
            actions(engine).correct(
                CorrectCommand(
                    target_id=TARGET_ID,
                    expected_version=2,
                    changes=CorrectionChanges(director_name="Camille Exemple"),
                ),
                actor="reviewer",
            )

        remote.before_verification = correct_during_get
        assert worker.run_once(worker_ref="worker", now=NOW).status == "waiting"
    assert request_row(engine)["result"]["activation_blocked"] == "target_changed_after_enqueue"
    assert remote.calls == [("GET", "leads/existing-lead")]


def test_sent_target_binding_and_acceptance_are_not_invalidated(worker_fixture):
    worker, _provider, engine = worker_fixture(verification_status=1)
    with actual_delivery(worker, 1):
        assert worker.run_once(worker_ref="worker", now=NOW).status == "completed"
    before = target_row(engine)
    service = actions(engine)
    with pytest.raises(ProspectionActionError, match="envoyée"):
        service.correct(
            CorrectCommand(
                target_id=TARGET_ID,
                expected_version=before["version"],
                changes=CorrectionChanges(director_name="Camille Exemple"),
            ),
            actor="reviewer",
        )
    with pytest.raises(ProspectionActionError, match="écartée"):
        service.reject(
            RejectCommand(
                target_id=TARGET_ID, expected_version=before["version"], reason="off_topic"
            ),
            actor="reviewer",
        )
    assert service.regenerate_pending_mail_v2() == 0
    assert target_row(engine) == before


@pytest.mark.parametrize("stored_name", [False, True])
def test_persisted_legacy_create_intent_reconciles_only_its_exact_name(worker_fixture, stored_name):
    worker, _provider, engine = worker_fixture(verification_status=12)
    name = f"Kivou assisted {NOW.date()} {OLD_REQUEST[:8]}"
    intent = {"kind": "mutation", "confirmed": False, "zero_matches": True, "attempt_count": 1}
    if stored_name:
        name = f"Kivou assisted legacy {OLD_REQUEST}"
        intent["campaign_name"] = name
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_request).values(
                result={"accounting": {"campaign:create": intent}}
            )
        )
    with actual_delivery(worker, 12) as remote:
        remote.campaigns["legacy-campaign"] = {"id": "legacy-campaign", "name": name, "status": 2}
        # A similar prefix from another request is not an exact reconciliation match.
        remote.campaigns["unrelated-campaign"] = {
            "id": "unrelated-campaign",
            "name": f"{name}-unrelated",
            "status": 2,
        }
        assert worker.run_once(worker_ref="worker", now=NOW).status == "waiting"
    assert ("POST", "campaigns") not in remote.calls
    assert remote.campaigns["legacy-campaign"]["name"] == name
    assert request_row(engine)["provider_campaign_id"] == "legacy-campaign"
    assert remote.imports[0]["campaign"] == "legacy-campaign"
    assert remote.campaign_searches == [name]


def test_absent_legacy_campaign_gets_full_identity_before_new_creation(worker_fixture):
    worker, _provider, engine = worker_fixture(verification_status=12)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_request).values(
                result={
                    "accounting": {
                        "campaign:create": {
                            "kind": "mutation",
                            "zero_matches": True,
                            "confirmed": False,
                            "attempt_count": 1,
                        }
                    }
                }
            )
        )
    with actual_delivery(worker, 12) as remote:
        assert worker.run_once(worker_ref="worker", now=NOW).status == "waiting"
    full_name = f"Kivou assisted {NOW.date()} {OLD_REQUEST}"
    assert remote.campaign_searches == [f"Kivou assisted {NOW.date()} {OLD_REQUEST[:8]}", full_name]
    assert remote.campaigns["campaign-1"]["name"] == full_name
    assert (
        request_row(engine)["result"]["accounting"]["campaign:create"]["campaign_name"] == full_name
    )
