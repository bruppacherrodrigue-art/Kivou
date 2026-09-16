from __future__ import annotations

import datetime as dt
import json

import pytest
import sqlalchemy as sa
from test_prospection_actions_service import NOW, seed

from signals.persistence.schema import prospect_send_item, prospect_send_request, prospect_target
from signals.prospection_actions.recovery import (
    RecoveryError,
    RecoveryPreview,
    recover_request,
)
from signals.prospection_actions.recovery import main as recovery_main
from signals.prospection_actions.worker import ProspectSendWorker

REQUEST_ID = "7b7a8aea-1111-4111-8111-111111111111"
CAMPAIGN_ID = "interrupted-campaign"
INVALID_EMAILS = {
    "contact@ambitionthd.com",
    "contact@malosse-sa.fr",
    "contact@bourguignon-dalalu.fr",
}


class Provider:
    def __init__(self, verification_by_lead: dict[str, int]) -> None:
        self.verification_by_lead = verification_by_lead
        self.create_campaign_calls: list[object] = []
        self.create_lead_calls: list[object] = []
        self.get_lead_calls: list[str] = []
        self.activate_calls: list[str] = []
        self.active = False

    def create_assisted_campaign(self, **_kwargs):
        self.create_campaign_calls.append(object())
        raise AssertionError("recovery must never create a campaign")

    def create_lead_or_batch(self, **_kwargs):
        self.create_lead_calls.append(object())
        raise AssertionError("recovery must never create a lead")

    def get_lead(self, provider_lead_id):
        self.get_lead_calls.append(provider_lead_id)
        return {
            "id": provider_lead_id,
            "verification_status": self.verification_by_lead[provider_lead_id],
        }

    def activate_campaign(self, provider_campaign_id):
        self.activate_calls.append(provider_campaign_id)
        self.active = True

    def get_campaign(self, _provider_campaign_id):
        return type("Campaign", (), {"status": "active" if self.active else "paused"})()

    def list_campaigns(self, *, search):
        return ()

    def list_leads(self, *, provider_campaign_id):
        return {"items": [], "next_starting_after": None}


