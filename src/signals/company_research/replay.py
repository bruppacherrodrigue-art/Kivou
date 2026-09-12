"""Replay the one-pass company judge over a bounded supplier-directory cohort."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import uuid
from collections.abc import Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from decimal import Decimal

import httpx
import sqlalchemy as sa

from signals.company_research.enrichment import (
    AnnuaireRawDirectorClient,
    CompanyEnrichmentService,
    CompanyWebCollector,
)
from signals.company_research.providers import company_enrichment_providers_from_environment
from signals.contact_discovery.deliverability import EmailMxVerifier
from signals.model_runtime.budget import DailyModelBudgetExhausted
from signals.persistence.database import create_database_engine
from signals.persistence.schema import supplier_directory
from signals.supplier_directory.store import SupplierDirectoryStore

AURA_DEPARTMENTS = ("01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m signals.company_research.replay")
    parser.add_argument("--force", action="store_true", help="ignore le cache de 90 jours")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-employees", type=int, default=10)
    parser.add_argument("--departments", default=",".join(AURA_DEPARTMENTS))
    parser.add_argument("--siren", action="append", default=[])
    parser.add_argument("--batch-id")
    return parser


@dataclass(frozen=True)
class ReplayExecutionResult:
    status: str
    processed: int
    cached: int
    cost_usd: Decimal
    errors: tuple[dict[str, str], ...]
    budget_usage: str | None = None


def _execute_cohort(
    *,
    service,
    sirens: Sequence[str],
    workers: int,
    force: bool,
) -> ReplayExecutionResult:
    costs = Decimal("0")
    cached = 0
    processed = 0
    errors: list[dict[str, str]] = []
    budget_usage: str | None = None
    remaining = iter(sirens)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending: dict[Future, str] = {}

        def submit_next() -> bool:
            try:
                siren = next(remaining)
            except StopIteration:
                return False
            pending[pool.submit(service.enrich, siren, force=force)] = siren
            return True

        for _ in range(min(workers, len(sirens))):
            submit_next()
        while pending and budget_usage is None:
            completed, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
            for future in completed:
                siren = pending.pop(future)
                try:
                    result = future.result()
                    costs += result.cost_usd
                    cached += int(result.cached)
                    processed += 1
                except DailyModelBudgetExhausted as error:
                    budget_usage = error.usage
                    for queued in pending:
                        queued.cancel()
                    pending.clear()
                    break
                except Exception as error:  # noqa: BLE001 - isolate one supplier failure
                    errors.append({"siren": siren, "error": type(error).__name__})
                submit_next()
    status = (
        "stopped_budget"
        if budget_usage is not None
        else "partial"
        if errors
        else "completed"
    )
    return ReplayExecutionResult(
        status=status,
        processed=processed,
        cached=cached,
        cost_usd=costs,
        errors=tuple(errors),
        budget_usage=budget_usage,
    )


def _cohort(engine, arguments) -> tuple[str, ...]:
    statement = sa.select(supplier_directory.c.siren).where(
        supplier_directory.c.suppressed_at.is_(None)
    )
    if arguments.siren:
        statement = statement.where(supplier_directory.c.siren.in_(tuple(arguments.siren)))
    else:
        departments = tuple(
            part.strip() for part in arguments.departments.split(",") if part.strip()
        )
        statement = statement.where(
            supplier_directory.c.employees >= arguments.min_employees,
            supplier_directory.c.department.in_(departments),
        )
    statement = statement.order_by(
        supplier_directory.c.employees.desc(), supplier_directory.c.siren
    )
    if arguments.limit > 0:
        statement = statement.limit(arguments.limit)
    with engine.connect() as connection:
        return tuple(connection.execute(statement).scalars())


def _metrics(engine, sirens: tuple[str, ...]) -> dict[str, int]:
    if not sirens:
        return {"domains": 0, "emails": 0, "families": 0, "families_confirmed": 0}
    with engine.connect() as connection:
        row = connection.execute(
            sa.select(
                sa.func.count(supplier_directory.c.domain),
                sa.func.count(supplier_directory.c.professional_email),
                sa.func.sum(
                    sa.case(
                        (sa.func.json_array_length(supplier_directory.c.family_keys) > 0, 1),
                        else_=0,
                    )
                ),
                sa.func.sum(
                    sa.case(
                        (supplier_directory.c.family_confirmation_status == "confirmed", 1),
                        else_=0,
                    )
                ),
            ).where(supplier_directory.c.siren.in_(sirens))
        ).one()
    return {
        "domains": int(row[0] or 0),
        "emails": int(row[1] or 0),
        "families": int(row[2] or 0),
        "families_confirmed": int(row[3] or 0),
    }


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not 1 <= arguments.workers <= 8 or arguments.limit < 0 or arguments.min_employees < 0:
        print("status=INVALID_ARGUMENTS", file=sys.stderr)
        return 2
    serper_key = os.environ.get("KIVOU_SERPER_API_KEY", "").strip()
    if not serper_key:
        print("status=PROVIDER_CONFIGURATION_MISSING", file=sys.stderr)
        return 2
    engine = create_database_engine()
    client = httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0), follow_redirects=True)
    directory = SupplierDirectoryStore(engine)
    director_client = AnnuaireRawDirectorClient(client=client)
    collector = CompanyWebCollector(serper_api_key=serper_key, client=client)
    batch_id = arguments.batch_id or f"enrichment-{uuid.uuid4()}"
    try:
        try:
            providers = company_enrichment_providers_from_environment(
                engine=engine,
                batch_id=batch_id,
                client=client,
            )
        except ValueError:
            print("status=PROVIDER_CONFIGURATION_MISSING", file=sys.stderr)
            return 2
        service = CompanyEnrichmentService(
            directory=directory,
            collector=collector,
            provider=providers.judge,
            arbiter=providers.arbiter,
            mx_verifier=EmailMxVerifier().verify,
            director_source=director_client.find,
        )
        sirens = _cohort(engine, arguments)
        before = _metrics(engine, sirens)
        execution = _execute_cohort(
            service=service,
            sirens=sirens,
            workers=arguments.workers,
            force=arguments.force,
        )
        after = _metrics(engine, sirens)
    finally:
        renderer_close = getattr(collector._renderer, "close", None)
        if callable(renderer_close):
            renderer_close()
        client.close()
        engine.dispose()
    print(
        json.dumps(
            {
                "status": execution.status,
                "batch_id": batch_id,
                "cohort": len(sirens),
                "processed": execution.processed,
                "cached": execution.cached,
                "before": before,
                "after": after,
                "cost_usd": str(execution.cost_usd.quantize(Decimal("0.000001"))),
                "errors": execution.errors,
                "budget_usage": execution.budget_usage,
                "observed_at": dt.datetime.now(dt.UTC).isoformat(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if execution.status in {"completed", "stopped_budget"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["AURA_DEPARTMENTS", "ReplayExecutionResult", "_execute_cohort", "main"]
