from __future__ import annotations

import datetime as dt
import threading

import pytest
import sqlalchemy as sa

from signals.alerts.lease import LeaseAcquisition, acquire, release
from signals.engagement.schema import signal_alert_job_lease
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 23, 10, 0, tzinfo=dt.UTC)
TTL = dt.timedelta(minutes=30)


@pytest.fixture
def engine(tmp_path):
    database = create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / 'alert-job-lease.db'}",
        connect_args={"timeout": 10},
    )
    migrate_to_latest(database)
    return database


def test_second_owner_observes_normal_contention(engine) -> None:
    with engine.begin() as connection:
        first = acquire(connection, owner_id="one", now=NOW, ttl=TTL)
    with engine.begin() as connection:
        second = acquire(connection, owner_id="two", now=NOW, ttl=TTL)

    assert first is LeaseAcquisition.ACQUIRED
    assert second is LeaseAcquisition.ALREADY_RUNNING


def test_expired_lease_is_reclaimed(engine) -> None:
    with engine.begin() as connection:
        acquire(connection, owner_id="one", now=NOW, ttl=TTL)
    with engine.begin() as connection:
        result = acquire(connection, owner_id="two", now=NOW + TTL, ttl=TTL)

    assert result is LeaseAcquisition.ACQUIRED
    with engine.connect() as connection:
        row = connection.execute(sa.select(signal_alert_job_lease)).one()
    assert row.owner_id == "two"
    assert row.acquired_at.replace(tzinfo=dt.UTC) == NOW + TTL


def test_release_only_removes_the_current_owners_lease(engine) -> None:
    with engine.begin() as connection:
        acquire(connection, owner_id="one", now=NOW, ttl=TTL)
    with engine.begin() as connection:
        release(connection, owner_id="two")
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(signal_alert_job_lease)) == 1

    with engine.begin() as connection:
        release(connection, owner_id="one")
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(signal_alert_job_lease)) == 0


def test_two_concurrent_jobs_have_exactly_one_owner(engine) -> None:
    barrier = threading.Barrier(2)
    results: list[LeaseAcquisition] = []
    errors: list[Exception] = []

    def compete(owner_id: str) -> None:
        try:
            barrier.wait(timeout=5)
            with engine.begin() as connection:
                results.append(acquire(connection, owner_id=owner_id, now=NOW, ttl=TTL))
        except (sa.exc.SQLAlchemyError, threading.BrokenBarrierError) as error:
            errors.append(error)

    threads = [
        threading.Thread(target=compete, args=("one",)),
        threading.Thread(target=compete, args=("two",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert sorted(results) == sorted(
        [LeaseAcquisition.ACQUIRED, LeaseAcquisition.ALREADY_RUNNING]
    )
    with engine.connect() as connection:
        rows = connection.execute(sa.select(signal_alert_job_lease)).all()
    assert len(rows) == 1
    assert rows[0].owner_id in {"one", "two"}


def test_technical_database_failure_is_not_normal_contention() -> None:
    class BrokenConnection:
        def execute(self, _statement):
            raise sa.exc.OperationalError("UPDATE lease", {}, RuntimeError("db unavailable"))

    with pytest.raises(sa.exc.OperationalError):
        acquire(BrokenConnection(), owner_id="one", now=NOW, ttl=TTL)  # type: ignore[arg-type]
