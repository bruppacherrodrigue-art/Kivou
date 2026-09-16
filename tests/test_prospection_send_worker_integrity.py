from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest
import sqlalchemy as sa
from test_prospection_actions_send import Suppressions, _seed_second_target
from test_prospection_actions_service import NOW, TARGET_ID, LinkIssuer, MxVerifier
from test_prospection_send_worker import send_item, target_row
from test_prospection_send_worker import worker_fixture as worker_fixture  # noqa: PLC0414

from signals.campaigns.instantly import HttpInstantlyProvider
from signals.persistence.schema import prospect_send_item, prospect_send_request, prospect_target
from signals.prospection_actions.contracts import CorrectCommand, CorrectionChanges, RejectCommand
from signals.prospection_actions.delivery import AssistedInstantlyDelivery
from signals.prospection_actions.service import ProspectionActions


def actions(engine):
    return ProspectionActions(
        engine,
        email_verifier=MxVerifier(),
        link_issuer=LinkIssuer(),
        suppression_checker=Suppressions(),
        clock=lambda: NOW,
    )


def add_second(engine):
    target_id = _seed_second_target(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_request).values(
                reserved_count=2,
                target_ids=[TARGET_ID, target_id],
            )
        )
        connection.execute(
            sa.insert(prospect_send_item).values(
                request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
                target_id=target_id,
                position=1,
                expected_version=2,
                status="queued",
                next_attempt_at=NOW,
                attempt_count=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    return target_id


@pytest.mark.parametrize("change", ["reject", "correct", "unreserve"])
@pytest.mark.parametrize("during_get", [False, True])
@pytest.mark.parametrize("verification_status", [1, -1, 12])
def test_current_authorization_is_checked_before_provider_and_finalization(
    worker_fixture, change, during_get, verification_status
):
    worker, provider, engine = worker_fixture(verification_status=verification_status)

    def change_target():
        if change == "reject":
            actions(engine).reject(
                RejectCommand(target_id=TARGET_ID, expected_version=2, reason="off_topic"),
                actor="reviewer",
            )
        elif change == "correct":
            actions(engine).correct(
                CorrectCommand(
                    target_id=TARGET_ID,
                    expected_version=2,
                    changes=CorrectionChanges(company_name="Changed company"),
                ),
                actor="reviewer",
            )
        else:
            with engine.begin() as connection:
                connection.execute(sa.update(prospect_target).values(send_request_id=None))

    if during_get:
        original = provider.get_lead

        def get(lead_id):
            change_target()
            return original(lead_id)

        provider.get_lead = get
    else:
        change_target()

    worker.run_once(worker_ref="worker", now=NOW)

    item = send_item(engine)
    assert item["status"] == "failed"
    assert item["error_code"] == "target_changed_after_enqueue"
    target = target_row(engine)
    assert target["status"] == ("rejected" if change == "reject" else "approved")
    assert target["version"] == (2 if change == "unreserve" else 3)
    assert provider.activate_calls == []
    if not during_get:
        assert (
            provider.create_campaign_calls
            == provider.create_lead_calls
            == provider.get_lead_calls
            == []
        )


@pytest.mark.parametrize("conflict", [False, True])
def test_existing_campaign_binds_request_and_all_siblings(worker_fixture, conflict):
    worker, provider, engine = worker_fixture(
        verification_status=1, provider_campaign_id="existing", instantly_id="existing-lead"
    )
    second = add_second(engine)
    with engine.begin() as connection:
        connection.execute(sa.update(prospect_send_request).values(provider_campaign_id=None))
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == second)
            .values(
                provider_campaign_id="other" if conflict else None,
                instantly_id="other-lead" if conflict else None,
            )
        )
    assert worker.run_once(worker_ref="worker-a", now=NOW).status == "waiting"
    worker.run_once(worker_ref="worker-b", now=NOW)
    assert provider.create_campaign_calls == []
    with engine.connect() as connection:
        request = connection.execute(sa.select(prospect_send_request)).mappings().one()
        item = (
            connection.execute(
                sa.select(prospect_send_item).where(prospect_send_item.c.target_id == second)
            )
            .mappings()
            .one()
        )
    assert request["provider_campaign_id"] == "existing"
    if conflict:
        assert item["error_code"] == "campaign_binding_conflict"
        assert provider.create_lead_calls == provider.activate_calls == []
    else:
        assert provider.create_lead_calls[0][0] == "existing"
        assert provider.activate_calls == ["existing"]


