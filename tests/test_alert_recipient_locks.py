"""Recipient serialization at the ALERT transport boundary, without real email."""

import datetime as dt
import queue
import threading
import time

import pytest
import sqlalchemy as sa
from alert_identity_helpers import verified_signed_up
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
)
from sqlalchemy.dialects import postgresql
from test_saas_company_service import _isolated_postgres_engine

from signals.accounts import email_verification
from signals.accounts.schema import auth_user
from signals.alerts.gateway import AlertDeliveryError, DeliveryResult, UncertainDelivery
from signals.alerts.job import run_alert_cycle
from signals.engagement import notifications
from signals.engagement.schema import (
    account_notification_preference,
    signal_alert_delivery,
    signal_alert_job_lease,
)


def prepare(engine, *, other=False):
    app = make_app(engine, Clock())
    client = verified_signed_up(app, engine)
    account_id = account_of(client)
    pay(engine, client, plan="essential")
    seed(engine, icp_of(client))
    other_id = None
    if other:
        other_id = account_of(verified_signed_up(app, engine, "bob@materiaux-leman.ch"))
    with engine.begin() as connection:
        for identifier in (account_id, other_id):
            if identifier is not None:
                notifications.preference(connection, account_id=identifier, now=NOW)
        user_id = connection.scalar(sa.select(auth_user.c.user_id).where(
            auth_user.c.account_id == account_id,
        ))
    return account_id, user_id, other_id


def cycle(engine, gateway, account_id):
    return run_alert_cycle(engine, gateway, account_id=account_id, now=NOW,
                           public_app_url=PUBLIC_APP_URL)


def capture_locks(engine):
    observed = []

    def capture(connection, statement, multiparams, params, execution_options):
        if isinstance(statement, sa.sql.Select) and statement._for_update_arg is not None:
            observed.append((connection, statement.compile(dialect=postgresql.dialect())))

    sa.event.listen(engine, "before_execute", capture)
    return observed, capture


def assert_job_lease_released(engine):
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(signal_alert_job_lease)) == 0


def test_exact_user_then_preference_locks_span_the_transport(tmp_path):
    engine = make_engine(tmp_path)
    account_id, _, _ = prepare(engine)
    observed, listener = capture_locks(engine)

    class Gateway:
        def send(self, message):
            assert len(observed) == 2
            user_connection, user_statement = observed[0]
            pref_connection, pref_statement = observed[1]
            assert user_connection is pref_connection
            assert user_connection.in_transaction()
            assert "FROM auth_user" in str(user_statement)
            assert "FROM account_notification_preference" in str(pref_statement)
            assert "FOR UPDATE" in str(user_statement)
            assert "FOR UPDATE" in str(pref_statement)
            assert account_id in user_statement.params.values()
            assert message.to_email in user_statement.params.values()
            assert account_id in pref_statement.params.values()
            return DeliveryResult(message.message_id)

    try:
        report = cycle(engine, Gateway(), account_id)
    finally:
        sa.event.remove(engine, "before_execute", listener)

    assert report.signals_sent == 1
    assert observed[0][0].closed
    assert_job_lease_released(engine)


def test_guard_commit_failure_after_submission_keeps_persistence_failure_semantics(tmp_path):
    engine = make_engine(tmp_path)
    account_id, _, _ = prepare(engine)
    observed, listener = capture_locks(engine)
    mailer = FakeMailer()
    failed = False

    def fail_guard_commit(connection):
        nonlocal failed
        if observed and connection is observed[0][0] and mailer.attempts and not failed:
            failed = True
            raise sa.exc.OperationalError("COMMIT", {}, RuntimeError("synthetic guard failure"))

    sa.event.listen(engine, "commit", fail_guard_commit)
    try:
        report = cycle(engine, mailer, account_id)
    finally:
        sa.event.remove(engine, "commit", fail_guard_commit)
        sa.event.remove(engine, "before_execute", listener)

    assert failed
    assert mailer.attempts == 1
    assert report.outcomes[0].result == "persistence_failed"
    assert report.outcomes[0].detail == "delivery_state_persistence_failed"
    assert report.has_current_incident
    with engine.connect() as connection:
        assert connection.scalar(sa.select(signal_alert_delivery.c.status)) == "sending"
    assert_job_lease_released(engine)


