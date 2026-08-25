from __future__ import annotations

import datetime as dt
import io
import json
import logging
import pathlib

import pytest
import sqlalchemy as sa
from engagement_helpers import (
    NOW,
    PUBLIC_APP_URL,
    Clock,
    FakeMailer,
    account_of,
    events,
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
from signals.alerts.policy import MAXIMUM_SIGNALS_PER_EMAIL
from signals.engagement.schema import signal_alert_delivery
from signals.persistence.schema import materialized_signal
from signals.runtime_events import configure_runtime_event_logging

RETRY_BASE = dt.timedelta(minutes=15)
DELIVERY_LEASE = dt.timedelta(minutes=30)


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    return make_engine(tmp_path)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def app(engine, clock):
    return make_app(engine, clock)


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


def subscriber(app, engine, *, count: int = 1, plan: str = "scale"):
    client = signed_up(app)
    icp = icp_of(client)
    pay(engine, client, plan=plan)
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


def test_expired_sending_lease_cannot_exceed_the_retry_budget(
    app, engine, mailer
) -> None:
    subscriber(app, engine)
    mailer.fail_with = failure("smtp_451", retryable=True)
    cycle(engine, mailer, now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(signal_alert_delivery).values(
                status="sending",
                attempt_count=5,
                lease_expires_at=NOW,
                next_attempt_at=None,
            )
        )

    report = cycle(engine, mailer, now=NOW)

    row = deliveries(engine)[0]
    assert mailer.attempts == 1
    assert row.attempt_count == 5
    assert row.status == "unknown_delivery_state"
    assert row.retryable is False
    assert row.next_attempt_at is None
    assert report.has_current_incident


def test_lowered_retry_budget_terminalizes_an_existing_due_failure(
    app, engine, mailer
) -> None:
    subscriber(app, engine)
    mailer.fail_with = failure("smtp_451", retryable=True)
    cycle(engine, mailer, now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(signal_alert_delivery).values(
                attempt_count=3,
                next_attempt_at=NOW,
            )
        )

    first = run_alert_cycle(
        engine,
        mailer,
        now=NOW,
        public_app_url=PUBLIC_APP_URL,
        delivery_lease_ttl=DELIVERY_LEASE,
        retry_base=RETRY_BASE,
        max_attempts=3,
    )
    second = run_alert_cycle(
        engine,
        mailer,
        now=NOW + dt.timedelta(days=1),
        public_app_url=PUBLIC_APP_URL,
        delivery_lease_ttl=DELIVERY_LEASE,
        retry_base=RETRY_BASE,
        max_attempts=3,
    )

    row = deliveries(engine)[0]
    assert mailer.attempts == 1
    assert row.status == "failed"
    assert row.attempt_count == 3
    assert row.retryable is False
    assert row.next_attempt_at is None
    assert first.has_current_incident
    assert not second.has_current_incident


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


def test_retry_is_suppressed_when_notifications_are_disabled(app, engine, mailer) -> None:
    client, _ = subscriber(app, engine)
    mailer.fail_with = failure("smtp_451", retryable=True)
    cycle(engine, mailer, now=NOW)
    attempts = deliveries(engine)[0].attempt_count
    client.patch("/notification-preferences", json={"email_enabled": False})

    report = cycle(engine, mailer, now=NOW + RETRY_BASE)

    row = deliveries(engine)[0]
    assert row.status == "suppressed"
    assert row.suppression_reason_code == "notifications_disabled"
    assert row.attempt_count == attempts
    assert row.retryable is False
    assert row.next_attempt_at is None
    assert row.lease_expires_at is None
    assert row.failed_at is not None
    assert row.last_error_code == "smtp_451"
    assert not report.has_current_incident
    assert mailer.attempts == 1
    assert len(events(engine, event_type="alert_failed")) == 1
    assert len(events(engine, event_type="alert_suppressed")) == 1


def test_retry_is_suppressed_when_entitlement_is_lost(app, engine, mailer) -> None:
    client, _ = subscriber(app, engine)
    mailer.fail_with = failure("smtp_451", retryable=True)
    cycle(engine, mailer, now=NOW)
    attempts = deliveries(engine)[0].attempt_count
    pay(engine, client, plan="scale", status="canceled")

    report = cycle(engine, mailer, now=NOW + RETRY_BASE)

    row = deliveries(engine)[0]
    assert row.status == "suppressed"
    assert row.suppression_reason_code == "entitlement_lost"
    assert row.attempt_count == attempts
    assert not report.has_current_incident
    assert mailer.attempts == 1


def test_inaccessible_signal_is_suppressed_while_the_rest_of_the_batch_sends(
    app, engine, mailer
) -> None:
    _, keys = subscriber(app, engine, count=2)
    mailer.fail_with = failure("smtp_451", retryable=True)
    cycle(engine, mailer, now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == keys[0])
            .values(invalidated_at=NOW, invalidation_reason="synthetic_test")
        )

    report = cycle(engine, mailer, now=NOW + RETRY_BASE)

    rows = {row.signal_key: row for row in deliveries(engine)}
    assert rows[keys[0]].status == "suppressed"
    assert rows[keys[0]].suppression_reason_code == "signal_inaccessible"
    assert rows[keys[0]].attempt_count == 1
    assert rows[keys[1]].status == "sent"
    assert rows[keys[1]].attempt_count == 2
    assert keys[0] not in mailer.last.text_body
    assert keys[1] in mailer.last.text_body
    assert report.signals_sent == 1
    assert not report.has_current_incident
    suppressed = events(engine, event_type="alert_suppressed")
    assert len(suppressed) == 1
    assert suppressed[0].properties == {
        "cadence": "priority",
        "reason_code": "signal_inaccessible",
        "signal_count": 1,
    }


