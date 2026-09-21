"""Operator CLI for a disabled-by-default Milo Mail SHADOW census."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import NoReturn

import httpx
from alembic import command

from signals.acquisition.store import AcquisitionStore
from signals.acquisition_programs.apollo_account import ApolloAccountProbe
from signals.acquisition_programs.census import CensusLimits, CensusStore, build_partitions
from signals.acquisition_programs.census_readiness import (
    ApolloCreditPricing,
    DatabaseAuthorization,
    ExecutionPermit,
    PermitStore,
    configuration_hash,
    database_revisions,
    migration_ready,
    preflight,
)
from signals.acquisition_programs.census_runtime import CensusRunner
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

_HEAD = "0072_milomail_census_readiness"


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        self.exit(2, "status=INVALID_ARGUMENTS\n")


class _ForbiddenInstantly:
    def __getattr__(self, _name: str) -> None:
        raise RuntimeError("Instantly is unavailable to the census")


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
    plan = commands.add_parser("plan", help="persist deterministic partitions; no Apollo calls")
    plan.add_argument("--program-config", type=Path, required=True)
    for name in ("run", "resume"):
        command = commands.add_parser(name, help="bounded Apollo preparation in SHADOW")
        command.add_argument("--census-id", required=True)
        command.add_argument("--program-config", type=Path, required=True)
        command.add_argument("--operations", type=Path)
        command.add_argument("--authorize-paid-apollo", action="store_true")
        command.add_argument("--phase", choices=("COVERAGE", "ENRICHMENT"))
        command.add_argument("--permit-id")
        command.add_argument("--database-authorization", type=Path)
        command.add_argument("--pricing", type=Path)
        command.add_argument("--probe-official-source", action="store_true")
        command.add_argument("--probe-apollo-free", action="store_true")
    pre = commands.add_parser("preflight", help="read-only checks before an authorized run")
    pre.add_argument("--census-id", required=True)
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
        if name == "purge-cache":
            command.add_argument("--acknowledge-cache-purge", action="store_true")
    usage = commands.add_parser(
        "reconcile-usage", help="record externally verified Apollo credits and CHF cost"
    )
    usage.add_argument("--census-id", required=True)
    usage.add_argument("--actual-credits", type=int, required=True)
    usage.add_argument("--actual-cost-chf", type=Decimal, required=True)
    usage.add_argument("--usage-evidence-ref", required=True)
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
    return result.stdout.strip() if result.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = dt.datetime.now(dt.UTC)
    try:
        # The CLI never migrates a database, and no default database URL exists.
        engine = create_database_engine()
        if args.command == "migrate-authorized":
            database = _read_model(args.database_authorization, DatabaseAuthorization)
            if not args.acknowledge_migration or database is None:
                raise ValueError("reviewed non-production migration requires acknowledgement")
            database.check_identity(engine, at=now)
            if database_revisions(engine) != ("0071_milomail_shadow_census",):
                raise ValueError("only an exact 0071 census database can be migrated")
            command.upgrade(alembic_config(engine), _HEAD)
            print(json.dumps({"status": "MIGRATED", "revision": current_revision(engine)}))
            return 0
        if args.command != "preflight" and not migration_ready(engine):
            raise ValueError("census database migration is not at the reviewed head")
        store = CensusStore(engine)
        if args.command == "preflight":
            database = _read_model(args.database_authorization, DatabaseAuthorization)
            pricing = _read_model(args.pricing, ApolloCreditPricing)
            source = OfficialSourceConfig.from_environment(os.environ)
            result = preflight(
                engine, census_id=args.census_id,
                limits=CensusLimits.from_environment(os.environ), database=database,
                pricing=pricing,
                apollo_key_present=bool(os.environ.get("MILOMAIL_CENSUS_APOLLO_API_KEY")),
                source_enabled=source.enabled, source_requests=source.max_requests,
                source_available=args.probe_official_source and _probe_official_source(),
                source_rate_limit_per_minute=source.rate_limit_per_minute,
                source_cache_ttl_days=source.cache_ttl_days,
                source_config=source,
                apollo_account=_probe_apollo_account(
                    os.environ.get("MILOMAIL_CENSUS_APOLLO_API_KEY", "")
                ) if args.probe_apollo_free else None,
                suppression_keyring=_optional_keyring(dict(os.environ)),
                at=now, permit_id=args.permit_id, code_sha=_code_sha(),
                app_version=version("signals"),
            )
        elif args.command == "issue-permit":
            database = _read_model(args.database_authorization, DatabaseAuthorization)
            permit = _read_model(args.permit, ExecutionPermit)
            pricing = _read_model(args.pricing, ApolloCreditPricing)
            limits = CensusLimits.from_environment(os.environ)
            limits.require_run_authorization()
            if database is None or permit is None or pricing is None:
                raise ValueError("permit, pricing and database authorization are required")
            pricing.check(limits, at=now)
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
            result = (
                store.status(args.census_id)
                if args.command == "status" else store.report(args.census_id)
            )
        elif args.command == "purge-cache":
            if not args.acknowledge_cache_purge:
                raise ValueError("cache purge requires explicit acknowledgement")
            cleared = store.purge_contact_cache(args.census_id, at=now)
            result = {"census_id": args.census_id, "contact_cache_rows_cleared": cleared,
                      "status": store.status(args.census_id)["status"]}
        elif args.command == "reconcile-usage":
            if not args.acknowledge_exclusive_attribution:
                raise ValueError("exclusive Apollo attribution requires explicit acknowledgement")
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
        else:
            if not args.authorize_paid_apollo:
                raise ValueError("paid Apollo use needs an explicit command flag")
            if not args.phase or not args.permit_id:
                raise ValueError("a bounded phase and execution permit are required")
            limits = CensusLimits.from_environment(os.environ)
            limits.require_run_authorization()
            database = _read_model(args.database_authorization, DatabaseAuthorization)
            pricing = _read_model(args.pricing, ApolloCreditPricing)
            if database is None or pricing is None:
                raise ValueError("database authorization and verified Apollo pricing are required")
            database.check(engine, at=now)
            pricing.check(limits, at=now)
            config = load_program_config(args.program_config)
            if config.enabled or config.campaign_mode != "SHADOW":
                raise ValueError("census requires a disabled SHADOW program")
            api_key = os.environ.get("MILOMAIL_CENSUS_APOLLO_API_KEY", "")
            if not api_key:
                raise ValueError("dedicated census Apollo credential is missing")
            if not args.probe_apollo_free:
                raise ValueError("free Apollo account verification is required")
            account = _probe_apollo_account(api_key)
            if (account is None or not account.credential_valid or
                    not account.usage_stats_available or not account.rate_stats_available or
                    account.credit_balance is None or account.credit_balance < limits.max_apollo_credits):
                raise ValueError("Apollo account capacity or rate limits unavailable")
            keys = _keyring(dict(os.environ))
            source = OfficialSourceConfig.from_environment(os.environ)
            if not source.enabled or source.max_requests == 0 or not args.probe_official_source or not _probe_official_source():
                raise ValueError("official company source is not verified and enabled")
            partitions = store.partitions(args.census_id)
            config_hash = configuration_hash(
                census_id=args.census_id, limits=limits, partitions=partitions,
                pricing=pricing, source_config=source,
            )
            with engine.connect() as connection:
                import sqlalchemy as sa

                from signals.persistence.schema import acquisition_census_permit
                permit_row = connection.execute(sa.select(acquisition_census_permit).where(
                    acquisition_census_permit.c.permit_id == args.permit_id,
                )).mappings().one_or_none()
            if permit_row is None or permit_row["configuration_hash"] != config_hash:
                raise ValueError("missing or mismatched execution permit")
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
                runner = CensusRunner(
                    engine,
                    census_id=args.census_id,
                    program_id=program_id,
                    config=config,
                    limits=limits,
                    organizations=ApolloOrganizationSearchClient(api_key=api_key, client=client),
                    companies=ApolloCompanyResearchClient(api_key=api_key, client=client),
                    contacts=ApolloContactDiscoveryClient(api_key=api_key, client=client),
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
                )
                runner.run(at=now, phase=args.phase, permit_id=args.permit_id,
                           configuration_hash=config_hash, database_id=database.database_id)
            result = store.report(args.census_id)
        print(json.dumps(result, default=str, sort_keys=True, ensure_ascii=False))
        return 3 if result.get("status") == "REVIEW_REQUIRED" else 0
    except Exception as error:  # noqa: BLE001 — process boundary must redact all failures
        # No exception text, URL, key, address or provider payload reaches logs.
        print(f"status=ERROR code={type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