def test_guard_database_failure_never_calls_transport_and_releases_job_lease(tmp_path):
    engine = make_engine(tmp_path)
    account_id, _, _ = prepare(engine)
    mailer = FakeMailer()

    def fail_lock(connection, statement, multiparams, params, execution_options):
        if isinstance(statement, sa.sql.Select) and statement._for_update_arg is not None:
            raise sa.exc.OperationalError("SELECT FOR UPDATE", {}, RuntimeError("synthetic"))

    sa.event.listen(engine, "before_execute", fail_lock)
    try:
        with pytest.raises(sa.exc.OperationalError):
            cycle(engine, mailer, account_id)
    finally:
        sa.event.remove(engine, "before_execute", fail_lock)

    assert mailer.attempts == 0
    assert_job_lease_released(engine)


@pytest.fixture
def postgres_engine():
    with _isolated_postgres_engine() as engine:
        yield engine


def assert_recipient_rows_locked(engine, account_id):
    for table in (auth_user, account_notification_preference):
        with engine.begin() as connection:
            with pytest.raises(sa.exc.OperationalError) as raised:
                connection.execute(sa.select(table).where(
                    table.c.account_id == account_id,
                ).with_for_update(nowait=True))
            assert raised.value.orig.sqlstate == "55P03"


def assert_recipient_rows_available(engine, account_id):
    with engine.begin() as connection:
        for table in (auth_user, account_notification_preference):
            assert connection.execute(sa.select(table).where(
                table.c.account_id == account_id,
            ).with_for_update(nowait=True)).first() is not None


@pytest.mark.parametrize("writer", ["verification_request", "preference_change"])
@pytest.mark.parametrize(("failure", "expected_status"), [
    (None, "sent"),
    ("retryable", "failed"),
    ("uncertain", "unknown_delivery_state"),
])
def test_postgres_serializes_recipient_changes_and_releases_only_its_rows(
    postgres_engine, writer, failure, expected_status,
):
    engine = postgres_engine
    account_id, user_id, other_id = prepare(engine, other=True)
    pids = queue.Queue()
    completed = threading.Event()
    errors = []

    def concurrent_change():
        try:
            with engine.begin() as connection:
                connection.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
                pids.put(connection.scalar(sa.select(sa.func.pg_backend_pid())))
                if writer == "verification_request":
                    email_verification.request_verification(
                        connection, user_id=user_id, email="changed@negoce-romand.ch",
                        now=NOW + dt.timedelta(minutes=2),
                    )
                else:
                    notifications.update_preference(
                        connection, account_id=account_id, email_enabled=None,
                        notification_email="changed@negoce-romand.ch",
                        now=NOW + dt.timedelta(minutes=2),
                    )
            completed.set()
        except BaseException as error:  # noqa: BLE001 - propagate worker failures to the test thread.
            errors.append(error)

    thread = threading.Thread(target=concurrent_change, daemon=True)

    class Gateway:
        def send(self, message):
            assert_recipient_rows_locked(engine, account_id)
            assert_recipient_rows_available(engine, other_id)
            thread.start()
            pid = pids.get(timeout=5)
            deadline = time.monotonic() + 3
            blocked = False
            while time.monotonic() < deadline:
                with engine.connect() as connection:
                    blocked = connection.scalar(sa.text(
                        "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                    ), {"pid": pid})
                if blocked:
                    break
                if completed.is_set() or errors:
                    break
                time.sleep(0.01)
            assert blocked, "recipient change did not wait for the transport's row lock"
            assert not completed.is_set()
            if failure == "retryable":
                raise AlertDeliveryError("smtp_451")
            if failure == "uncertain":
                raise UncertainDelivery()
            return DeliveryResult(message.message_id)

    try:
        report = cycle(engine, Gateway(), account_id)
    finally:
        if thread.ident is not None:
            thread.join(timeout=7)

    assert not thread.is_alive()
    assert errors == []
    assert completed.is_set()
    assert report.outcomes[0].result == expected_status
    assert_recipient_rows_available(engine, account_id)
    assert_job_lease_released(engine)
    with engine.connect() as connection:
        assert connection.scalar(sa.select(signal_alert_delivery.c.status)) == expected_status