@pytest.fixture
def interrupted_request(migrated_sqlite_engine, tmp_path):
    seed(migrated_sqlite_engine)
    with migrated_sqlite_engine.begin() as connection:
        original = dict(connection.execute(sa.select(prospect_target)).mappings().one())
        target_ids = []
        statuses: dict[str, int] = {}
        emails = [*INVALID_EMAILS] + [f"contact{index}@example{index}.fr" for index in range(17)]
        for position, email in enumerate(emails):
            target_id = f"{position + 1:08d}-1111-4111-8111-111111111111"
            lead_id = f"lead-{position + 1}"
            target = {
                **original,
                "target_id": target_id,
                "opportunity_key": f"incident-opportunity-{position}",
                "procedure_award_key": f"incident-procedure-{position}",
                "acquisition_opportunity_id": f"{position + 1:064x}",
                "email_address": email,
                "attribution_member_ref": f"{position + 1:064x}",
                "attribution_payload": {"member_ref": f"{position + 1:064x}"},
                "attribution_token_fingerprint": f"{position + 101:064x}",
                "status": "approved",
                "delivery_status": "not_sent",
                "provider_campaign_id": CAMPAIGN_ID,
                "instantly_id": lead_id,
                "send_request_id": None,
                "instantly_accepted_at": None,
                "sent_at": None,
                "version": 2,
            }
            connection.execute(sa.insert(prospect_target).values(**target))
            target_ids.append(target_id)
            statuses[lead_id] = -1 if email in INVALID_EMAILS else 1

        sent_id = "ffffffff-1111-4111-8111-111111111111"
        sent = {
            **original,
            "target_id": sent_id,
            "opportunity_key": "incident-original-acceptance",
            "procedure_award_key": "incident-original-acceptance",
            "acquisition_opportunity_id": "f" * 64,
            "email_address": "accepted@original.fr",
            "attribution_member_ref": "c" * 64,
            "attribution_payload": {"member_ref": "c" * 64},
            "attribution_token_fingerprint": "d" * 64,
            "status": "sent",
            "provider_campaign_id": CAMPAIGN_ID,
            "instantly_id": "accepted-lead",
            "instantly_accepted_at": NOW,
            "sent_at": None,
            "send_request_id": None,
            "version": 3,
        }
        connection.execute(sa.insert(prospect_target).values(**sent))
        target_ids.insert(0, sent_id)
        connection.execute(
            sa.insert(prospect_send_request).values(
                request_id=REQUEST_ID,
                payload_fingerprint="a" * 64,
                target_ids=target_ids,
                request_day=NOW.date(),
                reserved_count=21,
                sent_count=1,
                processed_count=1,
                failed_count=0,
                status="started",
                provider_campaign_id=None,
                created_by="incident-recovery",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    return migrated_sqlite_engine, tmp_path, Provider(statuses), tuple(target_ids)


def _run_until_terminal(worker: ProspectSendWorker) -> None:
    for minute in range(30):
        outcome = worker.run_once(
            worker_ref="recovery-test", now=NOW + dt.timedelta(minutes=minute)
        )
        if outcome.status in {"completed", "partial", "failed"}:
            return
    raise AssertionError("recovery queue did not become terminal")


def _failure_codes(engine) -> dict[str, str]:
    with engine.connect() as connection:
        return dict(
            connection.execute(
                sa.select(prospect_target.c.email_address, prospect_send_item.c.error_code)
                .join(
                    prospect_send_item,
                    prospect_send_item.c.target_id == prospect_target.c.target_id,
                )
                .where(prospect_send_item.c.status == "failed")
            ).all()
        )


def test_recovery_reconstructs_interrupted_batch_without_provider_mutations(interrupted_request):
    engine, tmp_path, provider, target_ids = interrupted_request

    preview = recover_request(engine, request_id=REQUEST_ID, dry_run=True)

    assert preview == RecoveryPreview(
        request_id=REQUEST_ID,
        approved_count=20,
        already_sent_count=1,
        existing_lead_count=20,
        create_lead_count=0,
    )
    assert provider.create_campaign_calls == provider.create_lead_calls == []
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(prospect_send_item)) == 0

    assert recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW) == preview
    assert recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW) == preview
    with engine.connect() as connection:
        request = dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
        items = (
            connection.execute(
                sa.select(prospect_send_item).order_by(prospect_send_item.c.position)
            )
            .mappings()
            .all()
        )
    assert (
        request["status"],
        request["reserved_count"],
        request["processed_count"],
        request["sent_count"],
        request["failed_count"],
    ) == ("queued", 21, 1, 1, 0)
    assert request["provider_campaign_id"] == CAMPAIGN_ID
    assert [item["target_id"] for item in items] == list(target_ids)
    assert items[0]["status"] == "sent"
    assert all(item["status"] == "queued" for item in items[1:])

    worker = ProspectSendWorker(
        engine,
        provider=provider,
        provider_account_id="founder@example.invalid",
        kill_switch_path=tmp_path / "disabled",
        clock=lambda: NOW,
    )
    _run_until_terminal(worker)

    assert provider.create_campaign_calls == provider.create_lead_calls == []
    with engine.connect() as connection:
        request = dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
        sent_count = connection.scalar(
            sa.select(sa.func.count())
            .select_from(prospect_target)
            .where(prospect_target.c.status == "sent")
        )
    assert request["status"] == "partial"
    assert (request["processed_count"], request["sent_count"], request["failed_count"]) == (
        21,
        18,
        3,
    )
    assert sent_count == 18
    assert _failure_codes(engine) == {email: "instantly_email_invalid" for email in INVALID_EMAILS}


def test_recovery_refuses_missing_or_cross_campaign_approved_targets_without_writes(
    interrupted_request,
):
    engine, _tmp_path, _provider, _target_ids = interrupted_request
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.email_address == "contact@ambitionthd.com")
            .values(instantly_id=None)
        )

    with pytest.raises(RecoveryError) as caught:
        recover_request(engine, request_id=REQUEST_ID, dry_run=False)

    assert caught.value.code == "RECOVERY_REMOTE_ID_MISSING"
    with engine.connect() as connection:
        request = dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
        item_count = connection.scalar(sa.select(sa.func.count()).select_from(prospect_send_item))
    assert request["status"] == "started"
    assert item_count == 0


def test_recovery_accounted_acceptance_is_never_worker_claimable(interrupted_request):
    engine, tmp_path, provider, target_ids = interrupted_request
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_request)
            .where(prospect_send_request.c.request_id == REQUEST_ID)
            .values(target_ids=[target_ids[0]], reserved_count=1, sent_count=1, processed_count=1)
        )

    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW)
    worker = ProspectSendWorker(
        engine,
        provider=provider,
        provider_account_id="founder@example.invalid",
        kill_switch_path=tmp_path / "disabled",
        clock=lambda: NOW,
    )

    assert worker.run_once(worker_ref="recovery-test", now=NOW).status == "idle"
    assert provider.activate_calls == []


def test_recovery_cli_uses_read_engine_for_dry_run_and_emits_safe_bounded_json(
    interrupted_request, capsys
):
    engine, _tmp_path, _provider, target_ids = interrupted_request
    write_used = False

    def write_engine():
        nonlocal write_used
        write_used = True
        return engine

    assert (
        recovery_main(
            [REQUEST_ID, "--dry-run"],
            read_engine_factory=lambda: engine,
            write_engine_factory=write_engine,
        )
        == 0
    )

    output = capsys.readouterr().out.splitlines()
    assert len(output) == 1
    payload = json.loads(output[0])
    assert payload == {
        "approved_count": 20,
        "already_sent_count": 1,
        "create_lead_count": 0,
        "existing_lead_count": 20,
        "request_id": REQUEST_ID,
        "status": "dry_run",
        "target_ids": list(target_ids),
    }
    assert write_used is False
    assert "@" not in output[0]


