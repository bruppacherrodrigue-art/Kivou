from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.billing.service import aware_datetime
from signals.engagement.schema import MAXIMUM_SIGNAL_NOTE_LENGTH, signal_note
from signals.persistence.conflicts import _conflict_insert


class NoteRevisionError(ValueError):
    def __init__(self, *, code: str, note: str | None, revision: int, updated_at) -> None:
        super().__init__(code)
        self.code = code
        self.note = note
        self.revision = revision
        self.updated_at = aware_datetime(updated_at)


@dataclasses.dataclass(frozen=True)
class StoredNote:
    account_id: str
    signal_key: str
    note: str | None
    updated_at: dt.datetime
    revision: int


def _stored(row) -> StoredNote:
    return StoredNote(
        row.account_id,
        row.signal_key,
        row.note or None,
        aware_datetime(row.updated_at),
        row.revision,
    )


def get(connection: sa.Connection, *, account_id: str, signal_key: str) -> StoredNote | None:
    row = connection.execute(
        sa.select(signal_note).where(
            signal_note.c.account_id == account_id,
            signal_note.c.signal_key == signal_key,
        )
    ).first()
    if row is None:
        return None
    return _stored(row)


def write_revisioned_note(
    connection: sa.Connection,
    *,
    table: sa.Table,
    account_id: str,
    key_column: str,
    key: str,
    text_column: str,
    text: str,
    maximum_length: int,
    expected_revision: int | None,
    now: dt.datetime,
):
    """One guarded write; a losing writer reads the authoritative conflict value.

    Missing revisions only permit an INSERT. A positive expected revision never
    creates an absent row. Keeping empty rows prevents a stale revision zero
    request from recreating a note after it has been cleared.
    """
    if len(text) > maximum_length:
        raise ValueError(f"note must contain at most {maximum_length} characters")
    if expected_revision is not None and (
        type(expected_revision) is not int or expected_revision < 0
    ):
        raise ValueError("expected_revision must be a non-negative integer")
    normalized = text if text.strip() else ""
    scope = sa.and_(table.c.account_id == account_id, table.c[key_column] == key)
    if expected_revision in (None, 0):
        statement = (
            _conflict_insert(connection, table)
            .values(
                {
                    "account_id": account_id,
                    key_column: key,
                    text_column: normalized,
                    "created_at": now,
                    "updated_at": now,
                    "revision": 1,
                }
            )
            .on_conflict_do_nothing(index_elements=[table.c.account_id, table.c[key_column]])
        )
    else:
        statement = (
            sa.update(table)
            .where(
                scope,
                table.c.revision == expected_revision,
            )
            .values({text_column: normalized, "revision": table.c.revision + 1, "updated_at": now})
        )
    row = connection.execute(statement.returning(*table.c)).first()
    if row is not None:
        return row
    current = connection.execute(sa.select(table).where(scope)).mappings().first()
    raise NoteRevisionError(
        code="note_revision_required" if expected_revision is None else "note_conflict",
        note=None if current is None else current[text_column] or None,
        revision=0 if current is None else current["revision"],
        updated_at=None if current is None else current["updated_at"],
    )


def put(
    connection: sa.Connection,
    *,
    account_id: str,
    signal_key: str,
    note: str,
    now: dt.datetime,
    expected_revision: int | None = None,
) -> StoredNote:
    return _stored(
        write_revisioned_note(
            connection,
            table=signal_note,
            account_id=account_id,
            key_column="signal_key",
            key=signal_key,
            text_column="note",
            text=note,
            maximum_length=MAXIMUM_SIGNAL_NOTE_LENGTH,
            expected_revision=expected_revision,
            now=now,
        )
    )
