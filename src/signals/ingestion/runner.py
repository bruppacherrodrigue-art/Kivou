from __future__ import annotations

import dataclasses
import datetime as dt
import time
from collections.abc import Callable, Mapping
from typing import Any

import sqlalchemy as sa

from signals.ingestion.model import IngestionCounters, SourceName
from signals.ingestion.pipeline import IngestionPipeline, PipelineFailure, PipelineResult
from signals.ingestion.sources import AcquisitionFailure, ProductionSource, checkpoint_window
from signals.ingestion.state import (
    advance_checkpoint,
    fail_checkpoint,
    finish_run,
    load_checkpoint,
    start_run,
)

SOURCE_ORDER: tuple[SourceName, ...] = ("simap", "boamp", "decp", "ted")


@dataclasses.dataclass(frozen=True)
class RunOptions:
    sources: tuple[SourceName, ...] = SOURCE_ORDER
    since: dt.date | None = None
    until: dt.datetime | None = None
    max_records: int | None = None
    dry_run: bool = False


@dataclasses.dataclass(frozen=True)
class SourceOutcome:
    source: SourceName
    status: str
    counters: IngestionCounters
    duration_seconds: float
    error_category: str | None = None


@dataclasses.dataclass(frozen=True)
class RunOutcome:
    outcomes: tuple[SourceOutcome, ...]
    exit_code: int


class IncompleteSourceWindow(RuntimeError):
    category = "incomplete_window"


def _add_pipeline(left: PipelineResult, right: PipelineResult) -> PipelineResult:
    return PipelineResult(
        records_persisted=left.records_persisted + right.records_persisted,
        representations_linked=(left.representations_linked + right.representations_linked),
        opportunity_conflicts=left.opportunity_conflicts + right.opportunity_conflicts,
        signals_materialized=left.signals_materialized + right.signals_materialized,
    )


def _category(error: BaseException) -> str:
    declared = getattr(error, "category", None)
    if declared:
        return str(declared)
    status = getattr(error, "status_code", None)
    if status == 202:
        # TED may return 202 for a temporarily unavailable XML export or a
        # gateway/WAF challenge. Retrying is bounded; a persistent 202 keeps
        # the checkpoint untouched for a later run.
        return "server_error"
    if status == 429:
        return "rate_limited"
    if isinstance(status, int) and status >= 500:
        return "server_error"
    if status in (401, 403):
        return "unauthorized"
    if isinstance(status, int) and status >= 400:
        return "client_error"
    name = type(error).__name__.lower()
    if "parse" in name or "mapping" in name:
        return "malformed"
    if "timeout" in name:
        return "timeout"
    return "network" if status is None and "http" in name else "unexpected"


