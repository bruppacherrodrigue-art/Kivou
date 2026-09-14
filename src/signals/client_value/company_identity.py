"""Exact public identity, lossless and account-specific private reconciliation.

Historical rows remain in place. Resolved aliases read/write the copied subject;
conflicting private values remain isolated, with a durable account-local reason.
No name, address or department is an identity proof for private work.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
from collections.abc import Iterable, Mapping

import sqlalchemy as sa

from signals.accounts.schema import account
from signals.engagement.prospecting_schema import (
    account_company_alias_override as overrides,
)
from signals.engagement.prospecting_schema import (
    account_company_membership,
    company_manual_contact,
)
from signals.engagement.prospecting_schema import (
    company_subject_alias as aliases,
)
from signals.engagement.schema import company_contact, company_note
from signals.persistence.conflicts import insert_if_absent

_IDENTITY_MUTEX_KEY = 0x4B49564F55494431


def _lock_identity_transaction(connection: sa.Connection) -> None:
    # Quarantining any group member and copying its private values must share
    # one transaction boundary. Acquire before alias/account row locks; one
    # reentrant mutex also prevents opposing multi-group audit lock orders.
    # No network work belongs in this scope.
    if connection.dialect.name == "sqlite":
        # Legacy sqlite3 SELECTs need not begin a real transaction. A no-op
        # write takes the database write lock before reading the alias group,
        # including when resolve_subject is called without register_alias first.
        connection.execute(
            aliases.update().where(sa.false()).values(alias_company_key=aliases.c.alias_company_key)
        )
        return
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _IDENTITY_MUTEX_KEY},
        )


@dataclasses.dataclass(frozen=True)
class CompanySubject:
    company_key: str
    canonical_company_key: str
    private_subject_key: str
    resolution: str


def _luhn(value: str) -> bool:
    total = 0
    for index, digit in enumerate(reversed(value)):
        number = int(digit) * (2 if index % 2 else 1)
        total += number - 9 if number > 9 else number
    return total % 10 == 0


def exact_french_siren(identifiers: Iterable, *, country: str | None) -> str | None:
    if country not in (None, "FR"):
        return None
    candidates = set()
    for identifier in identifiers or ():
        value = identifier.get("value") if isinstance(identifier, Mapping) else identifier.value
        scheme = (
            identifier.get("scheme", "") if isinstance(identifier, Mapping) else identifier.scheme
        )
        if not isinstance(value, str) or not re.fullmatch(r"[0-9\s]+", value):
            continue
        digits = re.sub(r"\s", "", value)
        kind = str(scheme).casefold()
        if kind == "siren" and len(digits) == 9 and _luhn(digits):
            candidates.add(digits)
        elif kind in ("siret", "boamp-company-id") and len(digits) == 14:
            # La Poste's documented SIRET exception still requires the exact legal SIREN.
            valid = _luhn(digits) or (digits[:9] == "356000000" and sum(map(int, digits)) % 5 == 0)
            if valid and _luhn(digits[:9]):
                candidates.add(digits[:9])
    return next(iter(candidates)) if len(candidates) == 1 else None


def register_alias(
    connection: sa.Connection, *, company_key: str, siren: str, now: dt.datetime
) -> str:
    if exact_french_siren([{"scheme": "siren", "value": siren}], country="FR") is None:
        return company_key
    _lock_identity_transaction(connection)
    canonical = f"cmp_directory_{siren}"
    for key in (company_key, canonical):
        insert_if_absent(
            connection,
            aliases,
            {
                "alias_company_key": key,
                "canonical_company_key": canonical,
                "identifier_type": "siren",
                "identifier_value": siren,
                "provenance": "exact_official_identifier",
                "resolution_status": "exact",
                "created_at": now,
                "updated_at": now,
            },
        )
    # Preserve the original proof, but quarantine it on contradiction. An old
    # account override must never keep routing private work to another company.
    binding = (
        connection.execute(
            sa.select(aliases).where(aliases.c.alias_company_key == company_key).with_for_update()
        )
        .mappings()
        .one()
    )
    if binding["canonical_company_key"] != canonical:
        connection.execute(
            aliases.update()
            .where(aliases.c.alias_company_key == company_key)
            .values(
                resolution_status="unresolved",
                updated_at=now,
            )
        )
        return company_key
    # Quarantine is durable: a later observation alone cannot adjudicate it.
    return canonical if binding["resolution_status"] == "exact" else company_key


def register_known_aliases(connection: sa.Connection, *, now: dt.datetime) -> int:
    from signals.companies.schema import saas_company

    count = 0
    for row in connection.execute(sa.select(saas_company)).mappings():
        siren = exact_french_siren(row["official_identifiers"], country=row["official_country"])
        if siren:
            register_alias(connection, company_key=row["company_key"], siren=siren, now=now)
            count += 1
    return count


def resolve_company_subject(
    connection: sa.Connection, *, account_id: str, company_key: str, now: dt.datetime
) -> CompanySubject:
    """Resolve an already access-checked company, registering its exact proof."""
    from signals.companies.schema import saas_company

    directory = re.fullmatch(r"cmp_directory_(\d{9})", company_key)
    siren = directory.group(1) if directory else None
    if siren is None:
        row = (
            connection.execute(
                sa.select(
                    saas_company.c.official_identifiers, saas_company.c.official_country
                ).where(
                    saas_company.c.company_key == company_key,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row:
            siren = exact_french_siren(row["official_identifiers"], country=row["official_country"])
    if siren:
        register_alias(connection, company_key=company_key, siren=siren, now=now)
    return resolve_subject(connection, account_id=account_id, company_key=company_key, now=now)


def _private_values(table, row):
    fields = {
        "company_note": ("body",),
        "company_contact": ("status", "contacted_at"),
        "company_manual_contact": ("name", "role", "email", "phone", "deleted_at"),
        "account_company_membership": (),
    }[table.name]
    return tuple(row[field] for field in fields)


def resolve_subject(
    connection: sa.Connection, *, account_id: str, company_key: str, now: dt.datetime
) -> CompanySubject:
    _lock_identity_transaction(connection)
    public = (
        connection.execute(
            sa.select(aliases)
            .where(
                aliases.c.alias_company_key == company_key,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if public is None or public["resolution_status"] != "exact":
        return CompanySubject(company_key, company_key, company_key, "unresolved")
    canonical = public["canonical_company_key"]
    # Serialize private migration/write, without blocking the KEY SHARE acquired
    # by an earlier workflow/event INSERT in a concurrent contacted transaction.
    # That transaction may itself be waiting for the identity mutex above.
    connection.execute(
        sa.select(account.c.account_id)
        .where(
            account.c.account_id == account_id,
        )
        .with_for_update(key_share=True)
    ).scalar_one()
    prior = (
        connection.execute(
            sa.select(overrides).where(
                overrides.c.account_id == account_id,
                overrides.c.alias_company_key == company_key,
            )
        )
        .mappings()
        .one_or_none()
    )
    if prior:
        return CompanySubject(company_key, canonical, prior["private_subject_key"], prior["mode"])
    keys = tuple(
        connection.execute(
            sa.select(aliases.c.alias_company_key).where(
                aliases.c.canonical_company_key == canonical,
                aliases.c.resolution_status == "exact",
            )
        ).scalars()
    )
    resolved = {
        row["alias_company_key"]: row
        for row in connection.execute(
            sa.select(overrides).where(
                overrides.c.account_id == account_id,
                overrides.c.alias_company_key.in_(keys),
            )
        ).mappings()
    }
    # Previously migrated historical copies must not become new conflicts.
    candidate_keys = tuple(key for key in keys if key not in resolved or key == canonical)
    tables = (company_note, company_contact, company_manual_contact, account_company_membership)
    rows_by_table = {
        table: list(
            connection.execute(
                sa.select(table).where(
                    table.c.account_id == account_id,
                    table.c.company_key.in_(candidate_keys),
                )
            ).mappings()
        )
        for table in tables
    }
    conflicting = any(
        len({_private_values(table, row) for row in rows}) > 1
        for table, rows in rows_by_table.items()
    )
    if not conflicting:
        for table, rows in rows_by_table.items():
            if rows:
                selected = max(rows, key=lambda row: row.get("revision", 1))
                insert_if_absent(connection, table, {**dict(selected), "company_key": canonical})
    for key in keys:
        if key in resolved:
            continue
        insert_if_absent(
            connection,
            overrides,
            {
                "account_id": account_id,
                "alias_company_key": key,
                "private_subject_key": key if conflicting else canonical,
                "mode": "isolated" if conflicting else "resolved",
                "reason": "legacy_private_values_conflict" if conflicting else "exact_identifier",
                "created_at": now,
                "updated_at": now,
            },
        )
    selected = (
        connection.execute(
            sa.select(overrides).where(
                overrides.c.account_id == account_id,
                overrides.c.alias_company_key == company_key,
            )
        )
        .mappings()
        .one()
    )
    return CompanySubject(company_key, canonical, selected["private_subject_key"], selected["mode"])
