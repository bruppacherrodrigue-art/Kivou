from __future__ import annotations

import datetime as dt
import secrets

import sqlalchemy as sa

from signals.accounts.schema import account, account_deletion_request
from signals.persistence.schema import METADATA

_SECRET_COLUMNS = {"password_hash", "token_hash"}


def _account_tables() -> tuple[sa.Table, ...]:
    return tuple(
        table
        for table in METADATA.sorted_tables
        if "account_id" in table.c
        and table is not account_deletion_request
    )


def export_account(connection: sa.Connection, *, account_id: str) -> dict[str, object]:
    account_row = connection.execute(
        sa.select(account).where(account.c.account_id == account_id)
    ).mappings().one()
    data: dict[str, list[dict[str, object]]] = {}
    for table in _account_tables():
        if table is account:
            continue
        columns = [column for column in table.c if column.name not in _SECRET_COLUMNS]
        rows = connection.execute(
            sa.select(*columns).where(table.c.account_id == account_id)
        ).mappings()
        data[table.name] = [dict(row) for row in rows]
    return {
        "account": dict(account_row),
        "profiles": data.get("target_icp", []),
        "data": data,
    }


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
            for table in reversed(_account_tables()):
                if table is account:
                    continue
                connection.execute(sa.delete(table).where(table.c.account_id == account_id))
            connection.execute(sa.delete(account).where(account.c.account_id == account_id))
            connection.execute(
                sa.update(account_deletion_request)
                .where(account_deletion_request.c.account_id == account_id)
                .values(completed_at=now)
            )
    return len(due)
