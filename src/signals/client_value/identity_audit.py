"""Bounded, resumable administrative identity reconciliation; no provider access.

Run registry pages first, then account pages. Dry-run is the default: the exact
resolver executes in a rolled-back transaction, including its account lock.
Only an explicit --execute commits. Historical private rows are never deleted.
Reports contain opaque identifiers, counts and closed reasons, never note bodies,
person names, emails, phone numbers, or exception messages / database URLs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.client_value.company_identity import (
    exact_french_siren,
    register_alias,
    resolve_subject,
)
from signals.companies.schema import saas_company
from signals.engagement.prospecting_schema import (
    account_company_alias_override,
    account_company_membership,
    company_manual_contact,
    company_subject_alias,
)
from signals.engagement.schema import company_contact, company_note
from signals.persistence.database import create_database_engine
from signals.persistence.schema import materialized_signal

MAX_BATCH_SIZE = 1000
MAX_ALIASES_PER_SUBJECT = 1000


def _account_keys():
    # Historical/draft profiles are identity references, not signal permissions.
    # This administrative query exposes no market facts and grants no membership.
    holders = sa.select(target_icp.c.account_id, saas_company.c.company_key).select_from(
        target_icp.join(
            materialized_signal, materialized_signal.c.target_icp_id == target_icp.c.target_icp_id
        ).join(
            saas_company,
            saas_company.c.identity_fingerprint
            == materialized_signal.c.company_identity_fingerprint,
        )
    )
    return sa.union(
        holders,
        *(
            sa.select(table.c.account_id, table.c.company_key)
            for table in (
                company_note,
                company_contact,
                company_manual_contact,
                account_company_membership,
            )
        ),
        sa.select(
            account_company_alias_override.c.account_id,
            account_company_alias_override.c.alias_company_key.label("company_key"),
        ),
    ).subquery()


def _registry_item(connection, row, *, now):
    key = row["company_key"]
    siren = exact_french_siren(row["official_identifiers"], country=row["official_country"])
    base = {"company_key": key}
    if siren is None:
        return {**base, "status": "unresolved", "reason": "no_unambiguous_exact_identifier"}
    canonical = f"cmp_directory_{siren}"
    prior = connection.scalar(
        sa.select(company_subject_alias.c.canonical_company_key).where(
            company_subject_alias.c.alias_company_key == key,
        )
    )
    actual = register_alias(connection, company_key=key, siren=siren, now=now)
    if prior is not None and prior != canonical:
        return {
            **base,
            "status": "conflict",
            "reason": "public_alias_binding_conflict",
            "canonical_company_key": prior,
            "candidate_company_key": canonical,
        }
    if actual != canonical:
        return {
            **base,
            "status": "conflict",
            "reason": "public_alias_binding_conflict",
            "canonical_company_key": actual,
            "candidate_company_key": canonical,
        }
    return {
        **base,
        "status": "registered",
        "reason": "exact_identifier",
        "canonical_company_key": canonical,
    }


def _account_item(connection, row, *, now):
    base = {"account_id": row["account_id"], "company_key": row["company_key"]}
    canonical = connection.scalar(
        sa.select(company_subject_alias.c.canonical_company_key).where(
            company_subject_alias.c.alias_company_key == row["company_key"],
            company_subject_alias.c.resolution_status == "exact",
        )
    )
    if canonical is not None:
        size = connection.scalar(
            sa.select(sa.func.count())
            .select_from(company_subject_alias)
            .where(
                company_subject_alias.c.canonical_company_key == canonical,
                company_subject_alias.c.resolution_status == "exact",
            )
        )
        if size > MAX_ALIASES_PER_SUBJECT:
            return {
                **base,
                "status": "blocked",
                "reason": "alias_group_limit",
                "canonical_company_key": canonical,
            }
    subject = resolve_subject(connection, **base, now=now)
    reasons = {
        "resolved": "exact_identifier",
        "isolated": "legacy_private_values_conflict",
        "unresolved": "no_registered_exact_alias",
    }
    return {
        **base,
        "status": subject.resolution,
        "reason": reasons[subject.resolution],
        "canonical_company_key": subject.canonical_company_key,
        "private_subject_key": subject.private_subject_key,
    }


def audit_identity_batch(
    engine: sa.Engine,
    *,
    phase: str,
    now: dt.datetime,
    execute: bool = False,
    limit: int = 100,
    after_account_id: str = "",
    after_company_key: str = "",
) -> dict:
    """One atomic page. `complete` means cursor exhaustion, not absence of issues.

    Both phases are replayable. Re-run registry from its beginning after any new
    source imports before starting account reconciliation. Resume a phase with
    the returned cursor; do not reuse a registry cursor for the accounts phase.
    Account pages are bounded by (account, alias), not an unbounded account fanout.
    A canonical group larger than MAX_ALIASES_PER_SUBJECT is reported for review.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_BATCH_SIZE:
        raise ValueError("limit must be an integer between 1 and 1000")
    if phase not in ("registry", "accounts"):
        raise ValueError("phase must be registry or accounts")
    if type(execute) is not bool:
        raise ValueError("execute must be boolean")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    if any(
        not isinstance(key, str) or len(key) > 64 for key in (after_account_id, after_company_key)
    ):
        raise ValueError("invalid identity audit cursor")
    if phase == "registry" and after_account_id:
        raise ValueError("registry cursor cannot include an account")
    if phase == "accounts" and bool(after_account_id) != bool(after_company_key):
        raise ValueError("account cursor requires both keys")
    cursor = {"after_account_id": after_account_id, "after_company_key": after_company_key}
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            if phase == "registry":
                query = (
                    sa.select(
                        saas_company.c.company_key,
                        saas_company.c.official_identifiers,
                        saas_company.c.official_country,
                    )
                    .where(
                        saas_company.c.company_key > after_company_key,
                    )
                    .order_by(saas_company.c.company_key)
                )
            else:
                keys = _account_keys()
                query = (
                    sa.select(keys)
                    .where(
                        sa.or_(
                            keys.c.account_id > after_account_id,
                            sa.and_(
                                keys.c.account_id == after_account_id,
                                keys.c.company_key > after_company_key,
                            ),
                        )
                    )
                    .order_by(keys.c.account_id, keys.c.company_key)
                )
            rows = connection.execute(query.limit(limit + 1)).mappings().all()
            selected = rows[:limit]
            items = [
                (_registry_item if phase == "registry" else _account_item)(
                    connection,
                    row,
                    now=now,
                )
                for row in selected
            ]
            if selected:
                cursor = {
                    "after_account_id": selected[-1].get("account_id", ""),
                    "after_company_key": selected[-1]["company_key"],
                }
            counts = dict(Counter(item["status"] for item in items))
            result = {
                "phase": phase,
                "dry_run": not execute,
                "selected": len(selected),
                "complete": len(rows) <= limit,
                "cursor": cursor,
                "counts": counts,
                "needs_review": sum(
                    counts.get(key, 0) for key in ("isolated", "conflict", "blocked")
                ),
                "items": items,
            }
            transaction.commit() if execute else transaction.rollback()
            return result
        except BaseException:
            transaction.rollback()
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("registry", "accounts"), required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--after-account-id", default="")
    parser.add_argument("--after-company-key", default="")
    parser.add_argument("--execute", action="store_true", help="commit this bounded page")
    arguments = parser.parse_args(argv)
    engine = None
    try:
        engine = create_database_engine()
        result = audit_identity_batch(engine, now=dt.datetime.now(tz=dt.UTC), **vars(arguments))
    except (ValueError, RuntimeError):
        print("identity_audit_configuration_invalid", file=sys.stderr)
        return 2
    except sa.exc.SQLAlchemyError:
        print("identity_audit_persistence_failed", file=sys.stderr)
        return 4
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
