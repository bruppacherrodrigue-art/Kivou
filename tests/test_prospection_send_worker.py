from __future__ import annotations

import datetime as dt
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
import sqlalchemy as sa
from test_prospection_actions_send import Suppressions, _seed_second_target, approve
from test_prospection_actions_service import NOW, TARGET_ID, LinkIssuer, MxVerifier, seed

from signals.campaigns.instantly import HttpInstantlyProvider
from signals.persistence.schema import prospect_send_item, prospect_send_request, prospect_target
from signals.prospection_actions.contracts import SendCommand, SendTarget
from signals.prospection_actions.delivery import AssistedInstantlyDelivery
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
        self.active = False
        self.campaigns: list[object] = []
        self.leads: list[dict[str, object]] = []

    def create_assisted_campaign(self, *, name, provider_account_id, execution_date):
        self.create_campaign_calls.append((name, provider_account_id, execution_date))
        campaign = type("Campaign", (), {"provider_campaign_id": "campaign-1", "name": name})()
        self.campaigns.append(campaign)
        return campaign

    def create_lead_or_batch(self, *, provider_campaign_id, leads, verify_leads_on_import=False):
        self.create_lead_calls.append((provider_campaign_id, leads, verify_leads_on_import))
        lead = {
            "id": "lead-1",
            "verification_status": self.verification_status,
            "email": leads[0]["email"],
            "campaign_id": provider_campaign_id,
        }
        self.leads.append(lead)
        return lead

    def get_lead(self, provider_lead_id):
        self.get_lead_calls.append(provider_lead_id)
        return {"id": provider_lead_id, "verification_status": self.verification_status}

    def activate_campaign(self, provider_campaign_id):
        self.activate_calls.append(provider_campaign_id)
        self.active = True

    def get_campaign(self, provider_campaign_id):
        return type("Campaign", (), {"status": "active" if self.active else "paused"})()

    def list_campaigns(self, *, search):
        return tuple(item for item in self.campaigns if item.name == search)

    def list_leads(self, *, provider_campaign_id):
        return {"items": self.leads, "next_starting_after": None}


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
                clock=lambda: NOW,
            ),
            provider,
            migrated_sqlite_engine,
        )

    return build


def test_worker_fails_closed_before_provider_when_opportunity_key_disappears(
    worker_fixture,
) -> None:
    worker, provider, engine = worker_fixture(verification_status=1)
    with engine.begin() as connection:
        connection.execute(sa.update(prospect_target).values(opportunity_key=""))

    outcome = worker.run_once(worker_ref="worker-a", now=NOW)

    assert outcome.status == "failed"
    assert provider.create_campaign_calls == []
    assert provider.create_lead_calls == []
    assert send_item(engine)["error_code"] == "missing_opportunity_key"


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


@pytest.mark.parametrize(
    ("verification_status", "final_status", "item_status", "activations"),
    [(1, "completed", "sent", ["campaign-1"]), (-1, "failed", "failed", [])],
)
def test_multi_item_request_reaches_both_terminal_items_then_activates_once(
    worker_fixture, verification_status, final_status, item_status, activations
):
    worker, provider, engine = worker_fixture(verification_status=verification_status)
    second_target_id = _seed_second_target(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_request).values(
                reserved_count=2,
                target_ids=[TARGET_ID, second_target_id],
            )
        )
        connection.execute(
            sa.insert(prospect_send_item).values(
                request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
                target_id=second_target_id,
                position=1,
                expected_version=2,
                status="queued",
                next_attempt_at=NOW,
                attempt_count=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    first = worker.run_once(worker_ref="worker-a", now=NOW)
    second = worker.run_once(worker_ref="worker-b", now=NOW)

    with engine.connect() as connection:
        statuses = (
            connection.execute(
                sa.select(prospect_send_item.c.status).order_by(prospect_send_item.c.position)
            )
            .scalars()
            .all()
        )
    assert first.status == "waiting"
    assert second.status == final_status
    assert statuses == [item_status, item_status]
    assert provider.activate_calls == activations


def test_acceptance_does_not_claim_smtp_delivery(worker_fixture):
    worker, _provider, engine = worker_fixture(verification_status=1)

    worker.run_once(worker_ref="worker-a", now=NOW)

    target = target_row(engine)
    assert target["status"] == "sent"
    assert utc(target["instantly_accepted_at"]) == NOW
    assert target["delivery_status"] == "not_sent"
    assert target["sent_at"] is None


def test_acceptance_clears_a_transient_verification_error(worker_fixture):
    worker, _provider, engine = worker_fixture(verification_status=1)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target).values(
                delivery_error="instantly_email_verification_pending"
            )
        )

    worker.run_once(worker_ref="worker-a", now=NOW)

    target = target_row(engine)
    assert target["status"] == "sent"
    assert target["delivery_error"] is None


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


