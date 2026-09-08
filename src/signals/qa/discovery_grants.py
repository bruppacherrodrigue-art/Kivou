"""Explicit QA-only reconciliation. Preview is read-only; apply binds its audit."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json

import sqlalchemy as sa

from signals.accounts.schema import account_landing_signal, target_icp
from signals.billing import discovery
from signals.billing.access import feed_access
from signals.billing.schema import discovery_signal_grant
from signals.ingestion.backfill import landing_cohort_plan
from signals.persistence import materialize_signal
from signals.persistence.database import create_database_engine
from signals.persistence.identity import signal_key
from signals.persistence.schema import materialized_signal


def reconcile_discovery_grants(
    engine: sa.Engine, *, account_id: str, now: dt.datetime,
    dry_run: bool = True, expected_audit: str | None = None,
) -> dict:
    """Replace only an explicitly marked QA token account, after reviewed preview.

    No migrations, provider calls, sessions or product events. Production/non-QA
    legacy grants are never reconciled by this entry point. The caller must pass
    the preview's audit_token back to apply, which rejects changed allocations,
    candidates or dates rather than silently applying a different selection.
    """
    if not account_id or not account_id.strip():
        raise ValueError("Explicit QA account_id required")
    with engine.begin() as connection:
        if dry_run and connection.dialect.name == "postgresql":
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        if not dry_run:
            discovery.lock_account(connection, account_id=account_id)
        landing = connection.execute(sa.select(account_landing_signal).where(
            account_landing_signal.c.account_id == account_id
        )).mappings().one_or_none()
        if landing is None or not landing["qa"]:
            raise ValueError("Account is not an explicitly marked QA token account")
        if feed_access(connection, account_id=account_id, as_of=now.date()).is_paid:
            raise ValueError("QA reconciliation is restricted to Discovery accounts")
        target = connection.scalar(sa.select(materialized_signal.c.target_icp_id).join(
            target_icp, materialized_signal.c.target_icp_id == target_icp.c.target_icp_id
        ).where(materialized_signal.c.signal_key == landing["signal_key"],
                target_icp.c.account_id == account_id))
        if target is None or not landing["opportunity_key"]:
            raise ValueError("QA bait has no account-owned materialization")
        before = discovery.cohort_audit(connection, account_id=account_id, now=now)
        plan = landing_cohort_plan(
            connection, target_icp_id=target, opportunity_key=landing["opportunity_key"],
            as_of=now.date(), materialized_at=now,
        )
        selected = [(key, prepared) for key, prepared in plan["prepared"]
                    if key in plan["grant_opportunities"]]
        facts = discovery.opportunity_facts(
            connection, [key for key, _prepared in selected], as_of=now.date()
        )
        proposed = [{"signal_key": signal_key(key, target_icp_id=target),
                     "opportunity_key": key,
                     "procedure_references": sorted(facts[key]["aliases"])}
                    for key, _prepared in selected]
        bait_preserved = any(row["signal_key"] == landing["signal_key"] for row in proposed)
        audit = {
            "account_id": account_id, "as_of": now.date().isoformat(),
            "before": before, "proposed_grants": proposed,
            "bait_preserved": bait_preserved, "candidates": plan["candidates"],
            "scan_truncated": plan["scan_truncated"],
            "eligible_procedures": len(proposed),
            "remaining": max(0, 3 - len(proposed)),
        }
        token = hashlib.sha256(json.dumps(audit, sort_keys=True).encode()).hexdigest()
        result = {**audit, "audit_token": token, "dry_run": dry_run, "after": before}
        if dry_run:
            return result
        if not expected_audit or expected_audit != token:
            raise ValueError("Reviewed dry-run audit_token required; rerun dry-run if state changed")
        if not bait_preserved or not 1 <= len(proposed) <= 3:
            raise ValueError("QA allocation cannot replace or remove the promised bait")
        connection.execute(sa.delete(discovery_signal_grant).where(
            discovery_signal_grant.c.account_id == account_id
        ))
        for (key, prepared), expected in zip(selected, proposed, strict=True):
            actual = materialize_signal(connection, **prepared).signal_key
            if actual != expected["signal_key"]:
                raise ValueError("QA materialization identity changed; transaction rolled back")
            connection.execute(sa.insert(discovery_signal_grant).values(
                account_id=account_id, signal_key=actual, opportunity_key=key,
                granted_at=now, created_at=now,
            ))
        result["after"] = discovery.cohort_audit(connection, account_id=account_id, now=now)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Read-only preview (default)")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-audit")
    args = parser.parse_args()
    try:
        engine = create_database_engine()
    except RuntimeError as exc:
        parser.error(str(exc))
    try:
        result = reconcile_discovery_grants(
            engine, account_id=args.account_id, now=dt.datetime.now(dt.UTC),
            dry_run=not args.apply, expected_audit=args.expected_audit,
        )
        print(json.dumps(result, sort_keys=True, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
