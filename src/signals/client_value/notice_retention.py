"""Scheduled bounded expiry of raw notice archives; extracted facts are retained."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import sqlalchemy as sa

from signals.persistence.database import create_database_engine
from signals.persistence.notice_schema import notice_source_snapshot


def run(
    connection: sa.Connection, *, now: dt.datetime, execute: bool = False, limit: int = 1000
) -> dict:
    if now.tzinfo is None or now.utcoffset() is None or not 1 <= limit <= 10000:
        raise ValueError("invalid retention scope")
    table = notice_source_snapshot
    predicate = sa.and_(table.c.expires_at <= now, table.c.payload_compressed.is_not(None))
    eligible = connection.execute(
        sa.select(sa.func.count()).select_from(table).where(predicate)
    ).scalar_one()
    purged = 0
    if execute and eligible:
        keys = (
            connection.execute(
                sa.select(table.c.snapshot_key)
                .where(predicate)
                .order_by(table.c.expires_at, table.c.snapshot_key)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        purged = connection.execute(
            table.update()
            .where(predicate, table.c.snapshot_key.in_(keys))
            .values(payload_compressed=None, payload_purged_at=now)
        ).rowcount
    return {"eligible": eligible, "purged": purged, "dry_run": not execute}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--limit", type=int, default=1000)
    arguments = parser.parse_args(argv)
    engine = None
    try:
        engine = create_database_engine()
        with engine.begin() as connection:
            result = run(
                connection,
                now=dt.datetime.now(dt.UTC),
                execute=arguments.execute,
                limit=arguments.limit,
            )
    except (RuntimeError, ValueError):
        print("retention_configuration_invalid", file=sys.stderr)
        return 2
    except sa.exc.SQLAlchemyError:
        print("retention_persistence_failed", file=sys.stderr)
        return 4
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
