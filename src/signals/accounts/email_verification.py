"""Possession of an email address, independent of login and attribution."""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import secrets

import sqlalchemy as sa

from signals.accounts import service as accounts
from signals.accounts.schema import auth_user, password_reset
from signals.persistence.schema import METADATA

PROOF_TTL = dt.timedelta(hours=24)
REQUEST_COOLDOWN = dt.timedelta(minutes=1)

email_identity = sa.Table(
    "email_identity", METADATA,
    sa.Column("user_id", sa.String(64), sa.ForeignKey("auth_user.user_id", ondelete="CASCADE"),
              primary_key=True),
    sa.Column("verified_email", sa.String(320)),
    sa.Column("verified_at", sa.DateTime(timezone=True)),
    sa.Column("pending_email", sa.String(320)),
    sa.Column("token_hash", sa.String(64), unique=True),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
    sa.Column("requested_at", sa.DateTime(timezone=True)),
)


class InvalidEmailProof(ValueError):
    pass


class EmailProofCooldown(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class PendingProof:
    email: str = dataclasses.field(repr=False)
    token: str = dataclasses.field(repr=False)


def _digest(token: str) -> str:
    return hashlib.sha256(b"kivou:email-verification:v1\0" + token.encode()).hexdigest()


def _aware(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


def is_user_verified(connection: sa.Connection, *, user_id: str) -> bool:
    """An attribution bearer must never reopen an identity that proved ownership."""
    return bool(connection.scalar(sa.select(sa.exists().where(
        email_identity.c.user_id == user_id,
        email_identity.c.verified_at.is_not(None),
        email_identity.c.verified_email.is_not(None),
    ))))


def is_verified_recipient(connection: sa.Connection, *, account_id: str, email: str) -> bool:
    normalized = accounts.normalize_email(email)
    return bool(connection.scalar(sa.select(sa.exists().where(
        auth_user.c.account_id == account_id,
        auth_user.c.is_active.is_(True),
        auth_user.c.email_normalized == normalized,
        email_identity.c.user_id == auth_user.c.user_id,
        email_identity.c.verified_email == normalized,
        email_identity.c.verified_at.is_not(None),
        email_identity.c.pending_email.is_(None),
    ))))


def state(connection: sa.Connection, *, user_id: str) -> dict:
    user = connection.execute(sa.select(auth_user).where(auth_user.c.user_id == user_id)).one()
    proof = connection.execute(sa.select(email_identity).where(
        email_identity.c.user_id == user_id,
    )).first()
    return {
        "email": user.email_normalized,
        "verified": bool(proof and proof.verified_at and
                         proof.verified_email == user.email_normalized),
        "pending_email": proof.pending_email if proof else None,
    }


def request_verification(connection: sa.Connection, *, user_id: str, email: str,
                         now: dt.datetime) -> PendingProof:
    from signals.engagement.notifications import validate_email

    normalized = validate_email(email)
    # The same lock serializes competing requests and proof consumption for this user.
    user = connection.execute(sa.select(auth_user).where(
        auth_user.c.user_id == user_id, auth_user.c.is_active.is_(True),
    ).with_for_update()).one()
    other = connection.scalar(sa.select(auth_user.c.user_id).where(
        auth_user.c.email_normalized == normalized, auth_user.c.user_id != user.user_id,
    ))
    if other is not None:
        raise accounts.EmailAlreadyUsed("adresse indisponible")
    current = connection.execute(sa.select(email_identity).where(
        email_identity.c.user_id == user_id,
    )).first()
    if current and current.requested_at and now < _aware(current.requested_at) + REQUEST_COOLDOWN:
        raise EmailProofCooldown("demande trop recente")
    token = secrets.token_urlsafe(32)
    values = {"pending_email": normalized, "token_hash": _digest(token),
                  "expires_at": now + PROOF_TTL, "requested_at": now}
    if current:
        connection.execute(sa.update(email_identity).where(
            email_identity.c.user_id == user_id,
        ).values(**values))
    else:
        connection.execute(sa.insert(email_identity).values(user_id=user_id, **values))
    return PendingProof(email=normalized, token=token)


def verify(connection: sa.Connection, *, token: str, now: dt.datetime) -> str:
    digest = _digest(token)
    candidate = connection.execute(sa.select(email_identity).where(
        email_identity.c.token_hash == digest,
    )).first()
    if candidate is None:
        raise InvalidEmailProof("lien invalide")
    # Lock before re-reading: a newer request may have invalidated the candidate.
    user = connection.execute(sa.select(auth_user).where(
        auth_user.c.user_id == candidate.user_id, auth_user.c.is_active.is_(True),
    ).with_for_update()).first()
    proof = connection.execute(sa.select(email_identity).where(
        email_identity.c.user_id == candidate.user_id,
        email_identity.c.token_hash == digest,
    )).first()
    if (user is None or proof is None or not proof.pending_email or not proof.expires_at
            or _aware(proof.expires_at) <= now):
        raise InvalidEmailProof("lien invalide ou expire")
    other = connection.scalar(sa.select(auth_user.c.user_id).where(
        auth_user.c.email_normalized == proof.pending_email,
        auth_user.c.user_id != user.user_id,
    ))
    if other is not None:
        raise accounts.EmailAlreadyUsed("adresse indisponible")
    consumed = connection.execute(sa.update(email_identity).where(
        email_identity.c.user_id == user.user_id,
        email_identity.c.token_hash == digest,
        email_identity.c.expires_at > now,
    ).values(verified_email=proof.pending_email, verified_at=now, pending_email=None,
             token_hash=None, expires_at=None))
    if consumed.rowcount != 1:
        raise InvalidEmailProof("lien deja utilise")
    # A reset sent to an earlier address must not recover the renamed identity.
    # Keep its history, but consume it under the same user lock as reset issuance.
    connection.execute(sa.update(password_reset).where(
        password_reset.c.user_id == user.user_id,
        password_reset.c.used_at.is_(None),
    ).values(used_at=now))
    connection.execute(sa.update(auth_user).where(auth_user.c.user_id == user.user_id).values(
        email_normalized=proof.pending_email, updated_at=now,
    ))
    # Preserve the user's opt-out; only the verified destination changes.
    from signals.engagement.notifications import update_preference
    update_preference(connection, account_id=user.account_id, email_enabled=None,
                      notification_email=proof.pending_email, now=now)
    accounts.revoke_all_sessions(connection, user_id=user.user_id, now=now)
    return user.user_id
