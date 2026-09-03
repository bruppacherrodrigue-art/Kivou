"""Le suivi commercial PAR ENTREPRISE — un compte, une entreprise, un statut.

PR1 §4 — un signal se juge un par un (`engagement/feedback.py`), mais une
démarche commerciale vise une ENTREPRISE : plusieurs signaux d'un même
attributaire ne racontent pas plusieurs démarches.

`contacted_at` est posé à CHAQUE passage en `contacted` depuis `to_contact`
(un nouveau cycle de prospection), conservé par `replied` (qui ne fait que
confirmer le cycle en cours), et jamais remis à nul par `to_contact` — reculer
le statut dit « je dois relancer », pas « je n'ai jamais appelé ». Un aller-
retour `contacted → to_contact → contacted` REFRAÎCHIT donc la date : c'est un
nouveau cycle, pas la poursuite du précédent.
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


def _upsert_contact(
    connection: sa.Connection,
    *,
    account_id: str,
    company_key: str,
    status: str,
    now: dt.datetime,
) -> StoredCompanyContact:
    """The one write, with `contacted_at` computed IN SQL — no read-then-write race.

    An app-level `existing = get_contact(...)` read, held in Python while a
    concurrent request writes the same row, would let two callers compute
    `contacted_at` from the same stale snapshot. Instead, the `to_contact`→
    `contacted` case is expressed as a `CASE` against the row's OWN current
    `status` column, evaluated by the database at write time — there is
    nothing to race, because there is no intermediate read to go stale.

    - entering `contacted` FROM `to_contact` (or absent) is a NEW cycle:
      `contacted_at` becomes `now`, even if a stale cycle had already set it.
    - entering `contacted` from anywhere else (already `contacted`, or
      `replied`) is not a new cycle: the existing value is kept, defaulting
      to `now` only if none exists yet.
    - `to_contact` and `replied` never move `contacted_at` forward; `replied`
      only fills it in if it was somehow still empty.
    """
    if status == "contacted":
        contacted_at_on_conflict = sa.case(
            (company_contact.c.status == "to_contact", now),
            else_=sa.func.coalesce(company_contact.c.contacted_at, now),
        )
    else:
        contacted_at_on_conflict = sa.func.coalesce(
            company_contact.c.contacted_at, now if status == "replied" else None
        )
    values = {
        "account_id": account_id,
        "company_key": company_key,
        "status": status,
        # First row for this company: nothing to race against yet.
        "contacted_at": now if status in {"contacted", "replied"} else None,
        "created_at": now,
        "updated_at": now,
    }
    row = upsert_returning(
        connection,
        company_contact,
        values,
        index_elements=[company_contact.c.account_id, company_contact.c.company_key],
        update_values={
            "status": status,
            "contacted_at": contacted_at_on_conflict,
            "updated_at": now,
        },
        returning=(
            company_contact.c.account_id,
            company_contact.c.company_key,
            company_contact.c.status,
            company_contact.c.contacted_at,
            company_contact.c.updated_at,
        ),
    )
    return _contact_row(row)


def set_contact(
    connection: sa.Connection,
    *,
    account_id: str,
    company_key: str,
    status: str,
    now: dt.datetime,
) -> StoredCompanyContact:
    """Upsert du statut choisi par le client. Voir `_upsert_contact` pour `contacted_at`."""
    if status not in COMPANY_CONTACT_STATUSES:
        raise InvalidContactStatus(
            f"statut de contact inconnu : {status!r} (attendu {COMPANY_CONTACT_STATUSES})"
        )
    return _upsert_contact(
        connection, account_id=account_id, company_key=company_key, status=status, now=now
    )


def mark_contacted_if_pending(
    connection: sa.Connection, *, account_id: str, company_key: str, now: dt.datetime
) -> bool:
    """Fait avancer une entreprise EN ATTENTE vers `contacted`. Jamais de recul.

    Une entreprise déjà `contacted` ou `replied` n'est pas rétrogradée par un
    signal marqué contacté après coup : l'action la plus avancée l'emporte.
    Une seule lecture ici pour décider — `_upsert_contact` n'en refait pas une
    seconde, `contacted_at` s'y calcule en SQL (voir sa docstring).
    """
    existing = get_contact(connection, account_id=account_id, company_key=company_key)
    if existing is not None and existing.status != "to_contact":
        return False
    _upsert_contact(
        connection, account_id=account_id, company_key=company_key, status="contacted", now=now
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
