from __future__ import annotations

import datetime as dt
import json
from dataclasses import replace

import httpx
import pytest
import sqlalchemy as sa
from test_prospection_actions_service import NOW, TARGET_ID
from test_prospection_send_worker import send_item, target_row
from test_prospection_send_worker import worker_fixture as worker_fixture  # noqa: PLC0414
from test_prospection_send_worker_integrity import actions, add_second

from signals.campaigns.instantly import HttpInstantlyProvider
from signals.persistence.schema import prospect_send_item, prospect_send_request, prospect_target
from signals.prospection_actions.contracts import (
    ApproveCommand,
    CorrectCommand,
    CorrectionChanges,
    RejectCommand,
    SendCommand,
    SendTarget,
)
from signals.prospection_actions.delivery import AssistedInstantlyDelivery


def request_row(engine):
    with engine.connect() as connection:
        return dict(connection.execute(sa.select(prospect_send_request)).mappings().one())


def test_render_failure_releases_owned_reservation_without_changing_target(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=-1)
    service = actions(engine)
    renderer = service._mail_renderer
    service._mail_renderer = lambda row: replace(
        renderer(row), contract_status="failed", contract_failure="url_count_invalid"
    )
    service.correct(
        CorrectCommand(
            target_id=TARGET_ID,
            expected_version=2,
            changes=CorrectionChanges(company_name="Changed company"),
        ),
        actor="reviewer",
    )
    before = target_row(engine)
    assert before["status"] == "pending_review"
    assert worker.run_once(worker_ref="worker", now=NOW).status == "failed"
    assert target_row(engine) == {**before, "send_request_id": None}
    assert send_item(engine)["error_code"] == "target_changed_after_enqueue"
    assert provider.create_campaign_calls == provider.get_lead_calls == []
    service._mail_renderer = renderer
    service.correct(
        CorrectCommand(
            target_id=TARGET_ID,
            expected_version=3,
            changes=CorrectionChanges(company_name="Corrected company"),
        ),
        actor="reviewer",
    )
    service.approve(ApproveCommand(target_id=TARGET_ID, expected_version=4), actor="reviewer")
    new_request_id = "aaaaaaaa-1111-4111-8111-111111111111"
    service.enqueue_send(
        SendCommand(
            request_id=new_request_id,
            targets=(SendTarget(target_id=TARGET_ID, expected_version=5),),
        ),
        actor="reviewer",
    )
    assert target_row(engine)["send_request_id"] == new_request_id


def test_changed_target_preserves_another_requests_reservation(worker_fixture):
    worker, _provider, engine = worker_fixture(verification_status=1)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target).values(
                status="pending_review", send_request_id="replacement-request"
            )
        )
    before = target_row(engine)
    worker.run_once(worker_ref="worker", now=NOW)
    assert target_row(engine) == before


@pytest.mark.parametrize("cancel_first", [False, True])
def test_pre_exposure_cancellation_does_not_block_valid_sibling(worker_fixture, cancel_first):
    worker, provider, engine = worker_fixture(verification_status=1)
    second = add_second(engine)
    cancelled = TARGET_ID if cancel_first else second
    actions(engine).reject(
        RejectCommand(target_id=cancelled, expected_version=2, reason="off_topic"),
        actor="reviewer",
    )
    for minute in range(3):
        worker.run_once(worker_ref="worker", now=NOW + dt.timedelta(minutes=minute))
    request = request_row(engine)
    assert request["status"] == "partial"
    assert (request["processed_count"], request["sent_count"], request["failed_count"]) == (2, 1, 1)
    assert not request["result"].get("activation_blocked")
    assert provider.activate_calls == ["campaign-1"]
    assert len(provider.create_lead_calls) == 1


def test_post_import_binding_conflict_blocks_activation_with_recovery_error(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=1)
    second = add_second(engine)
    worker.run_once(worker_ref="worker", now=NOW)
    provider.verification_status = 12
    worker.run_once(worker_ref="worker", now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == second)
            .values(provider_campaign_id="other-campaign")
        )
    for minute in (1, 2):
        assert (
            worker.run_once(worker_ref="worker", now=NOW + dt.timedelta(minutes=minute)).status
            == "waiting"
        )
        request = request_row(engine)
        assert request["result"]["activation_blocked"] == "campaign_binding_conflict"
        assert "reconcile imported lead" in request["error"].lower()
        assert request["next_attempt_at"] is not None
    assert provider.activate_calls == []
    with engine.connect() as connection:
        item = (
            connection.execute(
                sa.select(prospect_send_item).where(prospect_send_item.c.target_id == second)
            )
            .mappings()
            .one()
        )
        target = (
            connection.execute(
                sa.select(prospect_target).where(prospect_target.c.target_id == second)
            )
            .mappings()
            .one()
        )
    assert item["status"] == "failed"
    assert target["provider_campaign_id"] == "other-campaign"
    assert target["send_request_id"] is None


def test_exposure_block_remains_visible_while_sibling_is_pending(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=12)
    second = add_second(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_item)
            .where(prospect_send_item.c.target_id == second)
            .values(next_attempt_at=NOW + dt.timedelta(minutes=2))
        )
    worker.run_once(worker_ref="worker", now=NOW)
    actions(engine).reject(
        RejectCommand(target_id=TARGET_ID, expected_version=2, reason="off_topic"),
        actor="reviewer",
    )
    for minute in (1, 2):
        assert (
            worker.run_once(worker_ref="worker", now=NOW + dt.timedelta(minutes=minute)).status
            == "waiting"
        )
        request = request_row(engine)
        assert request["result"]["activation_blocked"] == "target_changed_after_enqueue"
        assert "reconcile imported lead" in request["error"].lower()
    assert provider.activate_calls == []


