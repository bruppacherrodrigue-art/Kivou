"""Password recovery and email possession share one identity boundary."""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from test_email_verification import EMAIL
from test_email_verification import prepared_email as email_fixture

from signals.accounts import email_verification as verification
from signals.accounts import service
from signals.accounts.schema import auth_user, password_reset

prepared_email = email_fixture

NEW_PASSWORD = "Replacement-password-2026!"
CHANGED_EMAIL = "changed@example.com"


class ResetDelivery:
    def __init__(self):
        self.messages = []

    def deliver(self, *, email, locale, reset_token):
        self.messages.append((email, locale, reset_token))


def request_reset(engine, now, email=EMAIL):
    delivery = ResetDelivery()
    with engine.begin() as connection:
        result = service.request_password_reset(
            connection, email=email, now=now, reset_ttl=dt.timedelta(hours=1),
            delivery=delivery,
        )
    assert result is None
    return delivery


def test_old_address_reset_cannot_confirm_after_email_change(prepared_email):
    engine, _, _, clock, user = prepared_email
    delivery = request_reset(engine, clock[0])
    assert len(delivery.messages) == 1
    assert delivery.messages[0][:2] == (EMAIL, "fr")
    reset_token = delivery.messages[0][2]
    with engine.begin() as connection:
        proof = verification.request_verification(
            connection, user_id=user["user_id"], email=CHANGED_EMAIL, now=clock[0],
        )
    with engine.begin() as connection:
        verification.verify(connection, token=proof.token, now=clock[0])

    with pytest.raises(service.InvalidResetToken), engine.begin() as connection:
        service.confirm_password_reset(
            connection, reset_token=reset_token, new_password=NEW_PASSWORD, now=clock[0],
        )

    with engine.connect() as connection:
        assert connection.scalar(sa.select(auth_user.c.email_normalized).where(
            auth_user.c.user_id == user["user_id"],
        )) == CHANGED_EMAIL
    assert request_reset(engine, clock[0], EMAIL).messages == []
    assert request_reset(engine, clock[0], "unknown@example.com").messages == []
    assert request_reset(engine, clock[0], CHANGED_EMAIL).messages[0][:2] == (
        CHANGED_EMAIL, "fr",
    )


def test_password_reset_invalidates_pending_proof_and_preserves_verified_history(prepared_email):
    engine, _, _, clock, user = prepared_email
    with engine.begin() as connection:
        initial = verification.request_verification(
            connection, user_id=user["user_id"], email=EMAIL, now=clock[0],
        )
        verification.verify(connection, token=initial.token, now=clock[0])
        history = connection.execute(sa.select(
            verification.email_identity.c.verified_email,
            verification.email_identity.c.verified_at,
        ).where(verification.email_identity.c.user_id == user["user_id"])).one()
        old_session = service.open_session(
            connection, user_id=user["user_id"], now=clock[0],
            session_ttl=dt.timedelta(days=1),
        )
    clock[0] += dt.timedelta(minutes=2)
    with engine.begin() as connection:
        pending = verification.request_verification(
            connection, user_id=user["user_id"], email=CHANGED_EMAIL, now=clock[0],
        )
    reset_token = request_reset(engine, clock[0]).messages[0][2]
    with engine.begin() as connection:
        assert service.confirm_password_reset(
            connection, reset_token=reset_token, new_password=NEW_PASSWORD, now=clock[0],
        ) == user["user_id"]

    with pytest.raises(verification.InvalidEmailProof), engine.begin() as connection:
        verification.verify(connection, token=pending.token, now=clock[0])

    with engine.begin() as connection:
        identity = connection.execute(sa.select(verification.email_identity).where(
            verification.email_identity.c.user_id == user["user_id"],
        )).one()
        assert (identity.verified_email, identity.verified_at) == tuple(history)
        assert identity.pending_email is None
        assert identity.token_hash is None
        assert identity.expires_at is None
        assert service.authenticate(
            connection, raw_token=old_session.raw_token, now=clock[0],
        ) is None
        session = service.log_in(
            connection, email=EMAIL, password=NEW_PASSWORD, now=clock[0],
            session_ttl=dt.timedelta(days=1),
        )
        assert session.user_id == user["user_id"]
    with pytest.raises(service.InvalidResetToken), engine.begin() as connection:
        service.confirm_password_reset(
            connection, reset_token=reset_token, new_password=NEW_PASSWORD, now=clock[0],
        )


def test_deactivated_user_cannot_reset_password(prepared_email):
    engine, _, _, clock, user = prepared_email
    reset_token = request_reset(engine, clock[0]).messages[0][2]
    with engine.begin() as connection:
        original_hash = connection.scalar(sa.select(auth_user.c.password_hash).where(
            auth_user.c.user_id == user["user_id"],
        ))
        connection.execute(sa.update(auth_user).where(
            auth_user.c.user_id == user["user_id"],
        ).values(is_active=False))

    with pytest.raises(service.InvalidResetToken), engine.begin() as connection:
        service.confirm_password_reset(
            connection, reset_token=reset_token, new_password=NEW_PASSWORD, now=clock[0],
        )

    with engine.connect() as connection:
        assert connection.scalar(sa.select(auth_user.c.password_hash).where(
            auth_user.c.user_id == user["user_id"],
        )) == original_hash
        assert connection.scalar(sa.select(password_reset.c.used_at).where(
            password_reset.c.user_id == user["user_id"],
        )) is None
    assert request_reset(engine, clock[0]).messages == []
