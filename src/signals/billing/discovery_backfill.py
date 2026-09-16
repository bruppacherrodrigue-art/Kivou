"""Safe catch-up for underfilled Discovery accounts; read-only by default.

Usage::

    python -m signals.billing.discovery_backfill --limit 500
    python -m signals.billing.discovery_backfill --limit 500 --apply

The first command only reports. ``--apply`` is deliberately required for any
grant mutation, and the underlying allocator remains idempotent and capped at
three named signals per account.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
from collections.abc import Callable, Sequence

import sqlalchemy as sa

from signals.accounts.schema import account, target_icp
from signals.billing import discovery
from signals.billing.catalogue import DISCOVERY_GRANT_LIMIT
from signals.persistence.database import create_database_engine


@dataclasses.dataclass(frozen=True)
class AccountReport:
    account_id: str
    granted_before: int
    eligible_candidates: int
    proposed_signal_ids: tuple[str, ...]
    granted_now: tuple[str, ...]
    scan_truncated: bool

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class CatchUpReport:
    mode: str
    as_of: dt.date
    zero_only: bool
    accounts_considered: int
    accounts_reported: int
    proposed_grants: int
    applied_grants: int
    accounts: tuple[AccountReport, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "as_of": self.as_of.isoformat(),
            "zero_only": self.zero_only,
            "accounts_considered": self.accounts_considered,
            "accounts_reported": self.accounts_reported,
            "proposed_grants": self.proposed_grants,
            "applied_grants": self.applied_grants,
            "accounts": [item.as_dict() for item in self.accounts],
        }


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _active_account_ids(connection: sa.Connection) -> tuple[str, ...]:
    return tuple(
        connection.scalars(
            sa.select(account.c.account_id)
            .where(
                sa.exists(
                    sa.select(sa.literal(1)).where(
                        target_icp.c.account_id == account.c.account_id,
                        target_icp.c.status == "active",
                        target_icp.c.plan_limit_code.is_(None),
                    )
                )
            )
            .order_by(account.c.account_id)
        )
    )


def catch_up(
    engine: sa.Engine,
    *,
    as_of: dt.date,
    now: dt.datetime,
    limit: int,
    apply: bool = False,
    zero_only: bool = True,
) -> CatchUpReport:
    """Report or fill a bounded set of existing underfilled accounts."""

    if limit < 1:
        raise ValueError("limit must be positive")
    with engine.connect() as connection:
        account_ids = _active_account_ids(connection)

    reports: list[AccountReport] = []
    considered = 0
    for account_id in account_ids:
        if len(reports) >= limit:
            break
        with engine.connect() as connection:
            preview = discovery.preview_initial_backfill(
                connection,
                account_id=account_id,
                as_of=as_of,
            )
        considered += 1
        if preview.plan_code != "discovery":
            continue
        granted_before = len(preview.granted_signal_keys)
        if granted_before >= DISCOVERY_GRANT_LIMIT or (zero_only and granted_before != 0):
            continue

        granted_now: tuple[str, ...] = ()
        if apply:
            with engine.begin() as connection:
                granted_now = discovery.reconcile_initial_backfill(
                    connection,
                    account_id=account_id,
                    as_of=as_of,
                    now=now,
                )
        reports.append(
            AccountReport(
                account_id=account_id,
                granted_before=granted_before,
                eligible_candidates=len(preview.eligible_signal_keys),
                proposed_signal_ids=preview.proposed_signal_keys,
                granted_now=granted_now,
                scan_truncated=preview.scan_truncated,
            )
        )

    return CatchUpReport(
        mode="apply" if apply else "dry_run",
        as_of=as_of,
        zero_only=zero_only,
        accounts_considered=considered,
        accounts_reported=len(reports),
        proposed_grants=sum(len(item.proposed_signal_ids) for item in reports),
        applied_grants=sum(len(item.granted_now) for item in reports),
        accounts=tuple(reports),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m signals.billing.discovery_backfill")
    parser.add_argument("--limit", type=_positive, default=500)
    parser.add_argument("--as-of", type=dt.date.fromisoformat)
    parser.add_argument(
        "--include-partial",
        action="store_true",
        help="also report/apply accounts already holding one or two lifetime grants",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="persist proposed grants; omitted means a strictly read-only dry run",
    )
    return parser


def main(
    arguments: Sequence[str] | None = None,
    *,
    engine_factory: Callable[[], sa.Engine] = create_database_engine,
    clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> int:
    parsed = _parser().parse_args(arguments)
    now = clock()
    if now.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    engine = engine_factory()
    try:
        report = catch_up(
            engine,
            as_of=parsed.as_of or now.date(),
            now=now,
            limit=parsed.limit,
            apply=parsed.apply,
            zero_only=not parsed.include_partial,
        )
    finally:
        engine.dispose()
    print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
