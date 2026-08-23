"""Durable alert batches, attempt leases and bounded retry transitions."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from collections.abc import Iterable, Sequence

import sqlalchemy as sa

from signals.alerts.gateway import message_id
from signals.engagement.schema import signal_alert_delivery

SUPPRESSION_REASON_CODES: frozenset[str] = frozenset(
    {
        "entitlement_lost",
        "notifications_disabled",
        "signal_inaccessible",
    }
)


class DeliveryStateConflict(RuntimeError):
    """The durable batch no longer has the state observed by this job."""


@dataclasses.dataclass(frozen=True)
class DeliveryBatch:
    account_id: str
    signal_keys: tuple[str, ...]
    batch_key: str
    message_id: str
    attempt_count: int


def logical_batch_key(account_id: str, signal_keys: Iterable[str]) -> str:
    canonical = json.dumps(
        [account_id, sorted(set(signal_keys))],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:40]


def retry_delay(base: dt.timedelta, attempt_count: int) -> dt.timedelta:
    exponent = max(0, attempt_count - 1)
    return min(base * (2**exponent), dt.timedelta(days=1))


def queue_batch(
    connection: sa.Connection,
    *,
    account_id: str,
    signal_keys: Iterable[str],
    cadence: str,
    now: dt.datetime,
) -> DeliveryBatch | None:
    """Persist one new logical batch without changing an existing retry batch."""

    requested = tuple(dict.fromkeys(signal_keys))
    if not requested:
        return None
    existing = {
        row.signal_key: row
        for row in connection.execute(
            sa.select(signal_alert_delivery).where(
                signal_alert_delivery.c.account_id == account_id,
                signal_alert_delivery.c.signal_key.in_(requested),
            )
        )
    }
    accepted = tuple(
        key
        for key in requested
        if key not in existing
        or (existing[key].status == "queued" and existing[key].batch_key is None)
    )
    if not accepted:
        return None

    batch_key = logical_batch_key(account_id, accepted)
    delivery_message_id = message_id(account_id=account_id, batch_key=batch_key)
    legacy_keys = tuple(key for key in accepted if key in existing)
    if legacy_keys:
        connection.execute(
            sa.update(signal_alert_delivery)
            .where(
                signal_alert_delivery.c.account_id == account_id,
                signal_alert_delivery.c.signal_key.in_(legacy_keys),
                signal_alert_delivery.c.status == "queued",
                signal_alert_delivery.c.batch_key.is_(None),
            )
            .values(
                batch_key=batch_key,
                delivery_message_id=delivery_message_id,
                updated_at=now,
            )
        )
    for signal_key in (key for key in accepted if key not in existing):
        connection.execute(
            sa.insert(signal_alert_delivery).values(
                account_id=account_id,
                signal_key=signal_key,
                status="queued",
                cadence=cadence,
                batch_key=batch_key,
                delivery_message_id=delivery_message_id,
                queued_at=now,
                attempt_count=0,
                created_at=now,
                updated_at=now,
            )
        )
    return DeliveryBatch(
        account_id=account_id,
        signal_keys=accepted,
        batch_key=batch_key,
        message_id=delivery_message_id,
        attempt_count=0,
    )


def _due(now: dt.datetime) -> sa.ColumnElement[bool]:
    return sa.or_(
        signal_alert_delivery.c.status == "queued",
        sa.and_(
            signal_alert_delivery.c.status.in_(("failed", "unknown_delivery_state")),
            signal_alert_delivery.c.retryable.is_(True),
            signal_alert_delivery.c.next_attempt_at.is_not(None),
            signal_alert_delivery.c.next_attempt_at <= now,
        ),
        sa.and_(
            signal_alert_delivery.c.status == "sending",
            signal_alert_delivery.c.lease_expires_at.is_not(None),
            signal_alert_delivery.c.lease_expires_at <= now,
        ),
    )


def next_due_batch(
    connection: sa.Connection,
    *,
    account_id: str,
    now: dt.datetime,
) -> DeliveryBatch | None:
    candidate = connection.execute(
        sa.select(
            signal_alert_delivery.c.batch_key,
            signal_alert_delivery.c.delivery_message_id,
        )
        .where(
            signal_alert_delivery.c.account_id == account_id,
            signal_alert_delivery.c.batch_key.is_not(None),
            signal_alert_delivery.c.delivery_message_id.is_not(None),
            _due(now),
        )
        .order_by(
            signal_alert_delivery.c.queued_at,
            signal_alert_delivery.c.batch_key,
        )
        .limit(1)
    ).one_or_none()
    if candidate is None:
        return None

    rows = connection.execute(
        sa.select(
            signal_alert_delivery.c.signal_key,
            signal_alert_delivery.c.attempt_count,
        )
        .where(
            signal_alert_delivery.c.account_id == account_id,
            signal_alert_delivery.c.batch_key == candidate.batch_key,
            signal_alert_delivery.c.delivery_message_id
            == candidate.delivery_message_id,
            _due(now),
        )
        .order_by(signal_alert_delivery.c.signal_key)
    ).all()
    if not rows:
        return None
    return DeliveryBatch(
        account_id=account_id,
        signal_keys=tuple(row.signal_key for row in rows),
        batch_key=candidate.batch_key,
        message_id=candidate.delivery_message_id,
        attempt_count=max(row.attempt_count for row in rows),
    )


def mark_sending(
    connection: sa.Connection,
    *,
    batch: DeliveryBatch,
    now: dt.datetime,
    lease_ttl: dt.timedelta,
) -> DeliveryBatch:
    result = connection.execute(
        sa.update(signal_alert_delivery)
        .where(*_owned_rows(batch), _due(now))
        .values(
            status="sending",
            attempt_count=signal_alert_delivery.c.attempt_count + 1,
            attempt_started_at=now,
            lease_expires_at=now + lease_ttl,
            next_attempt_at=None,
            retryable=None,
            updated_at=now,
        )
    )
    _expect_all(result, batch)
    return dataclasses.replace(batch, attempt_count=batch.attempt_count + 1)


def mark_sent(
    connection: sa.Connection,
    *,
    batch: DeliveryBatch,
    provider_message_id: str,
    now: dt.datetime,
) -> None:
    result = connection.execute(
        sa.update(signal_alert_delivery)
        .where(*_owned_rows(batch), signal_alert_delivery.c.status == "sending")
        .values(
            status="sent",
            sent_at=now,
            failed_at=None,
            provider_message_id=provider_message_id,
            last_error_code=None,
            retryable=False,
            lease_expires_at=None,
            next_attempt_at=None,
            updated_at=now,
        )
    )
    _expect_all(result, batch)


def mark_failed(
    connection: sa.Connection,
    *,
    batch: DeliveryBatch,
    error_code: str,
    retryable: bool,
    now: dt.datetime,
    retry_base: dt.timedelta,
    max_attempts: int,
) -> None:
    _mark_unsuccessful(
        connection,
        batch=batch,
        status="failed",
        error_code=error_code,
        retryable=retryable,
        now=now,
        retry_base=retry_base,
        max_attempts=max_attempts,
    )


def mark_unknown(
    connection: sa.Connection,
    *,
    batch: DeliveryBatch,
    error_code: str,
    now: dt.datetime,
    retry_base: dt.timedelta,
    max_attempts: int,
) -> None:
    _mark_unsuccessful(
        connection,
        batch=batch,
        status="unknown_delivery_state",
        error_code=error_code,
        retryable=True,
        now=now,
        retry_base=retry_base,
        max_attempts=max_attempts,
    )


def mark_suppressed(
    connection: sa.Connection,
    *,
    batch: DeliveryBatch,
    signal_keys: Sequence[str],
    reason_code: str,
    now: dt.datetime,
) -> None:
    if reason_code not in SUPPRESSION_REASON_CODES:
        raise ValueError("unsupported alert suppression reason")
    keys = tuple(signal_keys)
    result = connection.execute(
        sa.update(signal_alert_delivery)
        .where(
            *_owned_rows(batch, signal_keys=keys),
            signal_alert_delivery.c.status != "sent",
        )
        .values(
            status="suppressed",
            retryable=False,
            lease_expires_at=None,
            next_attempt_at=None,
            suppressed_at=now,
            suppression_reason_code=reason_code,
            updated_at=now,
        )
    )
    if result.rowcount != len(keys):
        raise DeliveryStateConflict(batch.batch_key)


def _mark_unsuccessful(
    connection: sa.Connection,
    *,
    batch: DeliveryBatch,
    status: str,
    error_code: str,
    retryable: bool,
    now: dt.datetime,
    retry_base: dt.timedelta,
    max_attempts: int,
) -> None:
    will_retry = retryable and batch.attempt_count < max_attempts
    next_attempt_at = (
        now + retry_delay(retry_base, batch.attempt_count) if will_retry else None
    )
    result = connection.execute(
        sa.update(signal_alert_delivery)
        .where(*_owned_rows(batch), signal_alert_delivery.c.status == "sending")
        .values(
            status=status,
            failed_at=now,
            last_error_code=error_code,
            retryable=will_retry,
            lease_expires_at=None,
            next_attempt_at=next_attempt_at,
            updated_at=now,
        )
    )
    _expect_all(result, batch)


def _owned_rows(
    batch: DeliveryBatch,
    *,
    signal_keys: Sequence[str] | None = None,
) -> tuple[sa.ColumnElement[bool], ...]:
    keys = tuple(signal_keys) if signal_keys is not None else batch.signal_keys
    return (
        signal_alert_delivery.c.account_id == batch.account_id,
        signal_alert_delivery.c.signal_key.in_(keys),
        signal_alert_delivery.c.batch_key == batch.batch_key,
        signal_alert_delivery.c.delivery_message_id == batch.message_id,
    )


def _expect_all(result: sa.CursorResult, batch: DeliveryBatch) -> None:
    if result.rowcount != len(batch.signal_keys):
        raise DeliveryStateConflict(batch.batch_key)
