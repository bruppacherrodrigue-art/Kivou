"""Dry-by-default maintenance for holder jobs attached to active accounts."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.companies.schema import winner_enrichment_job
from signals.persistence.database import create_database_engine
from signals.persistence.schema import materialized_signal


@dataclass(frozen=True)
class ActiveWinnerQueueReport:
    total_pending: int
    active_pending: int
    inactive_purge_candidates: int
    active_distinct_holders: int
    deleted: int


def active_account_signal_exists(signal_key) -> sa.ColumnElement[bool]:
    """Whether a signal belongs to a current, non-invalidated active ICP."""

    return sa.exists(
        sa.select(sa.literal(1))
        .select_from(
            materialized_signal.join(
                target_icp,
                materialized_signal.c.target_icp_id == target_icp.c.target_icp_id,
            )
        )
        .where(
            materialized_signal.c.signal_key == signal_key,
            materialized_signal.c.invalidated_at.is_(None),
            materialized_signal.c.target_icp_revision == target_icp.c.matching_revision,
            target_icp.c.status == "active",
        )
    )


def maintain_active_winner_queue(
    engine: sa.Engine, *, apply: bool = False
) -> ActiveWinnerQueueReport:
    """Measure the inactive pending queue, deleting it only with explicit opt-in."""

    pending = winner_enrichment_job.c.status == "pending"
    active = active_account_signal_exists(winner_enrichment_job.c.signal_key)
    active_holder = sa.case(
        (
            sa.func.length(materialized_signal.c.winner_identifier_value) == 14,
            sa.func.substr(materialized_signal.c.winner_identifier_value, 1, 9),
        ),
        (
            sa.func.length(materialized_signal.c.winner_identifier_value) == 9,
            materialized_signal.c.winner_identifier_value,
        ),
        else_=materialized_signal.c.company_identity_fingerprint,
    )
    with engine.begin() as connection:
        counts = connection.execute(
            sa.select(
                sa.func.sum(sa.case((pending, 1), else_=0)),
                sa.func.sum(sa.case((sa.and_(pending, active), 1), else_=0)),
                sa.func.sum(sa.case((sa.and_(pending, ~active), 1), else_=0)),
            ).select_from(winner_enrichment_job)
        ).one()
        active_distinct = connection.scalar(
            sa.select(sa.func.count(sa.distinct(active_holder)))
            .select_from(
                winner_enrichment_job.join(
                    materialized_signal,
                    winner_enrichment_job.c.signal_key == materialized_signal.c.signal_key,
                )
            )
            .where(pending, active)
        )
        candidates = int(counts[2] or 0)
        deleted = 0
        if apply and candidates:
            result = connection.execute(
                sa.delete(winner_enrichment_job).where(pending, ~active)
            )
            deleted = int(result.rowcount or 0)
    return ActiveWinnerQueueReport(
        total_pending=int(counts[0] or 0),
        active_pending=int(counts[1] or 0),
        inactive_purge_candidates=candidates,
        active_distinct_holders=int(active_distinct or 0),
        deleted=deleted,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m signals.company_research.winner_queue"
    )
    parser.add_argument("--apply-active-account-purge", action="store_true")
    arguments = parser.parse_args(argv)
    engine = create_database_engine()
    try:
        report = maintain_active_winner_queue(
            engine, apply=arguments.apply_active_account_purge
        )
    finally:
        engine.dispose()
    print(
        json.dumps(
            {"status": "applied" if arguments.apply_active_account_purge else "dry_run", **asdict(report)},
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ActiveWinnerQueueReport",
    "active_account_signal_exists",
    "main",
    "maintain_active_winner_queue",
]