def test_recovery_cli_requires_one_uuid_and_one_mode(capsys):
    assert recovery_main(["--dry-run"]) == 2
    assert recovery_main([REQUEST_ID, "--dry-run", "--apply"]) == 2
    assert capsys.readouterr().out.splitlines() == [
        '{"status":"configuration_invalid"}',
        '{"status":"configuration_invalid"}',
    ]


def test_recovery_rejects_existing_item_with_another_target_lead_without_writes(
    interrupted_request,
):
    engine, _tmp_path, _provider, target_ids = interrupted_request
    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_item)
            .where(
                prospect_send_item.c.request_id == REQUEST_ID,
                prospect_send_item.c.target_id == target_ids[1],
            )
            .values(instantly_id="accepted-lead")
        )
    with engine.connect() as connection:
        before_request = dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
        before_items = connection.execute(sa.select(prospect_send_item)).mappings().all()

    with pytest.raises(RecoveryError) as caught:
        recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW)

    assert caught.value.code == "RECOVERY_ITEM_INCONSISTENT"
    with engine.connect() as connection:
        assert (
            dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
            == before_request
        )
        assert connection.execute(sa.select(prospect_send_item)).mappings().all() == before_items


def test_recovery_rejects_existing_sent_item_while_target_is_approved(interrupted_request):
    engine, _tmp_path, _provider, target_ids = interrupted_request
    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_item)
            .where(
                prospect_send_item.c.request_id == REQUEST_ID,
                prospect_send_item.c.target_id.in_(target_ids[1:]),
            )
            .values(status="sent", completed_at=NOW)
        )
        connection.execute(
            sa.update(prospect_send_request)
            .where(prospect_send_request.c.request_id == REQUEST_ID)
            .values(status="completed", processed_count=21, sent_count=21, failed_count=0)
        )

    with pytest.raises(RecoveryError) as caught:
        recover_request(engine, request_id=REQUEST_ID, dry_run=True)

    assert caught.value.code == "RECOVERY_ITEM_INCONSISTENT"


def test_worker_fails_closed_when_recovered_item_lead_differs_from_target(interrupted_request):
    engine, tmp_path, provider, target_ids = interrupted_request
    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_item)
            .where(prospect_send_item.c.target_id == target_ids[1])
            .values(instantly_id="accepted-lead")
        )
    worker = ProspectSendWorker(
        engine,
        provider=provider,
        provider_account_id="founder@example.invalid",
        kill_switch_path=tmp_path / "disabled",
        clock=lambda: NOW,
    )

    outcome = worker.run_once(worker_ref="recovery-test", now=NOW)

    assert outcome.status == "waiting"
    assert provider.get_lead_calls == []
    with engine.connect() as connection:
        item = (
            connection.execute(
                sa.select(prospect_send_item).where(prospect_send_item.c.target_id == target_ids[1])
            )
            .mappings()
            .one()
        )
    assert item["error_code"] == "lead_binding_conflict"


def test_recovery_preserves_evidence_and_replays_coherent_partial_progress(interrupted_request):
    engine, _tmp_path, _provider, target_ids = interrupted_request
    evidence = {"accounting": {"lead:1": {"confirmed": True}}, "audit": "preserved"}
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_request)
            .where(prospect_send_request.c.request_id == REQUEST_ID)
            .values(result=evidence)
        )
    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_item)
            .where(prospect_send_item.c.target_id == target_ids[1])
            .values(status="sent", completed_at=NOW)
        )
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == target_ids[1])
            .values(status="sent", instantly_accepted_at=NOW)
        )
        connection.execute(
            sa.update(prospect_send_request)
            .where(prospect_send_request.c.request_id == REQUEST_ID)
            .values(status="waiting", processed_count=2, sent_count=2, failed_count=0)
        )
    with engine.connect() as connection:
        before_request = dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
        before_items = connection.execute(sa.select(prospect_send_item)).mappings().all()

    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW + dt.timedelta(minutes=1))

    with engine.connect() as connection:
        assert (
            dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
            == before_request
        )
        assert connection.execute(sa.select(prospect_send_item)).mappings().all() == before_items
    assert before_request["result"] == {**evidence, "recovery": {"state": "reconstructed"}}


