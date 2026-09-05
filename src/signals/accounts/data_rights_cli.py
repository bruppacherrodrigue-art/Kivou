"""Purge planifiée des comptes dont le délai de suppression est arrivé."""

from __future__ import annotations

import argparse
import datetime as dt
import sys

import sqlalchemy as sa

from signals.accounts.data_rights import purge_due_deletions
from signals.persistence.database import create_database_engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kivou-account-purge")
    parser.add_argument("--now", default=None)
    arguments = parser.parse_args(argv)
    try:
        now = (
            dt.datetime.fromisoformat(arguments.now)
            if arguments.now
            else dt.datetime.now(tz=dt.UTC)
        )
        if now.tzinfo is None:
            now = now.replace(tzinfo=dt.UTC)
        count = purge_due_deletions(create_database_engine(), now=now)
    except (RuntimeError, ValueError):
        print("configuration_invalid", file=sys.stderr)
        return 2
    except sa.exc.SQLAlchemyError:
        print("persistence_failed", file=sys.stderr)
        return 4
    print(f"accounts_purged={count}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
