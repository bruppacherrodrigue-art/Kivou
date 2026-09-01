"""Explicit worker for exact winner facts already stored by Kivou.

There is intentionally no scheduler, connector or network client in this
module.  Operators may invoke ``run_winner_enrichment_batch`` from a separate
job; HTTP GET handlers only call the batched read function.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from signals.companies.contracts import (
    WinnerEnrichmentSource,
    WinnerEnrichmentView,
    safe_https_url,
)
from signals.companies.indexing import index_signal_company_identity
from signals.companies.schema import saas_company, winner_enrichment_job
from signals.companies.store import get_or_create_company
from signals.persistence.schema import contract_award, materialized_signal, source_event

MAX_ENRICHMENT_ATTEMPTS = 3
MAX_ENRICHMENT_BATCH = 250
_WORKER_REF = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_UNRESOLVED = "winner_identity_unresolved"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WinnerEnrichmentBatch:
    processed: int
    completed: int
    partial: int
    failed: int


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def enqueue_winner_enrichment(
    connection: sa.Connection, *, signal_key: str, now: dt.datetime
) -> None:
    """Queue once, resetting only when the exact identity fingerprint changes."""

    fingerprint = connection.scalar(
        sa.select(materialized_signal.c.company_identity_fingerprint).where(
            materialized_signal.c.signal_key == signal_key
        )
    )
    values = {
        "signal_key": signal_key,
        "identity_fingerprint": fingerprint,
        "status": "pending",
        "attempt_count": 0,
        "error_code": None,
        "claimed_by": None,
        "queued_at": now,
        "started_at": None,
        "finished_at": None,
        "updated_at": now,
    }
    if connection.dialect.name == "postgresql":
        statement = postgresql_insert(winner_enrichment_job).values(**values)
    elif connection.dialect.name == "sqlite":
        statement = sqlite_insert(winner_enrichment_job).values(**values)
    else:  # pragma: no cover - supported runtimes are PostgreSQL and SQLite
        raise RuntimeError("unsupported winner-enrichment dialect")
    excluded = statement.excluded
    statement = statement.on_conflict_do_update(
        index_elements=[winner_enrichment_job.c.signal_key],
        set_={
            "identity_fingerprint": excluded.identity_fingerprint,
            "status": "pending",
            "attempt_count": 0,
            "error_code": None,
            "claimed_by": None,
            "queued_at": excluded.queued_at,
            "started_at": None,
            "finished_at": None,
            "updated_at": excluded.updated_at,
        },
        where=winner_enrichment_job.c.identity_fingerprint.is_distinct_from(
            excluded.identity_fingerprint
        ),
    )
    connection.execute(statement)


def _claim(
    connection: sa.Connection,
    *,
    now: dt.datetime,
    worker_ref: str,
    limit: int,
    retry_failed: bool,
) -> tuple[str, ...]:
    eligible = winner_enrichment_job.c.status == "pending"
    if retry_failed:
        eligible = sa.or_(
            eligible,
            sa.and_(
                winner_enrichment_job.c.status == "failed",
                winner_enrichment_job.c.attempt_count < MAX_ENRICHMENT_ATTEMPTS,
            ),
        )
    select_keys = (
        sa.select(winner_enrichment_job.c.signal_key)
        .where(eligible)
        .order_by(winner_enrichment_job.c.queued_at, winner_enrichment_job.c.signal_key)
        .limit(limit)
    )
    if connection.dialect.name == "postgresql":
        select_keys = select_keys.with_for_update(skip_locked=True)
    candidates = tuple(connection.execute(select_keys).scalars())
    claimed: list[str] = []
    for signal_key in candidates:
        condition = winner_enrichment_job.c.status == "pending"
        if retry_failed:
            condition = sa.or_(
                condition,
                sa.and_(
                    winner_enrichment_job.c.status == "failed",
                    winner_enrichment_job.c.attempt_count < MAX_ENRICHMENT_ATTEMPTS,
                ),
            )
        result = connection.execute(
            sa.update(winner_enrichment_job)
            .where(
                winner_enrichment_job.c.signal_key == signal_key,
                condition,
            )
            .values(
                status="in_progress",
                attempt_count=winner_enrichment_job.c.attempt_count + 1,
                error_code=None,
                claimed_by=worker_ref,
                started_at=now,
                finished_at=None,
                updated_at=now,
            )
        )
        if result.rowcount == 1:
            claimed.append(signal_key)
    return tuple(claimed)


def _is_complete(official: Any, identity_method: str) -> bool:
    return bool(
        official.name
        and official.country
        and official.address
        and official.website_url
        and identity_method in {"official_identifier", "official_domain"}
    )


def _finish(
    connection: sa.Connection,
    *,
    signal_key: str,
    status: str,
    now: dt.datetime,
    fingerprint: str | None,
    error_code: str | None = None,
) -> None:
    connection.execute(
        sa.update(winner_enrichment_job)
        .where(
            winner_enrichment_job.c.signal_key == signal_key,
            winner_enrichment_job.c.status == "in_progress",
        )
        .values(
            identity_fingerprint=fingerprint,
            status=status,
            error_code=error_code,
            finished_at=now,
            updated_at=now,
        )
    )
    logger.info(
        "winner_enrichment_finished",
        extra={
            "signal_key": signal_key,
            "winner_enrichment_status": status,
            "winner_enrichment_error_code": error_code,
        },
    )


def run_winner_enrichment_batch(
    connection: sa.Connection,
    *,
    now: dt.datetime,
    worker_ref: str,
    limit: int = 100,
    retry_failed: bool = False,
) -> WinnerEnrichmentBatch:
    """Project a bounded batch from database facts; never start automatically."""

    if not 1 <= limit <= MAX_ENRICHMENT_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_ENRICHMENT_BATCH}")
    if _WORKER_REF.fullmatch(worker_ref) is None:
        raise ValueError("worker_ref must be an opaque identifier of at most 64 characters")
    claimed = _claim(
        connection,
        now=now,
        worker_ref=worker_ref,
        limit=limit,
        retry_failed=retry_failed,
    )
    counts = {"completed": 0, "partial": 0, "failed": 0}
    for signal_key in claimed:
        indexed = index_signal_company_identity(connection, signal_key=signal_key)
        if indexed is None:
            _finish(
                connection,
                signal_key=signal_key,
                status="failed",
                now=now,
                fingerprint=None,
                error_code=_UNRESOLVED,
            )
            counts["failed"] += 1
            continue
        stored = get_or_create_company(
            connection,
            resolved=indexed.resolved,
            source_award_key=indexed.source_award_key,
            origin_signal_key=signal_key,
            now=now,
        )
        status = (
            "completed"
            if _is_complete(stored.official_identity, stored.identity_method.value)
            else "partial"
        )
        _finish(
            connection,
            signal_key=signal_key,
            status=status,
            now=now,
            fingerprint=stored.identity_fingerprint,
        )
        counts[status] += 1
    return WinnerEnrichmentBatch(
        processed=len(claimed),
        completed=counts["completed"],
        partial=counts["partial"],
        failed=counts["failed"],
    )


def _safe_source_url(value: str | None) -> str | None:
    try:
        return safe_https_url(value)
    except ValueError:
        return None


def _missing(row: sa.RowMapping) -> tuple[str, ...]:
    if row["company_key"] is None:
        return (
            "official_identity",
            "country",
            "address",
            "identifier_or_domain",
            "website",
        )
    missing: list[str] = []
    if not row["official_country"]:
        missing.append("country")
    if not row["official_address"]:
        missing.append("address")
    if row["identity_method"] not in {"official_identifier", "official_domain"}:
        missing.append("identifier_or_domain")
    if not row["official_website_url"]:
        missing.append("website")
    return tuple(missing)


def winner_enrichments_for_signals(
    connection: sa.Connection, *, signal_keys: tuple[str, ...]
) -> dict[str, WinnerEnrichmentView]:
    """Read all states and their safe public source with one SQL statement."""

    if not signal_keys:
        return {}
    if len(signal_keys) > MAX_ENRICHMENT_BATCH:
        raise ValueError(f"at most {MAX_ENRICHMENT_BATCH} signal keys can be read")
    source_award = contract_award.alias("winner_source_award")
    source_notice = source_event.alias("winner_source_notice")
    rows = connection.execute(
        sa.select(
            winner_enrichment_job,
            saas_company.c.company_key,
            saas_company.c.identity_method,
            saas_company.c.official_country,
            saas_company.c.official_address,
            saas_company.c.official_website_url,
            saas_company.c.official_observed_at,
            source_notice.c.source_system,
            source_notice.c.source_notice_id,
            source_notice.c.source_url,
            source_notice.c.discovered_at,
        )
        .select_from(
            winner_enrichment_job.join(
                materialized_signal,
                winner_enrichment_job.c.signal_key == materialized_signal.c.signal_key,
            )
            .outerjoin(
                saas_company,
                winner_enrichment_job.c.identity_fingerprint
                == saas_company.c.identity_fingerprint,
            )
            .join(
                source_award,
                source_award.c.award_key
                == sa.func.coalesce(
                    saas_company.c.source_award_key,
                    materialized_signal.c.materialization_award_key,
                ),
            )
            .join(
                source_notice,
                source_notice.c.event_key == source_award.c.event_key,
            )
        )
        .where(winner_enrichment_job.c.signal_key.in_(signal_keys))
    ).mappings()
    return {
        row["signal_key"]: WinnerEnrichmentView(
            status=row["status"],
            missing_fields=_missing(row),
            last_verified_at=_aware(
                row["official_observed_at"] or row["finished_at"]
            ),
            error_code=row["error_code"],
            source=WinnerEnrichmentSource(
                connector=row["source_system"],
                notice_id=row["source_notice_id"],
                url=_safe_source_url(row["source_url"]),
                retrieved_at=_aware(row["discovered_at"]),
            ),
        )
        for row in rows
    }


__all__ = [
    "MAX_ENRICHMENT_ATTEMPTS",
    "WinnerEnrichmentBatch",
    "enqueue_winner_enrichment",
    "run_winner_enrichment_batch",
    "winner_enrichments_for_signals",
]
