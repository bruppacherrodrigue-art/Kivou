from __future__ import annotations

import datetime as dt
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from test_prospection_actions_send import Suppressions, approve
from test_prospection_actions_service import NOW, TARGET_ID, LinkIssuer, MxVerifier, seed

from signals.persistence.schema import prospect_send_item, prospect_send_request, prospect_target
from signals.prospection_actions.contracts import SendCommand, SendTarget
from signals.prospection_actions.service import ProspectionActions
from signals.prospection_actions.worker import ProspectSendWorker


class Provider:
    def __init__(self, verification_status: int) -> None:
        self.verification_status = verification_status
        self.create_campaign_calls: list[tuple[object, ...]] = []
        self.create_lead_calls: list[tuple[object, ...]] = []
        self.get_lead_calls: list[str] = []
        self.activate_calls: list[str] = []
        self.sleep_calls: list[object] = []

    def create_assisted_campaign(self, *, name, provider_account_id, execution_date):
        self.create_campaign_calls.append((name, provider_account_id, execution_date))
        return type("Campaign", (), {"provider_campaign_id": "campaign-1"})()

    def create_lead_or_batch(self, *, provider_campaign_id, leads, verify_leads_on_import=False):
        self.create_lead_calls.append((provider_campaign_id, leads, verify_leads_on_import))
        return {"id": "lead-1", "verification_status": self.verification_status}

    def get_lead(self, provider_lead_id):
        self.get_lead_calls.append(provider_lead_id)
        return {"id": provider_lead_id, "verification_status": self.verification_status}

    def activate_campaign(self, provider_campaign_id):
        self.activate_calls.append(provider_campaign_id)


def send_item(engine):
    with engine.connect() as connection:
        return dict(connection.execute(sa.select(prospect_send_item)).mappings().one())


def target_row(engine):
    with engine.connect() as connection:
        return dict(connection.execute(sa.select(prospect_target)).mappings().one())


def utc(value):
    return value if value is None or value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


@pytest.fixture
def worker_fixture(migrated_sqlite_engine, tmp_path):
    def build(*, verification_status: int, instantly_id=None, provider_campaign_id=None):
        seed(migrated_sqlite_engine)
        actions = ProspectionActions(
            migrated_sqlite_engine,
            email_verifier=MxVerifier(),
            link_issuer=LinkIssuer(),
            suppression_checker=Suppressions(),
            kill_switch_path=tmp_path / "acquisition.disabled",
            clock=lambda: NOW,
        )
        approve(actions)
        actions.enqueue_send(
            SendCommand(
                request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
                targets=(SendTarget(target_id=TARGET_ID, expected_version=2),),
            ),
            actor="rodrigue@kivou.eu",
        )
        with migrated_sqlite_engine.begin() as connection:
            if instantly_id:
                connection.execute(sa.update(prospect_send_item).values(instantly_id=instantly_id))
                connection.execute(sa.update(prospect_target).values(instantly_id=instantly_id))
            if provider_campaign_id:
                connection.execute(
                    sa.update(prospect_send_request).values(
                        provider_campaign_id=provider_campaign_id
                    )
                )
                connection.execute(
                    sa.update(prospect_target).values(provider_campaign_id=provider_campaign_id)
                )
        provider = Provider(verification_status)
        return (
            ProspectSendWorker(
                migrated_sqlite_engine,
                provider=provider,
                provider_account_id="rodrigue@kivou.eu",
                kill_switch_path=tmp_path / "acquisition.disabled",
            ),
            provider,
            migrated_sqlite_engine,
        )

    return build


def test_worker_reads_pending_verification_once_and_reschedules(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=12)

    outcome = worker.run_once(worker_ref="worker-a", now=NOW)

    assert outcome.status == "waiting"
    assert provider.get_lead_calls == ["lead-1"]
    assert provider.sleep_calls == []
    item = send_item(engine)
    assert item["status"] == "verification_pending"
    assert utc(item["next_attempt_at"]) == NOW + dt.timedelta(minutes=1)


