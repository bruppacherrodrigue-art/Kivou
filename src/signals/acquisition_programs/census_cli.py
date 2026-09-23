"""Operator CLI for a disabled-by-default Milo Mail SHADOW census."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import Literal, NoReturn, cast

import httpx
from alembic import command

from signals.acquisition.store import AcquisitionStore
from signals.acquisition_programs.apollo_account import ApolloAccountProbe
from signals.acquisition_programs.census import CensusLimits, CensusStore, build_partitions
from signals.acquisition_programs.census_readiness import (
    APOLLO_ORG_SEARCH_PRICING_URL,
    HEAD,
    ApolloCreditPricing,
    DatabaseAuthorization,
    ExecutionPermit,
    PermitStore,
    account_capacity_ready,
    configuration_hash,
    database_revisions,
    migration_ready,
    preflight,
)
from signals.acquisition_programs.census_runtime import CensusRunner
from signals.acquisition_programs.census_sampling import SamplePlanStore
from signals.acquisition_programs.census_statistics import sample_report
from signals.acquisition_programs.census_usage_guard import A1UsageGuard
from signals.acquisition_programs.config import load_program_config
from signals.acquisition_programs.mail_provider import DnsMXResolver, MailProviderDetector
from signals.acquisition_programs.official_company import (
    OfficialCompanyMatcher,
    OfficialSourceConfig,
)
from signals.acquisition_programs.pipeline import ActiveCompanyEvidence, ProgramOperationalContext
from signals.acquisition_programs.runtime import MilomailShadowRuntime
from signals.acquisition_programs.store import AcquisitionProgramStore
from signals.company_research.apollo import ApolloCompanyResearchClient
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient

_HEAD = HEAD


def resolve_apollo_key(source: dict[str, str] | os._Environ[str], *, phase: str,
                       expected_ref: str | None = None) -> str:
    """Resolve a secret name only; never copy its value to a receipt or diagnostic."""
    ref = source.get("MILOMAIL_CENSUS_APOLLO_SECRET_REF", "")
    if ref:
        if (phase not in {"COVERAGE_A0", "COVERAGE_A1_SAMPLE", "CONTACT_YIELD_B0",
                          "FRANCE_B1_READY_BASE"} or
                ref != "KIVOU_APOLLO_API_KEY" or
                expected_ref != ref or
                source.get("KIVOU_ACQUISITION_ENVIRONMENT", "").upper() != "STAGING"):
            raise ValueError("shared Apollo secret is restricted to staging coverage")
    else:
        ref = "MILOMAIL_CENSUS_APOLLO_API_KEY"
        if expected_ref not in (None, ref):
            raise ValueError("Apollo secret reference differs from permit")
    value = source.get(ref, "")
    if not value:
        raise ValueError("Apollo credential is missing")
    return value


def _optional_apollo_key(phase: str | None) -> str:
    try:
        return resolve_apollo_key(dict(os.environ), phase=phase or "",
                                  expected_ref=os.environ.get(
                                      "MILOMAIL_CENSUS_APOLLO_SECRET_REF") or None)
    except ValueError:
        return ""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        self.exit(2, "status=INVALID_ARGUMENTS\n")


class _ForbiddenInstantly:
    def __getattr__(self, _name: str) -> None:
        raise RuntimeError("Instantly is unavailable to the census")


class _ForbiddenApolloOperation:
    def __getattr__(self, _name: str) -> None:
        raise RuntimeError("contact and enrichment Apollo operations are forbidden in A1")


def _keyring(source: dict[str, str]) -> SuppressionIdentityKeyring:
    version = source.get("KIVOU_SUPPRESSION_HMAC_KEY_VERSION", "")
    current = source.get("KIVOU_SUPPRESSION_HMAC_KEY", "")
    if not version or len(current.encode()) < 16:
        raise ValueError("Kivou suppression keyring is incomplete")
    retained_raw = source.get("KIVOU_SUPPRESSION_RETAINED_KEYS_JSON", "{}")
    retained = json.loads(retained_raw)
    if not isinstance(retained, dict):
        raise TypeError("Kivou suppression retained keys are invalid")
    keys: dict[str, bytes] = {}
    for item_version, secret in retained.items():
        if not isinstance(item_version, str) or not isinstance(secret, str) or len(secret.encode()) < 16:
            raise ValueError("Kivou suppression retained keys are invalid")
        keys[item_version] = secret.encode()
    if version in keys and keys[version] != current.encode():
        raise ValueError("Kivou suppression current key conflicts with retained keys")
    keys[version] = current.encode()
    return SuppressionIdentityKeyring(current_key_version=version, keys=keys)


def _optional_keyring(source: dict[str, str]) -> SuppressionIdentityKeyring | None:
    try:
        return _keyring(source)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _parser() -> _SafeArgumentParser:
    parser = _SafeArgumentParser(prog="milomail-census")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_SafeArgumentParser)
    bootstrap = commands.add_parser("bootstrap", help="read-only zero-cost coverage diagnostic")
    bootstrap.add_argument("--program-config", type=Path, required=True)
    bootstrap.add_argument("--census-id")
    bootstrap.add_argument("--database-authorization", type=Path)
    bootstrap.add_argument("--pricing", type=Path)
    bootstrap.add_argument("--probe-official-source", action="store_true")
    bootstrap.add_argument("--probe-apollo-free", action="store_true")
    plan = commands.add_parser("plan", help="persist deterministic partitions; no Apollo calls")
    plan.add_argument("--program-config", type=Path, required=True)
    plan.add_argument("--database-authorization", type=Path, required=True)
    sample = commands.add_parser("plan-sample", help="freeze A1 pages before a paid call")
    sample.add_argument("--census-id", required=True)
    sample.add_argument("--permit-id", required=True)
    sample.add_argument("--max-new-pages", type=int, default=81)
    sample.add_argument("--database-authorization", type=Path, required=True)
    for name in ("run", "resume"):
        command = commands.add_parser(name, help="bounded Apollo preparation in SHADOW")
        command.add_argument("--census-id", required=True)
        command.add_argument("--program-config", type=Path, required=True)
        command.add_argument("--operations", type=Path)
        command.add_argument("--authorize-paid-apollo", action="store_true")
        command.add_argument("--phase", choices=("COVERAGE", "COVERAGE_A0",
                                               "COVERAGE_A1_SAMPLE", "ENRICHMENT"))
        command.add_argument("--a0", action="store_true",
                             help="at most the first page of each permitted partition")
        command.add_argument("--permit-id")
        command.add_argument("--database-authorization", type=Path)
        command.add_argument("--pricing", type=Path)
        command.add_argument("--probe-official-source", action="store_true")
        command.add_argument("--probe-apollo-free", action="store_true")
    pre = commands.add_parser("preflight", help="read-only checks before an authorized run")
    pre.add_argument("--census-id", required=True)
    pre.add_argument("--phase", choices=("COVERAGE", "COVERAGE_A0",
                                           "COVERAGE_A1_SAMPLE", "ENRICHMENT"))
    pre.add_argument("--database-authorization", type=Path)
    pre.add_argument("--pricing", type=Path)
    pre.add_argument("--permit-id")
    pre.add_argument("--probe-official-source", action="store_true")
    pre.add_argument("--probe-apollo-free", action="store_true")
    issue = commands.add_parser("issue-permit", help="record an approved bounded permit")
    issue.add_argument("--permit", type=Path, required=True)
    issue.add_argument("--database-authorization", type=Path, required=True)
    issue.add_argument("--pricing", type=Path, required=True)
    revoke = commands.add_parser("revoke-permit", help="stop future Apollo reservations")
    revoke.add_argument("--permit-id", required=True)
    revoke.add_argument("--database-authorization", type=Path, required=True)
    migrate = commands.add_parser("migrate-authorized", help="upgrade a reviewed non-production census database")
    migrate.add_argument("--database-authorization", type=Path, required=True)
    migrate.add_argument("--acknowledge-migration", action="store_true")
    for name in ("status", "report", "purge-cache"):
        command = commands.add_parser(
            name,
            help="purge retained person response cache" if name == "purge-cache"
            else "read persisted census state",
        )
        command.add_argument("--census-id", required=True)
        if name == "report":
            command.add_argument("--public-aggregate", action="store_true")
            command.add_argument("--sample-permit-id")
            command.add_argument("--forecast-low", type=Decimal)
            command.add_argument("--forecast-central", type=Decimal)
            command.add_argument("--forecast-high", type=Decimal)
            command.add_argument("--forecast-source")
        if name == "purge-cache":
            command.add_argument("--database-authorization", type=Path, required=True)
            command.add_argument("--acknowledge-cache-purge", action="store_true")
    usage = commands.add_parser(
        "reconcile-usage", help="record externally verified Apollo credits and CHF cost"
    )
    usage.add_argument("--census-id", required=True)
    usage.add_argument("--actual-credits", type=int)
    usage.add_argument("--actual-cost-chf", type=Decimal)
    usage.add_argument("--usage-evidence-ref")
    usage.add_argument("--shared-pool", action="store_true")
    usage.add_argument("--permit-id")
    usage.add_argument("--pool-before", type=int)
    usage.add_argument("--pool-after", type=int)
    usage.add_argument("--database-authorization", type=Path, required=True)
    usage.add_argument("--acknowledge-exclusive-attribution", action="store_true")
    return parser


def _read_model(path: Path | None, model):
    if path is None:
        return None
    body = path.read_bytes()
    if len(body) > 65_536:
        raise ValueError("operator evidence file is too large")
    return model.model_validate_json(body)


def _probe_official_source() -> bool:
    # Public, read-only, no person query. No Apollo request is involved.
    try:
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            response = client.get("https://recherche-entreprises.api.gouv.fr/search",
                                  params={"q": "000000000", "per_page": 1, "page": 1})
        return response.status_code == 200 and isinstance(response.json().get("results"), list)
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


def _probe_apollo_account(api_key: str):
    if not api_key:
        return None
    with httpx.Client(timeout=5.0, follow_redirects=False) as client:
        return ApolloAccountProbe(api_key=api_key, client=client).inspect_free()


def _code_sha() -> str | None:
    root = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0 and len(result.stdout.strip()) == 40:
        return result.stdout.strip()
    # An isolated staging checkout may deliberately omit .git. Bind the
    # diagnostic to the exact Python source bytes instead of claiming a SHA.
    package = root / "src/signals"
    if not package.is_dir():
        return None
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def _bootstrap(args: argparse.Namespace, *, at: dt.datetime) -> dict:
    """Diagnose bounded COVERAGE even when no database URL is configured."""
    config = load_program_config(args.program_config)
    partitions = build_partitions(config)
    limits = CensusLimits.from_environment(os.environ)
    source = OfficialSourceConfig.from_environment(os.environ)
    database = _read_model(args.database_authorization, DatabaseAuthorization)
    pricing = _read_model(args.pricing, ApolloCreditPricing)
    phase: Literal["COVERAGE", "COVERAGE_A0"] = (
        "COVERAGE_A0" if pricing and pricing.billing_basis == "PREPAID_SHARED_POOL"
        else "COVERAGE"
    )
    try:
        api_key = resolve_apollo_key(dict(os.environ), phase=phase,
                                     expected_ref=os.environ.get("MILOMAIL_CENSUS_APOLLO_SECRET_REF") or None)
    except ValueError:
        api_key = ""
    key_present = bool(api_key)
    pricing_ready = False
    if pricing:
        try:
            pricing.check(limits, at=at, phase=phase)
            pricing_ready = True
        except ValueError:
            pass
    try:
        limits.require_run_authorization(phase=phase)
        limits_ready = True
    except ValueError:
        limits_ready = False
    credit_caps_ready = limits.max_apollo_credits > 0 and (
        limits.max_cost_chf > 0 or phase == "COVERAGE_A0")
    checks = {
        "program": "READY" if not config.enabled and config.campaign_mode == "SHADOW" and
        config.max_daily_contacts == config.max_monthly_contacts == 0 and
        config.max_cost_chf == 0 else "PROGRAM_NOT_DISABLED_SHADOW",
        "nine_partitions": "READY" if len(partitions) == 9 else "PARTITION_COUNT_MISMATCH",
        "apollo_key": "READY" if key_present else "CREDENTIAL_MISSING",
        "suppression_keys": "READY" if _optional_keyring(dict(os.environ)) else "CREDENTIAL_MISSING",
        "official_source": "READY" if source.enabled and source.max_requests > 0 and
        source.rate_limit_per_minute <= 60 else "DISABLED_OR_RATE_ABOVE_60",
        "limits": "READY" if limits_ready else "ZERO_OR_DISABLED",
        "no_enrichment": "READY" if limits.max_enrichments == 0 else "ENRICHMENT_CAP_NONZERO",
        "credit_caps": "READY" if credit_caps_ready else "ZERO_CREDIT_OR_CHF_CAP",
        "operation_cost": (
            "READY" if credit_caps_ready and pricing_ready else
            "ORG_SEARCH_REQUIRES_CREDIT" if not credit_caps_ready else
            "PRICE_OR_CREDIT_CATEGORY_UNVERIFIED"
        ),
        "pricing": "READY" if pricing_ready else "UNVERIFIED" if pricing else "MISSING",
    }
    db_report: dict | None = None
    if not os.environ.get("KIVOU_DATABASE_URL"):
        checks["database"] = "DATABASE_URL_MISSING"
        checks["migration"] = "DATABASE_URL_MISSING"
    else:
        try:
            engine = create_database_engine()
            checks["database"] = "AUTHORIZATION_MISSING" if database is None else "READY"
            if engine.dialect.name != "postgresql":
                checks["database"] = "NON_POSTGRESQL_DATABASE"
            elif database is not None:
                database.check_identity(engine, at=at)
            checks["migration"] = "READY" if migration_ready(engine) else "MISSING_OR_DIVERGED"
            if args.census_id and checks["migration"] == "READY":
                persisted_partitions = CensusStore(engine).partitions(args.census_id)
                checks["plan_configuration"] = (
                    "READY" if {part.partition_id for part in partitions} ==
                    {part["partition_id"] for part in persisted_partitions}
                    else "FILTER_SIGNATURE_MISMATCH"
                )
                account = _probe_apollo_account(api_key) if args.probe_apollo_free else None
                db_report = preflight(
                    engine, census_id=args.census_id, limits=limits, database=database,
                    pricing=pricing, apollo_key_present=key_present,
                    source_enabled=source.enabled, source_requests=source.max_requests,
                    source_available=args.probe_official_source and _probe_official_source(),
                    suppression_keyring=_optional_keyring(dict(os.environ)),
                    apollo_account=account, at=at, phase=phase,
                    source_rate_limit_per_minute=source.rate_limit_per_minute,
                    source_cache_ttl_days=source.cache_ttl_days, source_config=source,
                    code_sha=_code_sha(), app_version=version("signals"),
                )
        except Exception:  # noqa: BLE001 — keep database URLs and passwords out of diagnostics
            checks["database"] = "UNREACHABLE_OR_UNAUTHORIZED"
            checks["migration"] = "UNVERIFIED"
    if db_report:
        checks.update({f"persisted_{key}": value
                       for key, value in db_report["checks"].items()})
    required = [name for name in (
        "KIVOU_DATABASE_URL", "KIVOU_ACQUISITION_ENVIRONMENT",
        os.environ.get("MILOMAIL_CENSUS_APOLLO_SECRET_REF") or
        "MILOMAIL_CENSUS_APOLLO_API_KEY", "KIVOU_SUPPRESSION_HMAC_KEY",
        "KIVOU_SUPPRESSION_HMAC_KEY_VERSION",
    ) if not os.environ.get(name)]
    return {
        "status": "BLOCKED" if any(value != "READY" for value in checks.values()) else "READY",
        "phase": phase, "checks": checks,
        "blockers": [name for name, value in checks.items() if value != "READY"],
        "required_environment_variables": required,
        "partitions_planned": len(partitions),
        "caps": {"partitions": limits.max_partitions, "pages": limits.max_pages,
                 "candidates": limits.max_candidates, "enrichments": limits.max_enrichments,
                 "credits": limits.max_apollo_credits, "cost_chf": str(limits.max_cost_chf)},
        "apollo_plan": pricing.plan_name if pricing else None,
        "apollo_secret_ref": os.environ.get("MILOMAIL_CENSUS_APOLLO_SECRET_REF") or
        "MILOMAIL_CENSUS_APOLLO_API_KEY",
        "billing_basis": pricing.billing_basis if pricing else None,
        "apollo_operation_credit_category": "ORG_SEARCH",
        "apollo_org_search_pricing_source": APOLLO_ORG_SEARCH_PRICING_URL,
        "pricing_verified_at": pricing.verified_at.isoformat() if pricing else None,
        "official_rate_limit_per_minute": source.rate_limit_per_minute,
        "database_preflight": db_report,
        "execution_authorized": False,
        "contact_enrichment_allowed": False,
        "instantly_mutation_allowed": False,
        "code_sha": _code_sha(), "app_version": version("signals"),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = dt.datetime.now(dt.UTC)
    try:
        if args.command == "bootstrap":
            print(json.dumps(_bootstrap(args, at=now), default=str,
                             sort_keys=True, ensure_ascii=False))
            return 0
        # The CLI never migrates a database, and no default database URL exists.
        engine = create_database_engine()
        if args.command == "migrate-authorized":
            database = _read_model(args.database_authorization, DatabaseAuthorization)
            if not args.acknowledge_migration or database is None:
                raise ValueError("reviewed non-production migration requires acknowledgement")
            database.check_identity(engine, at=now)
            revisions = database_revisions(engine)
            if revisions == ("0073_milomail_a0_prepaid",):
                if (database.environment != "staging" or
                        engine.url.database != "kivou_milomail_census_a0"):
                    raise ValueError("A1 migration requires the isolated A0 staging database")
            elif revisions == ("0074_milomail_a1_sample_plan",):
                if (database.environment != "staging" or
                        engine.url.database != "kivou_milomail_census_a0"):
                    raise ValueError("B0 migration requires the isolated A0 staging database")
            elif revisions != ("0071_milomail_shadow_census",):
                raise ValueError("only exact 0071 or isolated A0 0073/0074 can be migrated")
            command.upgrade(alembic_config(engine), _HEAD)
            print(json.dumps({"status": "MIGRATED", "revision": current_revision(engine)}))
            return 0
        if args.command != "preflight" and not migration_ready(engine):
            raise ValueError("census database migration is not at the reviewed head")
        if args.command in {"plan", "plan-sample", "purge-cache", "reconcile-usage"}:
            mutation_database = _read_model(args.database_authorization,
                                            DatabaseAuthorization)
            if mutation_database is None:
                raise ValueError("database authorization is required for census mutations")
            mutation_database.check(engine, at=now)
        store = CensusStore(engine)
        if args.command == "preflight":
            database = _read_model(args.database_authorization, DatabaseAuthorization)
            pricing = _read_model(args.pricing, ApolloCreditPricing)
            source = OfficialSourceConfig.from_environment(os.environ)
            result = preflight(
                engine, census_id=args.census_id,
                limits=CensusLimits.from_environment(os.environ), database=database,
                pricing=pricing,
                apollo_key_present=bool(_optional_apollo_key(args.phase)),
                source_enabled=source.enabled, source_requests=source.max_requests,
                source_available=args.probe_official_source and _probe_official_source(),
                source_rate_limit_per_minute=source.rate_limit_per_minute,
                source_cache_ttl_days=source.cache_ttl_days,
                source_config=source,
                apollo_account=_probe_apollo_account(
                    _optional_apollo_key(args.phase)
                ) if args.probe_apollo_free else None,
                suppression_keyring=_optional_keyring(dict(os.environ)),
                at=now, permit_id=args.permit_id, code_sha=_code_sha(),
                app_version=version("signals"),
                phase=args.phase,
            )
        elif args.command == "issue-permit":
            database = _read_model(args.database_authorization, DatabaseAuthorization)
            permit = _read_model(args.permit, ExecutionPermit)
            pricing = _read_model(args.pricing, ApolloCreditPricing)
            limits = CensusLimits.from_environment(os.environ)
            limits.require_run_authorization(phase=permit.phase if permit else None)
            if database is None or permit is None or pricing is None:
                raise ValueError("permit, pricing and database authorization are required")
            pricing.check(limits, at=now, phase=permit.phase)
            source = OfficialSourceConfig.from_environment(os.environ)
            PermitStore(engine).issue(permit, database=database, pricing=pricing,
                                      limits=limits, at=now, source_config=source)
            result = {"permit_id": permit.permit_id, "status": "RECORDED", "phase": permit.phase}
        elif args.command == "revoke-permit":
            database = _read_model(args.database_authorization, DatabaseAuthorization)
            if database is None:
                raise ValueError("database authorization is required")
            database.check(engine, at=now)
            PermitStore(engine).revoke(args.permit_id)
            result = {"permit_id": args.permit_id, "status": "REVOKED"}
        elif args.command in {"status", "report"}:
            if args.command == "status":
                result = store.status(args.census_id)
            else:
                if args.sample_permit_id:
                    if not args.public_aggregate:
                        raise ValueError("A1 report requires public aggregate mode")
                    result = sample_report(engine, args.census_id, args.sample_permit_id)
                else:
                    rates = (args.forecast_low, args.forecast_central, args.forecast_high)
                    if any(rate is not None for rate in rates) and not all(
                        rate is not None for rate in rates
                    ):
                        raise ValueError("all three forecast rates are required")
                    result = store.report(
                        args.census_id,
                        forecast_rates=rates if all(rate is not None for rate in rates) else None,
                        forecast_source=args.forecast_source,
                        public_aggregate=args.public_aggregate,
                    )
        elif args.command == "purge-cache":
            if not args.acknowledge_cache_purge:
                raise ValueError("cache purge requires explicit acknowledgement")
            cleared = store.purge_contact_cache(args.census_id, at=now)
            result = {"census_id": args.census_id, "apollo_cache_rows_cleared": cleared,
                      "status": store.status(args.census_id)["status"]}
        elif args.command == "reconcile-usage":
            if args.shared_pool:
                if (args.acknowledge_exclusive_attribution or
                        args.pool_before is None or args.pool_after is None or
                        args.pool_before < 0 or args.pool_after < 0):
                    raise ValueError("shared-pool balances are required without exclusive attribution")
                ledger = store.report(args.census_id)
                if ledger["billing_basis"] != "PREPAID_SHARED_POOL":
                    raise ValueError("shared-pool reconciliation requires a prepaid permit")
                if args.permit_id:
                    from signals.persistence.schema import acquisition_census_call

                    with engine.connect() as connection:
                        import sqlalchemy as sa

                        attempted = connection.scalar(sa.select(sa.func.count()).select_from(
                            acquisition_census_call,
                        ).where(acquisition_census_call.c.permit_id == args.permit_id,
                                acquisition_census_call.c.kind == "ORG_SEARCH")) or 0
                        reserved = connection.scalar(sa.select(sa.func.coalesce(
                            sa.func.sum(acquisition_census_call.c.reserved_credits), 0,
                        )).where(acquisition_census_call.c.permit_id == args.permit_id)) or 0
                else:
                    attempted = sum(value for key, value in ledger["api_calls"].items()
                                    if key.startswith("ORG_SEARCH:"))
                    reserved = ledger["apollo_credits_reserved_upper_bound"]
                delta = args.pool_before - args.pool_after
                if delta < 0:
                    raise ValueError("shared Apollo pool increased; top-up or concurrent change requires review")
                result = {
                    "census_id": args.census_id, "attribution": "SHARED_POOL_AMBIGUOUS",
                    "pool_before": args.pool_before, "pool_after": args.pool_after,
                    "pool_delta": delta, "billable_attempts_reserved": attempted,
                    "credits_reserved_upper_bound": reserved,
                    "delta_equals_reserved_upper_bound":
                    delta == reserved,
                    "incremental_charge_chf": "0.00", "allocation_cost_chf": None,
                    "receipt_recorded_as_exclusive": False,
                }
            else:
                if (not args.acknowledge_exclusive_attribution or
                        args.actual_credits is None or args.actual_cost_chf is None or
                        not args.usage_evidence_ref):
                    raise ValueError("exclusive Apollo attribution requires complete evidence")
                store.record_actual_usage(
                    args.census_id, credits=args.actual_credits,
                    cost_chf=args.actual_cost_chf,
                    evidence_ref=args.usage_evidence_ref, at=now,
                )
                result = store.report(args.census_id)
        elif args.command == "plan":
            config = load_program_config(args.program_config)
            if config.enabled or config.campaign_mode != "SHADOW":
                raise ValueError("census requires a disabled SHADOW program")
            program_id = AcquisitionProgramStore(engine).register(config, at=now)
            census_id = store.plan(
                program_id=program_id, partitions=build_partitions(config), at=now
            )
            result = {
                "census_id": census_id,
                "status": "PLANNED",
                "partitions": len(store.partitions(census_id)),
                "estimated_result_count": None,
                "apollo_calls": 0,
                "credits_spent": 0,
            }
        elif args.command == "plan-sample":
            result = SamplePlanStore(engine).plan(
                args.census_id, permit_id=args.permit_id,
                max_new_pages=args.max_new_pages, at=now,
            )
        else:
            if not args.authorize_paid_apollo:
                raise ValueError("paid Apollo use needs an explicit command flag")
            if not args.phase or not args.permit_id:
                raise ValueError("a bounded phase and execution permit are required")
            limits = CensusLimits.from_environment(os.environ)
            limits.require_run_authorization(phase=args.phase)
            if args.phase in {"COVERAGE", "COVERAGE_A0", "COVERAGE_A1_SAMPLE"} and limits.max_enrichments != 0:
                raise ValueError("coverage cannot authorize contact enrichment")
            database = _read_model(args.database_authorization, DatabaseAuthorization)
            pricing = _read_model(args.pricing, ApolloCreditPricing)
            if database is None or pricing is None:
                raise ValueError("database authorization and verified Apollo pricing are required")
            database.check(engine, at=now)
            pricing.check(limits, at=now, phase=args.phase)
            config = load_program_config(args.program_config)
            if config.enabled or config.campaign_mode != "SHADOW":
                raise ValueError("census requires a disabled SHADOW program")
            if args.phase == "COVERAGE_A0" and not args.a0:
                raise ValueError("A0 requires first-page-only execution")
            if args.a0 and args.phase != "COVERAGE_A0":
                raise ValueError("first-page-only requires an A0 permit")
            if not args.probe_apollo_free:
                raise ValueError("free Apollo account verification is required")
            keys = _keyring(dict(os.environ))
            source = OfficialSourceConfig.from_environment(os.environ)
            if args.phase in {"COVERAGE", "COVERAGE_A0", "COVERAGE_A1_SAMPLE"} and source.rate_limit_per_minute > 60:
                raise ValueError("coverage official source rate exceeds 60 per minute")
            if args.phase == "COVERAGE_A1_SAMPLE" and source.max_requests > 600:
                raise ValueError("A1 official source cap exceeds 600 requests")
            if not source.enabled or source.max_requests == 0 or not args.probe_official_source or not _probe_official_source():
                raise ValueError("official company source is not verified and enabled")
            partitions = store.partitions(args.census_id)
            sample_plan = (SamplePlanStore(engine).details(args.permit_id)
                           if args.phase == "COVERAGE_A1_SAMPLE" else None)
            if sample_plan and (sample_plan["census_id"] != args.census_id or
                                not SamplePlanStore(engine).verify_baseline(args.permit_id)):
                raise ValueError("A1 sample plan or cached A0 baseline changed")
            config_hash = configuration_hash(
                census_id=args.census_id, limits=limits, partitions=partitions,
                pricing=pricing, source_config=source,
                sample_plan_hash=sample_plan["plan_hash"] if sample_plan else None,
            )
            with engine.connect() as connection:
                import sqlalchemy as sa

                from signals.persistence.schema import acquisition_census_permit
                permit_row = connection.execute(sa.select(acquisition_census_permit).where(
                    acquisition_census_permit.c.permit_id == args.permit_id,
                )).mappings().one_or_none()
            if permit_row is None or permit_row["configuration_hash"] != config_hash:
                raise ValueError("missing or mismatched execution permit")
            api_key = resolve_apollo_key(dict(os.environ), phase=args.phase,
                                         expected_ref=permit_row["apollo_secret_ref"])
            account = _probe_apollo_account(api_key)
            if not account_capacity_ready(account, pricing, limits):
                raise ValueError("Apollo account capacity or rate limits unavailable")
            if args.phase == "COVERAGE_A1_SAMPLE" and (
                account is None or account.organization_search_day_consumed is None
            ):
                raise ValueError("A1 requires the free Apollo Organization Search counter")
            PermitStore.validate_terms(
                ExecutionPermit.model_validate({
                    **dict(permit_row),
                    **{key: permit_row[key].replace(tzinfo=dt.UTC) for key in
                       ("issued_at", "valid_from", "expires_at")},
                }), pricing=pricing, limits=limits,
            )
            operations = (
                ProgramOperationalContext.model_validate_json(args.operations.read_bytes())
                if args.operations else ProgramOperationalContext()
            )
            program_id = AcquisitionProgramStore(engine).register(config, at=now)
            if store.status(args.census_id)["program_id"] != program_id:
                raise ValueError("census/program configuration identity mismatch")
            acquisition = AcquisitionStore(engine, clock=lambda: now)
            shadow = MilomailShadowRuntime(
                engine, acquisition, keys, _ForbiddenInstantly(),  # type: ignore[arg-type]
            )
            with (
                httpx.Client(timeout=20.0, follow_redirects=False) as client,
                httpx.Client(timeout=source.timeout_seconds, follow_redirects=False) as official_client,
            ):
                official_matcher = OfficialCompanyMatcher(
                    engine, source, client=official_client, census_id=args.census_id,
                )
                usage_guard = None
                if args.phase == "COVERAGE_A1_SAMPLE":
                    usage_guard = A1UsageGuard(
                        engine, permit_id=args.permit_id,
                        probe=lambda: _probe_apollo_account(api_key),
                    )
                    usage_guard.begin(at=now)
                runner = CensusRunner(
                    engine,
                    census_id=args.census_id,
                    program_id=program_id,
                    config=config,
                    limits=limits,
                    organizations=ApolloOrganizationSearchClient(api_key=api_key, client=client),
                    companies=cast(ApolloCompanyResearchClient, (
                        _ForbiddenApolloOperation() if args.phase == "COVERAGE_A1_SAMPLE"
                        else ApolloCompanyResearchClient(api_key=api_key, client=client)
                    )),
                    contacts=cast(ApolloContactDiscoveryClient, (
                        _ForbiddenApolloOperation() if args.phase == "COVERAGE_A1_SAMPLE"
                        else ApolloContactDiscoveryClient(api_key=api_key, client=client)
                    )),
                    mail_provider=MailProviderDetector(
                        DnsMXResolver(), ttl_seconds=config.mx_cache_ttl_seconds,
                        timeout_seconds=config.dns_timeout_seconds,
                        attempts=config.dns_attempts,
                    ),
                    company_activity=lambda _: ActiveCompanyEvidence(status="UNKNOWN"),
                    company_activity_for_candidate=lambda company, candidate: official_matcher.assess(
                        company, candidate, at=dt.datetime.now(dt.UTC),
                    ).activity(),
                    acquisition=acquisition,
                    shadow=shadow,
                    operations=operations,
                    official_matcher=official_matcher if args.phase == "COVERAGE_A1_SAMPLE" else None,
                    usage_after_checkpoint=(usage_guard.after_checkpoint
                                            if usage_guard is not None else None),
                )
                runner.run(at=now, phase=args.phase, permit_id=args.permit_id,
                           configuration_hash=config_hash, database_id=database.database_id,
                           smoke_first_page_only=args.a0)
            result = store.report(args.census_id)
            if usage_guard is not None:
                result["a1_usage"] = usage_guard.status()
        print(json.dumps(result, default=str, sort_keys=True, ensure_ascii=False))
        return 3 if result.get("status") == "REVIEW_REQUIRED" else 0
    except Exception as error:  # noqa: BLE001 — process boundary must redact all failures
        # No exception text, URL, key, address or provider payload reaches logs.
        print(f"status=ERROR code={type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
