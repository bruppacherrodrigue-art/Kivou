"""One private user-entered contact, with CAS and deletion tombstones.

This module has no provider, directory-write or email-sending dependency.
"""

from __future__ import annotations

import datetime as dt
from typing import Self

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from signals.billing.service import aware_datetime
from signals.client_value.capabilities import usable_phone
from signals.engagement.prospecting_schema import company_manual_contact as contacts
from signals.persistence.conflicts import _conflict_insert


class ManualContactWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    role: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    expected_revision: int = Field(ge=0, strict=True)

    @field_validator("role", "email", "phone", mode="before")
    @classmethod
    def empty_optional(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("phone")
    @classmethod
    def phone_is_usable(cls, value):
        if value is not None and usable_phone(value) is None:
            raise ValueError("renseignez un numéro de téléphone complet")
        return value

    @model_validator(mode="after")
    def reachable(self) -> Self:
        if self.email is None and self.phone is None:
            raise ValueError("renseignez un email ou un téléphone")
        return self


class ContactConflict(ValueError):
    def __init__(self, current: dict):
        super().__init__("manual_contact_conflict")
        self.current = current


def _view(row) -> dict:
    return {
        "contact": None
        if row is None or row["deleted_at"]
        else {key: row[key] for key in ("name", "role", "email", "phone", "source")},
        "revision": row["revision"] if row else 0,
        "updated_at": aware_datetime(row["updated_at"]).isoformat() if row else None,
    }


def get_contact(connection, *, account_id: str, company_key: str) -> dict:
    row = (
        connection.execute(
            sa.select(contacts).where(
                contacts.c.account_id == account_id,
                contacts.c.company_key == company_key,
            )
        )
        .mappings()
        .one_or_none()
    )
    return _view(row)


def _write(connection, *, account_id, company_key, expected_revision, values, now):
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("invalid contact revision")
    scope = sa.and_(contacts.c.account_id == account_id, contacts.c.company_key == company_key)
    if expected_revision == 0:
        statement = (
            _conflict_insert(connection, contacts)
            .values(
                account_id=account_id,
                company_key=company_key,
                created_at=now,
                updated_at=now,
                revision=1,
                source="user",
                **values,
            )
            .on_conflict_do_nothing(index_elements=[contacts.c.account_id, contacts.c.company_key])
        )
    else:
        statement = (
            sa.update(contacts)
            .where(scope, contacts.c.revision == expected_revision)
            .values(
                updated_at=now,
                revision=contacts.c.revision + 1,
                **values,
            )
        )
    row = connection.execute(statement.returning(*contacts.c)).mappings().one_or_none()
    if row is None:
        raise ContactConflict(
            get_contact(connection, account_id=account_id, company_key=company_key)
        )
    return _view(row)


def put_contact(
    connection, *, account_id: str, company_key: str, payload: ManualContactWrite, now: dt.datetime
) -> dict:
    return _write(
        connection,
        account_id=account_id,
        company_key=company_key,
        expected_revision=payload.expected_revision,
        now=now,
        values={**payload.model_dump(exclude={"expected_revision"}), "deleted_at": None},
    )


def delete_contact(
    connection, *, account_id: str, company_key: str, expected_revision: int, now: dt.datetime
) -> dict:
    return _write(
        connection,
        account_id=account_id,
        company_key=company_key,
        expected_revision=expected_revision,
        now=now,
        values={"name": None, "role": None, "email": None, "phone": None, "deleted_at": now},
    )