def test_permanent_recipient_refusal_blocks_new_rows_and_is_controlled(
    app, engine, mailer
) -> None:
    _, keys = subscriber(app, engine, count=12)
    mailer.fail_with = failure("smtp_recipient_refused", retryable=False)

    first = cycle(engine, mailer, now=NOW)
    second = cycle(engine, mailer, now=NOW + dt.timedelta(hours=1))
    third = cycle(engine, mailer, now=NOW + dt.timedelta(days=1))

    rows = deliveries(engine)
    assert len(keys) > 5
    assert mailer.attempts == 1
    assert len(rows) == MAXIMUM_SIGNALS_PER_EMAIL
    assert {row.status for row in rows} == {"failed"}
    assert {row.last_error_code for row in rows} == {"smtp_recipient_refused"}
    assert len({row.recipient_context_fingerprint for row in rows}) == 1
    assert rows[0].recipient_context_fingerprint is not None
    assert [item.result for item in first.outcomes] == ["failed"]
    assert not first.has_current_incident
    assert [item.result for item in second.outcomes] == ["recipient_refused"]
    assert [item.result for item in third.outcomes] == ["recipient_refused"]
    assert not second.has_current_incident
    assert not third.has_current_incident


def test_generic_terminal_smtp_failure_does_not_install_a_recipient_block(
    app, engine, mailer
) -> None:
    subscriber(app, engine, count=12)
    mailer.fail_with = failure("smtp_550", retryable=False)

    first = cycle(engine, mailer, now=NOW)
    second = cycle(engine, mailer, now=NOW + dt.timedelta(hours=1))

    assert first.has_current_incident
    assert [item.detail for item in first.outcomes] == ["smtp_550"]
    assert not second.has_current_incident
    assert second.signals_sent == 2
    assert mailer.attempts == 2
    assert len(deliveries(engine)) == 12