def test_recovery_replays_coherent_completed_queue_without_writes(interrupted_request):
    engine, _tmp_path, _provider, target_ids = interrupted_request
    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_item)
            .where(prospect_send_item.c.target_id.in_(target_ids[1:]))
            .values(status="sent", completed_at=NOW)
        )
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id.in_(target_ids[1:]))
            .values(status="sent", instantly_accepted_at=NOW)
        )
        connection.execute(
            sa.update(prospect_send_request)
            .where(prospect_send_request.c.request_id == REQUEST_ID)
            .values(status="completed", processed_count=21, sent_count=21, failed_count=0)
        )
    with engine.connect() as connection:
        before_request = dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
        before_items = connection.execute(sa.select(prospect_send_item)).mappings().all()

    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW + dt.timedelta(minutes=1))

    with engine.connect() as connection:
        assert (
            dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
            == before_request
        )
        assert connection.execute(sa.select(prospect_send_item)).mappings().all() == before_items


def test_recovery_accepts_legacy_sentinel_owned_by_the_same_request(interrupted_request):
    engine, _tmp_path, _provider, target_ids = interrupted_request
    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == target_ids[0])
            .values(send_request_id=REQUEST_ID)
        )
    with engine.connect() as connection:
        before_request = dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
        before_items = connection.execute(sa.select(prospect_send_item)).mappings().all()

    recover_request(engine, request_id=REQUEST_ID, dry_run=True)
    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW + dt.timedelta(minutes=1))

    with engine.connect() as connection:
        assert (
            dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
            == before_request
        )
        assert connection.execute(sa.select(prospect_send_item)).mappings().all() == before_items


def test_recovery_replays_terminal_waiting_activation_retry_without_writes(interrupted_request):
    engine, tmp_path, provider, _target_ids = interrupted_request
    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW)

    def activation_fails(_campaign_id):
        raise RuntimeError("activation unavailable")

    provider.activate_campaign = activation_fails
    worker = ProspectSendWorker(
        engine,
        provider=provider,
        provider_account_id="founder@example.invalid",
        kill_switch_path=tmp_path / "disabled",
        clock=lambda: NOW,
    )
    for minute in range(25):
        worker.run_once(worker_ref="recovery-test", now=NOW + dt.timedelta(minutes=minute))
    with engine.connect() as connection:
        before_request = dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
        before_items = connection.execute(sa.select(prospect_send_item)).mappings().all()
    assert (
        before_request["status"],
        before_request["processed_count"],
        before_request["sent_count"],
        before_request["failed_count"],
    ) == (
        "waiting",
        21,
        18,
        3,
    )
    assert before_request["next_attempt_at"] is not None
    assert before_request["error"] == "Instantly activation failed"

    recover_request(engine, request_id=REQUEST_ID, dry_run=True)
    recover_request(
        engine, request_id=REQUEST_ID, dry_run=False, now=NOW + dt.timedelta(minutes=26)
    )

    with engine.connect() as connection:
        assert (
            dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
            == before_request
        )
        assert connection.execute(sa.select(prospect_send_item)).mappings().all() == before_items


def test_recovery_replays_running_snapshot_after_last_terminal_item_crash(interrupted_request):
    engine, _tmp_path, _provider, target_ids = interrupted_request
    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW)
    with engine.begin() as connection:
        targets = {
            row["target_id"]: dict(row)
            for row in connection.execute(
                sa.select(prospect_target).where(prospect_target.c.target_id.in_(target_ids[1:]))
            ).mappings()
        }
        for target_id, target in targets.items():
            invalid = target["email_address"] in INVALID_EMAILS
            connection.execute(
                sa.update(prospect_send_item)
                .where(prospect_send_item.c.target_id == target_id)
                .values(
                    status="failed" if invalid else "sent",
                    error_code="instantly_email_invalid" if invalid else None,
                    completed_at=NOW,
                )
            )
            connection.execute(
                sa.update(prospect_target)
                .where(prospect_target.c.target_id == target_id)
                .values(
                    status="approved" if invalid else "sent",
                    send_request_id=None if invalid else REQUEST_ID,
                    instantly_accepted_at=None if invalid else NOW,
                    delivery_error="instantly email invalid" if invalid else None,
                )
            )
        connection.execute(
            sa.update(prospect_send_request)
            .where(prospect_send_request.c.request_id == REQUEST_ID)
            .values(status="running", processed_count=20, sent_count=17, failed_count=3)
        )
    with engine.connect() as connection:
        before_request = dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
        before_items = connection.execute(sa.select(prospect_send_item)).mappings().all()

    recover_request(engine, request_id=REQUEST_ID, dry_run=True)
    recover_request(engine, request_id=REQUEST_ID, dry_run=False, now=NOW + dt.timedelta(minutes=1))

    with engine.connect() as connection:
        assert (
            dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
            == before_request
        )
        assert connection.execute(sa.select(prospect_send_item)).mappings().all() == before_items