class IngestionRunner:
    def __init__(
        self,
        engine: sa.Engine,
        *,
        sources: Mapping[SourceName, ProductionSource],
        pipeline: IngestionPipeline,
        clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.engine = engine
        self.sources = sources
        self.pipeline = pipeline
        self.clock = clock or (lambda: dt.datetime.now(tz=dt.UTC))
        self.sleep = sleep

    def _acquire(self, source: ProductionSource, window: Any, options: RunOptions, started):
        for attempt in range(3):
            try:
                return source.acquire(
                    window,
                    retrieved_at=started,
                    max_records=options.max_records,
                )
            # Source isolation requires turning an unexpected adapter or pipeline
            # failure into one failed source outcome while the other sources run.
            except Exception as error:
                category = _category(error)
                if category not in {"timeout", "network", "server_error"} or attempt == 2:
                    raise
                self.sleep(float(2**attempt))
        raise AssertionError("bounded retry loop exhausted")  # pragma: no cover

    def run(self, options: RunOptions) -> RunOutcome:
        validation_now = self.clock()
        requested_until = options.until
        if requested_until is not None:
            if requested_until.tzinfo is None:
                requested_until = requested_until.replace(tzinfo=dt.UTC)
            if requested_until > validation_now:
                raise ValueError("--until cannot be in the future")
        outcomes = []
        for source_name in options.sources:
            source = self.sources[source_name]
            started = self.clock()
            until = options.until or started
            if until.tzinfo is None:
                until = until.replace(tzinfo=dt.UTC)
            previous = None
            run_id = None
            if not options.dry_run:
                with self.engine.begin() as connection:
                    previous = load_checkpoint(connection, source=source_name)
                    run_id = start_run(
                        connection,
                        source=source_name,
                        started_at=started,
                        dry_run=False,
                    )
            acquisition = None
            pipeline_total = PipelineResult()
            try:
                window = checkpoint_window(
                    source_name,
                    checkpoint_end=previous.window_end if previous else None,
                    until=until,
                    explicit_since=options.since,
                )
                acquisition_error = None
                try:
                    acquisition = self._acquire(source, window, options, started)
                except AcquisitionFailure as error:
                    acquisition = error.partial
                    acquisition_error = error
                if options.dry_run:
                    if acquisition_error is not None:
                        raise acquisition_error
                    counters = IngestionCounters(
                        records_fetched=acquisition.fetched,
                        records_accepted=acquisition.accepted,
                        records_rejected=acquisition.rejected,
                    )
                    outcomes.append(
                        SourceOutcome(
                            source_name,
                            "dry_run",
                            counters,
                            (self.clock() - started).total_seconds(),
                        )
                    )
                    continue
                if not acquisition.complete and acquisition_error is None:
                    raise IncompleteSourceWindow(
                        "selected source window was bounded before exhaustion"
                    )
                for publication in acquisition.publications:
                    try:
                        item = self.pipeline.process(
                            publication,
                            as_of=until.date(),
                            persisted_at=started,
                        )
                    except PipelineFailure as error:
                        pipeline_total = _add_pipeline(pipeline_total, error.partial)
                        raise
                    pipeline_total = _add_pipeline(pipeline_total, item)
                if acquisition_error is not None:
                    raise acquisition_error
                counters = IngestionCounters(
                    records_fetched=acquisition.fetched,
                    records_accepted=acquisition.accepted,
                    records_rejected=acquisition.rejected,
                    records_persisted=pipeline_total.records_persisted,
                    representations_linked=pipeline_total.representations_linked,
                    opportunity_conflicts=pipeline_total.opportunity_conflicts,
                    signals_materialized=pipeline_total.signals_materialized,
                )
                finished = self.clock()
                with self.engine.begin() as connection:
                    checkpoint = advance_checkpoint(
                        connection,
                        source=source_name,
                        cursor=acquisition.cursor_after,
                        window_end=until,
                        completed_at=finished,
                    )
                    assert run_id is not None
                    finish_run(
                        connection,
                        run_id=run_id,
                        finished_at=finished,
                        status="success",
                        counters=counters,
                        checkpoint_after=checkpoint,
                    )
                outcomes.append(
                    SourceOutcome(
                        source_name,
                        "success",
                        counters,
                        (finished - started).total_seconds(),
                    )
                )
            # This is the source isolation boundary: record the failure and
            # continue with the next selected public source.
            except Exception as error:  # noqa: BLE001
                category = _category(error)
                counters = IngestionCounters(
                    records_fetched=acquisition.fetched if acquisition else 0,
                    records_accepted=acquisition.accepted if acquisition else 0,
                    records_rejected=acquisition.rejected if acquisition else 0,
                    records_persisted=pipeline_total.records_persisted,
                    representations_linked=pipeline_total.representations_linked,
                    opportunity_conflicts=pipeline_total.opportunity_conflicts,
                    signals_materialized=pipeline_total.signals_materialized,
                    rate_limited_count=1 if category == "rate_limited" else 0,
                )
                finished = self.clock()
                if not options.dry_run:
                    with self.engine.begin() as connection:
                        retained_checkpoint = fail_checkpoint(
                            connection, source=source_name, failed_at=finished
                        )
                        assert run_id is not None
                        finish_run(
                            connection,
                            run_id=run_id,
                            finished_at=finished,
                            status="rate_limited" if category == "rate_limited" else "failed",
                            counters=counters,
                            checkpoint_after=retained_checkpoint,
                            error_category=category,
                            error_message=str(error),
                        )
                outcomes.append(
                    SourceOutcome(
                        source_name,
                        "rate_limited" if category == "rate_limited" else "failed",
                        counters,
                        (finished - started).total_seconds(),
                        error_category=category,
                    )
                )
        return RunOutcome(
            tuple(outcomes),
            exit_code=0 if all(item.status in {"success", "dry_run"} for item in outcomes) else 1,
        )