@pytest.mark.parametrize("kind", ["campaign", "lead"])
@pytest.mark.parametrize("mode", ["page_two", "cycle", "malformed", "foreign_scope"])
def test_actual_adapter_reconciliation_scans_complete_scoped_pages(worker_fixture, kind, mode):
    worker, _provider, engine = worker_fixture(
        verification_status=12, provider_campaign_id="existing" if kind == "lead" else None
    )
    email = target_row(engine)["email_address"]
    observed = []

    def handler(request):
        observed.append(
            (
                request.method,
                request.url.path,
                json.loads(request.content) if request.content else dict(request.url.params),
            )
        )
        if request.url.path.endswith("/leads/list"):
            body = json.loads(request.content)
            assert body["campaign"] == ("existing" if kind == "lead" else "remote-campaign")
            if kind == "campaign":
                return httpx.Response(
                    200,
                    json={
                        "items": [{"id": "lead-1", "email": email, "campaign": "remote-campaign"}],
                        "next_starting_after": None,
                    },
                )
            cursor = body.get("starting_after")
            item = {
                "id": "lead-1",
                "email": email,
                "campaign": "foreign" if mode == "foreign_scope" else "existing",
            }
        elif request.url.path.endswith("/campaigns") and request.method == "GET":
            cursor = request.url.params.get("starting_after")
            item = {"id": "remote-campaign", "name": request.url.params["search"], "status": 2}
        elif "/leads/" in request.url.path and request.method == "GET":
            return httpx.Response(200, json={"id": "lead-1", "verification_status": 12})
        else:
            return httpx.Response(500, json={"error": "mutation must not be needed"})
        if mode == "malformed":
            return httpx.Response(200, json={"items": [], "next_starting_after": 42})
        if mode == "cycle":
            return httpx.Response(200, json={"items": [], "next_starting_after": "repeated"})
        return httpx.Response(
            200,
            json={
                "items": [item] if cursor or mode == "foreign_scope" else [],
                "next_starting_after": None if cursor or mode == "foreign_scope" else "page-2",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        worker._delivery = AssistedInstantlyDelivery(
            provider=HttpInstantlyProvider(api_key="synthetic", client=client),
            provider_account_id="sender@example.invalid",
        )
        outcome = worker.run_once(worker_ref="worker", now=NOW)
    assert outcome.status == "waiting"
    assert target_row(engine)["instantly_credit_units"] == 0
    assert target_row(engine)["instantly_request_count"] == len(observed)
    assert all(method == "GET" or path.endswith("/leads/list") for method, path, _ in observed)
    if mode == "page_two" or (kind == "campaign" and mode == "foreign_scope"):
        assert send_item(engine)["instantly_id"] == "lead-1"
    else:
        assert "reconciliation" in send_item(engine)["error_message"].lower()


def test_import_costs_survive_pending_then_acceptance(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=12)
    worker.run_once(worker_ref="worker-a", now=NOW)
    pending = target_row(engine)
    assert pending["instantly_credit_units"] == 1
    # Campaign create, lead import, verification, plus all reconciliation HTTP reads.
    assert pending["instantly_request_count"] == 7
    provider.verification_status = 1
    worker.run_once(worker_ref="worker-b", now=NOW + dt.timedelta(minutes=1))
    accepted = target_row(engine)
    assert accepted["instantly_credit_units"] == 1
    assert accepted["instantly_request_count"] == 11
    assert provider.get_lead_calls == ["lead-1", "lead-1"]


def test_invalid_import_retains_costs_and_historical_totals(worker_fixture):
    worker, _provider, engine = worker_fixture(verification_status=-1)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target).values(instantly_credit_units=7, instantly_request_count=11)
        )
    worker.run_once(worker_ref="worker", now=NOW)
    target = target_row(engine)
    assert target["instantly_credit_units"] == 8
    assert target["instantly_request_count"] == 18
    assert send_item(engine)["status"] == "failed"


@pytest.mark.parametrize("point", ["before_import", "after_import"])
def test_import_intent_preserves_declared_costs_and_confirms_credit_once(worker_fixture, point):
    worker, provider, engine = worker_fixture(verification_status=12)
    original = provider.create_lead_or_batch
    crashed = False

    class Crash(BaseException):
        pass

    def import_and_crash(**kwargs):
        nonlocal crashed
        if not crashed:
            crashed = True
            if point == "after_import":
                original(**kwargs)
            raise Crash()
        return original(**kwargs)

    provider.create_lead_or_batch = import_and_crash
    with pytest.raises(Crash):
        worker.run_once(worker_ref="worker-a", now=NOW)
    before = target_row(engine)
    assert before["instantly_credit_units"] == 0
    assert before["instantly_request_count"] == 6
    assert (
        worker.run_once(worker_ref="worker-b", now=NOW + dt.timedelta(minutes=6)).status
        == "waiting"
    )
    assert target_row(engine)["instantly_credit_units"] == 1
    assert len(provider.create_lead_calls) == 1
    assert target_row(engine)["instantly_request_count"] == 8
    provider.verification_status = 1
    assert (
        worker.run_once(worker_ref="worker-c", now=NOW + dt.timedelta(minutes=7)).status
        == "completed"
    )
    assert target_row(engine)["instantly_credit_units"] == 1
    with engine.connect() as connection:
        result = connection.scalar(sa.select(prospect_send_request.c.result))
    assert result["accounting"][f"lead:{TARGET_ID}:import"]["confirmed"] is True
