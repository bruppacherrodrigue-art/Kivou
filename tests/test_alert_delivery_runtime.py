from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from engagement_helpers import (
    NOW,
    PUBLIC_APP_URL,
    Clock,
    FakeMailer,
    account_of,
    failure,
    icp_of,
    make_app,
    make_engine,
    pay,
    seed,
    signed_up,
)

from signals.alerts.delivery import logical_batch_key, mark_sent
from signals.alerts.gateway import UncertainDelivery
from signals.alerts.job import run_alert_cycle
from signals.alerts.lease import acquire, release
from signals.engagement.schema import signal_alert_delivery

RETRY_BASE = dt.timedelta(minutes=15)
DELIVERY_LEASE = dt.timedelta(minutes=30)


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    return make_engine(tmp_path)


@pytest.fixture
def app(engine):
    return make_app(engine, Clock())


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


def subscriber(app, engine, *, count: int = 1):
    client = signed_up(app)
    icp = icp_of(client)
    pay(engine, client, plan="scale")
    return client, seed(engine, icp, count=count)


def cycle(engine, mailer, *, now: dt.datetime):
    return run_alert_cycle(
        engine,
        mailer,
        now=now,
        public_app_url=PUBLIC_APP_URL,
        delivery_lease_ttl=DELIVERY_LEASE,
        retry_base=RETRY_BASE,
        max_attempts=5,
    )


def deliveries(engine) -> list[sa.Row]:
    with engine.connect() as connection:
        return connection.execute(sa.select(signal_alert_delivery)).all()


def aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.UTC)


def test_batch_identity_cannot_collide_on_delimited_signal_keys() -> None:
    assert logical_batch_key("acc", ["a:b", "c"]) != logical_batch_key(
        "acc", ["a", "b:c"]
    )


def test_retryable_failure_uses_backoff_and_the_same_message_id(app, engine, mailer) -> None:
    subscriber(app, engine)
    mailer.fail_with = failure("smtp_451", retryable=True)

    first = cycle(engine, mailer, now=NOW)
    row = deliveries(engine)[0]
    first_message_id = row.delivery_message_id

    assert first.has_current_incident
    assert row.status == "failed"
    assert row.retryable is True
    assert aware(row.next_attempt_at) == NOW + RETRY_BASE
    assert mailer.attempts == 1

    early = cycle(engine, mailer, now=NOW + dt.timedelta(minutes=14))
    assert early.signals_sent == 0
    assert mailer.attempts == 1

    cycle(engine, mailer, now=NOW + RETRY_BASE)
    assert mailer.last.message_id == first_message_id
    assert deliveries(engine)[0].status == "sent"
    assert mailer.attempts == 2


def test_permanent_failure_is_terminal(app, engine, mailer) -> None:
    subscriber(app, engine)
    mailer.fail_with = failure("smtp_550", retryable=False)

    cycle(engine, mailer, now=NOW)
    cycle(engine, mailer, now=NOW + dt.timedelta(days=1))

    row = deliveries(engine)[0]
    assert mailer.attempts == 1
    assert row.status == "failed"
    assert row.retryable is False
    assert row.next_attempt_at is None


def test_expired_sending_lease_is_reclaimed_with_same_message_id(app, engine, mailer) -> None:
    subscriber(app, engine)
    mailer.fail_with = failure("smtp_451", retryable=True)
    cycle(engine, mailer, now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(signal_alert_delivery).values(
                status="sending",
                lease_expires_at=NOW,
                next_attempt_at=None,
            )
        )
    expected = deliveries(engine)[0].delivery_message_id

    cycle(engine, mailer, now=NOW)

    row = deliveries(engine)[0]
    assert mailer.last.message_id == expected
    assert row.attempt_count == 2
    assert row.status == "sent"


def test_retry_budget_is_bounded(app, engine, mailer) -> None:
    subscriber(app, engine)
    instants = [
        NOW,
        NOW + dt.timedelta(minutes=15),
        NOW + dt.timedelta(minutes=45),
        NOW + dt.timedelta(minutes=105),
        NOW + dt.timedelta(minutes=225),
    ]
    for instant in instants:
        mailer.fail_with = failure("smtp_451", retryable=True)
        cycle(engine, mailer, now=instant)

    row = deliveries(engine)[0]
    assert mailer.attempts == 5
    assert row.attempt_count == 5
    assert row.retryable is False
    assert row.next_attempt_at is None


