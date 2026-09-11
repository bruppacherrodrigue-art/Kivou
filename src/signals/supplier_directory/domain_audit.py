"""Audit confirmed supplier domains against the central rejection policy."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence

import sqlalchemy as sa
from pydantic import Field
from sqlalchemy.engine import Engine

from signals.company_research.domain import rejected_supplier_domain
from signals.founder_api.contracts import FounderContract
from signals.persistence.database import create_database_engine, resolve_database_url
from signals.persistence.schema import (
    prospect_send_request,
    prospect_target,
    supplier_directory,
)
from signals.supplier_directory.store import SupplierDirectoryStore

_REVERIFICATION_REASON = "blocked_domain_audit"
_AUDIT_COLUMNS = (
    supplier_directory.c.siren,
    supplier_directory.c.domain,
    supplier_directory.c.legal_name,
    supplier_directory.c.domain_validation_method,
    supplier_directory.c.suppressed_at,
)


class DomainAuditConflict(RuntimeError):
    """The selected directory state changed or is in an active send."""

    def __init__(self) -> None:
        super().__init__("domain audit conflict")


class BlockedDomainRecord(FounderContract):
    siren: str
    domain: str
    legal_name: str


class DomainAuditResult(FounderContract):
    examined_count: int = Field(ge=0)
    affected_count: int = Field(ge=0)
    modified_count: int = Field(ge=0)
    affected: tuple[BlockedDomainRecord, ...]


def _confirmed_active_domains(connection: sa.Connection) -> tuple[sa.RowMapping, ...]:
    statement = (
        sa.select(*_AUDIT_COLUMNS)
        .where(
            supplier_directory.c.suppressed_at.is_(None),
            supplier_directory.c.domain.is_not(None),
            supplier_directory.c.domain_validation_method.is_not(None),
        )
        .order_by(
            supplier_directory.c.siren,
            supplier_directory.c.domain,
            supplier_directory.c.legal_name,
        )
    )
    return tuple(connection.execute(statement).mappings())


def _locked_candidate_domains(
    connection: sa.Connection, candidate_sirens: Sequence[str]
) -> tuple[sa.RowMapping, ...]:
    statement = (
        sa.select(*_AUDIT_COLUMNS)
        .where(supplier_directory.c.siren.in_(tuple(sorted(candidate_sirens))))
        .order_by(supplier_directory.c.siren)
        .with_for_update(nowait=True)
    )
    return tuple(connection.execute(statement).mappings())


def _affected_domains(rows: tuple[sa.RowMapping, ...]) -> tuple[BlockedDomainRecord, ...]:
    return tuple(
        BlockedDomainRecord(
            siren=str(row["siren"]),
            domain=str(row["domain"]),
            legal_name=str(row["legal_name"]),
        )
        for row in rows
        if rejected_supplier_domain(str(row["domain"]))
    )


def _candidate_state_matches(
    locked_rows: tuple[sa.RowMapping, ...],
    affected: tuple[BlockedDomainRecord, ...],
) -> bool:
    if len(locked_rows) != len(affected):
        return False
    locked_by_siren = {str(row["siren"]): row for row in locked_rows}
    for candidate in affected:
        row = locked_by_siren.get(candidate.siren)
        if row is None:
            return False
        domain = row["domain"]
        if not (
            row["suppressed_at"] is None
            and row["domain_validation_method"] is not None
            and domain is not None
            and str(domain).casefold() == candidate.domain.casefold()
            and rejected_supplier_domain(str(domain))
        ):
            return False
    return True


def _started_send_exists(
    connection: sa.Connection, affected: tuple[BlockedDomainRecord, ...]
) -> bool:
    if not affected:
        return False
    return bool(
        connection.scalar(
            sa.select(sa.literal(1))
            .select_from(
                prospect_target.join(
                    prospect_send_request,
                    prospect_target.c.send_request_id == prospect_send_request.c.request_id,
                )
            )
            .where(
                prospect_target.c.siren.in_(row.siren for row in affected),
                prospect_send_request.c.status == "started",
            )
            .limit(1)
        )
    )


def audit_confirmed_domains(
    engine: Engine,
    *,
    observed_at: dt.datetime,
    apply: bool = False,
) -> DomainAuditResult:
    """Report or quarantine active confirmed domains rejected by current policy."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    if not apply:
        with engine.connect() as connection:
            rows = _confirmed_active_domains(connection)
        affected = _affected_domains(rows)
        return DomainAuditResult(
            examined_count=len(rows),
            affected_count=len(affected),
            modified_count=0,
            affected=affected,
        )

    with engine.begin() as connection:
        rows = _confirmed_active_domains(connection)
        affected = _affected_domains(rows)
        if affected:
            locked_rows = _locked_candidate_domains(
                connection,
                tuple(row.siren for row in affected),
            )
            if not _candidate_state_matches(locked_rows, affected):
                raise DomainAuditConflict()
        if _started_send_exists(connection, affected):
            raise DomainAuditConflict()
        store = SupplierDirectoryStore(engine)
        for row in affected:
            modified = store.mark_for_reverification(
                row.siren,
                reason=_REVERIFICATION_REASON,
                observed_at=observed_at,
                expected_domain=row.domain,
                connection=connection,
            )
            if not modified:
                raise DomainAuditConflict()
    return DomainAuditResult(
        examined_count=len(rows),
        affected_count=len(affected),
        modified_count=len(affected),
        affected=affected,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m signals.supplier_directory.domain_audit"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="quarantine les domaines confirmés bloqués",
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = _parser().parse_args(arguments)
    try:
        engine = create_database_engine(resolve_database_url())
    except (ImportError, OSError, RuntimeError, TypeError, ValueError, sa.exc.SQLAlchemyError):
        print("configuration_invalid", file=sys.stderr)
        return 2
    try:
        result = audit_confirmed_domains(
            engine,
            observed_at=dt.datetime.now(dt.UTC),
            apply=parsed.apply,
        )
    except (OSError, RuntimeError, TypeError, ValueError, sa.exc.SQLAlchemyError):
        print("domain_audit_failed", file=sys.stderr)
        return 4
    finally:
        engine.dispose()
    print(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())


__all__ = [
    "BlockedDomainRecord",
    "DomainAuditConflict",
    "DomainAuditResult",
    "audit_confirmed_domains",
    "main",
]