def test_activation_failure_keeps_accepted_item_terminal_and_respects_due_time(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=1)

    def fail_activation(_campaign_id):
        raise RuntimeError("temporary outage")

    provider.activate_campaign = fail_activation
    outcome = worker.run_once(worker_ref="worker-a", now=NOW)

    item = send_item(engine)
    with engine.connect() as connection:
        request = dict(connection.execute(sa.select(prospect_send_request)).mappings().one())
    assert outcome.status == "waiting"
    assert item["status"] == "sent"
    assert request["sent_count"] == request["processed_count"] == 1
    assert utc(request["next_attempt_at"]) == NOW + dt.timedelta(minutes=1)
    assert request["error"] == "Instantly activation failed"
    assert worker.run_once(worker_ref="worker-b", now=NOW) == type(outcome)("idle")


def test_stale_worker_does_not_activate_campaign(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=1)
    original = provider.get_lead

    def reclaim_during_verification(lead_id):
        with engine.begin() as connection:
            connection.execute(sa.update(prospect_send_request).values(lease_id="replacement"))
        return original(lead_id)

    provider.get_lead = reclaim_during_verification

    outcome = worker.run_once(worker_ref="worker-a", now=NOW)

    assert outcome.status == "lost"
    assert provider.activate_calls == []


def test_activation_reconciliation_avoids_a_second_mutation_after_ambiguous_crash(worker_fixture):
    worker, provider, _engine = worker_fixture(verification_status=1)
    original = provider.activate_campaign

    def activate_then_crash(campaign_id):
        original(campaign_id)
        raise RuntimeError("connection dropped after activation")

    provider.activate_campaign = activate_then_crash
    first = worker.run_once(worker_ref="worker-a", now=NOW)
    second = worker.run_once(worker_ref="worker-b", now=NOW + dt.timedelta(minutes=1))

    assert first.status == "waiting"
    assert second.status == "completed"
    assert provider.activate_calls == ["campaign-1"]


def test_completed_campaign_recovery_with_actual_adapter_does_not_activate_twice(worker_fixture):
    worker, _provider, engine = worker_fixture(
        verification_status=1, provider_campaign_id="campaign-1", instantly_id="lead-1"
    )
    remote_status = 2
    observed = []
    crashed = False

    class ProcessCrash(BaseException):
        pass

    def handler(request):
        nonlocal remote_status
        observed.append((request.method, request.url.path))
        if request.url.path == "/api/v2/leads/lead-1":
            return httpx.Response(200, json={"id": "lead-1", "verification_status": 1})
        if request.url.path.endswith("/activate"):
            remote_status = 3
        return httpx.Response(
            200, json={"id": "campaign-1", "name": "Kivou assisted test", "status": remote_status}
        )

    @sa.event.listens_for(engine, "commit")
    def crash_after_remote_activation(_connection):
        nonlocal crashed
        if remote_status == 3 and not crashed:
            crashed = True
            raise ProcessCrash()

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        worker._delivery = AssistedInstantlyDelivery(
            provider=HttpInstantlyProvider(api_key="synthetic-test-key", client=client),
            provider_account_id="sender@example.invalid",
        )
        with pytest.raises(ProcessCrash):
            worker.run_once(worker_ref="worker-a", now=NOW)
        assert (
            worker.run_once(worker_ref="worker-b", now=NOW + dt.timedelta(minutes=6)).status
            == "completed"
        )

    assert observed == [
        ("GET", "/api/v2/leads/lead-1"),
        ("GET", "/api/v2/campaigns/campaign-1"),
        ("GET", "/api/v2/campaigns/campaign-1"),
        ("POST", "/api/v2/campaigns/campaign-1/activate"),
        ("GET", "/api/v2/campaigns/campaign-1"),
    ]


