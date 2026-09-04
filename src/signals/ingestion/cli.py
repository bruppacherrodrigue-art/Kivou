from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import math
import os
import signal
import threading

from signals.connectors.boamp import BoampClient
from signals.connectors.decp import PAGE_SIZE as DECP_PAGE_SIZE
from signals.connectors.simap import SimapClient
from signals.connectors.ted import TedClient
from signals.documents.fetch import DocumentFetcher
from signals.ingestion.france import FranceLinker
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.runner import IngestionRunner, RunOptions, SourceOutcome
from signals.ingestion.sources import production_sources
from signals.ingestion.tender_notices import (
    BoampTenderNotices,
    SimapTenderNotices,
    TedTenderNotices,
    TenderNoticeJob,
)
from signals.persistence.database import create_database_engine

DECP_MAX_WINDOWS_ENV = "KIVOU_DECP_MAX_WINDOWS_PER_RUN"
DECP_BATCH_SIZE_ENV = "KIVOU_DECP_BATCH_SIZE"
DECP_TIME_BUDGET_ENV = "KIVOU_DECP_TIME_BUDGET_SECONDS"
DECP_OVERLAP_DAYS_ENV = "KIVOU_DECP_OVERLAP_DAYS"
INGESTION_STALE_RUN_ENV = "KIVOU_INGESTION_STALE_RUN_SECONDS"
TED_REQUEST_INTERVAL_ENV = "KIVOU_TED_REQUEST_INTERVAL_SECONDS"
TED_MAX_ATTEMPTS_ENV = "KIVOU_TED_MAX_ATTEMPTS"
TED_MAX_RETRY_ENV = "KIVOU_TED_MAX_RETRY_SECONDS"
TED_MAX_RECORDS_ENV = "KIVOU_TED_MAX_RECORDS_PER_RUN"
TED_TIME_BUDGET_ENV = "KIVOU_TED_TIME_BUDGET_SECONDS"

DEFAULT_DECP_MAX_WINDOWS_PER_RUN = 2
DEFAULT_DECP_BATCH_SIZE = DECP_PAGE_SIZE
DEFAULT_DECP_TIME_BUDGET_SECONDS = 1200
DEFAULT_DECP_OVERLAP_DAYS = 30
DEFAULT_INGESTION_STALE_RUN_SECONDS = 3600
DEFAULT_TED_REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_TED_MAX_ATTEMPTS = 4
DEFAULT_TED_MAX_RETRY_SECONDS = 120.0
DEFAULT_TED_MAX_RECORDS_PER_RUN = 500
DEFAULT_TED_TIME_BUDGET_SECONDS = 1200
DEFAULT_TENDER_STORAGE_QUOTA_BYTES = 10 * 1024 * 1024 * 1024


