from __future__ import annotations

import datetime as dt
import pathlib

import sqlalchemy as sa
from feed_helpers import make_account, make_icp

from signals.connectors.ted import NoticeRef
from signals.feed.query import feed_page
from signals.ingestion.france import FranceLinker
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.runner import IngestionRunner, RunOptions
from signals.ingestion.sources import TedSource
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import (
    contract_award,
    materialized_signal,
    opportunity_representation,
    source_event,
)

RUN_AT = dt.datetime(2026, 8, 18, 10, tzinfo=dt.UTC)
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "ted" / "550374-2026.xml"


class FrozenTed:
    def search(self, query, *, limit=25, page=1):
        return ([NoticeRef("550374-2026")], 1) if page == 1 else ([], 1)

    def fetch_notice_xml(self, publication_number):
        assert publication_number == "550374-2026"
        return FIXTURE.read_bytes()


def _counts(connection):
    return tuple(
        connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
        for table in (
            source_event,
            contract_award,
            opportunity_representation,
            materialized_signal,
        )
    )


def test_frozen_public_award_reaches_the_customer_feed_and_replays_idempotently(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'e2e.db'}")
    migrate_to_latest(engine)
    with engine.begin() as connection:
        account_id = make_account(connection, "e2e@example.test", "E2E SA")
        target_id = make_icp(
            connection,
            account_id,
            offers=["staffing_and_labour", "equipment_rental", "materials_and_components"],
            buyer_trades=[],
            territories=["FR"],
            minimum_contract_value={"currency": "EUR", "minimum_amount": 0},
        )

    def run_once():
        return IngestionRunner(
            engine,
            sources={"ted": TedSource(FrozenTed())},
            pipeline=IngestionPipeline(engine, linker=FranceLinker()),
            clock=lambda: RUN_AT,
        ).run(RunOptions(sources=("ted",)))

    first = run_once()
    with engine.connect() as connection:
        before_counts = _counts(connection)
        before_signal = connection.execute(
            sa.select(materialized_signal.c.signal_key, materialized_signal.c.revision)
        ).one()
        page = feed_page(connection, account_id=account_id, as_of=RUN_AT.date(), freshness="all")

    assert first.exit_code == 0
    assert first.outcomes[0].counters.signals_materialized == 1
    assert len(page.items) == 1
    assert page.items[0].signal.target_icp_id == target_id
    assert page.items[0].display is not None

    second = run_once()
    with engine.connect() as connection:
        after_counts = _counts(connection)
        after_signal = connection.execute(
            sa.select(materialized_signal.c.signal_key, materialized_signal.c.revision)
        ).one()
        replayed_page = feed_page(
            connection, account_id=account_id, as_of=RUN_AT.date(), freshness="all"
        )

    assert second.exit_code == 0
    assert second.outcomes[0].counters.signals_materialized == 0
    assert before_counts == after_counts == (1, 1, 1, 1)
    assert before_signal == after_signal
    assert len(replayed_page.items) == 1
    assert replayed_page.items[0].signal.signal_key == before_signal.signal_key
