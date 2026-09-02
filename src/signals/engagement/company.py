"""Le suivi commercial PAR ENTREPRISE — un compte, une entreprise, un statut.

PR1 §4 — un signal se juge un par un (`engagement/feedback.py`), mais une
démarche commerciale vise une ENTREPRISE : plusieurs signaux d'un même
attributaire ne racontent pas plusieurs démarches. `contacted_at` se pose au
premier passage vers `contacted`/`replied` et n'est plus jamais remis à nul —
reculer le statut à `to_contact` dit « je dois relancer », pas « je n'ai
jamais appelé ».
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.billing.service import aware_datetime
from signals.engagement.schema import COMPANY_CONTACT_STATUSES, company_contact, company_note
from signals.persistence.conflicts import upsert_returning


class InvalidContactStatus(ValueError):
    """Un statut de contact que le vocabulaire fermé n'admet pas."""


@dataclasses.dataclass(frozen=True)
class StoredCompanyContact:
    account_id: str
    company_key: str
    status: str
    contacted_at: dt.datetime | None
    updated_at: dt.datetime


def _contact_row(row: sa.Row) -> StoredCompanyContact:
    return StoredCompanyContact(
        account_id=row.account_id,
        company_key=row.company_key,
        status=row.status,
        contacted_at=None if row.contacted_at is None else aware_datetime(row.contacted_at),
        updated_at=aware_datetime(row.updated_at),
    )


def get_contact(
    connection: sa.Connection, *, account_id: str, company_key: str
) -> StoredCompanyContact | None:
    row = connection.execute(
        sa.select(company_contact).where(
            company_contact.c.account_id == account_id,
            company_contact.c.company_key == company_key,
        )
    ).first()
    return None if row is None else _contact_row(row)


def contacts_by_company(
    connection: sa.Connection, *, account_id: str
) -> dict[str, StoredCompanyContact]:
    """Toutes les lignes de suivi du compte, indexées par entreprise — une requête."""
    rows = connection.execute(
        sa.select(company_contact).where(company_contact.c.account_id == account_id)
    ).all()
    return {row.company_key: _contact_row(row) for row in rows}


def set_contact(
    connection: sa.Connection,
    *,
    account_id: str,
    company_key: str,
    status: str,
    now: dt.datetime,
) -> StoredCompanyContact:
    """Upsert du statut. `contacted_at` se pose une fois, ne se remet jamais à nul."""
    if status not in COMPANY_CONTACT_STATUSES:
        raise InvalidContactStatus(
            f"statut de contact inconnu : {status!r} (attendu {COMPANY_CONTACT_STATUSES})"
        )
    existing = get_contact(connection, account_id=account_id, company_key=company_key)
    contacted_at = existing.contacted_at if existing is not None else None
    if contacted_at is None and status in {"contacted", "replied"}:
        contacted_at = now
    values = {
        "account_id": account_id,
        "company_key": company_key,
        "status": status,
        "contacted_at": contacted_at,
        "created_at": now,
        "updated_at": now,
    }
    row = upsert_returning(
        connection,
        company_contact,
        values,
        index_elements=[company_contact.c.account_id, company_contact.c.company_key],
        update_values={"status": status, "contacted_at": contacted_at, "updated_at": now},
        returning=(
            company_contact.c.account_id,
            company_contact.c.company_key,
            company_contact.c.status,
            company_contact.c.contacted_at,
            company_contact.c.updated_at,
        ),
    )
    return _contact_row(row)


def mark_contacted_if_pending(
    connection: sa.Connection, *, account_id: str, company_key: str, now: dt.datetime
) -> bool:
    """Fait avancer une entreprise EN ATTENTE vers `contacted`. Jamais de recul.

    Une entreprise déjà `contacted` ou `replied` n'est pas rétrogradée par un
    signal marqué contacté après coup : l'action la plus avancée l'emporte.
    """
    existing = get_contact(connection, account_id=account_id, company_key=company_key)
    if existing is not None and existing.status != "to_contact":
        return False
    set_contact(
        connection,
        account_id=account_id,
        company_key=company_key,
        status="contacted",
        now=now,
    )
    return True


@dataclasses.dataclass(frozen=True)
class StoredCompanyNote:
    account_id: str
    company_key: str
    body: str
    updated_at: dt.datetime


def get_note(
    connection: sa.Connection, *, account_id: str, company_key: str
) -> StoredCompanyNote | None:
    row = connection.execute(
        sa.select(company_note).where(
            company_note.c.account_id == account_id,
            company_note.c.company_key == company_key,
        )
    ).first()
    if row is None:
        return None
    return StoredCompanyNote(row.account_id, row.company_key, row.body, aware_datetime(row.updated_at))


def put_note(
    connection: sa.Connection,
    *,
    account_id: str,
    company_key: str,
    body: str,
    now: dt.datetime,
) -> StoredCompanyNote | None:
    """Un corps vide (ou blanc) supprime la note et rend `None`."""
    if not body.strip():
        connection.execute(
            sa.delete(company_note).where(
                company_note.c.account_id == account_id,
                company_note.c.company_key == company_key,
            )
        )
        return None
    values = {
        "account_id": account_id,
        "company_key": company_key,
        "body": body,
        "created_at": now,
        "updated_at": now,
    }
    row = upsert_returning(
        connection,
        company_note,
        values,
        index_elements=[company_note.c.account_id, company_note.c.company_key],
        update_values={"body": body, "updated_at": now},
        returning=(
            company_note.c.account_id,
            company_note.c.company_key,
            company_note.c.body,
            company_note.c.updated_at,
        ),
    )
    return StoredCompanyNote(row.account_id, row.company_key, row.body, aware_datetime(row.updated_at))


__all__ = [
    "InvalidContactStatus",
    "StoredCompanyContact",
    "StoredCompanyNote",
    "contacts_by_company",
    "get_contact",
    "get_note",
    "mark_contacted_if_pending",
    "put_note",
    "set_contact",
]
