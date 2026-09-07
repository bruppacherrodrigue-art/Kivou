"""An operator-scoped ALERT cycle keeps the normal lease and recipient gate."""

import datetime as dt

import pytest
import sqlalchemy as sa
from alert_identity_helpers import verify_recipient
from engagement_helpers import (
    NOW,
    PUBLIC_APP_URL,
    Clock,
    FakeMailer,
    account_of,
    icp_of,
    make_app,
    make_engine,
    pay,
    seed,
    signed_up,
)

from signals.accounts.schema import account, account_landing_signal
from signals.alerts import job, lease
from signals.engagement.schema import signal_alert_delivery, signal_alert_job_lease


@pytest.fixture
def engine(tmp_path):
    return make_engine(tmp_path)


def seed_accounts(engine):
    with engine.begin() as connection:
        connection.execute(sa.insert(account), [
            {"account_id": identifier, "display_name": identifier, "locale": "fr",
                 "onboarding_status": "account_created", "created_at": NOW, "updated_at": NOW}
            for identifier in ("acc_excluded", "acc_selected")
        ])
        connection.execute(sa.insert(account_landing_signal).values(
            account_id="acc_selected", qa=True, created_at=NOW,
        ))


def lease_rows(engine):
    with engine.connect() as connection:
        return connection.execute(sa.select(signal_alert_job_lease)).all()


@pytest.mark.parametrize(("selected", "expected"), [
    ("acc_selected", ["acc_selected"]),
    ("acc_missing", []),
    ("", []),
    (None, ["acc_excluded", "acc_selected"]),
])
def test_account_filter_keeps_the_lease_and_never_processes_excluded_accounts(
    engine, monkeypatch, selected, expected,
):
    seed_accounts(engine)
    processed = []

    def worker(_engine, _gateway, *, account_id, **kwargs):
        processed.append(account_id)
        assert len(lease_rows(engine)) == 1
        with engine.begin() as connection:
            assert lease.acquire(
                connection, owner_id="competing-cycle", now=NOW,
                ttl=dt.timedelta(minutes=30),
            ) is lease.LeaseAcquisition.ALREADY_RUNNING
        return job.AlertOutcome(account_id, "weekly", "nothing_to_send")

    monkeypatch.setattr(job, "_run_for_account", worker)
    kwargs = {} if selected is None else {"account_id": selected}

    report = job.run_alert_cycle(
        engine, FakeMailer(), now=NOW, public_app_url=PUBLIC_APP_URL, **kwargs,
    )

    assert processed == expected
    assert report.accounts_considered == len(expected)
    assert [outcome.account_id for outcome in report.outcomes] == expected
    assert lease_rows(engine) == []


def test_scoped_cycle_respects_a_lease_already_held_by_the_global_cycle(engine, monkeypatch):
    seed_accounts(engine)
    with engine.begin() as connection:
        lease.acquire(connection, owner_id="global-cycle", now=NOW,
                      ttl=dt.timedelta(minutes=30))
    monkeypatch.setattr(job, "_run_for_account", lambda *args, **kwargs: pytest.fail(
        "a scoped cycle processed an account despite the existing global lease"
    ))

    report = job.run_alert_cycle(
        engine, FakeMailer(), account_id="acc_selected", now=NOW,
        public_app_url=PUBLIC_APP_URL,
    )

    assert report.already_running
    assert report.accounts_considered == 0
    assert lease_rows(engine)[0].owner_id == "global-cycle"


def test_scoped_cycle_releases_its_lease_after_a_worker_error(engine, monkeypatch):
    seed_accounts(engine)

    def failed_worker(*args, **kwargs):
        raise RuntimeError("synthetic worker failure")

    monkeypatch.setattr(job, "_run_for_account", failed_worker)
    with pytest.raises(RuntimeError, match="synthetic worker failure"):
        job.run_alert_cycle(engine, FakeMailer(), account_id="acc_selected", now=NOW,
                            public_app_url=PUBLIC_APP_URL)

    assert lease_rows(engine) == []


@pytest.mark.parametrize("verified", [False, True])
def test_scoped_qa_cycle_preserves_verified_proof_and_leaves_other_accounts_alone(engine, verified):
    app = make_app(engine, Clock())
    selected = signed_up(app)
    excluded = signed_up(app, "bob@materiaux-leman.ch")
    selected_id, excluded_id = account_of(selected), account_of(excluded)
    for client in (selected, excluded):
        pay(engine, client, plan="essential")
        seed(engine, icp_of(client))
    verify_recipient(engine, excluded)
    if verified:
        verify_recipient(engine, selected)
    with engine.begin() as connection:
        connection.execute(sa.insert(account_landing_signal).values(
            account_id=selected_id, qa=True, created_at=NOW,
        ))
    mailer = FakeMailer()

    report = job.run_alert_cycle(engine, mailer, account_id=selected_id, now=NOW,
                                 public_app_url=PUBLIC_APP_URL)

    assert report.accounts_considered == 1
    assert report.outcomes[0].account_id == selected_id
    assert report.outcomes[0].cadence == "weekly"
    assert mailer.attempts == int(verified)
    assert report.signals_sent == int(verified)
    if not verified:
        assert report.outcomes[0].result == "recipient_context_unverifiable"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(signal_alert_delivery)
                                 .where(signal_alert_delivery.c.account_id == excluded_id)) == 0
        assert connection.scalar(sa.select(account_landing_signal.c.qa)
                                 .where(account_landing_signal.c.account_id == selected_id)) is True
