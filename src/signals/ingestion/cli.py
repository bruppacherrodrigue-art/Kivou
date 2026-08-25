from __future__ import annotations

import argparse
import datetime as dt
import os
import signal
import threading

from signals.ingestion.france import FranceLinker
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.runner import IngestionRunner, RunOptions, SourceOutcome
from signals.ingestion.sources import production_sources
from signals.persistence.database import create_database_engine

DECP_MAX_WINDOWS_ENV = "KIVOU_DECP_MAX_WINDOWS_PER_RUN"
DECP_TIME_BUDGET_ENV = "KIVOU_DECP_TIME_BUDGET_SECONDS"
DECP_OVERLAP_DAYS_ENV = "KIVOU_DECP_OVERLAP_DAYS"
INGESTION_STALE_RUN_ENV = "KIVOU_INGESTION_STALE_RUN_SECONDS"

DEFAULT_DECP_MAX_WINDOWS_PER_RUN = 2
DEFAULT_DECP_TIME_BUDGET_SECONDS = 1200
DEFAULT_DECP_OVERLAP_DAYS = 30
DEFAULT_INGESTION_STALE_RUN_SECONDS = 3600


def summarize(outcome: SourceOutcome) -> str:
    counters = outcome.counters
    error = f" error={outcome.error_category}" if outcome.error_category else ""
    return (
        f"source={outcome.source} fetched={counters.records_fetched} "
        f"persisted={counters.records_persisted} linked={counters.representations_linked} "
        f"materialized={counters.signals_materialized} skipped={counters.records_rejected} "
        f"conflicts={counters.opportunity_conflicts} "
        f"rate_limited={counters.rate_limited_count} status={outcome.status}{error} "
        f"pending={int(outcome.work_pending)} "
        f"duration={outcome.duration_seconds:.3f}s"
    )


def _instant(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _environment_positive_integer(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return _positive_integer(raw)
    except argparse.ArgumentTypeError as error:
        raise SystemExit(f"{name} must be a positive integer") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m signals.ingestion")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run one bounded ingestion cycle")
    run.add_argument(
        "--source",
        action="append",
        choices=("simap", "boamp", "decp", "ted"),
        help="source to run; repeatable; defaults to all MVP sources",
    )
    run.add_argument("--since", type=dt.date.fromisoformat)
    run.add_argument("--until", type=_instant)
    run.add_argument("--max-records", type=int)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--decp-max-windows-per-run", type=_positive_integer)
    run.add_argument("--decp-time-budget-seconds", type=_positive_integer)
    run.add_argument("--decp-overlap-days", type=_positive_integer)
    run.add_argument("--ingestion-stale-run-seconds", type=_positive_integer)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.max_records is not None and arguments.max_records < 1:
        raise SystemExit("--max-records must be positive")
    decp_max_windows = arguments.decp_max_windows_per_run or _environment_positive_integer(
        DECP_MAX_WINDOWS_ENV,
        DEFAULT_DECP_MAX_WINDOWS_PER_RUN,
    )
    decp_time_budget = arguments.decp_time_budget_seconds or _environment_positive_integer(
        DECP_TIME_BUDGET_ENV,
        DEFAULT_DECP_TIME_BUDGET_SECONDS,
    )
    decp_overlap_days = arguments.decp_overlap_days or _environment_positive_integer(
        DECP_OVERLAP_DAYS_ENV,
        DEFAULT_DECP_OVERLAP_DAYS,
    )
    stale_run_seconds = arguments.ingestion_stale_run_seconds or _environment_positive_integer(
        INGESTION_STALE_RUN_ENV,
        DEFAULT_INGESTION_STALE_RUN_SECONDS,
    )

    cancellation = threading.Event()

    def request_termination(_signum: int, _frame: object) -> None:
        cancellation.set()

    previous_sigterm = signal.signal(signal.SIGTERM, request_termination)
    sources = {}
    try:
        sources = production_sources()
        selected = tuple(arguments.source or ("simap", "boamp", "decp", "ted"))
        engine = create_database_engine()
        pipeline = IngestionPipeline(engine, linker=FranceLinker())
        result = IngestionRunner(
            engine,
            sources=sources,
            pipeline=pipeline,
            cancel_requested=cancellation.is_set,
        ).run(
            RunOptions(
                sources=selected,
                since=arguments.since,
                until=arguments.until,
                max_records=arguments.max_records,
                dry_run=arguments.dry_run,
                decp_max_windows_per_run=decp_max_windows,
                decp_time_budget_seconds=decp_time_budget,
                decp_overlap_days=decp_overlap_days,
                ingestion_stale_run_seconds=stale_run_seconds,
            )
        )
    finally:
        for adapter in sources.values():
            client = getattr(adapter, "client", None)
            if client is not None:
                client.close()
        signal.signal(signal.SIGTERM, previous_sigterm)
    for outcome in result.outcomes:
        print(summarize(outcome))
    return result.exit_code
