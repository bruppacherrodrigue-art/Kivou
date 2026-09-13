from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from feed_helpers import make_account, make_icp, materialize_simap

from signals.accounts.schema import target_icp
from signals.companies.schema import winner_enrichment_job
from signals.company_research.winner_worker import select_winner_enrichment_candidates
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import contract_award, materialized_signal, source_event

NOW = dt.datetime(2026, 8, 18, 10, tzinfo=dt.UTC)
ACTIVATED_AT = dt.datetime(2026, 8, 18, 8, tzinfo=dt.UTC)


def _engine(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'winner-worker.db'}")
    migrate_to_latest(engine)
    return engine


def _seed(connection, fixture: str, suffix: str):
    account_id = make_account(connection, f"winner-worker-{suffix}@kivou.eu", suffix)
    icp_id = make_icp(connection, account_id, label=f"ICP {suffix}")
    return materialize_simap(connection, fixture, target_icp_id=icp_id), icp_id


def test_selector_keeps_only_post_activation_recent_current_active_signals(tmp_path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        eligible, _ = _seed(connection, "28066-04", "eligible")
        _, draft_icp = _seed(connection, "33885-03", "draft")
        _, stale_icp = _seed(connection, "38147-02", "stale")
        invalidated, _ = _seed(connection, "38918-02", "invalidated")
        old, _ = _seed(connection, "33112-02", "old")
        pre_activation, _ = _seed(connection, "42486-01", "pre-activation")

        connection.execute(
            sa.update(target_icp).where(target_icp.c.target_icp_id == draft_icp).values(status="draft")
        )
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == stale_icp)
            .values(matching_revision=target_icp.c.matching_revision + 1)
        )
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == invalidated.signal_key)
            .values(invalidated_at=NOW, invalidation_reason="test")
        )
        old_award_key = connection.scalar(
            sa.select(materialized_signal.c.materialization_award_key).where(
                materialized_signal.c.signal_key == old.signal_key
            )
        )
        old_event_key = connection.scalar(
            sa.select(contract_award.c.event_key).where(contract_award.c.award_key == old_award_key)
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == old_award_key)
            .values(award_date=dt.date(2026, 7, 18), contract_notification_date=None)
        )
        connection.execute(
            sa.update(source_event)
            .where(source_event.c.event_key == old_event_key)
            .values(published_on=dt.date(2026, 7, 18))
        )
        connection.execute(
            sa.update(winner_enrichment_job)
            .where(winner_enrichment_job.c.signal_key == pre_activation.signal_key)
            .values(queued_at=ACTIVATED_AT - dt.timedelta(seconds=1))
        )

        selected = select_winner_enrichment_candidates(
            connection, now=NOW, activated_at=ACTIVATED_AT, limit=20
        )

    assert tuple(item.signal_key for item in selected) == (eligible.signal_key,)


def test_selector_returns_only_one_job_per_holder_in_a_batch(tmp_path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        first, _ = _seed(connection, "28066-04", "first")
        second, _ = _seed(connection, "28066-04", "second")

        selected = select_winner_enrichment_candidates(
            connection, now=NOW, activated_at=ACTIVATED_AT, limit=20
        )

    assert len(selected) == 1
    assert selected[0].signal_key in {first.signal_key, second.signal_key}
    assert selected[0].holder_key
