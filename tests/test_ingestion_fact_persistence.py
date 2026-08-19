from __future__ import annotations

import sqlalchemy as sa
from feed_helpers import MATERIALIZED_AT, boamp_award

from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.materialization import persist_award_facts
from signals.persistence.schema import (
    contract_award,
    materialized_signal,
    opportunity_representation,
    source_event,
)


def test_facts_persist_without_any_customer_target_or_signal(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'facts.db'}")
    migrate_to_latest(engine)
    event, awards = boamp_award("26-80978")

    with engine.begin() as connection:
        first = persist_award_facts(
            connection, event=event, award=awards[0], persisted_at=MATERIALIZED_AT
        )
    with engine.begin() as connection:
        second = persist_award_facts(
            connection, event=event, award=awards[0], persisted_at=MATERIALIZED_AT
        )

    with engine.connect() as connection:
        counts = {
            table.name: connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            for table in (
                source_event,
                contract_award,
                opportunity_representation,
                materialized_signal,
            )
        }

    assert first.event_key == second.event_key
    assert first.award_key == second.award_key
    assert first.opportunity_key == second.opportunity_key
    assert counts == {
        "source_event": 1,
        "contract_award": 1,
        "opportunity_representation": 1,
        "materialized_signal": 0,
    }
