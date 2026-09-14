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


def maintain_active_winner_queue(
    engine: sa.Engine, *, apply: bool = False
) -> ActiveWinnerQueueReport:
    """Measure the inactive pending queue, deleting it only with explicit opt-in."""

    queue_signal = materialized_signal.alias("queue_signal")
    active_signal = materialized_signal.alias("active_signal")
    active_icp = target_icp.alias("active_icp")

    def holder_key(table):
        return sa.case(
            (
                sa.func.length(table.c.winner_identifier_value) == 14,
                sa.func.substr(table.c.winner_identifier_value, 1, 9),
            ),
            (
                sa.func.length(table.c.winner_identifier_value) == 9,
                table.c.winner_identifier_value,
            ),
            else_=table.c.company_identity_fingerprint,
        )

    queue_holder = holder_key(queue_signal)
    active_holder_exists = sa.exists(
        sa.select(sa.literal(1))
        .select_from(
            active_signal.join(
                active_icp,
                active_signal.c.target_icp_id == active_icp.c.target_icp_id,
            )
        )
        .where(
            holder_key(active_signal) == queue_holder,
            active_signal.c.invalidated_at.is_(None),
            active_signal.c.target_icp_revision == active_icp.c.matching_revision,
            active_icp.c.status == "active",
        )
    )
    pending_join = winner_enrichment_job.join(
        queue_signal,
        winner_enrichment_job.c.signal_key == queue_signal.c.signal_key,
    )
    with engine.begin() as connection:
        rows = (
            connection.execute(
                sa.select(
                    winner_enrichment_job.c.signal_key,
                    queue_holder.label("holder_key"),
                    active_holder_exists.label("holder_has_active_account"),
                )
                .select_from(pending_join)
                .where(winner_enrichment_job.c.status == "pending")
            )
            .mappings()
            .all()
        )
        candidate_keys = tuple(
            row["signal_key"] for row in rows if not row["holder_has_active_account"]
        )
        active_holders = {
            row["holder_key"]
            for row in rows
            if row["holder_has_active_account"] and row["holder_key"] is not None
        }
        candidates = len(candidate_keys)
        deleted = 0
        if apply and candidates:
            result = connection.execute(
                sa.delete(winner_enrichment_job).where(
                    winner_enrichment_job.c.signal_key.in_(candidate_keys),
                    winner_enrichment_job.c.status == "pending",
                )
            )
            deleted = int(result.rowcount or 0)
    return ActiveWinnerQueueReport(
        total_pending=len(rows),
        active_pending=len(rows) - candidates,
        inactive_purge_candidates=candidates,
        active_distinct_holders=len(active_holders),
        deleted=deleted,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m signals.company_research.winner_queue")
    parser.add_argument("--apply-active-account-purge", action="store_true")
    arguments = parser.parse_args(argv)
    engine = create_database_engine()
    try:
        report = maintain_active_winner_queue(engine, apply=arguments.apply_active_account_purge)
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
                "status": "applied" if arguments.apply_active_account_purge else "dry_run",
                **asdict(report),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ActiveWinnerQueueReport",
    "main",
    "maintain_active_winner_queue",
]
