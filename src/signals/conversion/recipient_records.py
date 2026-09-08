"""Server-side addresses for opaque attribution tokens, never URL payloads."""

from __future__ import annotations

import datetime as dt
import re

import sqlalchemy as sa

from signals.engagement.notifications import validate_email
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import METADATA

attribution_recipient = sa.Table(
    "attribution_recipient",
    METADATA,
    sa.Column("nonce", sa.String(64), primary_key=True),
    sa.Column("email_normalized", sa.String(320), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)


def normalize_recipient(email: str) -> str:
    if not isinstance(email, str) or not email.strip():
        raise ValueError("Attribution recipient is required")
    try:
        normalized = validate_email(email)
    except (ValueError, RuntimeError):
        raise ValueError("Attribution recipient is invalid") from None
    if len(normalized) > 320:
        raise ValueError("Attribution recipient is invalid")
    return normalized


def _utc(value: dt.datetime) -> dt.datetime:
    # SQLite returns naive values for timezone-aware SQL columns.
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def bind_recipient(
    connection: sa.Connection, *, nonce: str, recipient_email: str,
    expires_at: dt.datetime, created_at: dt.datetime,
) -> None:
    """Bind once in the caller's transaction; a retry cannot change the address."""
    if re.fullmatch(r"(?:[0-9a-f]{32}|[0-9a-f]{64})", nonce) is None:
        raise ValueError("Invalid attribution recipient key")
    if any(value.tzinfo is None or value.utcoffset() is None
           for value in (expires_at, created_at)) or expires_at <= created_at:
        raise ValueError("Invalid attribution recipient lifetime")
    email = normalize_recipient(recipient_email)
    insert_if_absent(
        connection, attribution_recipient,
        {"nonce": nonce, "email_normalized": email,
         "expires_at": expires_at, "created_at": created_at},
        index_elements=[attribution_recipient.c.nonce],
    )
    row = connection.execute(sa.select(attribution_recipient).where(
        attribution_recipient.c.nonce == nonce,
    )).mappings().one()
    if row["email_normalized"] != email or _utc(row["expires_at"]) != _utc(expires_at):
        raise ValueError("Attribution recipient binding conflicts")


def resolve_recipient(
    connection: sa.Connection, *, nonce: str, now: dt.datetime, lock: bool = False,
) -> str:
    query = sa.select(attribution_recipient).where(attribution_recipient.c.nonce == nonce)
    if lock:
        query = query.with_for_update()
    row = connection.execute(query).mappings().one_or_none()
    if row is None or not _utc(row["created_at"]) <= now < _utc(row["expires_at"]):
        raise ValueError("Attribution recipient unavailable")
    return normalize_recipient(row["email_normalized"])
