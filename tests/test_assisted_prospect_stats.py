from __future__ import annotations

import sqlalchemy as sa
from test_assisted_prospect_preparation import NOW, Links, seed_directory, signal

from signals.persistence.schema import prospect_target
from signals.prospection_actions.preparation import ProspectPreparationService
from signals.prospection_actions.stats import assisted_stats


def test_assisted_stats_report_review_delivery_and_costs(migrated_sqlite_engine) -> None:
    seed_directory(migrated_sqlite_engine, 8)
    ProspectPreparationService(
        migrated_sqlite_engine, link_issuer=Links(), clock=lambda: NOW
    ).prepare(signal(), cycle_ref="cycle-stats")
    with migrated_sqlite_engine.begin() as connection:
        ids = tuple(connection.execute(sa.select(prospect_target.c.target_id)).scalars())
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == ids[0])
            .values(
                status="sent",
                approved_at=NOW,
                sent_at=NOW,
                opened_at=NOW,
                clicked_at=NOW,
                instantly_credit_units=1,
                instantly_request_count=3,
            )
        )
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == ids[1])
            .values(status="rejected", rejected_at=NOW, rejection_reason="off_topic")
        )

    result = assisted_stats(migrated_sqlite_engine, since=NOW)

    assert result.prepared == len(ids)
    assert result.approved == 1
    assert result.rejected_by_reason == {"off_topic": 1}
    assert (result.sent, result.opened, result.clicks) == (1, 1, 1)
    assert (result.instantly_credit_units, result.instantly_request_count) == (1, 3)
