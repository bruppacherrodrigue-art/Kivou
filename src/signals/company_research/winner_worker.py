"""Bounded selection for model enrichment of newly materialized winners."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import httpx
import sqlalchemy as sa

from signals.companies.active_scope import active_account_signal_exists
from signals.companies.enrichment import MAX_ENRICHMENT_ATTEMPTS, run_winner_enrichment_batch
from signals.companies.france import FrenchOfficialCompanyClient
from signals.companies.schema import winner_enrichment_job
from signals.company_research.company_requests import run_company_enrichment_requests
from signals.company_research.enrichment import (
    AnnuaireRawDirectorClient,
    CompanyEnrichmentInput,
    CompanyEnrichmentRunResult,
    CompanyEnrichmentService,
    CompanyWebCollector,
)
from signals.company_research.instance_lock import InstanceAlreadyRunning, exclusive_instance_lock
from signals.company_research.providers import company_enrichment_providers_from_environment
from signals.contact_discovery.deliverability import EmailMxVerifier
from signals.model_runtime.budget import DailyModelBudgetExhausted
from signals.persistence.database import create_database_engine
from signals.persistence.schema import contract_award, materialized_signal, source_event
from signals.supplier_directory.store import SupplierDirectoryStore
from signals.supplier_discovery.families import default_supplier_family_for_naf

MAX_WINNER_MODEL_BATCH = 100
RECENT_SIGNAL_WINDOW = dt.timedelta(days=30)


@dataclass(frozen=True)
class WinnerEnrichmentCandidate:
    signal_key: str
    holder_key: str


@dataclass(frozen=True)
class WinnerModelEnrichmentBatch:
    processed: int
    completed: int
    cached: int
    failed: int
    cost_usd: Decimal
    budget_usage: str | None = None


class WinnerCompanyEnrichmentService(Protocol):
    def enrich(
        self,
        siren: str,
        *,
        directors_raw: tuple[dict[str, object], ...] = (),
        force: bool = False,
    ) -> CompanyEnrichmentRunResult: ...


def _holder_key() -> sa.ColumnElement[str]:
    identifier = materialized_signal.c.winner_identifier_value
    return sa.case(
        (sa.func.length(identifier) == 14, sa.func.substr(identifier, 1, 9)),
        (sa.func.length(identifier) == 9, identifier),
        else_=sa.func.coalesce(
            materialized_signal.c.company_identity_fingerprint,
            winner_enrichment_job.c.identity_fingerprint,
            winner_enrichment_job.c.signal_key,
        ),
    )


def select_winner_enrichment_candidates(
    connection: sa.Connection,
    *,
    now: dt.datetime,
    activated_at: dt.datetime,
    limit: int = 25,
) -> tuple[WinnerEnrichmentCandidate, ...]:
    """Return one pending job per recent active holder after activation."""

    if now.tzinfo is None or activated_at.tzinfo is None:
        raise ValueError("winner enrichment clocks must be timezone-aware")
    if not 1 <= limit <= MAX_WINNER_MODEL_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_WINNER_MODEL_BATCH}")
    effective_date = sa.func.coalesce(
        contract_award.c.award_date,
        contract_award.c.contract_notification_date,
        source_event.c.published_on,
    )
    holder_key = _holder_key()
    ranked = (
        sa.select(
            winner_enrichment_job.c.signal_key.label("signal_key"),
            holder_key.label("holder_key"),
            sa.func.row_number()
            .over(
                partition_by=holder_key,
                order_by=(
                    winner_enrichment_job.c.queued_at,
                    winner_enrichment_job.c.signal_key,
                ),
            )
            .label("holder_rank"),
            winner_enrichment_job.c.queued_at.label("queued_at"),
        )
        .select_from(
            winner_enrichment_job.join(
                materialized_signal,
                winner_enrichment_job.c.signal_key == materialized_signal.c.signal_key,
            )
            .join(
                contract_award,
                materialized_signal.c.materialization_award_key == contract_award.c.award_key,
            )
            .join(source_event, contract_award.c.event_key == source_event.c.event_key)
        )
        .where(
            sa.or_(
                winner_enrichment_job.c.status == "pending",
                sa.and_(
                    winner_enrichment_job.c.status == "failed",
                    winner_enrichment_job.c.attempt_count < MAX_ENRICHMENT_ATTEMPTS,
                ),
            ),
            winner_enrichment_job.c.queued_at >= activated_at,
            active_account_signal_exists(winner_enrichment_job.c.signal_key),
            effective_date >= now.date() - RECENT_SIGNAL_WINDOW,
            effective_date <= now.date(),
        )
        .subquery("ranked_winner_enrichment")
    )
    rows = connection.execute(
        sa.select(ranked.c.signal_key, ranked.c.holder_key)
        .where(ranked.c.holder_rank == 1)
        .order_by(ranked.c.queued_at, ranked.c.signal_key)
        .limit(limit)
    )
    return tuple(
        WinnerEnrichmentCandidate(signal_key=row.signal_key, holder_key=row.holder_key)
        for row in rows
    )


def _siren_for_job(connection: sa.Connection, signal_key: str) -> str | None:
    row = connection.execute(
        sa.select(
            materialized_signal.c.winner_identifier_value,
            winner_enrichment_job.c.identity_fingerprint,
        )
        .select_from(
            winner_enrichment_job.join(
                materialized_signal,
                winner_enrichment_job.c.signal_key == materialized_signal.c.signal_key,
            )
        )
        .where(winner_enrichment_job.c.signal_key == signal_key)
    ).one_or_none()
    if row is None:
        return None
    identifier = str(row.winner_identifier_value or "").strip()
    if re.fullmatch(r"\d{14}", identifier):
        return identifier[:9]
    if re.fullmatch(r"\d{9}", identifier):
        return identifier
    from signals.companies.schema import saas_company

    identifiers = connection.scalar(
        sa.select(saas_company.c.official_identifiers).where(
            saas_company.c.identity_fingerprint == row.identity_fingerprint
        )
    )
    for item in identifiers or ():
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        scheme = str(item.get("scheme") or "").casefold()
        if scheme == "siret" and re.fullmatch(r"\d{14}", value):
            return value[:9]
        if scheme == "siren" and re.fullmatch(r"\d{9}", value):
            return value
    return None


def _mark_failed(engine: sa.Engine, *, signal_key: str, now: dt.datetime, error_code: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.update(winner_enrichment_job)
            .where(winner_enrichment_job.c.signal_key == signal_key)
            .values(
                status="failed",
                error_code=error_code,
                finished_at=now,
                updated_at=now,
            )
        )


def _return_to_pending(engine: sa.Engine, *, signal_key: str, now: dt.datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.update(winner_enrichment_job)
            .where(winner_enrichment_job.c.signal_key == signal_key)
            .values(
                status="pending",
                attempt_count=0,
                error_code=None,
                claimed_by=None,
                started_at=None,
                finished_at=None,
                updated_at=now,
            )
        )


def run_winner_company_enrichment_batch(
    engine: sa.Engine,
    *,
    now: dt.datetime,
    activated_at: dt.datetime,
    worker_ref: str,
    identity_source: Callable[[str], CompanyEnrichmentInput | None],
    enrichment_service: WinnerCompanyEnrichmentService,
    limit: int = 25,
    official_company_provider: FrenchOfficialCompanyClient | None = None,
) -> WinnerModelEnrichmentBatch:
    """Resolve and model-enrich one serialized batch of new winner jobs."""

    with engine.connect() as connection:
        candidates = select_winner_enrichment_candidates(
            connection, now=now, activated_at=activated_at, limit=limit
        )
    processed = completed = cached = failed = 0
    cost = Decimal("0")
    budget_usage = None
    directory = SupplierDirectoryStore(engine, clock=lambda: now)
    for candidate in candidates:
        processed += 1
        with engine.begin() as connection:
            projected = run_winner_enrichment_batch(
                connection,
                now=now,
                worker_ref=worker_ref,
                limit=1,
                retry_failed=True,
                official_company_provider=official_company_provider,
                signal_keys=(candidate.signal_key,),
            )
        if projected.failed or not projected.processed:
            failed += 1
            continue
        with engine.connect() as connection:
            siren = _siren_for_job(connection, candidate.signal_key)
        try:
            identity = None if siren is None else identity_source(siren)
        except Exception:  # noqa: BLE001 - isolate registry failures to one job
            _mark_failed(
                engine,
                signal_key=candidate.signal_key,
                now=now,
                error_code="winner_directory_identity_failed",
            )
            failed += 1
            continue
        if identity is None:
            _mark_failed(
                engine,
                signal_key=candidate.signal_key,
                now=now,
                error_code="winner_directory_identity_unresolved",
            )
            failed += 1
            continue
        try:
            directory.upsert_identity(
                siren=identity.siren,
                legal_name=identity.legal_name,
                naf_code=identity.naf_code,
                family_key=default_supplier_family_for_naf(identity.naf_code) or "",
                department=identity.department,
                city=identity.city,
                employees=identity.employees,
                observed_at=now,
                naf_label=identity.naf_label,
            )
            result = enrichment_service.enrich(
                identity.siren,
                directors_raw=identity.directors_raw,
            )
        except DailyModelBudgetExhausted as error:
            _return_to_pending(engine, signal_key=candidate.signal_key, now=now)
            budget_usage = error.usage
            break
        except Exception:  # noqa: BLE001 - one winner failure must not lose the batch
            _mark_failed(
                engine,
                signal_key=candidate.signal_key,
                now=now,
                error_code="winner_model_enrichment_failed",
            )
            failed += 1
            continue
        completed += 1
        cached += int(result.cached)
        cost += result.cost_usd
    return WinnerModelEnrichmentBatch(
        processed=processed,
        completed=completed,
        cached=cached,
        failed=failed,
        cost_usd=cost,
        budget_usage=budget_usage,
    )


def _aware_environment_instant(name: str) -> dt.datetime:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _run_locked(arguments: argparse.Namespace) -> int:
    try:
        activated_at = (
            None
            if arguments.requests_only
            else _aware_environment_instant("KIVOU_WINNER_ENRICHMENT_ACTIVATED_AT")
        )
    except ValueError as error:
        print(f"status=CONFIGURATION_ERROR detail={error}", file=sys.stderr)
        return 2
    serper_key = os.environ.get("KIVOU_SERPER_API_KEY", "").strip()
    if not serper_key:
        print("status=PROVIDER_CONFIGURATION_MISSING", file=sys.stderr)
        return 2
    try:
        engine = create_database_engine()
        client = httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0), follow_redirects=True)
        collector = CompanyWebCollector(serper_api_key=serper_key, client=client)
        identity_client = AnnuaireRawDirectorClient(client=client)
        batch_id = f"winner-enrichment-{uuid.uuid4()}"
        try:
            providers = company_enrichment_providers_from_environment(
                engine=engine,
                batch_id=batch_id,
                client=client,
            )
            service = CompanyEnrichmentService(
                directory=SupplierDirectoryStore(engine),
                collector=collector,
                provider=providers.judge,
                arbiter=providers.arbiter,
                mx_verifier=EmailMxVerifier().verify,
            )
            shared = {
                "now": dt.datetime.now(dt.UTC),
                "worker_ref": batch_id[:64],
                "identity_source": identity_client.profile,
                "enrichment_service": service,
                "limit": arguments.limit,
            }
            if arguments.requests_only:
                result = run_company_enrichment_requests(
                    engine, clock=lambda: dt.datetime.now(dt.UTC), **shared
                )
            else:
                result = run_winner_company_enrichment_batch(
                    engine,
                    activated_at=activated_at,
                    official_company_provider=FrenchOfficialCompanyClient(),
                    **shared,
                )
        finally:
            renderer_close = getattr(collector._renderer, "close", None)
            if callable(renderer_close):
                renderer_close()
            client.close()
            engine.dispose()
    except ValueError:
        print("status=PROVIDER_CONFIGURATION_MISSING", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "stopped_budget" if result.budget_usage else "completed",
                "batch_id": batch_id,
                "processed": result.processed,
                "completed": result.completed,
                "cached": result.cached,
                "failed": result.failed,
                "cost_usd": str(result.cost_usd.quantize(Decimal("0.000001"))),
                "budget_usage": result.budget_usage,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if result.failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m signals.company_research.winner_worker")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--requests-only", action="store_true")
    arguments = parser.parse_args(argv)
    maximum = 25 if arguments.requests_only else MAX_WINNER_MODEL_BATCH
    if not 1 <= arguments.limit <= maximum:
        print("status=INVALID_ARGUMENTS", file=sys.stderr)
        return 2
    lock_path = os.environ.get(
        "KIVOU_WINNER_ENRICHMENT_LOCK_FILE", "/srv/kivou/run/winner-enrichment.lock"
    )
    try:
        with exclusive_instance_lock(lock_path):
            return _run_locked(arguments)
    except InstanceAlreadyRunning:
        print("status=INSTANCE_ALREADY_RUNNING", file=sys.stderr)
        return os.EX_TEMPFAIL


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "MAX_WINNER_MODEL_BATCH",
    "RECENT_SIGNAL_WINDOW",
    "WinnerEnrichmentCandidate",
    "WinnerModelEnrichmentBatch",
    "main",
    "run_winner_company_enrichment_batch",
    "select_winner_enrichment_candidates",
]
