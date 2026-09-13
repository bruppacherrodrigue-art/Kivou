import dataclasses
import datetime as dt

import sqlalchemy as sa
from test_notice_source_snapshot import (
    connection as connection,  # noqa: PLC0414 — fixture re-export
)
from test_notice_source_snapshot import raw_record, snapshot

from signals.client_value import notice_retention
from signals.persistence.notice_schema import notice_source_snapshot


def test_retention_cli_defaults_to_dry_run_and_only_erases_expired_bytes(
    connection, monkeypatch, capsys
):
    old = snapshot(collected_at=dt.datetime(2024, 1, 1, tzinfo=dt.UTC))
    fresh_record = raw_record()
    fresh_record["idweb"] = "fresh"
    fresh = snapshot(
        fresh_record, source_notice_id="fresh", collected_at=dt.datetime(2026, 9, 13, tzinfo=dt.UTC)
    )
    for item in (old, fresh):
        connection.execute(
            notice_source_snapshot.insert().values(
                **dataclasses.asdict(item), created_at=item.collected_at
            )
        )
    monkeypatch.setattr(notice_retention, "create_database_engine", lambda: connection.engine)
    # Use the current transaction so fixture DDL/data are visible on both dialects.
    assert notice_retention.run(
        connection, now=dt.datetime(2026, 9, 13, tzinfo=dt.UTC), execute=False
    ) == {"eligible": 1, "purged": 0, "dry_run": True}
    assert (
        notice_retention.run(connection, now=dt.datetime(2026, 9, 13, tzinfo=dt.UTC), execute=True)[
            "purged"
        ]
        == 1
    )
    assert (
        connection.execute(
            sa.select(sa.func.count()).select_from(notice_source_snapshot)
        ).scalar_one()
        == 2
    )
    assert (
        connection.execute(
            sa.select(notice_source_snapshot.c.payload_compressed).where(
                notice_source_snapshot.c.snapshot_key == fresh.snapshot_key
            )
        ).scalar_one()
        is not None
    )
    assert (
        notice_retention.run(connection, now=dt.datetime(2026, 9, 13, tzinfo=dt.UTC), execute=True)[
            "purged"
        ]
        == 0
    )
    assert capsys.readouterr().out == ""