def test_worker_reuses_existing_lead_without_import(worker_fixture):
    worker, provider, _engine = worker_fixture(
        instantly_id="existing-lead",
        provider_campaign_id="existing-campaign",
        verification_status=1,
    )

    worker.run_once(worker_ref="worker-a", now=NOW)

    assert provider.create_campaign_calls == []
    assert provider.create_lead_calls == []
    assert provider.get_lead_calls == ["existing-lead"]


def test_acceptance_does_not_claim_smtp_delivery(worker_fixture):
    worker, _provider, engine = worker_fixture(verification_status=1)

    worker.run_once(worker_ref="worker-a", now=NOW)

    target = target_row(engine)
    assert target["status"] == "sent"
    assert utc(target["instantly_accepted_at"]) == NOW
    assert target["delivery_status"] == "not_sent"
    assert target["sent_at"] is None


def test_campaign_activation_runs_once_after_the_last_terminal_item(worker_fixture):
    worker, provider, _engine = worker_fixture(verification_status=1)

    first = worker.run_once(worker_ref="worker-a", now=NOW)
    replay = worker.run_once(worker_ref="worker-b", now=NOW + dt.timedelta(minutes=1))

    assert first.status == "completed"
    assert replay.status == "idle"
    assert provider.activate_calls == ["campaign-1"]


def test_worker_rechecks_kill_switch_before_campaign_activation(worker_fixture):
    worker, provider, _engine = worker_fixture(verification_status=1)

    class DelayedKillSwitch:
        def __init__(self) -> None:
            self.calls = 0

        def exists(self) -> bool:
            self.calls += 1
            return self.calls >= 3

    worker._kill_switch_path = DelayedKillSwitch()

    outcome = worker.run_once(worker_ref="worker-a", now=NOW)

    assert outcome.status == "waiting"
    assert provider.activate_calls == []


@pytest.mark.parametrize(
    ("verification_status", "error_code"),
    [
        (-1, "instantly_email_invalid"),
        (-2, "instantly_email_risky"),
        (-3, "instantly_email_catch_all"),
        (-4, "instantly_email_job_change"),
    ],
)
def test_terminal_verification_failure_is_visible_and_releases_target(
    worker_fixture, verification_status, error_code
):
    worker, _provider, engine = worker_fixture(verification_status=verification_status)

    worker.run_once(worker_ref="worker-a", now=NOW)

    item = send_item(engine)
    target = target_row(engine)
    assert item["status"] == "failed"
    assert item["error_code"] == error_code
    assert target["status"] == "approved"
    assert target["send_request_id"] is None


def test_expired_lease_is_reclaimed(worker_fixture):
    worker, _provider, engine = worker_fixture(verification_status=12)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_request).values(
                status="running",
                lease_id="abandoned",
                lease_expires_at=NOW - dt.timedelta(seconds=1),
            )
        )

    worker.run_once(worker_ref="worker-b", now=NOW)

    with engine.connect() as connection:
        request = dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
    assert request["claimed_by"] == "worker-b"


@pytest.mark.skipif(
    not os.environ.get("POSTGRES_TEST_DATABASE_URL"),
    reason="requires disposable PostgreSQL database",
)
def test_postgresql_skip_locked_allows_a_single_claimant(tmp_path):
    from signals.persistence.database import create_database_engine, migrate_to_latest

    engine = create_database_engine(os.environ["POSTGRES_TEST_DATABASE_URL"])
    migrate_to_latest(engine)
    try:
        seed(engine)
        actions = ProspectionActions(
            engine,
            email_verifier=MxVerifier(),
            link_issuer=LinkIssuer(),
            suppression_checker=Suppressions(),
            clock=lambda: NOW,
        )
        approve(actions)
        actions.enqueue_send(
            SendCommand(
                request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
                targets=(SendTarget(target_id=TARGET_ID, expected_version=2),),
            ),
            actor="rodrigue@kivou.eu",
        )
        worker = ProspectSendWorker(
            engine, provider=Provider(12), provider_account_id="rodrigue@kivou.eu"
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(
                    lambda ref: worker.run_once(worker_ref=ref, now=NOW),
                    ("worker-a", "worker-b"),
                )
            )
        assert sum(outcome.status != "idle" for outcome in outcomes) == 1
    finally:
        engine.dispose()
