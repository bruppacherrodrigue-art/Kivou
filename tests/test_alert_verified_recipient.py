"""ALERT requires current proof both before queueing and before SMTP."""

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

from signals.accounts.schema import auth_user
from signals.alerts import delivery
from signals.alerts.gateway import SmtpAlertGateway, SmtpConfiguration
from signals.alerts.job import run_alert_cycle
from signals.engagement import notifications
from signals.engagement.schema import account_notification_preference, signal_alert_delivery


def prepared(tmp_path, *, verified=True):
    engine = make_engine(tmp_path)
    app = make_app(engine, Clock())
    client = signed_up(app)
    icp = icp_of(client)
    pay(engine, client, plan="essential")
    seed(engine, icp)
    if verified:
        verify_recipient(engine, client)
    return engine, client, account_of(client)


def rows(engine):
    with engine.connect() as connection:
        return connection.execute(sa.select(signal_alert_delivery)).all()


def invalidate(connection, account_id, change):
    from signals.accounts.email_verification import email_identity as table

    user = connection.execute(
        sa.select(auth_user).where(auth_user.c.account_id == account_id)
    ).one()
    identity = table.c.user_id == user.user_id
    if change == "missing":
        connection.execute(sa.delete(table).where(identity))
    elif change == "inactive":
        connection.execute(
            sa.update(auth_user).where(auth_user.c.user_id == user.user_id).values(is_active=False)
        )
    elif change == "disabled":
        connection.execute(
            sa.update(account_notification_preference)
            .where(account_notification_preference.c.account_id == account_id)
            .values(email_enabled=False)
        )
    elif change in {"changed_unverified", "changed_verified"}:
        address = "new-alerts@negoce-romand.ch"
        if change == "changed_verified":
            # The old address remains verified too: comparing only its proof is insufficient.
            second_user = dict(user._mapping)
            second_user.update(user_id="usr_other_verified", email_normalized=address)
            connection.execute(sa.insert(auth_user).values(**second_user))
            connection.execute(sa.insert(table).values(
                user_id=second_user["user_id"], verified_email=address,
                verified_at=NOW, requested_at=NOW,
            ))
        connection.execute(
            sa.update(account_notification_preference)
            .where(account_notification_preference.c.account_id == account_id)
            .values(notification_email=address, updated_at=NOW + dt.timedelta(seconds=1))
        )
    else:
        changes = {
            "unverified": {"verified_email": None, "verified_at": None},
            "no_timestamp": {"verified_at": None},
            "mismatched": {"verified_email": "different@negoce-romand.ch"},
            "pending": {"pending_email": "pending@negoce-romand.ch"},
        }
        connection.execute(sa.update(table).where(identity).values(**changes[change]))


def test_notification_preference_defaults_to_no_verified_proof():
    preference = notifications.NotificationPreference(
        account_id="acc_legacy", email_enabled=True,
        notification_email="alice@negoce-romand.ch", created_at=NOW, updated_at=NOW,
    )
    assert preference.can_receive_email is False


def test_an_old_account_without_proof_never_queues_or_sends(tmp_path):
    engine, _, _ = prepared(tmp_path, verified=False)
    mailer = FakeMailer()

    report = run_alert_cycle(engine, mailer, now=NOW, public_app_url=PUBLIC_APP_URL)

    assert mailer.attempts == 0
    assert rows(engine) == []
    assert report.outcomes[0].result == "recipient_context_unverifiable"


@pytest.mark.parametrize("change", [
    "missing", "unverified", "no_timestamp", "mismatched", "pending", "inactive",
])
def test_preference_requires_current_exact_active_identity(tmp_path, change):
    engine, _, account_id = prepared(tmp_path)
    with engine.begin() as connection:
        assert notifications.preference(connection, account_id=account_id, now=NOW).can_receive_email
        invalidate(connection, account_id, change)
        current = notifications.preference(connection, account_id=account_id, now=NOW)

    assert current.can_receive_email is False


def test_another_accounts_verified_email_is_not_proof(tmp_path):
    engine, client, account_id = prepared(tmp_path, verified=False)
    app = make_app(engine, Clock())
    other = signed_up(app, "bob@materiaux-leman.ch")
    verify_recipient(engine, other)
    response = client.patch(
        "/notification-preferences", json={"notification_email": "bob@materiaux-leman.ch"}
    )
    assert response.status_code == 200

    with engine.begin() as connection:
        current = notifications.preference(connection, account_id=account_id, now=NOW)

    assert current.can_receive_email is False


def test_verified_weekly_recipient_queues_and_sends(tmp_path):
    engine, _, _ = prepared(tmp_path)
    mailer = FakeMailer()

    report = run_alert_cycle(engine, mailer, now=NOW, public_app_url=PUBLIC_APP_URL)

    assert report.signals_sent == 1
    assert mailer.last.to_email == "alice@negoce-romand.ch"
    assert rows(engine)[0].status == "sent"


@pytest.mark.parametrize("change", ["missing", "pending", "changed_unverified", "changed_verified"])
def test_queued_batches_fail_closed_after_recipient_changes(tmp_path, change):
    engine, _, account_id = prepared(tmp_path)
    mailer = FakeMailer()
    run_alert_cycle(engine, mailer, now=NOW, public_app_url=None)
    assert rows(engine)[0].status == "queued"
    with engine.begin() as connection:
        invalidate(connection, account_id, change)

    report = run_alert_cycle(engine, mailer, now=NOW, public_app_url=PUBLIC_APP_URL)

    assert report.outcomes[0].result == "suppressed"
    assert mailer.attempts == 0
    assert rows(engine)[0].status == "suppressed"
    assert rows(engine)[0].retryable is False


@pytest.mark.parametrize("change", [
    "missing", "pending", "inactive", "disabled", "changed_unverified", "changed_verified",
])
def test_proof_is_rechecked_immediately_before_real_smtp_gateway(tmp_path, monkeypatch, change):
    engine, _, account_id = prepared(tmp_path)
    original = delivery.mark_sending

    def change_after_initial_check(connection, **kwargs):
        batch = original(connection, **kwargs)
        invalidate(connection, account_id, change)
        return batch

    def smtp_must_not_open(*args, **kwargs):
        pytest.fail("SMTP attempted after recipient proof or preference changed")

    monkeypatch.setattr(delivery, "mark_sending", change_after_initial_check)
    monkeypatch.setattr("smtplib.SMTP", smtp_must_not_open)
    gateway = SmtpAlertGateway(SmtpConfiguration(host="smtp.invalid", port=587,
                                               from_email="alerts@kivou.test"))

    report = run_alert_cycle(engine, gateway, now=NOW, public_app_url=PUBLIC_APP_URL)

    assert report.outcomes[0].result == "suppressed"
    assert rows(engine)[0].status == "suppressed"
    assert rows(engine)[0].retryable is False
    assert rows(engine)[0].lease_expires_at is None
