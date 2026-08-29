from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.engagement.schema import signal_note
from signals.persistence.conflicts import upsert_returning


@dataclasses.dataclass(frozen=True)
class StoredNote:
    account_id: str
    signal_key: str
    note: str
    updated_at: dt.datetime


def get(connection: sa.Connection, *, account_id: str, signal_key: str) -> StoredNote | None:
    row = connection.execute(
        sa.select(signal_note).where(
            signal_note.c.account_id == account_id,
            signal_note.c.signal_key == signal_key,
        )
    ).first()
    if row is None:
        return None
    from signals.billing.service import aware_datetime

    return StoredNote(row.account_id, row.signal_key, row.note, aware_datetime(row.updated_at))


def put(
    connection: sa.Connection,
    *,
    account_id: str,
    signal_key: str,
    note: str,
    now: dt.datetime,
) -> StoredNote | None:
    if not note.strip():
        connection.execute(
            sa.delete(signal_note).where(
                signal_note.c.account_id == account_id,
                signal_note.c.signal_key == signal_key,
            )
        )
        return None
    values = {
        "account_id": account_id,
        "signal_key": signal_key,
        "note": note,
        "created_at": now,
        "updated_at": now,
    }
    row = upsert_returning(
        connection,
        signal_note,
        values,
        index_elements=[signal_note.c.account_id, signal_note.c.signal_key],
        update_values={"note": note, "updated_at": now},
        returning=(
            signal_note.c.account_id,
            signal_note.c.signal_key,
            signal_note.c.note,
            signal_note.c.updated_at,
        ),
    )
    from signals.billing.service import aware_datetime

    return StoredNote(row.account_id, row.signal_key, row.note, aware_datetime(row.updated_at))
