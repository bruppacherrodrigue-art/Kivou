"""Operator-only B1 commands; output contains aggregates and opaque references only."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
from collections import Counter
from decimal import Decimal
from pathlib import Path

import httpx
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from signals.acquisition_programs.apollo_account import ApolloAccountProbe, ApolloAccountState
from signals.acquisition_programs.b1_decisions import B1DecisionStore
from signals.acquisition_programs.census import CensusLimits
from signals.acquisition_programs.census_b1 import B1Caps, B1PlanStore
from signals.acquisition_programs.census_b1_runtime import B1Runner
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
from signals.acquisition_programs.export_preview import (
    ExportLead,
    ExportSector,
    build_export_preview,
)
from signals.acquisition_programs.http_accounting_store import LegalHttpAttemptStore
from signals.acquisition_programs.legal_pages import LegalPageResolver
from signals.acquisition_programs.mail_provider import DnsMXResolver, MailProviderDetector
from signals.acquisition_programs.official_company import (
    OfficialCompanyMatcher,
    OfficialSourceConfig,
)
from signals.compliance.milomail_rules import POLICY_VERSION_V2
from signals.compliance.suppression import MILOMAIL_SUPPRESSION_SCOPE, SuppressionIdentityKeyring
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.persistence.database import create_database_engine
from signals.persistence.schema import (
    acquisition_census_b1_decision,
    acquisition_census_b1_entry,
    acquisition_census_b1_ready_lead,
    acquisition_census_partition,
    acquisition_census_permit,
    acquisition_contact_suppression,
)
from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient


def _model(path: Path, model):
    return model.model_validate_json(path.read_text())


def _partitions(engine: sa.Engine, census_id: str) -> tuple[dict, ...]:
    with engine.connect() as connection:
        return tuple(dict(row) for row in connection.execute(sa.select(
            acquisition_census_partition.c.partition_id,
            acquisition_census_partition.c.filter_signature,
        ).where(acquisition_census_partition.c.census_id == census_id)).mappings())


def _probe(secret_ref: str) -> tuple[str, ApolloAccountState]:
    key = resolve_apollo_key(dict(os.environ), phase="FRANCE_B1_READY_BASE",
                             expected_ref=secret_ref)
    with httpx.Client(timeout=10) as client:
        account = ApolloAccountProbe(api_key=key, client=client).inspect_free()
    if (not account.credential_valid or account.credit_balance is None or
            not account.usage_stats_available or not account.rate_stats_available):
        raise ValueError("Apollo free account probe is unavailable")
    return key, account


def _pricing(path: Path, account: ApolloAccountState, at: dt.datetime) -> ApolloCreditPricing:
    original = _model(path, ApolloCreditPricing)
    if original.billing_basis != "PREPAID_SHARED_POOL" or original.person_enrichment_credits_max != 9:
        raise ValueError("B1 requires the verified prepaid baseline and no-phone credit envelope")
    return original.model_copy(update={
        "person_enrichment_credits_max": 1,
        "credit_balance": account.credit_balance,
        "credit_balance_observed_at": at,
    })


def _suppressed(engine: sa.Engine, keys: SuppressionIdentityKeyring, email: str,
                *, at: dt.datetime) -> bool:
    hashes = keys.identities_for_email(email, scope=MILOMAIL_SUPPRESSION_SCOPE)
    table = acquisition_contact_suppression
    with engine.connect() as connection:
        versions = tuple(connection.execute(sa.select(table.c.identity_key_version).where(
            table.c.scope == MILOMAIL_SUPPRESSION_SCOPE,
        ).distinct()).scalars())
        keys.require_versions_covered(versions)
        return bool(connection.scalar(sa.select(sa.func.count()).select_from(table).where(
            table.c.scope == MILOMAIL_SUPPRESSION_SCOPE,
            table.c.identity_hmac.in_(tuple(hashes.values())),
            table.c.effective_at <= at,
        )))


def _safe_report(engine: sa.Engine, census_id: str, permit_id: str,
                 *, keys: SuppressionIdentityKeyring | None, at: dt.datetime) -> dict:
    report = B1PlanStore(engine).summary(permit_id)
    table = acquisition_census_b1_decision
    with engine.connect() as connection:
        decisions = connection.execute(sa.select(
            table.c.candidate_id, table.c.decision, table.c.reason_codes,
            table.c.activity_status, table.c.decided_at,
            table.c.decision_id,
        ).where(
            table.c.ruleset_version == POLICY_VERSION_V2,
        ).order_by(table.c.decided_at.desc(), table.c.decision_id.desc())).all()
        lead_status = connection.execute(sa.select(
            acquisition_census_b1_ready_lead.c.decision,
            acquisition_census_b1_ready_lead.c.segment,
            sa.func.count(),
        ).group_by(acquisition_census_b1_ready_lead.c.decision,
                   acquisition_census_b1_ready_lead.c.segment)).all()
        b1_results = connection.execute(sa.select(acquisition_census_b1_entry.c.result).where(
            acquisition_census_b1_entry.c.plan_id == permit_id,
            acquisition_census_b1_entry.c.status == "COMPLETE",
        )).scalars().all()
    latest: dict[str, str] = {}
    reason_counts: Counter[str] = Counter()
    activity_counts: Counter[str] = Counter()
    for candidate_id, decision, reasons, activity, _decided_at, _decision_id in decisions:
        if candidate_id not in latest:
            latest[candidate_id] = decision
            reason_counts.update(reasons or [])
            activity_counts[activity] += 1
    report.update({
        "phase": "FRANCE_B1_READY_BASE",
        "replayed_decisions_v2": dict(Counter(latest.values())),
        "replayed_reason_codes_v2": dict(reason_counts),
        "replayed_activity_v2": dict(activity_counts),
        "new_leaders_found": sum(bool(result and result.get("leader_found"))
                                 for result in b1_results),
        "new_professional_emails_found": sum(bool(result and result.get(
            "professional_email_found")) for result in b1_results),
        "verified_leads_by_decision_segment": [
            {"decision": decision, "segment": segment, "count": count}
            for decision, segment, count in lead_status
        ],
        "http_attempts": LegalHttpAttemptStore(engine).summary(census_id),
        "instantly_mutations": 0, "emails_sent": 0,
    })
    if keys is not None:
        with engine.connect() as connection:
            lead_rows = connection.execute(sa.select(acquisition_census_b1_ready_lead).where(
                acquisition_census_b1_ready_lead.c.program_key == "milomail",
            )).mappings().all()
        sector_labels: dict[str, ExportSector] = {
            "digital_or_creative_agency": "Agences",
            "consulting": "Conseil",
            "recruiting_agency": "Recrutement",
        }
        records = tuple(ExportLead(
            status=row["decision"], email=row["professional_email"],
            company_domain=row["company_domain"],
            sector=sector_labels.get(row["sector"]),
            country_code=row["country"],
        ) for row in lead_rows)
        preview_key = hmac.new(keys.keys[keys.current_key_version],
                               b"milomail-export-preview-v1", hashlib.sha256).digest()
        preview = build_export_preview(
            records, is_suppressed=lambda email: _suppressed(engine, keys, email, at=at),
            hmac_key=preview_key, campaign_ref="milomail-france-b1",
        )
        report["instantly_dry_run"] = preview.model_dump(mode="json")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="milomail-b1")
    parser.add_argument("command", choices=("plan", "replay-b0", "replay-b1", "preflight", "issue-permit",
                                            "run", "resume", "status", "report",
                                            "reconcile-usage", "revoke"))
    parser.add_argument("--census-id", required=True)
    parser.add_argument("--permit-id", required=True)
    parser.add_argument("--database-authorization", type=Path, required=True)
    parser.add_argument("--pricing", type=Path)
    parser.add_argument("--program-config", type=Path)
    parser.add_argument("--seed")
    parser.add_argument("--authorize-paid-apollo", action="store_true")
    parser.add_argument("--max-actions", type=int, default=25)
    args = parser.parse_args(argv)
    now = dt.datetime.now(dt.UTC)
    try:
        engine = create_database_engine()
        database = _model(args.database_authorization, DatabaseAuthorization)
        database.check(engine, at=now)
        if not migration_ready(engine) or engine.url.database != "kivou_milomail_census_a0":
            raise ValueError("B1 requires isolated staging census database at 0076")
        store = B1PlanStore(engine)
        if args.command in {"status", "report"}:
            status_keys = _keyring(dict(os.environ)) if args.command == "report" else None
            output = (_safe_report(engine, args.census_id, args.permit_id,
                                   keys=status_keys, at=now) if args.command == "report"
                      else store.summary(args.permit_id))
        elif args.command in {"replay-b0", "replay-b1"}:
            if not args.program_config:
                raise ValueError("B1 replay requires program configuration")
            config = load_program_config(args.program_config).model_copy(
                update={"policy_version": POLICY_VERSION_V2})
            replay_keys = _keyring(dict(os.environ))
            decisions = B1DecisionStore(engine)
            suppression = lambda email: _suppressed(engine, replay_keys, email, at=now)
            output = (decisions.replay_b0(
                census_id=args.census_id, config=config, at=now,
                is_suppressed=suppression,
            ) if args.command == "replay-b0" else decisions.replay_b1(
                plan_id=args.permit_id, config=config, at=now,
                is_suppressed=suppression,
            ))
        elif args.command == "revoke":
            PermitStore(engine).revoke(args.permit_id)
            output = {"permit_id": args.permit_id, "status": "REVOKED"}
        else:
            if not args.pricing:
                raise ValueError("B1 needs a verified pricing attestation")
            caps = B1Caps.from_environment(os.environ)
            ref = (os.environ.get("MILOMAIL_CENSUS_APOLLO_SECRET_REF") or
                   "MILOMAIL_CENSUS_APOLLO_API_KEY")
            key, account = _probe(ref)
            pricing = _pricing(args.pricing, account, now)
            source = OfficialSourceConfig.from_environment(os.environ)
            if args.command == "plan":
                if not args.seed:
                    raise ValueError("B1 plan needs a public deterministic seed")
                assert account.credit_balance is not None
                store.plan(args.census_id, permit_id=args.permit_id,
                           caps=caps, pool_balance=account.credit_balance,
                           seed=args.seed, at=now)
                output = store.summary(args.permit_id)
            else:
                plan = store.details(args.permit_id)
                limits = CensusLimits.model_validate(plan["cumulative_limits"])
                partitions = _partitions(engine, args.census_id)
                config_hash = configuration_hash(
                    census_id=args.census_id, limits=limits, partitions=partitions,
                    pricing=pricing, source_config=source,
                    sample_plan_hash=plan["plan_hash"],
                )
                checks = {
                    "database": "READY", "migration": "READY",
                    "nine_partitions": "READY" if len(partitions) == 9 else "INVALID",
                    "plan": "READY" if plan["caps"] == caps.__dict__ else "CHANGED",
                    "reserve": "READY" if account.credit_balance is not None and
                    account.credit_balance - max(
                        0, plan["caps"]["max_new_credits"] - plan["credits_reserved"]
                    ) >= 1000 else "LOW",
                    "official_source": "READY" if source.enabled and
                    source.rate_limit_per_minute <= 60 else "DISABLED",
                    "suppression": "READY", "pricing": "READY", "permit": "MISSING",
                }
                keys: SuppressionIdentityKeyring | None = None
                try:
                    keys = _keyring(dict(os.environ))
                    with engine.connect() as connection:
                        versions = tuple(connection.execute(sa.select(
                            acquisition_contact_suppression.c.identity_key_version,
                        ).where(acquisition_contact_suppression.c.scope ==
                                MILOMAIL_SUPPRESSION_SCOPE).distinct()).scalars())
                    keys.require_versions_covered(versions)
                except (ValueError, TypeError):
                    checks["suppression"] = "UNAVAILABLE"
                try:
                    pricing.check(limits, at=now, phase="FRANCE_B1_READY_BASE")
                except ValueError:
                    checks["pricing"] = "INVALID"
                with engine.connect() as connection:
                    permit = connection.execute(sa.select(acquisition_census_permit).where(
                        acquisition_census_permit.c.permit_id == args.permit_id,
                    )).mappings().one_or_none()
                if permit is not None:
                    checks["permit"] = "READY" if (
                        permit["status"] == "ACTIVE" and
                        permit["configuration_hash"] == config_hash and
                        permit["expires_at"].replace(tzinfo=dt.UTC) > now
                    ) else "INVALID"
                preflight = {
                    "phase": "FRANCE_B1_READY_BASE", "checks": checks,
                    "ready": all(value == "READY" for value in checks.values()),
                    "database_id": database_identity(engine)[0],
                    "pool_balance": account.credit_balance,
                    "max_new_credits": plan["caps"]["max_new_credits"],
                    "minimum_remaining_balance": 1000,
                    "new_pages_planned": len(plan["pages"]),
                    "companies_initially_planned": plan["companies_planned"],
                    "instantly_mutation_allowed": False,
                    "email_sending_allowed": False,
                    "max_incremental_charge_chf": "0.00",
                }
                if args.command == "reconcile-usage":
                    if account.credit_balance is None:
                        raise ValueError("B1 reconciliation requires the current Apollo balance")
                    output = store.reconcile_usage(
                        args.permit_id, pool_after=account.credit_balance, at=now,
                    )
                elif args.command == "preflight":
                    output = preflight
                elif args.command == "issue-permit":
                    if not all(value == "READY" for name, value in checks.items()
                               if name != "permit"):
                        raise ValueError("B1 configuration preflight is not ready")
                    permit_model = ExecutionPermit(
                        permit_id=args.permit_id, census_id=args.census_id,
                        phase="FRANCE_B1_READY_BASE", environment="staging",
                        database_id=database.database_id,
                        allowed_partitions=tuple(part["partition_id"] for part in partitions),
                        max_pages=len(plan["pages"]),
                        max_candidates=(plan["caps"]["max_new_pages"] * 25 +
                                        plan["caps"]["max_person_searches"]),
                        max_enrichments=plan["caps"]["max_enrichments"],
                        max_credits=plan["caps"]["max_new_credits"],
                        max_cost_chf=Decimal(0), price_chf_per_credit=None,
                        billing_basis="PREPAID_SHARED_POOL", apollo_secret_ref=ref,
                        pricing_reference=pricing.source_reference,
                        configuration_hash=config_hash, sample_plan_hash=plan["plan_hash"],
                        issued_by_reference="user-prompt-2026-09-22-b1-900-reserve1000",
                        issued_at=now, valid_from=now,
                        expires_at=min(now + dt.timedelta(hours=4), database.expires_at),
                    )
                    PermitStore(engine).issue(permit_model, database=database,
                                              pricing=pricing, limits=limits,
                                              at=now, source_config=source)
                    output = {"permit_id": args.permit_id,
                              "configuration_hash": config_hash,
                              "status": "ACTIVE"}
                else:
                    if not args.authorize_paid_apollo or not preflight["ready"]:
                        raise ValueError("B1 paid Apollo requires explicit flag and green preflight")
                    if not args.program_config:
                        raise ValueError("B1 run requires Milo Mail program config")
                    if keys is None:
                        raise ValueError("B1 suppression keyring unavailable")
                    config = load_program_config(args.program_config).model_copy(
                        update={"policy_version": POLICY_VERSION_V2})
                    with httpx.Client(timeout=20) as client:
                        runner = B1Runner(
                            engine, census_id=args.census_id, permit_id=args.permit_id,
                            config=config, limits=limits,
                            database_id=database.database_id,
                            configuration_hash=config_hash,
                            contacts=ApolloContactDiscoveryClient(api_key=key, client=client),
                            organizations=ApolloOrganizationSearchClient(api_key=key, client=client),
                            account_probe=lambda: ApolloAccountProbe(
                                api_key=key, client=client,
                            ).inspect_credits_free(),
                            detector=MailProviderDetector(DnsMXResolver()),
                            official=OfficialCompanyMatcher(
                                engine, source, client=client, census_id=args.census_id,
                                attempt_sink=LegalHttpAttemptStore(engine).record,
                            ),
                            legal_pages=LegalPageResolver(engine, client=client,
                                attempt_sink=LegalHttpAttemptStore(engine).record),
                            suppression_keys=keys,
                        )
                        output = runner.run(at=now, max_actions=args.max_actions)
        print(json.dumps(output, sort_keys=True, default=str))
        return 0
    except (ValueError, TypeError, SQLAlchemyError, RuntimeError) as error:
        # No provider response, identity, email or credential enters operator logs.
        print(json.dumps({"status": "ERROR", "error_type": type(error).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
