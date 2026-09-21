"""Operator CLI for a disabled-by-default Milo Mail SHADOW census."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import NoReturn

import httpx

from signals.acquisition.store import AcquisitionStore
from signals.acquisition_programs.census import CensusLimits, CensusStore, build_partitions
from signals.acquisition_programs.census_runtime import CensusRunner
from signals.acquisition_programs.config import load_program_config
from signals.acquisition_programs.mail_provider import DnsMXResolver, MailProviderDetector
from signals.acquisition_programs.pipeline import ActiveCompanyEvidence, ProgramOperationalContext
from signals.acquisition_programs.runtime import MilomailShadowRuntime
from signals.acquisition_programs.store import AcquisitionProgramStore
from signals.company_research.apollo import ApolloCompanyResearchClient
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.persistence.database import create_database_engine, current_revision
from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient

_HEAD = "0071_milomail_shadow_census"


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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = dt.datetime.now(dt.UTC)
    try:
        # The CLI never migrates a database, and no default database URL exists.
        engine = create_database_engine()
        if current_revision(engine) != _HEAD:
            raise ValueError("census database migration is not at the reviewed head")
        store = CensusStore(engine)
        if args.command in {"status", "report"}:
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
            limits = CensusLimits.from_environment(os.environ)
            limits.require_run_authorization()
            config = load_program_config(args.program_config)
            if config.enabled or config.campaign_mode != "SHADOW":
                raise ValueError("census requires a disabled SHADOW program")
            api_key = os.environ.get("MILOMAIL_CENSUS_APOLLO_API_KEY", "")
            if not api_key:
                raise ValueError("dedicated census Apollo credential is missing")
            keys = _keyring(dict(os.environ))
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
            with httpx.Client(timeout=20.0, follow_redirects=False) as client:
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
                    # Apollo does not establish an active legal entity. Until
                    # public registry evidence is supplied, policy holds it.
                    company_activity=lambda _: ActiveCompanyEvidence(status="UNKNOWN"),
                    acquisition=acquisition,
                    shadow=shadow,
                    operations=operations,
                )
                runner.run(at=now)
            result = store.report(args.census_id)
        print(json.dumps(result, default=str, sort_keys=True, ensure_ascii=False))
        return 3 if result.get("status") == "REVIEW_REQUIRED" else 0
    except Exception as error:  # noqa: BLE001 — process boundary must redact all failures
        # No exception text, URL, key, address or provider payload reaches logs.
        print(f"status=ERROR code={type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