@pytest.mark.parametrize("mutation", ["create", "import", "activate"])
def test_actual_adapter_counts_each_mutation_attempt_after_429(worker_fixture, mutation):
    worker, _provider, engine = worker_fixture(verification_status=1)
    email = target_row(engine)["email_address"]
    observed = []
    attempts = {"create": 0, "import": 0, "activate": 0}
    campaigns, leads = [], []
    active = False

    def handler(request):
        nonlocal active
        observed.append((request.method, request.url.path))
        body = json.loads(request.content) if request.content else {}
        if request.url.path.endswith("/leads/list"):
            return httpx.Response(200, json={"items": leads, "next_starting_after": None})
        if request.method == "GET":
            if request.url.path.endswith("/campaigns"):
                return httpx.Response(200, json={"items": campaigns, "next_starting_after": None})
            if "/leads/" in request.url.path:
                return httpx.Response(200, json={"id": "lead-1", "verification_status": 1})
            return httpx.Response(
                200,
                json={
                    "id": "campaign-1",
                    "name": campaigns[0]["name"],
                    "status": 1 if active else 2,
                },
            )
        kind = (
            "activate"
            if request.url.path.endswith("/activate")
            else "create"
            if request.url.path.endswith("/campaigns")
            else "import"
        )
        attempts[kind] += 1
        if kind == mutation and attempts[kind] == 1:
            return httpx.Response(429, json={"error": "synthetic rate limit"})
        if kind == "create":
            campaigns.append({"id": "campaign-1", "name": body["name"], "status": 2})
            return httpx.Response(200, json=campaigns[0])
        if kind == "import":
            leads.append({"id": "lead-1", "email": email, "campaign": "campaign-1"})
            return httpx.Response(200, json=leads[0])
        active = True
        return httpx.Response(200, json={"id": "campaign-1"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        worker._delivery = AssistedInstantlyDelivery(
            provider=HttpInstantlyProvider(api_key="synthetic", client=client),
            provider_account_id="sender@example.invalid",
        )
        assert worker.run_once(worker_ref="worker", now=NOW).status == "waiting"
        assert (
            worker.run_once(worker_ref="worker", now=NOW + dt.timedelta(minutes=1)).status
            == "completed"
        )
        assert (
            worker.run_once(worker_ref="worker", now=NOW + dt.timedelta(minutes=2)).status == "idle"
        )
    assert attempts[mutation] == 2
    target = target_row(engine)
    assert target["instantly_request_count"] == len(observed)
    assert target["instantly_credit_units"] == 1
    key = f"lead:{TARGET_ID}:import" if mutation == "import" else f"campaign:{mutation}"
    ledger = request_row(engine)["result"]["accounting"]
    assert ledger[key]["attempt_count"] == 2
    assert ledger[f"lead:{TARGET_ID}:import"]["confirmed"] is True


@pytest.mark.parametrize("legacy_ledger", [False, True])
@pytest.mark.parametrize("kind", ["campaign", "lead"])
def test_changing_pagination_cursors_keep_ledger_bounded_across_retries(
    worker_fixture, legacy_ledger, kind
):
    worker, _provider, engine = worker_fixture(
        verification_status=12, provider_campaign_id="existing" if kind == "lead" else None
    )
    phase = f"lead:{TARGET_ID}:list" if kind == "lead" else "campaign:list"
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_request).values(
                result={
                    "activation": {"state": "paused"},
                    "audit_marker": "preserved",
                    "accounting": {
                        f"{phase}:old-page-{page}": {
                            "kind": "read",
                            "attempts": 4,
                            "receipt": f"receipt-{page}",
                        }
                        for page in range(3)
                    }
                    if legacy_ledger
                    else {},
                }
            )
        )
        connection.execute(
            sa.update(prospect_target).values(
                instantly_request_count=12 if legacy_ledger else 0, instantly_credit_units=7
            )
        )
    observed = []
    cursor = ""

    def handler(request):
        observed.append(request)
        body = json.loads(request.content) if request.content else dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "items": [],
                "next_starting_after": 42 if body.get("starting_after") else cursor,
            },
        )

    sizes = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        worker._delivery = AssistedInstantlyDelivery(
            provider=HttpInstantlyProvider(api_key="synthetic", client=client),
            provider_account_id="sender@example.invalid",
        )
        for attempt in range(6):
            cursor = f"page-{attempt}-" + "x" * 200
            assert (
                worker.run_once(worker_ref="worker", now=NOW + dt.timedelta(minutes=attempt)).status
                == "waiting"
            )
            result = request_row(engine)["result"]
            ledger = result["accounting"]
            assert set(ledger) == {phase}
            expected_count = len(observed) + (12 if legacy_ledger else 0)
            assert ledger[phase]["read_count"] == expected_count
            assert target_row(engine)["instantly_request_count"] == expected_count
            assert target_row(engine)["instantly_credit_units"] == 7
            assert cursor not in json.dumps(result)
            assert result["activation"] == {"state": "paused"}
            assert result["audit_marker"] == "preserved"
            sizes.append(len(json.dumps(result)))
    assert len(observed) == 18
    assert max(sizes) - min(sizes) < 10
