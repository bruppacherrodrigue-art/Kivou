"""Sanitized operator boundary for one factual Card Intelligence page."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections.abc import Callable

import sqlalchemy as sa

from signals.card_intelligence.backfill import (
    MAX_BACKFILL_ITEMS,
    BackfillResult,
    backfill_factual_presentations,
)
from signals.feed.policy import CANDIDATE_SCAN_CAP
from signals.persistence.database import create_database_engine

_FAILED_SUMMARY = (
    "scanned=0 published=0 unchanged=0 failed=1 next_offset=none"
)

EngineFactory = Callable[[], sa.Engine]
Clock = Callable[[], dt.datetime]


class _SafeArgumentParser(argparse.ArgumentParser):
    """Never reflect an operator-supplied value into logs."""

    def error(self, _message: str) -> None:
        self.exit(2, f"{_FAILED_SUMMARY}\n")


def _account_id(value: str) -> str:
    if re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z_-]{0,63}", value) is None:
        raise argparse.ArgumentTypeError("invalid account identifier")
    return value


def _as_of(value: str) -> dt.date:
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("invalid date") from error
    return parsed


def _limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("invalid limit") from error
    if not 1 <= parsed <= MAX_BACKFILL_ITEMS:
        raise argparse.ArgumentTypeError("invalid limit")
    return parsed


def _offset(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("invalid offset") from error
    if not 0 <= parsed <= CANDIDATE_SCAN_CAP:
        raise argparse.ArgumentTypeError("invalid offset")
    return parsed


def _parser() -> _SafeArgumentParser:
    parser = _SafeArgumentParser(prog="python -m signals.card_intelligence")
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_SafeArgumentParser,
    )
    backfill = commands.add_parser(
        "backfill-fallbacks",
        help="publish one bounded page of deterministic factual fallbacks",
    )
    backfill.add_argument("--account-id", required=True, type=_account_id)
    backfill.add_argument("--as-of", required=True, type=_as_of)
    backfill.add_argument("--language", required=True, choices=("fr", "en"))
    backfill.add_argument("--limit", required=True, type=_limit)
    backfill.add_argument("--offset", required=True, type=_offset)
    return parser


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _summary(result: BackfillResult) -> str:
    next_offset = "none" if result.next_offset is None else str(result.next_offset)
    return (
        f"scanned={result.scanned} published={result.published} "
        f"unchanged={result.unchanged} failed={result.failed} "
        f"next_offset={next_offset}"
    )


def main(
    argv: list[str] | None = None,
    *,
    engine_factory: EngineFactory = create_database_engine,
    clock: Clock = _now,
) -> int:
    arguments = _parser().parse_args(argv)
    assert arguments.command == "backfill-fallbacks"

    engine: sa.Engine | None = None
    result: BackfillResult | None = None
    exit_code = 0
    try:
        now = clock()
        engine = engine_factory()
        result = backfill_factual_presentations(
            engine,
            account_id=arguments.account_id,
            as_of=arguments.as_of,
            language=arguments.language,
            limit=arguments.limit,
            offset=arguments.offset,
            now=now,
        )
    except ValueError:
        exit_code = 2
    except Exception:  # noqa: BLE001 - sanitized process boundary
        exit_code = 1
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:  # noqa: BLE001 - sanitized cleanup boundary
                if exit_code == 0:
                    exit_code = 1

    if exit_code != 0 or result is None:
        print(_FAILED_SUMMARY, file=sys.stderr)
        return exit_code or 1

    print(_summary(result))
    return 1 if result.failed else 0


__all__ = ["main"]