@pytest.mark.parametrize("after_claim", [False, True])
def test_queued_item_with_already_sent_target_skips_every_provider_call(
    worker_fixture, after_claim
):
    worker, provider, engine = worker_fixture(verification_status=-1)
    claim = worker._claim(worker_ref="worker-a", now=NOW) if after_claim else None
    accepted_at = NOW - dt.timedelta(days=1)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target).values(
                status="sent",
                instantly_id="previous-lead",
                provider_campaign_id="previous-campaign",
                instantly_accepted_at=accepted_at,
            )
        )
    before = target_row(engine)
    observed = []

    def track(name, original):
        def call(*args, **kwargs):
            observed.append(name)
            return original(*args, **kwargs)

        return call

    for name in (
        "get_campaign",
        "list_campaigns",
        "create_assisted_campaign",
        "list_leads",
        "create_lead_or_batch",
        "get_lead",
        "activate_campaign",
    ):
        setattr(provider, name, track(name, getattr(provider, name)))

    outcome = (
        worker._process(claim) if after_claim else worker.run_once(worker_ref="worker-a", now=NOW)
    )

    assert observed == []
    assert outcome.status == "completed"
    assert target_row(engine) == before
    item = send_item(engine)
    assert item["status"] == "sent"
    assert item["instantly_id"] == "previous-lead"
    assert utc(item["completed_at"]) == accepted_at
    with engine.connect() as connection:
        request = connection.execute(sa.select(prospect_send_request)).mappings().one()
    assert request["sent_count"] == request["processed_count"] == 1
    assert request["failed_count"] == 0
    assert request["lease_id"] is None


def test_already_sent_shortcut_cannot_use_a_replaced_lease(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=-1)
    claim = worker._claim(worker_ref="worker-a", now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target).values(status="sent", instantly_id="prior-lead")
        )
        connection.execute(sa.update(prospect_send_request).values(lease_id="new-owner"))

    assert worker._process(claim).status == "lost"
    assert send_item(engine)["status"] == "running"
    assert target_row(engine)["status"] == "sent"
    assert (
        provider.create_campaign_calls
        == provider.create_lead_calls
        == provider.get_lead_calls
        == []
    )


