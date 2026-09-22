"""Operator-only Milo Mail B0 commands; every response is aggregate and redacted."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import traceback
from decimal import Decimal
from pathlib import Path

import httpx
import sqlalchemy as sa

from signals.acquisition_programs.apollo_account import ApolloAccountProbe, ApolloAccountState
from signals.acquisition_programs.census import CensusLimits, CensusStore
from signals.acquisition_programs.census_b0 import B0PlanStore, B0Runner
from signals.acquisition_programs.census_cli import _keyring, resolve_apollo_key
from signals.acquisition_programs.census_readiness import (
    ApolloCreditPricing,
    DatabaseAuthorization,
    ExecutionPermit,
    PermitStore,
    configuration_hash,
    database_identity,
    migration_ready,
)
from signals.acquisition_programs.config import load_program_config
from signals.acquisition_programs.legal_pages import LegalPageResolver
from signals.acquisition_programs.mail_provider import DnsMXResolver, MailProviderDetector
from signals.acquisition_programs.official_company import (
    OfficialCompanyMatcher,
    OfficialSourceConfig,
)
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.persistence.database import create_database_engine
from signals.persistence.schema import acquisition_census_partition, acquisition_census_permit


def _model(path: Path, model):
    return model.model_validate_json(path.read_text())


def _partitions(engine: sa.Engine, census_id: str) -> tuple[dict, ...]:
    with engine.connect() as connection:
        return tuple(dict(row) for row in connection.execute(sa.select(
            acquisition_census_partition.c.partition_id,
            acquisition_census_partition.c.filter_signature,
        ).where(acquisition_census_partition.c.census_id == census_id)).mappings())


def _probe(secret_ref: str) -> tuple[str, ApolloAccountState]:
    key = resolve_apollo_key(dict(os.environ), phase="CONTACT_YIELD_B0", expected_ref=secret_ref)
    with httpx.Client() as client:
        account = ApolloAccountProbe(api_key=key, client=client).inspect_free()
    if not account.credential_valid or account.credit_balance is None:
        raise ValueError("Apollo free account probe failed")
    return key, account


def _preflight(engine: sa.Engine, *, census_id: str, permit_id: str,
               database: DatabaseAuthorization, pricing: ApolloCreditPricing,
               limits: CensusLimits, source: OfficialSourceConfig,
               at: dt.datetime) -> dict:
    checks: dict[str, str] = {}
    try:
        database.check(engine, at=at)
        checks["database"] = "READY"
    except ValueError:
        checks["database"] = "UNAUTHORIZED"
    checks["migration"] = "READY" if migration_ready(engine) else "MISSING_OR_DIVERGED"
    plan = B0PlanStore(engine).details(permit_id)
    partitions = _partitions(engine, census_id)
    checks["a1_baseline"] = "READY" if len(partitions) == 9 and CensusStore(engine).status(census_id)["pages_reserved"] == 90 else "INCOMPLETE"
    checks["plan"] = "READY" if plan["companies_planned"] <= 200 and plan["credit_cap"] <= 1500 else "INVALID"
    checks["official_source"] = "READY" if source.enabled and source.max_requests > 0 and source.rate_limit_per_minute <= 60 else "DISABLED"
    try:
        _keyring(dict(os.environ))
        checks["suppression"] = "READY"
    except (ValueError, TypeError):
        checks["suppression"] = "KEYS_MISSING"
    with engine.connect() as connection:
        permit_row = connection.execute(sa.select(acquisition_census_permit).where(
            acquisition_census_permit.c.permit_id == permit_id,
        )).mappings().one_or_none()
    checks["permit"] = "READY" if permit_row and permit_row["status"] == "ACTIVE" else "MISSING_OR_REVOKED"
    ref = (permit_row["apollo_secret_ref"] if permit_row else
           os.environ.get("MILOMAIL_CENSUS_APOLLO_SECRET_REF") or "MILOMAIL_CENSUS_APOLLO_API_KEY")
    account = None
    try:
        _, account = _probe(ref)
        checks["apollo_key"] = "READY"
    except ValueError:
        checks["apollo_key"] = "MISSING_OR_INVALID"
    balance = account.credit_balance if account else None
    checks["reserve"] = ("READY" if balance is not None and balance >= 500 and
                         plan["pool_before"] is not None and
                         plan["pool_before"] - plan["credit_cap"] >= 500
                         else "INSUFFICIENT_OR_UNKNOWN")
    try:
        pricing.check(limits, at=at, phase="CONTACT_YIELD_B0")
        checks["pricing"] = "READY"
    except ValueError:
        checks["pricing"] = "UNKNOWN_OR_STALE"
    if permit_row:
        expected = configuration_hash(census_id=census_id, limits=limits,
                                      partitions=partitions, pricing=pricing,
                                      source_config=source,
                                      sample_plan_hash=plan["plan_hash"])
        checks["configuration"] = ("READY" if expected == permit_row["configuration_hash"]
                                   else "CHANGED")
    else:
        checks["configuration"] = "PERMIT_MISSING"
    return {"phase": "CONTACT_YIELD_B0", "ready": all(value == "READY" for value in checks.values()),
            "checks": checks, "database_id": database_identity(engine)[0],
            "apollo_pool_balance": balance,
            "credit_cap": plan["credit_cap"], "minimum_remaining_pool_balance": 500,
            "companies_planned": plan["companies_planned"],
            "instantly_mutation_allowed": False, "email_sending_allowed": False,
            "max_incremental_charge_chf": "0.00"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="milomail-b0")
    parser.add_argument("command", choices=("plan", "preflight", "issue-permit", "run",
                                            "resume", "status", "report", "revoke",
                                            "refresh-official"))
    parser.add_argument("--census-id", required=True)
    parser.add_argument("--permit-id", required=True)
    parser.add_argument("--database-authorization", type=Path, required=True)
    parser.add_argument("--pricing", type=Path)
    parser.add_argument("--program-config", type=Path)
    parser.add_argument("--a1-report", type=Path)
    parser.add_argument("--max-companies", type=int, default=0)
    parser.add_argument("--max-credits", type=int, default=0)
    parser.add_argument("--all-after-calibration", action="store_true")
    parser.add_argument("--authorize-paid-apollo", action="store_true")
    parser.add_argument("--acknowledge-public-requests", action="store_true")
    args = parser.parse_args(argv)
    now = dt.datetime.now(dt.UTC)
    try:
        engine = create_database_engine()
        database = _model(args.database_authorization, DatabaseAuthorization)
        database.check(engine, at=now)
        if not migration_ready(engine) or engine.url.database != "kivou_milomail_census_a0":
            raise ValueError("B0 requires the reviewed 0075 isolated census database")
        store = B0PlanStore(engine)
        if args.command == "plan":
            if args.max_companies == 0 or args.max_credits == 0:
                raise ValueError("B0 plan needs explicit company and credit limits")
            ref = os.environ.get("MILOMAIL_CENSUS_APOLLO_SECRET_REF") or "MILOMAIL_CENSUS_APOLLO_API_KEY"
            _, account = _probe(ref)
            assert account.credit_balance is not None
            result = store.plan(args.census_id, permit_id=args.permit_id,
                                pool_balance=account.credit_balance,
                                max_companies=args.max_companies,
                                max_credits=min(args.max_credits, account.credit_balance - 500),
                                at=now)
        elif args.command == "status":
            result = store.details(args.permit_id)
        elif args.command == "report":
            result = store.report(args.permit_id)
            result["census_summary"] = store.census_report(args.census_id)
            if args.a1_report:
                result["projection"] = store.projection(
                    args.permit_id, a1_report=json.loads(args.a1_report.read_text()),
                    all_b0_permits=True)
        elif args.command == "revoke":
            PermitStore(engine).revoke(args.permit_id)
            result = {"permit_id": args.permit_id, "status": "REVOKED"}
        elif args.command == "refresh-official":
            source = OfficialSourceConfig.from_environment(os.environ)
            if (not args.acknowledge_public_requests or not source.enabled or
                    source.max_requests == 0 or source.max_requests > 600 or
                    source.rate_limit_per_minute > 60 or args.max_companies == 0):
                raise ValueError("bounded public-source authorization is required")
            with httpx.Client(timeout=20) as client:
                result = store.refresh_official(
                    args.permit_id,
                    matcher=OfficialCompanyMatcher(engine, source, client=client,
                                                   census_id=args.census_id),
                    resolver=LegalPageResolver(engine, client=client),
                    max_companies=args.max_companies, at=now,
                )
        else:
            if not args.pricing:
                raise ValueError("B0 pricing evidence is required")
            pricing = _model(args.pricing, ApolloCreditPricing)
            limits = CensusLimits.from_environment(os.environ)
            source = OfficialSourceConfig.from_environment(os.environ)
            if args.command == "issue-permit":
                plan = store.details(args.permit_id)
                _, account = _probe(os.environ.get("MILOMAIL_CENSUS_APOLLO_SECRET_REF") or
                                    "MILOMAIL_CENSUS_APOLLO_API_KEY")
                if account.credit_balance < plan["credit_cap"] + 500:
                    raise ValueError("Apollo prepaid reserve is insufficient")
                ref = os.environ.get("MILOMAIL_CENSUS_APOLLO_SECRET_REF") or "MILOMAIL_CENSUS_APOLLO_API_KEY"
                permit = ExecutionPermit(
                    permit_id=args.permit_id, census_id=args.census_id,
                    phase="CONTACT_YIELD_B0", environment="staging",
                    database_id=database.database_id,
                    allowed_partitions=tuple(p["partition_id"] for p in _partitions(engine, args.census_id)),
                    max_pages=0, max_candidates=plan["companies_planned"],
                    max_enrichments=min(400, plan["companies_planned"] * 2),
                    max_credits=plan["credit_cap"], max_cost_chf=Decimal(0),
                    price_chf_per_credit=None, billing_basis="PREPAID_SHARED_POOL",
                    apollo_secret_ref=ref, pricing_reference=pricing.source_reference,
                    configuration_hash=configuration_hash(
                        census_id=args.census_id, limits=limits,
                        partitions=_partitions(engine, args.census_id), pricing=pricing,
                        source_config=source, sample_plan_hash=plan["plan_hash"]),
                    sample_plan_hash=plan["plan_hash"],
                    issued_by_reference="user-prompt-2026-09-22-b0-1500-reserve500",
                    issued_at=now, valid_from=now, expires_at=now + dt.timedelta(hours=2),
                )
                PermitStore(engine).issue(permit, database=database, pricing=pricing,
                                          limits=limits, at=now, source_config=source)
                result = {"permit_id": permit.permit_id, "configuration_hash":
                          permit.configuration_hash, "status": "ACTIVE"}
            else:
                report = _preflight(engine, census_id=args.census_id, permit_id=args.permit_id,
                                    database=database, pricing=pricing, limits=limits,
                                    source=source, at=now)
                if args.command == "preflight":
                    result = report
                else:
                    if not args.authorize_paid_apollo or not report["ready"]:
                        raise ValueError("paid Apollo requires explicit flag and green B0 preflight")
                    if not args.program_config:
                        raise ValueError("Milo Mail program configuration is required")
                    with engine.connect() as connection:
                        permit_row = connection.execute(sa.select(acquisition_census_permit).where(
                            acquisition_census_permit.c.permit_id == args.permit_id,
                        )).mappings().one()
                    key, _ = _probe(permit_row["apollo_secret_ref"])
                    with httpx.Client(timeout=20) as client:
                        runner = B0Runner(
                            engine, census_id=args.census_id, permit_id=args.permit_id,
                            config=load_program_config(args.program_config), limits=limits,
                            database_id=database.database_id,
                            configuration_hash=permit_row["configuration_hash"],
                            contacts=ApolloContactDiscoveryClient(api_key=key, client=client),
                            account_probe=lambda: ApolloAccountProbe(api_key=key, client=client).inspect_free(),
                            detector=MailProviderDetector(DnsMXResolver()),
                            official=OfficialCompanyMatcher(engine, source, client=client,
                                                            census_id=args.census_id),
                            legal_pages=LegalPageResolver(engine, client=client),
                            suppression_keys=_keyring(dict(os.environ)),
                        )
                        result = runner.run(at=now, micro_only=not args.all_after_calibration)
        print(json.dumps(result, sort_keys=True, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001 - redact arbitrary provider/database failures
        # Category only: provider errors and database exceptions may carry PII or secrets.
        known = {
            "B0 permits exceed cumulative census reservations": "CUMULATIVE_LIMIT",
            "B0 permit differs from frozen plan or Apollo reserve": "PLAN_OR_RESERVE",
            "B0 permit must cover only incremental contact work": "PERMIT_LIMIT",
            "another B0 permit is active for this census": "PERMIT_ALREADY_ACTIVE",
            "permit configuration hash does not match current plan": "CONFIGURATION_CHANGED",
            "permit cannot outlive database authorization": "DATABASE_AUTH_EXPIRING",
            "B0 cannot preserve 500 prepaid Apollo credits": "POOL_RESERVE",
            "Apollo credit balance is stale": "STALE_BALANCE",
            "Apollo pricing is stale": "STALE_PRICING",
        }
        frames = traceback.extract_tb(exc.__traceback__)
        origin = (f"{Path(frames[-1].filename).name}:{frames[-1].lineno}"
                  if frames and "/signals/" in frames[-1].filename else "REDACTED")
        print(json.dumps({"status": "BLOCKED", "error_type": type(exc).__name__,
                          "error_origin": origin,
                          "error_code": known.get(str(exc), "REDACTED") if isinstance(exc, ValueError)
                          else "REDACTED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
