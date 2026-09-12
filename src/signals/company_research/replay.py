"""Replay the one-pass company judge over a bounded supplier-directory cohort."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

import httpx
import sqlalchemy as sa

from signals.company_research.enrichment import (
    AnnuaireRawDirectorClient,
    CompanyEnrichmentService,
    CompanyWebCollector,
)
from signals.company_research.providers import OpenRouterCompanyEnrichmentProvider
from signals.contact_discovery.deliverability import EmailMxVerifier
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
    return parser


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
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not serper_key or not openrouter_key:
        print("status=PROVIDER_CONFIGURATION_MISSING", file=sys.stderr)
        return 2
    engine = create_database_engine()
    client = httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0), follow_redirects=True)
    directory = SupplierDirectoryStore(engine)
    director_client = AnnuaireRawDirectorClient(client=client)
    service = CompanyEnrichmentService(
        directory=directory,
        collector=CompanyWebCollector(serper_api_key=serper_key, client=client),
        provider=OpenRouterCompanyEnrichmentProvider(
            api_key=openrouter_key,
            client=client,
        ),
        mx_verifier=EmailMxVerifier().verify,
        director_source=director_client.find,
    )
    try:
        sirens = _cohort(engine, arguments)
        before = _metrics(engine, sirens)
        costs = Decimal("0")
        cached = 0
        errors: list[dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
            future_by_siren = {
                pool.submit(service.enrich, siren, force=arguments.force): siren
                for siren in sirens
            }
            for completed, future in enumerate(as_completed(future_by_siren), 1):
                siren = future_by_siren[future]
                try:
                    result = future.result()
                    costs += result.cost_usd
                    cached += int(result.cached)
                except Exception as error:  # noqa: BLE001 - one fiche must not stop the pass
                    errors.append({"siren": siren, "error": type(error).__name__})
                if completed % 10 == 0 or completed == len(sirens):
                    print(
                        f"progress={completed}/{len(sirens)} errors={len(errors)}",
                        file=sys.stderr,
                        flush=True,
                    )
        after = _metrics(engine, sirens)
    finally:
        client.close()
        engine.dispose()
    print(
        json.dumps(
            {
                "status": "completed" if not errors else "partial",
                "cohort": len(sirens),
                "processed": len(sirens) - len(errors),
                "cached": cached,
                "before": before,
                "after": after,
                "cost_usd": str(costs.quantize(Decimal("0.000001"))),
                "errors": errors,
                "observed_at": dt.datetime.now(dt.UTC).isoformat(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["AURA_DEPARTMENTS", "main"]
