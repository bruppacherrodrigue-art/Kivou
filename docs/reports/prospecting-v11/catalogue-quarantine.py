"""Recoverably hide the 30 audited staging fixtures; defaults to a read-only preview.

Apply only after retaining the database backup and checking the preview manifest.
No rows are deleted; restoring suppressed_at from that backup reverses this action.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os

import sqlalchemy as sa

from signals.persistence.database import create_database_engine
from signals.persistence.schema import supplier_directory

CREATED = dt.datetime(2026, 9, 11, 11, 1, 5, 975418, tzinfo=dt.UTC)
MANIFEST = {f"9900000{index:02d}": f"Entreprise test {index:02d}" for index in range(1, 31)}


def matches(row):
    created = row["created_at"]
    instant = (
        created.replace(tzinfo=dt.UTC) if created.tzinfo is None else created.astimezone(dt.UTC)
    )
    return (
        row["legal_name"] == MANIFEST.get(row["siren"])
        and row["city"] == "Blois"
        and instant == CREATED
    )


def run(connection, *, now, execute=False):
    statement = sa.select(supplier_directory).where(supplier_directory.c.siren.in_(MANIFEST))
    if execute:
        statement = statement.with_for_update()
    rows = list(connection.execute(statement).mappings())
    if len(rows) != len(MANIFEST) or any(not matches(row) for row in rows):
        raise ValueError("catalogue fixture manifest mismatch")
    eligible = [row["siren"] for row in rows if row["suppressed_at"] is None]
    changed = 0
    if execute and eligible:
        result = connection.execute(
            supplier_directory.update()
            .where(
                supplier_directory.c.siren.in_(eligible),
                supplier_directory.c.suppressed_at.is_(None),
            )
            .values(suppressed_at=now)
        )
        changed = result.rowcount
    return {"manifest": len(rows), "eligible": len(eligible), "quarantined": changed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    engine = None
    try:
        url = sa.make_url(os.environ.get("KIVOU_DATABASE_URL", ""))
        if (
            os.environ.get("KIVOU_ACQUISITION_ENVIRONMENT") != "STAGING"
            or url.get_backend_name() != "postgresql"
            or url.database != "kivou_staging"
            or url.query
        ):
            raise ValueError("staging target required")
        engine = create_database_engine(url)
        with engine.begin() as connection:
            if not args.apply:
                connection.execute(sa.text("SET TRANSACTION READ ONLY"))
            if connection.scalar(sa.text("SELECT current_database()")) != "kivou_staging":
                raise ValueError("staging database required")
            connection.execute(sa.text("SET LOCAL statement_timeout = '10000ms'"))
            result = run(connection, now=dt.datetime.now(dt.UTC), execute=args.apply)
        print(
            json.dumps({"status": "applied" if args.apply else "preview", **result}, sort_keys=True)
        )
        return 0
    except (ValueError, OSError, sa.exc.SQLAlchemyError):
        print(json.dumps({"status": "failed", "code": "catalogue_quarantine_refused"}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