def test_uncertain_delivery_reuses_identity_with_a_bounded_retry(app, engine, mailer) -> None:
    subscriber(app, engine)
    mailer.fail_with = UncertainDelivery()
    first = cycle(engine, mailer, now=NOW)
    row = deliveries(engine)[0]
    identifier = row.delivery_message_id

    assert first.has_current_incident
    assert row.status == "unknown_delivery_state"
    assert row.retryable is True
    assert aware(row.next_attempt_at) == NOW + RETRY_BASE

    cycle(engine, mailer, now=NOW + RETRY_BASE)
    assert mailer.last.message_id == identifier
    assert deliveries(engine)[0].status == "sent"


def test_uncertain_delivery_stops_at_the_retry_budget(app, engine, mailer) -> None:
    subscriber(app, engine)
    instants = [
        NOW,
        NOW + dt.timedelta(minutes=15),
        NOW + dt.timedelta(minutes=45),
        NOW + dt.timedelta(minutes=105),
        NOW + dt.timedelta(minutes=225),
    ]
    for instant in instants:
        mailer.fail_with = UncertainDelivery()
        cycle(engine, mailer, now=instant)

    row = deliveries(engine)[0]
    assert mailer.attempts == 5
    assert row.status == "unknown_delivery_state"
    assert row.retryable is False
    assert row.next_attempt_at is None

    cycle(engine, mailer, now=NOW + dt.timedelta(days=2))
    assert mailer.attempts == 5


def test_retry_batch_does_not_absorb_a_new_signal(app, engine, mailer) -> None:
    client, original_keys = subscriber(app, engine)
    mailer.fail_with = failure("smtp_451", retryable=True)
    cycle(engine, mailer, now=NOW)
    icp = client.get("/target-icps").json()[0]["target_icp_id"]
    new_keys = seed(engine, icp, count=1, offset=1)

    cycle(engine, mailer, now=NOW + RETRY_BASE)

    assert original_keys[0] in mailer.last.text_body
    assert new_keys[0] not in mailer.last.text_body
    cycle(engine, mailer, now=NOW + RETRY_BASE)
    assert new_keys[0] in mailer.last.text_body


def test_historical_terminal_failure_does_not_poison_the_current_report(
    app, engine, mailer
) -> None:
    client, keys = subscriber(app, engine)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(signal_alert_delivery).values(
                account_id=account_of(client),
                signal_key=keys[0],
                status="failed",
                cadence="priority",
                queued_at=NOW,
                failed_at=NOW,
                attempt_count=1,
                retryable=False,
                last_error_code="historical_terminal",
                created_at=NOW,
                updated_at=NOW,
            )
        )

    report = cycle(engine, mailer, now=NOW + dt.timedelta(days=1))

    assert not report.has_current_incident
    assert mailer.attempts == 0


def test_post_accept_persistence_failure_documents_possible_duplicate(
    app, engine, mailer, monkeypatch
) -> None:
    subscriber(app, engine)

    def persistence_failure(*_args, **_kwargs):
        raise sa.exc.OperationalError("UPDATE", {}, RuntimeError("synthetic"))

    monkeypatch.setattr("signals.alerts.delivery.mark_sent", persistence_failure)
    report = cycle(engine, mailer, now=NOW)
    first_identifier = mailer.last.message_id

    assert report.has_current_incident
    assert [item.result for item in report.outcomes] == ["persistence_failed"]
    assert deliveries(engine)[0].status == "sending"

    monkeypatch.setattr("signals.alerts.delivery.mark_sent", mark_sent)
    cycle(engine, mailer, now=NOW + DELIVERY_LEASE)

    assert mailer.attempts == 2
    assert [message.message_id for message in mailer.sent] == [
        first_identifier,
        first_identifier,
    ]
    assert deliveries(engine)[0].status == "sent"


def test_normal_global_lease_contention_returns_already_running(app, engine, mailer) -> None:
    subscriber(app, engine)
    with engine.begin() as connection:
        acquire(connection, owner_id="other-job", now=NOW, ttl=dt.timedelta(hours=1))

    report = cycle(engine, mailer, now=NOW)

    assert report.already_running
    assert report.accounts_considered == 0
    assert report.outcomes == ()
    assert mailer.attempts == 0
    with engine.begin() as connection:
        release(connection, owner_id="other-job")