def summarize(outcome: SourceOutcome) -> str:
    counters = outcome.counters
    error = f" error={outcome.error_category}" if outcome.error_category else ""
    error_type = f" error_type={outcome.error_type}" if outcome.error_type else ""
    return (
        f"source={outcome.source} fetched={counters.records_fetched} "
        f"persisted={counters.records_persisted} linked={counters.representations_linked} "
        f"materialized={counters.signals_materialized} skipped={counters.records_rejected} "
        f"conflicts={counters.opportunity_conflicts} "
        f"rate_limited={counters.rate_limited_count} status={outcome.status}{error}{error_type} "
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


def _positive_number(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive number") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


def _environment_positive_number(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return _positive_number(raw)
    except argparse.ArgumentTypeError as error:
        raise SystemExit(f"{name} must be a positive number") from error


def _decp_batch_size(value: str) -> int:
    parsed = _positive_integer(value)
    if parsed > DECP_PAGE_SIZE:
        raise argparse.ArgumentTypeError(f"must be at most {DECP_PAGE_SIZE}")
    return parsed


def _environment_decp_batch_size() -> int:
    raw = os.environ.get(DECP_BATCH_SIZE_ENV)
    if raw is None:
        return DEFAULT_DECP_BATCH_SIZE
    try:
        return _decp_batch_size(raw)
    except argparse.ArgumentTypeError as error:
        raise SystemExit(f"{DECP_BATCH_SIZE_ENV} {error}") from error


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
    run.add_argument("--decp-batch-size", type=_decp_batch_size)
    run.add_argument("--decp-time-budget-seconds", type=_positive_integer)
    run.add_argument("--decp-overlap-days", type=_positive_integer)
    run.add_argument("--ted-request-interval-seconds", type=_positive_number)
    run.add_argument("--ted-max-attempts", type=_positive_integer)
    run.add_argument("--ted-max-retry-seconds", type=_positive_number)
    run.add_argument("--ted-max-records-per-run", type=_positive_integer)
    run.add_argument("--ted-time-budget-seconds", type=_positive_integer)
    run.add_argument("--ingestion-stale-run-seconds", type=_positive_integer)
    tender = commands.add_parser(
        "tender-notices", help="capture documents when calls for tenders are published"
    )
    tender.add_argument(
        "--source", choices=("boamp", "ted", "simap", "all"), required=True
    )
    tender.add_argument("--since", type=dt.date.fromisoformat)
    tender.add_argument("--until", type=dt.date.fromisoformat)
    tender.add_argument("--max-records", type=_positive_integer)
    tender.add_argument("--request-interval-seconds", type=_positive_number)
    tender.add_argument("--storage-quota-bytes", type=_positive_integer)
    return parser


def _run_tender_notices(arguments: argparse.Namespace) -> int:
    until = arguments.until or dt.datetime.now(dt.UTC).date()
    since = arguments.since or (until - dt.timedelta(days=1))
    quota = arguments.storage_quota_bytes or _environment_positive_integer(
        "KIVOU_TENDER_DOCUMENT_STORAGE_QUOTA_BYTES",
        DEFAULT_TENDER_STORAGE_QUOTA_BYTES,
    )
    interval = arguments.request_interval_seconds or _environment_positive_number(
        "KIVOU_TENDER_REQUEST_INTERVAL_SECONDS", 2.0
    )
    enabled = lambda: os.environ.get("KIVOU_TENDER_NOTICES_ENABLED", "0") == "1"
    with contextlib.ExitStack() as stack:
        boamp = stack.enter_context(BoampClient())
        ted = stack.enter_context(TedClient(request_interval_seconds=interval))
        simap = stack.enter_context(SimapClient())
        fetcher = stack.enter_context(DocumentFetcher())
        sources = {
            "boamp": BoampTenderNotices(boamp),
            "ted": TedTenderNotices(ted),
            "simap": SimapTenderNotices(simap),
        }
        job = TenderNoticeJob(
            create_database_engine(),
            sources=sources,
            fetcher=fetcher,
            quota_bytes=quota,
            request_interval_seconds=interval,
            enabled=enabled,
        )
        selected = tuple(sources) if arguments.source == "all" else (arguments.source,)
        for source in selected:
            outcome = job.run(
                source=source,
                since=since,
                until=until,
                max_records=arguments.max_records,
            )
            print(
                f"source={source} notices={outcome.notices_ingested} "
                f"documents={outcome.documents_created} "
                f"stopped={outcome.stopped_reason or 'complete'}"
            )
            if outcome.stopped_reason:
                break
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "tender-notices":
        return _run_tender_notices(arguments)
    if arguments.max_records is not None and arguments.max_records < 1:
        raise SystemExit("--max-records must be positive")
    decp_max_windows = arguments.decp_max_windows_per_run or _environment_positive_integer(
        DECP_MAX_WINDOWS_ENV,
        DEFAULT_DECP_MAX_WINDOWS_PER_RUN,
    )
    decp_batch_size = arguments.decp_batch_size or _environment_decp_batch_size()
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
    ted_request_interval = (
        arguments.ted_request_interval_seconds
        or _environment_positive_number(
            TED_REQUEST_INTERVAL_ENV,
            DEFAULT_TED_REQUEST_INTERVAL_SECONDS,
        )
    )
    ted_max_attempts = arguments.ted_max_attempts or _environment_positive_integer(
        TED_MAX_ATTEMPTS_ENV,
        DEFAULT_TED_MAX_ATTEMPTS,
    )
    ted_max_retry = arguments.ted_max_retry_seconds or _environment_positive_number(
        TED_MAX_RETRY_ENV,
        DEFAULT_TED_MAX_RETRY_SECONDS,
    )
    ted_max_records = arguments.ted_max_records_per_run or _environment_positive_integer(
        TED_MAX_RECORDS_ENV,
        DEFAULT_TED_MAX_RECORDS_PER_RUN,
    )
    ted_time_budget = arguments.ted_time_budget_seconds or _environment_positive_integer(
        TED_TIME_BUDGET_ENV,
        DEFAULT_TED_TIME_BUDGET_SECONDS,
    )

    cancellation = threading.Event()

    def request_termination(_signum: int, _frame: object) -> None:
        cancellation.set()

    previous_sigterm = signal.signal(signal.SIGTERM, request_termination)
    sources = {}
    try:
        sources = production_sources(
            ted_request_interval_seconds=ted_request_interval,
            ted_max_attempts=ted_max_attempts,
            ted_max_retry_seconds=ted_max_retry,
        )
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
                decp_batch_size=decp_batch_size,
                decp_time_budget_seconds=decp_time_budget,
                decp_overlap_days=decp_overlap_days,
                ted_max_records_per_run=ted_max_records,
                ted_time_budget_seconds=ted_time_budget,
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
