"""Explicit bounded command; importing the API never starts card generation."""

from __future__ import annotations

import argparse
import datetime as dt

from signals.card_intelligence.backfill import (
    MAX_BACKFILL_ITEMS,
    backfill_factual_presentations,
)
from signals.feed import policy
from signals.persistence.database import create_database_engine


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m signals.card_intelligence")
    commands = root.add_subparsers(dest="command", required=True)
    backfill = commands.add_parser(
        "backfill-fallbacks",
        help="publish deterministic factual fallbacks; never call a model provider",
    )
    backfill.add_argument("--account-id", required=True)
    backfill.add_argument("--as-of", type=dt.date.fromisoformat, required=True)
    backfill.add_argument("--language", choices=("fr", "en"), required=True)
    backfill.add_argument("--limit", type=int, choices=range(1, MAX_BACKFILL_ITEMS + 1), required=True)
    backfill.add_argument(
        "--offset",
        type=int,
        choices=range(policy.CANDIDATE_SCAN_CAP),
        default=0,
        help="stable feed offset; use next_offset from the previous bounded run",
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command != "backfill-fallbacks":  # pragma: no cover - argparse closes the set
        raise AssertionError(args.command)
    now = dt.datetime.now(dt.UTC)
    result = backfill_factual_presentations(
        create_database_engine(),
        account_id=args.account_id,
        as_of=args.as_of,
        language=args.language,
        limit=args.limit,
        offset=args.offset,
        now=now,
    )
    print(
        f"scanned={result.scanned} published={result.published} "
        f"unchanged={result.unchanged} failed={result.failed} "
        f"next_offset={result.next_offset}"
    )
    for failure in result.failures:
        print(f"failed_item={failure}")
    return 1 if result.failed else 0
