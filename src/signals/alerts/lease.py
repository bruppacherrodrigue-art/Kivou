"""Durable cross-process lease for the transactional alert job."""

from __future__ import annotations

import datetime as dt
import enum

import sqlalchemy as sa

from signals.engagement.schema import signal_alert_job_lease

DEFAULT_JOB_NAME = "signals.alerts"


class LeaseAcquisition(enum.StrEnum):
    ACQUIRED = "acquired"
    ALREADY_RUNNING = "already_running"


def acquire(
    connection: sa.Connection,
    *,
    owner_id: str,
    now: dt.datetime,
    ttl: dt.timedelta,
    job_name: str = DEFAULT_JOB_NAME,
) -> LeaseAcquisition:
    """Acquire or reclaim the lease with one compare-and-set transaction.

    Unique-key contention is an expected no-op. Every other persistence error
    deliberately propagates so the caller can report an execution incident.
    """

    expires_at = now + ttl
    updated = connection.execute(
        sa.update(signal_alert_job_lease)
        .where(
            signal_alert_job_lease.c.job_name == job_name,
            signal_alert_job_lease.c.lease_expires_at <= now,
        )
        .values(
            owner_id=owner_id,
            acquired_at=now,
            lease_expires_at=expires_at,
            updated_at=now,
        )
    )
    if updated.rowcount == 1:
        return LeaseAcquisition.ACQUIRED

    try:
        with connection.begin_nested():
            connection.execute(
                sa.insert(signal_alert_job_lease).values(
                    job_name=job_name,
                    owner_id=owner_id,
                    acquired_at=now,
                    lease_expires_at=expires_at,
                    updated_at=now,
                )
            )
    except sa.exc.IntegrityError:
        return LeaseAcquisition.ALREADY_RUNNING
    return LeaseAcquisition.ACQUIRED


def release(
    connection: sa.Connection,
    *,
    owner_id: str,
    job_name: str = DEFAULT_JOB_NAME,
) -> None:
    """Release only a lease that is still owned by this invocation."""

    connection.execute(
        sa.delete(signal_alert_job_lease).where(
            signal_alert_job_lease.c.job_name == job_name,
            signal_alert_job_lease.c.owner_id == owner_id,
        )
    )