def test_semantic_preference_noop_preserves_timestamp_and_recipient_block(
    app, engine, mailer, clock
) -> None:
    client, _ = subscriber(app, engine, count=12)
    mailer.fail_with = failure("smtp_recipient_refused", retryable=False)
    cycle(engine, mailer, now=NOW)
    before = client.get("/notification-preferences").json()
    stored_fingerprint = deliveries(engine)[0].recipient_context_fingerprint

    clock.advance(dt.timedelta(hours=1))
    response = client.patch(
        "/notification-preferences",
        json={
            "email_enabled": before["email_enabled"],
            "notification_email": before["notification_email"].upper(),
        },
    )
    assert response.status_code == 200
    assert response.json()["updated_at"] == before["updated_at"]

    report = cycle(engine, mailer, now=NOW + dt.timedelta(hours=1))

    assert [item.result for item in report.outcomes] == ["recipient_refused"]
    assert mailer.attempts == 1
    assert len(deliveries(engine)) == MAXIMUM_SIGNALS_PER_EMAIL
    assert {row.recipient_context_fingerprint for row in deliveries(engine)} == {
        stored_fingerprint
    }


def test_changed_notification_address_rearms_only_future_signals(
    app, engine, mailer, clock
) -> None:
    client, _ = subscriber(app, engine, count=11)
    mailer.fail_with = failure("smtp_recipient_refused", retryable=False)
    cycle(engine, mailer, now=NOW)
    refused_fingerprint = deliveries(engine)[0].recipient_context_fingerprint

    clock.advance(dt.timedelta(minutes=1))
    response = client.patch(
        "/notification-preferences",
        json={"notification_email": "new-alerts@negoce-romand.ch"},
    )
    assert response.status_code == 200

    report = cycle(engine, mailer, now=NOW + dt.timedelta(hours=1))

    assert report.signals_sent == 1
    assert mailer.attempts == 2
    assert mailer.last.to_email == "new-alerts@negoce-romand.ch"
    rows = deliveries(engine)
    assert len(rows) == 11
    sent = next(row for row in rows if row.status == "sent")
    assert sent.recipient_context_fingerprint != refused_fingerprint
    assert {row.status for row in rows if row.signal_key != sent.signal_key} == {
        "failed"
    }


def test_changed_preference_version_rearms_future_signals(
    app, engine, mailer, clock
) -> None:
    client, _ = subscriber(app, engine, count=11)
    mailer.fail_with = failure("smtp_recipient_refused", retryable=False)
    cycle(engine, mailer, now=NOW)
    refused_fingerprint = deliveries(engine)[0].recipient_context_fingerprint

    clock.advance(dt.timedelta(minutes=1))
    assert (
        client.patch(
            "/notification-preferences", json={"email_enabled": False}
        ).status_code
        == 200
    )
    clock.advance(dt.timedelta(minutes=1))
    assert (
        client.patch(
            "/notification-preferences", json={"email_enabled": True}
        ).status_code
        == 200
    )

    report = cycle(engine, mailer, now=NOW + dt.timedelta(hours=1))

    assert report.signals_sent == 1
    sent = next(row for row in deliveries(engine) if row.status == "sent")
    assert sent.recipient_context_fingerprint != refused_fingerprint
    assert mailer.attempts == 2


def test_changed_eligibility_plan_and_cadence_rearm_future_signals(
    app, engine, mailer
) -> None:
    client, _ = subscriber(app, engine, count=11, plan="scale")
    mailer.fail_with = failure("smtp_recipient_refused", retryable=False)
    cycle(engine, mailer, now=NOW)
    refused_fingerprint = deliveries(engine)[0].recipient_context_fingerprint

    pay(engine, client, plan="pro", now=NOW + dt.timedelta(minutes=1))
    report = cycle(engine, mailer, now=NOW + dt.timedelta(days=1))

    assert report.signals_sent == 1
    sent = next(row for row in deliveries(engine) if row.status == "sent")
    assert sent.cadence == "daily"
    assert sent.recipient_context_fingerprint != refused_fingerprint
    assert mailer.attempts == 2


