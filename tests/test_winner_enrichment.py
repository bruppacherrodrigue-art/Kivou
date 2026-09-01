"""The factual winner worker is explicit, replayable and provider-free."""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from feed_helpers import make_account, make_icp, materialize_simap

from signals.companies.enrichment import (
    MAX_ENRICHMENT_ATTEMPTS,
    run_winner_enrichment_batch,
    winner_enrichments_for_signals,
)
from signals.companies.schema import saas_company, winner_enrichment_job
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import contract_award, materialized_signal

NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)


@pytest.fixture
def engine(tmp_path):
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'winner.db'}")
    migrate_to_latest(value)
    return value


def _seed(connection, fixture: str = "33112-02"):
    account_id = make_account(connection, f"winner-{fixture}@kivou.eu", "Winner")
    icp_id = make_icp(connection, account_id)
    return materialize_simap(connection, fixture, target_icp_id=icp_id)


def test_materialization_enqueues_once_without_running_the_worker(engine) -> None:
    with engine.begin() as connection:
        signal = _seed(connection)
        before = connection.execute(
            sa.select(winner_enrichment_job).where(
                winner_enrichment_job.c.signal_key == signal.signal_key
            )
        ).one()
        materialize_simap(
            connection,
            "33112-02",
            target_icp_id=connection.scalar(
                sa.select(materialized_signal.c.target_icp_id).where(
                    materialized_signal.c.signal_key == signal.signal_key
                )
            ),
        )
        after = connection.execute(
            sa.select(winner_enrichment_job).where(
                winner_enrichment_job.c.signal_key == signal.signal_key
            )
        ).one()

    assert before.status == after.status == "pending"
    assert before.attempt_count == after.attempt_count == 0
    assert before.queued_at == after.queued_at


def test_worker_projects_only_stored_public_facts_and_is_idempotent(engine) -> None:
    with engine.begin() as connection:
        signal = _seed(connection)
        batch = run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="winner-test", limit=10
        )
        second = run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="winner-test", limit=10
        )
        views = winner_enrichments_for_signals(
            connection, signal_keys=(signal.signal_key,)
        )
        companies = connection.scalar(sa.select(sa.func.count()).select_from(saas_company))

    assert batch.processed == 1
    assert batch.completed + batch.partial == 1
    assert batch.failed == 0
    assert second.processed == 0
    assert companies == 1
    view = views[signal.signal_key]
    assert view.status in {"completed", "partial"}
    assert view.source.connector == "simap"
    assert view.source.notice_id
    assert view.source.retrieved_at is not None
    assert view.error_code is None


def test_malformed_source_fails_with_a_bounded_code_and_retry_budget(engine) -> None:
    with engine.begin() as connection:
        signal = _seed(connection)
        award_key = connection.scalar(
            sa.select(materialized_signal.c.materialization_award_key).where(
                materialized_signal.c.signal_key == signal.signal_key
            )
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == award_key)
            .values(awardee_parties=[{"malformed": True}])
        )
        for attempt in range(MAX_ENRICHMENT_ATTEMPTS):
            result = run_winner_enrichment_batch(
                connection,
                now=NOW + dt.timedelta(minutes=attempt),
                worker_ref="winner-retry",
                limit=1,
                retry_failed=attempt > 0,
            )
            assert result.failed == 1
        exhausted = run_winner_enrichment_batch(
            connection,
            now=NOW + dt.timedelta(hours=1),
            worker_ref="winner-retry",
            limit=1,
            retry_failed=True,
        )
        row = connection.execute(
            sa.select(winner_enrichment_job).where(
                winner_enrichment_job.c.signal_key == signal.signal_key
            )
        ).one()

    assert exhausted.processed == 0
    assert row.status == "failed"
    assert row.attempt_count == MAX_ENRICHMENT_ATTEMPTS
    assert row.error_code == "winner_identity_unresolved"


def test_two_worker_passes_cannot_claim_the_same_signal(engine) -> None:
    with engine.begin() as connection:
        signal = _seed(connection)
        first = run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="worker-a", limit=1
        )
        second = run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="worker-b", limit=1
        )
        row = connection.execute(
            sa.select(winner_enrichment_job).where(
                winner_enrichment_job.c.signal_key == signal.signal_key
            )
        ).one()

    assert first.processed == 1
    assert second.processed == 0
    assert row.claimed_by == "worker-a"


def test_batch_rejects_unbounded_or_unsafe_operator_inputs(engine) -> None:
    with engine.begin() as connection:
        _seed(connection)
        with pytest.raises(ValueError, match="limit"):
            run_winner_enrichment_batch(
                connection, now=NOW, worker_ref="winner-test", limit=0
            )
        with pytest.raises(ValueError, match="worker_ref"):
            run_winner_enrichment_batch(
                connection, now=NOW, worker_ref="contains a secret/value", limit=1
            )
