from __future__ import annotations

import datetime as dt
import secrets

import sqlalchemy as sa

from signals.accounts.schema import account, account_deletion_request, target_icp


def export_account(connection: sa.Connection, *, account_id: str) -> dict[str, object]:
    account_row = connection.execute(
        sa.select(account).where(account.c.account_id == account_id)
    ).mappings().one()
    profiles = connection.execute(
        sa.select(target_icp)
        .where(target_icp.c.account_id == account_id)
        .order_by(target_icp.c.created_at, target_icp.c.target_icp_id)
    ).mappings()
    return {"account": dict(account_row), "profiles": [dict(row) for row in profiles]}


def request_deletion(
    connection: sa.Connection, *, account_id: str, now: dt.datetime
) -> dt.datetime:
    scheduled_for = now + dt.timedelta(hours=24)
    existing = connection.execute(
        sa.select(account_deletion_request).where(
            account_deletion_request.c.account_id == account_id
        )
    ).mappings().one_or_none()
    if existing is not None:
        return existing["scheduled_for"]
    connection.execute(
        sa.insert(account_deletion_request).values(
            request_id=secrets.token_hex(32),
            account_id=account_id,
            requested_at=now,
            scheduled_for=scheduled_for,
        )
    )
    return scheduled_for


def purge_due_deletions(engine: sa.Engine, *, now: dt.datetime) -> int:
    with engine.begin() as connection:
        due = connection.execute(
            sa.select(account_deletion_request.c.account_id).where(
                account_deletion_request.c.completed_at.is_(None),
                account_deletion_request.c.scheduled_for <= now,
            )
        ).scalars().all()
        for account_id in due:
            connection.execute(sa.delete(account).where(account.c.account_id == account_id))
            connection.execute(
                sa.update(account_deletion_request)
                .where(account_deletion_request.c.account_id == account_id)
                .values(completed_at=now)
            )
    return len(due)