def test_recipient_refusal_is_strictly_isolated_between_accounts(
    app, engine, mailer
) -> None:
    subscriber(app, engine, count=11)
    mailer.fail_with = failure("smtp_recipient_refused", retryable=False)
    cycle(engine, mailer, now=NOW)

    bob = signed_up(app, "bob@materiaux-leman.ch")
    bob_icp = icp_of(bob, "Materiaux")
    pay(engine, bob, plan="scale")
    bob_key = seed(engine, bob_icp, count=1)[0]

    report = cycle(engine, mailer, now=NOW + dt.timedelta(hours=1))

    assert report.signals_sent == 1
    assert mailer.attempts == 2
    assert mailer.last.to_email == "bob@materiaux-leman.ch"
    assert bob_key in mailer.last.text_body


def test_ambiguous_batch_is_never_resent_to_a_changed_address(
    app, engine, mailer, clock
) -> None:
    client, _ = subscriber(app, engine, count=2)
    mailer.fail_with = UncertainDelivery()
    first = cycle(engine, mailer, now=NOW)
    assert first.has_current_incident
    original = deliveries(engine)
    original_fingerprint = original[0].recipient_context_fingerprint

    clock.advance(dt.timedelta(minutes=1))
    assert (
        client.patch(
            "/notification-preferences",
            json={"notification_email": "changed@negoce-romand.ch"},
        ).status_code
        == 200
    )
    retry = cycle(engine, mailer, now=NOW + RETRY_BASE)

    assert not retry.has_current_incident
    assert mailer.attempts == 1
    rows = deliveries(engine)
    assert {row.status for row in rows} == {"suppressed"}
    assert {row.suppression_reason_code for row in rows} == {
        "recipient_context_changed"
    }
    assert {row.recipient_context_fingerprint for row in rows} == {
        original_fingerprint
    }

    icp = client.get("/target-icps").json()[0]["target_icp_id"]
    new_key = seed(engine, icp, count=1, offset=2)[0]
    fresh = cycle(engine, mailer, now=NOW + RETRY_BASE + dt.timedelta(minutes=1))

    assert fresh.signals_sent == 1
    assert mailer.attempts == 2
    assert mailer.last.to_email == "changed@negoce-romand.ch"
    assert new_key in mailer.last.text_body


def test_alert_submission_emits_one_safe_json_event_per_signal(
    app, engine, mailer
) -> None:
    client, keys = subscriber(app, engine, count=2)
    logger = logging.getLogger("signals.runtime_events")
    previous_handlers = logger.handlers[:]
    previous_level = logger.level
    previous_propagate = logger.propagate
    stream = io.StringIO()
    logger.handlers.clear()
    configure_runtime_event_logging(stream=stream)
    try:
        report = cycle(engine, mailer, now=NOW)
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers[:] = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate

    assert report.signals_sent == 2
    payloads = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(payloads) == 2
    assert {payload["signal_ref"] for payload in payloads} == set(keys)
    assert {payload["account_ref"] for payload in payloads} == {
        account_of(client)
    }
    for payload in payloads:
        assert payload["event"] == "delivery"
        assert payload["channel"] == "alert"
        assert payload["status"] == "submitted"
        assert payload["code"] == "smtp_submission_accepted"
        assert payload["retryable"] is False
        assert payload["attempt"] == 1

    rendered = stream.getvalue()
    for forbidden in (
        "alice@negoce-romand.ch",
        PUBLIC_APP_URL,
        mailer.last.text_body,
        mailer.last.message_id,
        "Traceback",
        "Exception",
    ):
        assert forbidden not in rendered


def test_preference_suppression_emits_the_terminal_delivery_state(
    app, engine, mailer, monkeypatch
) -> None:
    client, keys = subscriber(app, engine)
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(
        "signals.alerts.job.emit_delivery_event",
        lambda **payload: recorded.append(payload),
    )
    mailer.fail_with = failure("smtp_450", retryable=True)
    cycle(engine, mailer, now=NOW)
    recorded.clear()
    client.patch("/notification-preferences", json={"email_enabled": False})

    cycle(engine, mailer, now=NOW + RETRY_BASE)

    assert recorded == [
        {
            "channel": "alert",
            "account_ref": account_of(client),
            "signal_ref": keys[0],
            "status": "suppressed",
            "code": "notifications_disabled",
            "retryable": False,
            "attempt": 1,
        }
    ]