def test_last_already_sent_item_leaves_activation_for_a_dedicated_retry(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=1)
    second_target_id = _seed_second_target(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_request).values(
                reserved_count=2,
                target_ids=[TARGET_ID, second_target_id],
            )
        )
        connection.execute(
            sa.insert(prospect_send_item).values(
                request_id="484be03d-fbe4-46b1-9900-b99b4068fcbd",
                target_id=second_target_id,
                position=1,
                expected_version=2,
                status="queued",
                next_attempt_at=NOW,
                attempt_count=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            sa.update(prospect_target)
            .where(
                prospect_target.c.target_id == second_target_id,
            )
            .values(status="sent", instantly_id="prior-lead", instantly_accepted_at=NOW)
        )
    reconcile_calls = []
    original = provider.get_campaign

    def reconcile(campaign_id):
        reconcile_calls.append(campaign_id)
        return original(campaign_id)

    provider.get_campaign = reconcile
    assert worker.run_once(worker_ref="worker-a", now=NOW).status == "waiting"
    assert worker.run_once(worker_ref="worker-b", now=NOW).status == "waiting"
    assert len(provider.create_campaign_calls) == len(provider.create_lead_calls) == 1
    assert provider.get_lead_calls == ["lead-1"]
    assert provider.activate_calls == reconcile_calls == []
    with engine.connect() as connection:
        request = connection.execute(sa.select(prospect_send_request)).mappings().one()
    assert request["processed_count"] == request["sent_count"] == 2
    assert request["failed_count"] == 0
    assert utc(request["next_attempt_at"]) == NOW
    assert request["lease_id"] is None

    assert worker.run_once(worker_ref="worker-c", now=NOW).status == "completed"
    assert provider.activate_calls == ["campaign-1"]
    assert reconcile_calls == ["campaign-1", "campaign-1"]


def test_target_sent_during_verification_is_never_downgraded(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=-1)
    original = provider.get_lead

    def sent_during_verification(lead_id):
        with engine.begin() as connection:
            connection.execute(
                sa.update(prospect_target).values(
                    status="sent",
                    instantly_accepted_at=NOW - dt.timedelta(minutes=1),
                )
            )
        return original(lead_id)

    provider.get_lead = sent_during_verification
    outcome = worker.run_once(worker_ref="worker-a", now=NOW)

    assert outcome.status == "waiting"
    assert target_row(engine)["status"] == "sent"
    assert send_item(engine)["status"] == "sent"
    assert provider.activate_calls == []


def test_campaign_creation_interruption_reconciles_before_retrying_mutation(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=12)
    original = worker._persist_campaign
    calls = 0

    def crash_after_remote_create(claim, campaign_id, *, now, connection):
        nonlocal calls
        calls += 1
        return False if calls == 1 else original(claim, campaign_id, now=now, connection=connection)

    worker._persist_campaign = crash_after_remote_create
    assert worker.run_once(worker_ref="worker-a", now=NOW).status == "lost"
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_request).values(lease_expires_at=NOW - dt.timedelta(seconds=1))
        )

    recovered = worker.run_once(worker_ref="worker-b", now=NOW)

    assert recovered.status == "waiting"
    assert len(provider.create_campaign_calls) == 1
    assert len(provider.create_lead_calls) == 1


def test_lead_import_interruption_reconciles_before_retrying_mutation(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=12)
    original = worker._persist_lead
    calls = 0

    def crash_after_remote_import(claim, campaign_id, instantly_id, *, now, connection):
        nonlocal calls
        calls += 1
        return (
            False
            if calls == 1
            else original(claim, campaign_id, instantly_id, now=now, connection=connection)
        )

    worker._persist_lead = crash_after_remote_import
    assert worker.run_once(worker_ref="worker-a", now=NOW).status == "lost"
    with engine.begin() as connection:
        connection.execute(
            sa.update(prospect_send_request).values(lease_expires_at=NOW - dt.timedelta(seconds=1))
        )

    recovered = worker.run_once(worker_ref="worker-b", now=NOW)

    assert recovered.status == "waiting"
    assert len(provider.create_campaign_calls) == 1
    assert len(provider.create_lead_calls) == 1


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


