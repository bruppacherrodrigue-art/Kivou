from __future__ import annotations

import argparse
import datetime as dt

from signals.ingestion.france import FranceLinker
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.runner import IngestionRunner, RunOptions, SourceOutcome
from signals.ingestion.sources import production_sources
from signals.persistence.database import create_database_engine


def summarize(outcome: SourceOutcome) -> str:
    counters = outcome.counters
    error = f" error={outcome.error_category}" if outcome.error_category else ""
    return (
        f"source={outcome.source} fetched={counters.records_fetched} "
        f"persisted={counters.records_persisted} linked={counters.representations_linked} "
        f"materialized={counters.signals_materialized} skipped={counters.records_rejected} "
        f"conflicts={counters.opportunity_conflicts} "
        f"rate_limited={counters.rate_limited_count} status={outcome.status}{error} "
        f"duration={outcome.duration_seconds:.3f}s"
    )


def _instant(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


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
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.max_records is not None and arguments.max_records < 1:
        raise SystemExit("--max-records must be positive")
    sources = production_sources()
    selected = tuple(arguments.source or ("simap", "boamp", "decp", "ted"))
    engine = create_database_engine()
    pipeline = IngestionPipeline(engine, linker=FranceLinker())
    try:
        result = IngestionRunner(engine, sources=sources, pipeline=pipeline).run(
            RunOptions(
                sources=selected,
                since=arguments.since,
                until=arguments.until,
                max_records=arguments.max_records,
                dry_run=arguments.dry_run,
            )
        )
    finally:
        for adapter in sources.values():
            client = getattr(adapter, "client", None)
            if client is not None:
                client.close()
    for outcome in result.outcomes:
        print(summarize(outcome))
    return result.exit_code
