from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from engagement_helpers import seed
from fastapi.testclient import TestClient
from feed_helpers import COMPLETE_ICP_INPUT, ORIGIN, PASSWORD

from signals.api import ApiConfig, create_app
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import for_you_sentence
from signals.personalization.for_you_backfill import backfill, parse_args


class FakeProvider:
    def generate_sentence(self, _value):
        return "travaux de bâtiment | vos travaux répondent aux besoins"


def _engine(tmp_path, *, count: int = 3):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'backfill.db'}")
    migrate_to_latest(engine)
    client = TestClient(
        create_app(engine, ApiConfig(cookie_secure=False, allowed_origin=ORIGIN)),
        headers={"Origin": ORIGIN},
    )
    assert (
        client.post(
            "/auth/signup",
            json={
                "email": "backfill@example.com",
                "password": PASSWORD,
                "company_name": "Test SA",
                "locale": "fr",
            },
        ).status_code
        == 201
    )
    icp = client.post(
        "/target-icps", json={"label": "Travaux", "customer_input": COMPLETE_ICP_INPUT}
    ).json()["target_icp_id"]
    seed(engine, icp, count=count)
    with engine.begin() as connection:
        connection.execute(sa.delete(for_you_sentence))
    return engine


def test_backfill_enqueues_and_runs_exact_limit(tmp_path) -> None:
    engine = _engine(tmp_path, count=3)

    report = backfill(
        engine,
        FakeProvider(),
        limit=2,
        since=dt.date(2026, 1, 1),
        now=dt.datetime(2026, 9, 4, 9, tzinfo=dt.UTC),
        concurrency=2,
        daily_limit=20,
    )

    assert report.attempted == 2
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(for_you_sentence)) == 2


def test_backfill_respects_since_and_does_not_requeue_cached_pair(tmp_path) -> None:
    engine = _engine(tmp_path, count=1)
    now = dt.datetime(2026, 9, 4, 9, tzinfo=dt.UTC)

    first = backfill(engine, FakeProvider(), limit=1, since=dt.date(2027, 1, 1), now=now)
    second = backfill(engine, FakeProvider(), limit=1, since=dt.date(2026, 1, 1), now=now)
    third = backfill(engine, FakeProvider(), limit=1, since=dt.date(2026, 1, 1), now=now)

    assert first.attempted == 0
    assert second.attempted == 1
    assert third.attempted == 0


def test_cli_requires_bounded_valid_window() -> None:
    with pytest.raises(SystemExit):
        parse_args([])
    with pytest.raises(SystemExit):
        parse_args(["--limit", "0", "--since", "2026-01-01"])
    parsed = parse_args(["--limit", "50", "--since", "2026-08-01"])
    assert parsed.limit == 50
    assert parsed.since == dt.date(2026, 8, 1)