@pytest.mark.parametrize(
    ("mutation", "calls"),
    [
        ("create_assisted_campaign", "create_campaign_calls"),
        ("create_lead_or_batch", "create_lead_calls"),
        ("activate_campaign", "activate_calls"),
        ("list_campaigns", "create_campaign_calls"),
        ("list_leads", "create_lead_calls"),
        ("get_campaign", "activate_calls"),
    ],
)
def test_inflight_mutation_blocks_reclaim_after_lease_expiry(worker_fixture, mutation, calls):
    worker, provider, engine = worker_fixture(verification_status=1)
    entered, release, reclaim_entered, reclaim_finished = (Event() for _ in range(4))
    current = [NOW]
    worker._clock = lambda: current[0]
    original = getattr(provider, mutation)

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5), "test did not release provider call"
        return original(*args, **kwargs)

    setattr(provider, mutation, paused)
    # A second engine guarantees independent pooled DBAPI connections.
    contender_engine = sa.create_engine(engine.url)
    contender = ProspectSendWorker(
        contender_engine, provider=provider, provider_account_id="rodrigue@kivou.eu"
    )

    @sa.event.listens_for(contender_engine, "before_cursor_execute")
    def before_reclaim(_connection, _cursor, statement, _parameters, _context, _many):
        if "prospect_send" in statement or statement == "BEGIN IMMEDIATE":
            reclaim_entered.set()

    def reclaim():
        try:
            return contender._claim(worker_ref="worker-b", now=current[0])
        finally:
            reclaim_finished.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(worker.run_once, worker_ref="worker-a", now=NOW)
            try:
                assert entered.wait(5)
                current[0] = NOW + dt.timedelta(minutes=16)
                second = pool.submit(reclaim)
                assert reclaim_entered.wait(5)
                assert not reclaim_finished.wait(0.1), "in-flight request was reclaimable"
            finally:
                release.set()
            assert first.result(timeout=5).status == "completed"
            assert second.result(timeout=5) is None
        assert len(getattr(provider, calls)) == 1
    finally:
        contender_engine.dispose()


def test_elapsed_provider_calls_renew_using_fresh_time(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=1)
    current = [NOW]
    worker._clock = lambda: current[0]

    def advance(original):
        def call(*args, **kwargs):
            result = original(*args, **kwargs)
            current[0] += dt.timedelta(minutes=4)
            return result

        return call

    for name in ("create_assisted_campaign", "create_lead_or_batch", "get_lead", "get_campaign"):
        setattr(provider, name, advance(getattr(provider, name)))
    original = provider.activate_campaign

    def activate(campaign_id):
        with engine.connect() as connection:
            expiry = connection.scalar(sa.select(prospect_send_request.c.lease_expires_at))
        assert utc(expiry) > current[0]
        original(campaign_id)

    provider.activate_campaign = activate
    assert worker.run_once(worker_ref="worker-a", now=NOW).status == "completed"
    # Declaring activation durably requires reopening the guard and re-reading status.
    assert current[0] == NOW + dt.timedelta(minutes=20)
    assert provider.activate_calls == ["campaign-1"]
    assert utc(target_row(engine)["instantly_accepted_at"]) == NOW + dt.timedelta(minutes=12)


def test_sqlite_busy_claim_skips_without_mutation(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=1)
    contender_engine = sa.create_engine(engine.url, connect_args={"timeout": 0.01})
    contender = ProspectSendWorker(
        contender_engine, provider=provider, provider_account_id="rodrigue@kivou.eu"
    )
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            assert contender.run_once(worker_ref="worker-b", now=NOW).status == "idle"
        assert worker.run_once(worker_ref="worker-a", now=NOW).status == "completed"
        assert len(provider.create_campaign_calls) == len(provider.create_lead_calls) == 1
        assert provider.activate_calls == ["campaign-1"]
    finally:
        contender_engine.dispose()


@pytest.mark.parametrize("kind", ["campaign", "lead"])
def test_multiple_remote_matches_are_visible_and_due_without_mutation(worker_fixture, kind):
    worker, provider, engine = worker_fixture(
        verification_status=1,
        provider_campaign_id="campaign-1" if kind == "lead" else None,
    )
    if kind == "campaign":
        provider.list_campaigns = lambda *, search: tuple(
            type("Campaign", (), {"name": search, "provider_campaign_id": f"campaign-{i}"})()
            for i in range(2)
        )
    else:
        email = target_row(engine)["email_address"]
        provider.leads = [
            {"id": f"lead-{i}", "email": email, "campaign_id": "campaign-1"} for i in range(2)
        ]

    assert worker.run_once(worker_ref="worker-a", now=NOW).status == "waiting"
    assert provider.create_campaign_calls == provider.create_lead_calls == []
    item = send_item(engine)
    assert item["error_message"] == f"reconciliation_required: multiple {kind}s"
    assert utc(item["next_attempt_at"]) == NOW + dt.timedelta(minutes=1)
    with engine.connect() as connection:
        request = connection.execute(sa.select(prospect_send_request)).mappings().one()
    assert request["error"] == item["error_message"]
    assert request["lease_id"] is None


