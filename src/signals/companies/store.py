"""SQLAlchemy Core persistence for opaque SaaS company identities."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from signals.companies.contracts import CompanyOfficialIdentity
from signals.companies.identity import IdentityMethod, ResolvedOfficialCompany, company_key
from signals.companies.schema import saas_company


@dataclass(frozen=True)
class StoredCompany:
    company_key: str
    identity_fingerprint: str
    identity_method: IdentityMethod
    identity_validation: dict[str, str]
    source_award_key: str
    origin_signal_key: str
    official_identity: CompanyOfficialIdentity
    created_at: dt.datetime
    updated_at: dt.datetime


@dataclass(frozen=True)
class CompanyCandidate:
    resolved: ResolvedOfficialCompany
    source_award_key: str
    origin_signal_key: str


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def _stored(row: RowMapping) -> StoredCompany:
    observed_at = _aware(row["official_observed_at"])
    return StoredCompany(
        company_key=row["company_key"],
        identity_fingerprint=row["identity_fingerprint"],
        identity_method=IdentityMethod(row["identity_method"]),
        identity_validation=dict(row["identity_validation"]),
        source_award_key=row["source_award_key"],
        origin_signal_key=row["origin_signal_key"],
        official_identity=CompanyOfficialIdentity(
            name=row["official_name"],
            country=row["official_country"],
            address=row["official_address"],
            identifiers=tuple(row["official_identifiers"]),
            website_url=row["official_website_url"],
            observed_at=observed_at,
        ),
        created_at=_aware(row["created_at"]),
        updated_at=_aware(row["updated_at"]),
    )


def _by_fingerprint(connection: sa.Connection, fingerprint: str) -> StoredCompany | None:
    row = connection.execute(
        sa.select(saas_company).where(saas_company.c.identity_fingerprint == fingerprint)
    ).mappings().one_or_none()
    return None if row is None else _stored(row)


def _by_fingerprints(
    connection: sa.Connection,
    fingerprints: tuple[str, ...],
) -> dict[str, StoredCompany]:
    if not fingerprints:
        return {}
    rows = connection.execute(
        sa.select(saas_company).where(
            saas_company.c.identity_fingerprint.in_(fingerprints),
        )
    ).mappings()
    return {
        stored.identity_fingerprint: stored
        for stored in (_stored(row) for row in rows)
    }


def get_company_by_key(connection: sa.Connection, *, company_key: str) -> StoredCompany | None:
    row = connection.execute(
        sa.select(saas_company).where(saas_company.c.company_key == company_key)
    ).mappings().one_or_none()
    return None if row is None else _stored(row)


def _candidate_values(candidate: CompanyCandidate, *, now: dt.datetime) -> dict[str, object]:
    resolved = candidate.resolved
    official = resolved.official
    return {
        "company_key": company_key(),
        "identity_fingerprint": resolved.identity_fingerprint,
        "identity_method": resolved.identity_method.value,
        "identity_validation": resolved.validation_evidence,
        "source_award_key": candidate.source_award_key,
        "origin_signal_key": candidate.origin_signal_key,
        "official_name": official.name,
        "official_country": official.country,
        "official_address": official.address,
        "official_identifiers": [
            identifier.model_dump(mode="json") for identifier in official.identifiers
        ],
        "official_website_url": official.website_url,
        "official_observed_at": official.observed_at,
        "created_at": now,
        "updated_at": now,
    }


def get_or_create_companies(
    connection: sa.Connection,
    *,
    candidates: tuple[CompanyCandidate, ...],
    now: dt.datetime,
) -> dict[str, StoredCompany]:
    """Converge one bounded candidate set with one insert and one read."""
    unique = {
        candidate.resolved.identity_fingerprint: candidate
        for candidate in candidates
    }
    if not unique:
        return {}
    fingerprints = tuple(sorted(unique))
    values = [
        _candidate_values(unique[fingerprint], now=now)
        for fingerprint in fingerprints
    ]
    if connection.dialect.name == "postgresql":
        statement = postgresql_insert(saas_company).on_conflict_do_nothing(
            index_elements=[saas_company.c.identity_fingerprint],
        )
    elif connection.dialect.name == "sqlite":
        statement = sqlite_insert(saas_company).on_conflict_do_nothing(
            index_elements=[saas_company.c.identity_fingerprint],
        )
    else:  # pragma: no cover - supported runtimes are PostgreSQL and SQLite
        raise RuntimeError("unsupported company store dialect")
    connection.execute(statement, values)
    stored = _by_fingerprints(connection, fingerprints)
    if len(stored) != len(unique):  # pragma: no cover - insert/select invariant
        raise RuntimeError("company batch could not be read")
    return stored


def get_or_create_company(
    connection: sa.Connection,
    *,
    resolved: ResolvedOfficialCompany,
    source_award_key: str,
    origin_signal_key: str,
    now: dt.datetime,
) -> StoredCompany:
    """Create once by exact fingerprint and converge safely after a concurrent insert."""
    existing = _by_fingerprint(connection, resolved.identity_fingerprint)
    if existing is not None:
        return existing

    values = _candidate_values(
        CompanyCandidate(
            resolved=resolved,
            source_award_key=source_award_key,
            origin_signal_key=origin_signal_key,
        ),
        now=now,
    )
    try:
        with connection.begin_nested():
            connection.execute(sa.insert(saas_company).values(**values))
    except IntegrityError:
        concurrent = _by_fingerprint(connection, resolved.identity_fingerprint)
        if concurrent is None:  # pragma: no cover - a non-fingerprint integrity defect
            raise
        return concurrent

    created = _by_fingerprint(connection, resolved.identity_fingerprint)
    if created is None:  # pragma: no cover - insert/select invariant
        raise RuntimeError("created company could not be read")
    return created
