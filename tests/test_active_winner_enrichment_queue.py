from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from feed_helpers import make_account, make_icp, materialize_simap

from signals.accounts.schema import target_icp
from signals.companies.schema import winner_enrichment_job
from signals.company_research.winner_queue import maintain_active_winner_queue
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 9, 12, 12, tzinfo=dt.UTC)


def _engine(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'queue.db'}")
    migrate_to_latest(engine)
    return engine


def test_inactive_winner_queue_cleanup_is_dry_and_pending_only(tmp_path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        active_account = make_account(connection, "active-holder@example.test", "Active")
        active_icp = make_icp(connection, active_account)
        active = materialize_simap(connection, "33112-02", target_icp_id=active_icp)

        inactive_account = make_account(
            connection, "inactive-holder@example.test", "Inactive"
        )
        inactive_icp = make_icp(connection, inactive_account)
        inactive = materialize_simap(
            connection, "29997-02", target_icp_id=inactive_icp
        )
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == inactive_icp)
            .values(status="draft")
        )

    dry = maintain_active_winner_queue(engine, apply=False)
    with engine.connect() as connection:
        dry_jobs = connection.scalar(
            sa.select(sa.func.count()).select_from(winner_enrichment_job)
        )

    assert dry.total_pending == 2
    assert dry.active_pending == 1
    assert dry.inactive_purge_candidates == 1
    assert dry.deleted == 0
    assert dry_jobs == 2

    applied = maintain_active_winner_queue(engine, apply=True)
    with engine.connect() as connection:
        remaining = tuple(
            connection.scalars(sa.select(winner_enrichment_job.c.signal_key))
        )

    assert applied.deleted == 1
    assert remaining == (active.signal_key,)
    assert inactive.signal_key not in remaining


def test_cleanup_never_deletes_non_pending_history(tmp_path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        account_id = make_account(connection, "history-holder@example.test", "History")
        icp_id = make_icp(connection, account_id)
        signal = materialize_simap(connection, "33112-02", target_icp_id=icp_id)
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == icp_id)
            .values(status="draft")
        )
        connection.execute(
            sa.update(winner_enrichment_job)
            .where(winner_enrichment_job.c.signal_key == signal.signal_key)
            .values(
                status="completed",
                attempt_count=1,
                claimed_by="historical-worker",
                started_at=NOW,
                finished_at=NOW,
            )
        )

    report = maintain_active_winner_queue(engine, apply=True)

    assert report.inactive_purge_candidates == 0
    assert report.deleted == 0