@pytest.mark.parametrize("mutation", ["campaign", "lead", "activation"])
@pytest.mark.parametrize("crash_at", ["persistence", "commit"])
def test_crash_before_mutation_commit_reconciles_without_duplicate(
    worker_fixture, mutation, crash_at
):
    worker, provider, engine = worker_fixture(verification_status=1)
    crashed = False

    class ProcessCrash(BaseException):
        pass

    @sa.event.listens_for(engine, "before_cursor_execute")
    def crash_before_persistence(_connection, _cursor, statement, parameters, _context, _many):
        nonlocal crashed
        if (
            crash_at != "persistence"
            or crashed
            or not statement.startswith("UPDATE prospect_send_")
        ):
            return
        if mutation == "campaign":
            matched = bool(provider.create_campaign_calls) and "provider_campaign_id=" in statement
        elif mutation == "lead":
            matched = bool(provider.create_lead_calls) and "instantly_id=" in statement
        else:
            matched = bool(provider.activate_calls) and '"active"' in str(parameters)
        if matched:
            crashed = True
            raise ProcessCrash()

    @sa.event.listens_for(engine, "commit")
    def crash_before_commit(_connection):
        nonlocal crashed
        calls = {
            "campaign": provider.create_campaign_calls,
            "lead": provider.create_lead_calls,
            "activation": provider.activate_calls,
        }
        if crash_at == "commit" and not crashed and calls[mutation]:
            crashed = True
            raise ProcessCrash()

    with pytest.raises(ProcessCrash):
        worker.run_once(worker_ref="worker-a", now=NOW)
    with engine.connect() as connection:
        request = connection.execute(sa.select(prospect_send_request)).mappings().one()
    if mutation == "campaign":
        assert request["provider_campaign_id"] is None
    elif mutation == "lead":
        assert send_item(engine)["instantly_id"] is None
    else:
        assert not (request["result"] or {}).get("activation")
    assert (
        worker.run_once(worker_ref="worker-b", now=NOW + dt.timedelta(minutes=16)).status
        == "completed"
    )
    assert len(provider.create_campaign_calls) == len(provider.create_lead_calls) == 1
    assert provider.activate_calls == ["campaign-1"]


@pytest.mark.parametrize(
    "method", ["create_assisted_campaign", "create_lead_or_batch", "get_lead", "activate_campaign"]
)
def test_provider_errors_are_masked_and_retry_after_current_time(worker_fixture, method):
    worker, provider, engine = worker_fixture(verification_status=1)
    current = [NOW]
    worker._clock = lambda: current[0]

    def fail(*_args, **_kwargs):
        current[0] += dt.timedelta(minutes=20)
        raise RuntimeError("Bearer secret-token private@email.example " + "raw" * 1000)

    setattr(provider, method, fail)
    assert worker.run_once(worker_ref="worker-a", now=NOW).status == "waiting"
    with engine.connect() as connection:
        request = connection.execute(sa.select(prospect_send_request)).mappings().one()
    expected = (
        "Instantly activation failed"
        if method == "activate_campaign"
        else "Instantly provider request failed"
    )
    assert request["error"] == expected
    assert utc(request["next_attempt_at"]) == current[0] + dt.timedelta(minutes=1)
    assert "secret-token" not in str(send_item(engine))
    assert request["lease_id"] is None


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
