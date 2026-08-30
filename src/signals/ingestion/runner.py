from __future__ import annotations

import dataclasses
import datetime as dt
import time
from collections.abc import Callable, Mapping
from typing import Any

import sqlalchemy as sa

from signals.connectors.decp import PAGE_SIZE as DECP_PAGE_SIZE
from signals.ingestion.convergence import (
    advance_decp_batch,
    decp_checkpoint_high_water,
    next_decp_window,
    plan_decp_cycle,
)
from signals.ingestion.model import IngestionCounters, SourceName
from signals.ingestion.pipeline import IngestionPipeline, PipelineFailure, PipelineResult
from signals.ingestion.sources import AcquisitionFailure, ProductionSource, checkpoint_window
from signals.ingestion.state import (
    advance_checkpoint,
    complete_checkpoint_pass,
    fail_checkpoint,
    finish_run,
    load_checkpoint,
    reconcile_stale_runs,
    save_checkpoint_cursor,
    start_run,
)
from signals.ingestion.ted_convergence import plan_ted_cycle

SOURCE_ORDER: tuple[SourceName, ...] = ("simap", "boamp", "decp", "ted")


@dataclasses.dataclass(frozen=True)
class RunOptions:
    sources: tuple[SourceName, ...] = SOURCE_ORDER
    since: dt.date | None = None
    until: dt.datetime | None = None
    max_records: int | None = None
    dry_run: bool = False
    decp_max_windows_per_run: int | None = None
    decp_batch_size: int = DECP_PAGE_SIZE
    decp_time_budget_seconds: float | None = None
    decp_overlap_days: int = 30
    ted_max_records_per_run: int = 500
    ted_time_budget_seconds: float = 1200
    ingestion_stale_run_seconds: int = 3600


@dataclasses.dataclass(frozen=True)
class SourceOutcome:
    source: SourceName
    status: str
    counters: IngestionCounters
    duration_seconds: float
    error_category: str | None = None
    work_pending: bool = False
    error_type: str | None = None


@dataclasses.dataclass(frozen=True)
class RunOutcome:
    outcomes: tuple[SourceOutcome, ...]
    exit_code: int


class IncompleteSourceWindow(RuntimeError):
    category = "incomplete_window"


class BoundedPassComplete(RuntimeError):
    category = "bounded_pass_complete"


class IngestionTerminated(RuntimeError):
    category = "terminated"


def _add_pipeline(left: PipelineResult, right: PipelineResult) -> PipelineResult:
    return PipelineResult(
        records_persisted=left.records_persisted + right.records_persisted,
        representations_linked=(left.representations_linked + right.representations_linked),
        opportunity_conflicts=left.opportunity_conflicts + right.opportunity_conflicts,
        signals_materialized=left.signals_materialized + right.signals_materialized,
    )


def _add_counters(left: IngestionCounters, right: IngestionCounters) -> IngestionCounters:
    return IngestionCounters(
        **{
            field.name: getattr(left, field.name) + getattr(right, field.name)
            for field in dataclasses.fields(IngestionCounters)
        }
    )


def _counters(
    acquisition: Any | None,
    pipeline: PipelineResult,
    *,
    category: str | None = None,
) -> IngestionCounters:
    return IngestionCounters(
        records_fetched=acquisition.fetched if acquisition else 0,
        records_accepted=acquisition.accepted if acquisition else 0,
        records_rejected=acquisition.rejected if acquisition else 0,
        records_persisted=pipeline.records_persisted,
        representations_linked=pipeline.representations_linked,
        opportunity_conflicts=pipeline.opportunity_conflicts,
        signals_materialized=pipeline.signals_materialized,
        rate_limited_count=1 if category == "rate_limited" else 0,
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


_ERROR_TYPE_FAMILIES: tuple[tuple[type[BaseException], str], ...] = (
    (TimeoutError, "TimeoutError"),
    (ConnectionError, "ConnectionError"),
    (TypeError, "TypeError"),
    (ValueError, "ValueError"),
    (OSError, "OSError"),
    (RuntimeError, "RuntimeError"),
)


def _error_type(error: BaseException) -> str:
    root = error
    seen = {id(root)}
    while True:
        try:
            reduced = BaseException.__reduce__(root)
        except BaseException:  # noqa: BLE001
            break
        if type(reduced) is not tuple or len(reduced) != 3:
            break
        state = reduced[2]
        if type(state) is not dict:
            break
        cause = state.get("cause")
        if not isinstance(cause, BaseException):
            break
        if id(cause) in seen:
            break
        seen.add(id(cause))
        root = cause
    for family, label in _ERROR_TYPE_FAMILIES:
        if isinstance(root, family):
            return label
    return "Exception"


class IngestionRunner:
    def __init__(
        self,
        engine: sa.Engine,
        *,
        sources: Mapping[SourceName, ProductionSource],
        pipeline: IngestionPipeline,
        clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> None:
        self.engine = engine
        self.sources = sources
        self.pipeline = pipeline
        self.clock = clock or (lambda: dt.datetime.now(tz=dt.UTC))
        self.sleep = sleep
        self.monotonic = monotonic
        self.cancel_requested = cancel_requested or (lambda: False)

    def _acquire(
        self,
        source: ProductionSource,
        window: Any,
        options: RunOptions,
        started: dt.datetime,
        *,
        should_stop: Callable[[], None] | None = None,
    ):
        max_attempts = 1 if source.source == "ted" and options.dry_run else 3
        for attempt in range(max_attempts):
            try:
                self._check_cancellation()
                arguments = {
                    "retrieved_at": started,
                    "max_records": options.max_records,
                }
                if should_stop is not None:
                    arguments["should_stop"] = should_stop
                return source.acquire(window, **arguments)
            # Source isolation requires turning an unexpected adapter or pipeline
            # failure into one failed source outcome while the other sources run.
            except Exception as error:
                category = _category(error)
                if (
                    category not in {"timeout", "network", "server_error"}
                    or attempt == max_attempts - 1
                ):
                    raise
                self.sleep(float(2**attempt))
        raise AssertionError("bounded retry loop exhausted")  # pragma: no cover

    def _start_persisted_run(
        self,
        *,
        source: SourceName,
        started_at: dt.datetime,
        stale_after_seconds: int,
    ):
        with self.engine.begin() as connection:
            reconcile_stale_runs(
                connection,
                source=source,
                stale_before=started_at - dt.timedelta(seconds=stale_after_seconds),
                reconciled_at=started_at,
            )
            previous = load_checkpoint(connection, source=source)
            run_id = start_run(
                connection,
                source=source,
                started_at=started_at,
                dry_run=False,
            )
        return previous, run_id

    def _acquire_decp_batch(
        self,
        source: ProductionSource,
        window: Any,
        options: RunOptions,
        started: dt.datetime,
        *,
        offset: int,
        expected_total: int | None,
        batch_size: int,
        deadline: float | None,
    ):
        for attempt in range(3):
            try:
                if attempt:
                    self._check_decp_stop(deadline=deadline)
                else:
                    self._check_cancellation()
                return source.acquire_batch(
                    window,
                    retrieved_at=started,
                    offset=offset,
                    expected_total=expected_total,
                    batch_size=batch_size,
                )
            except Exception as error:
                category = _category(error)
                if category not in {"timeout", "network", "server_error"} or attempt == 2:
                    raise
                self.sleep(float(2**attempt))
        raise AssertionError("bounded retry loop exhausted")  # pragma: no cover

    def _check_cancellation(self) -> None:
        if self.cancel_requested():
            raise IngestionTerminated("ingestion termination requested")

    def _check_decp_stop(self, *, deadline: float | None) -> None:
        self._check_cancellation()
        if deadline is not None and self.monotonic() >= deadline:
            raise BoundedPassComplete("DECP pass time budget reached")

    def _check_ted_stop(self, *, deadline: float | None) -> None:
        self._check_cancellation()
        if deadline is not None and self.monotonic() >= deadline:
            raise BoundedPassComplete("TED pass time budget reached")

    @staticmethod
    def _ted_window_end(
        *,
        previous: dt.datetime | None,
        cycle_until: dt.date,
        requested_until: dt.datetime,
    ) -> dt.datetime:
        candidate = (
            requested_until
            if cycle_until == requested_until.date()
            else dt.datetime.combine(cycle_until, dt.time.min, tzinfo=dt.UTC)
        )
        return max(previous, candidate) if previous is not None else candidate

    def _run_ted(
        self,
        *,
        source: ProductionSource,
        options: RunOptions,
        started: dt.datetime,
        until: dt.datetime,
    ) -> SourceOutcome:
        previous, run_id = self._start_persisted_run(
            source="ted",
            started_at=started,
            stale_after_seconds=options.ingestion_stale_run_seconds,
        )
        deadline = self.monotonic() + options.ted_time_budget_seconds
        total = IngestionCounters()
        acquisition = None
        unit_pipeline = PipelineResult()
        unit_accounted = True
        work_pending = False
        try:
            window = checkpoint_window(
                "ted",
                checkpoint_end=previous.window_end if previous else None,
                until=until,
                explicit_since=options.since,
            )
            cursor = plan_ted_cycle(
                cursor=previous.cursor if previous else None,
                window=window,
                page_size=source.page_size,
            )
            with self.engine.begin() as connection:
                save_checkpoint_cursor(
                    connection,
                    source="ted",
                    cursor=cursor.as_dict(),
                    updated_at=started,
                )

            record_limit = options.ted_max_records_per_run
            if options.max_records is not None:
                record_limit = min(record_limit, options.max_records)

            while not cursor.complete:
                if total.records_accepted >= record_limit:
                    work_pending = True
                    break
                self._check_ted_stop(deadline=deadline)
                acquisition = None
                unit_pipeline = PipelineResult()
                unit_accounted = False
                acquisition_error = None
                try:
                    unit = source.acquire_unit(cursor, retrieved_at=started)
                    acquisition = unit.acquisition
                except AcquisitionFailure as error:
                    acquisition = error.partial
                    acquisition_error = error

                acquisition_category = (
                    _category(acquisition_error) if acquisition_error is not None else None
                )
                if acquisition_error is not None:
                    total = _add_counters(
                        total,
                        _counters(acquisition, unit_pipeline, category=acquisition_category),
                    )
                    unit_accounted = True
                    raise acquisition_error

                for publication in acquisition.publications:
                    try:
                        item = self.pipeline.process(
                            publication,
                            as_of=until.date(),
                            persisted_at=started,
                        )
                    except PipelineFailure as error:
                        unit_pipeline = _add_pipeline(unit_pipeline, error.partial)
                        raise
                    unit_pipeline = _add_pipeline(unit_pipeline, item)

                total = _add_counters(total, _counters(acquisition, unit_pipeline))
                unit_accounted = True
                cursor = unit.cursor_after
                unit_finished = self.clock()
                with self.engine.begin() as connection:
                    if cursor.complete:
                        advance_checkpoint(
                            connection,
                            source="ted",
                            cursor=cursor.as_dict(),
                            window_end=self._ted_window_end(
                                previous=previous.window_end if previous else None,
                                cycle_until=cursor.cycle_until,
                                requested_until=until,
                            ),
                            completed_at=unit_finished,
                        )
                    else:
                        save_checkpoint_cursor(
                            connection,
                            source="ted",
                            cursor=cursor.as_dict(),
                            updated_at=unit_finished,
                        )
                self._check_cancellation()

            finished = self.clock()
            with self.engine.begin() as connection:
                checkpoint = complete_checkpoint_pass(
                    connection,
                    source="ted",
                    completed_at=finished,
                )
                finish_run(
                    connection,
                    run_id=run_id,
                    finished_at=finished,
                    status="success",
                    counters=total,
                    checkpoint_after=checkpoint,
                )
            return SourceOutcome(
                "ted",
                "success",
                total,
                (finished - started).total_seconds(),
                work_pending=work_pending,
            )
        except BoundedPassComplete:
            finished = self.clock()
            with self.engine.begin() as connection:
                checkpoint = complete_checkpoint_pass(
                    connection,
                    source="ted",
                    completed_at=finished,
                )
                finish_run(
                    connection,
                    run_id=run_id,
                    finished_at=finished,
                    status="success",
                    counters=total,
                    checkpoint_after=checkpoint,
                )
            return SourceOutcome(
                "ted",
                "success",
                total,
                (finished - started).total_seconds(),
                work_pending=True,
            )
        except Exception as error:  # noqa: BLE001
            category = _category(error)
            if not unit_accounted:
                total = _add_counters(
                    total,
                    _counters(acquisition, unit_pipeline, category=category),
                )
            finished = self.clock()
            with self.engine.begin() as connection:
                retained_checkpoint = fail_checkpoint(
                    connection,
                    source="ted",
                    failed_at=finished,
                )
                finish_run(
                    connection,
                    run_id=run_id,
                    finished_at=finished,
                    status="rate_limited" if category == "rate_limited" else "failed",
                    counters=total,
                    checkpoint_after=retained_checkpoint,
                    error_category=category,
                    error_message=str(error),
                )
            return SourceOutcome(
                "ted",
                "rate_limited" if category == "rate_limited" else "failed",
                total,
                (finished - started).total_seconds(),
                error_category=category,
                error_type=_error_type(error),
                work_pending=True,
            )

    def _run_decp(
        self,
        *,
        source: ProductionSource,
        options: RunOptions,
        started: dt.datetime,
        until: dt.datetime,
    ) -> SourceOutcome:
        previous, run_id = self._start_persisted_run(
            source="decp",
            started_at=started,
            stale_after_seconds=options.ingestion_stale_run_seconds,
        )
        deadline = (
            self.monotonic() + options.decp_time_budget_seconds
            if options.decp_time_budget_seconds is not None
            else None
        )
        total = IngestionCounters()
        acquisition = None
        unit_pipeline = PipelineResult()
        unit_accounted = True
        work_pending = False
        try:
            cursor = plan_decp_cycle(
                cursor=previous.cursor if previous else None,
                checkpoint_end=previous.window_end if previous else None,
                until=until,
                overlap_days=options.decp_overlap_days,
                explicit_since=options.since,
            )
            with self.engine.begin() as connection:
                save_checkpoint_cursor(
                    connection,
                    source="decp",
                    cursor=cursor.as_dict(),
                    updated_at=started,
                )

            completed_windows = 0
            while (window := next_decp_window(cursor)) is not None:
                if (
                    options.decp_max_windows_per_run is not None
                    and completed_windows >= options.decp_max_windows_per_run
                ):
                    work_pending = True
                    break
                if (
                    options.max_records is not None
                    and total.records_fetched >= options.max_records
                ):
                    work_pending = True
                    break
                remaining_records = (
                    options.max_records - total.records_fetched
                    if options.max_records is not None
                    else options.decp_batch_size
                )
                batch_size = min(options.decp_batch_size, remaining_records)
                acquisition = None
                batch = None
                unit_pipeline = PipelineResult()
                unit_accounted = False
                self._check_decp_stop(deadline=deadline)
                acquisition_error = None
                try:
                    batch = self._acquire_decp_batch(
                        source,
                        window,
                        options,
                        started,
                        offset=cursor.offset,
                        expected_total=cursor.window_total,
                        batch_size=batch_size,
                        deadline=deadline,
                    )
                    acquisition = batch.acquisition
                except AcquisitionFailure as error:
                    acquisition = error.partial
                    acquisition_error = error

                acquisition_category = (
                    _category(acquisition_error) if acquisition_error is not None else None
                )
                if acquisition_category in {
                    BoundedPassComplete.category,
                    IngestionTerminated.category,
                }:
                    raise acquisition_error
                for publication in acquisition.publications:
                    try:
                        item = self.pipeline.process(
                            publication,
                            as_of=until.date(),
                            persisted_at=started,
                        )
                    except PipelineFailure as error:
                        unit_pipeline = _add_pipeline(unit_pipeline, error.partial)
                        raise
                    unit_pipeline = _add_pipeline(unit_pipeline, item)

                total = _add_counters(
                    total,
                    _counters(acquisition, unit_pipeline, category=acquisition_category),
                )
                unit_accounted = True
                if acquisition_error is not None:
                    raise acquisition_error

                assert batch is not None
                cursor = advance_decp_batch(
                    cursor,
                    window,
                    next_offset=batch.next_offset,
                    window_total=batch.window_total,
                    day_complete=batch.day_complete,
                )
                unit_finished = self.clock()
                with self.engine.begin() as connection:
                    if batch.day_complete:
                        high_water = decp_checkpoint_high_water(
                            previous=previous.window_end if previous else None,
                            completed_window=window,
                            requested_until=until,
                        )
                        advance_checkpoint(
                            connection,
                            source="decp",
                            cursor=cursor.as_dict(),
                            window_end=high_water,
                            completed_at=unit_finished,
                        )
                    else:
                        save_checkpoint_cursor(
                            connection,
                            source="decp",
                            cursor=cursor.as_dict(),
                            updated_at=unit_finished,
                        )
                if batch.day_complete:
                    completed_windows += 1
                self._check_cancellation()

            finished = self.clock()
            with self.engine.begin() as connection:
                checkpoint = complete_checkpoint_pass(
                    connection,
                    source="decp",
                    completed_at=finished,
                )
                finish_run(
                    connection,
                    run_id=run_id,
                    finished_at=finished,
                    status="success",
                    counters=total,
                    checkpoint_after=checkpoint,
                )
            return SourceOutcome(
                "decp",
                "success",
                total,
                (finished - started).total_seconds(),
                work_pending=work_pending,
            )
        except Exception as error:  # noqa: BLE001
            category = _category(error)
            if not unit_accounted:
                total = _add_counters(
                    total,
                    _counters(acquisition, unit_pipeline, category=category),
                )
            if category == BoundedPassComplete.category:
                finished = self.clock()
                with self.engine.begin() as connection:
                    checkpoint = complete_checkpoint_pass(
                        connection,
                        source="decp",
                        completed_at=finished,
                    )
                    finish_run(
                        connection,
                        run_id=run_id,
                        finished_at=finished,
                        status="success",
                        counters=total,
                        checkpoint_after=checkpoint,
                    )
                return SourceOutcome(
                    "decp",
                    "success",
                    total,
                    (finished - started).total_seconds(),
                    work_pending=True,
                )

            finished = self.clock()
            with self.engine.begin() as connection:
                retained_checkpoint = fail_checkpoint(
                    connection,
                    source="decp",
                    failed_at=finished,
                )
                finish_run(
                    connection,
                    run_id=run_id,
                    finished_at=finished,
                    status="rate_limited" if category == "rate_limited" else "failed",
                    counters=total,
                    checkpoint_after=retained_checkpoint,
                    error_category=category,
                    error_message=str(error),
                )
            return SourceOutcome(
                "decp",
                "rate_limited" if category == "rate_limited" else "failed",
                total,
                (finished - started).total_seconds(),
                error_category=category,
                error_type=_error_type(error),
                work_pending=True,
            )

    def run(self, options: RunOptions) -> RunOutcome:
        if options.decp_max_windows_per_run is not None and options.decp_max_windows_per_run < 1:
            raise ValueError("DECP max windows must be positive")
        if options.decp_batch_size < 1 or options.decp_batch_size > DECP_PAGE_SIZE:
            raise ValueError(f"DECP batch size must be between 1 and {DECP_PAGE_SIZE}")
        if options.decp_time_budget_seconds is not None and options.decp_time_budget_seconds <= 0:
            raise ValueError("DECP time budget must be positive")
        if options.decp_overlap_days < 1:
            raise ValueError("DECP overlap must be positive")
        if options.ted_max_records_per_run < 1:
            raise ValueError("TED max records must be positive")
        if options.ted_time_budget_seconds <= 0:
            raise ValueError("TED time budget must be positive")
        if options.ingestion_stale_run_seconds < 1:
            raise ValueError("ingestion stale-run threshold must be positive")
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
            if source_name == "decp" and not options.dry_run:
                outcome = self._run_decp(
                    source=source,
                    options=options,
                    started=started,
                    until=until,
                )
                outcomes.append(outcome)
                if outcome.error_category == IngestionTerminated.category:
                    break
                continue
            if (
                source_name == "ted"
                and not options.dry_run
                and hasattr(source, "acquire_unit")
            ):
                outcome = self._run_ted(
                    source=source,
                    options=options,
                    started=started,
                    until=until,
                )
                outcomes.append(outcome)
                if outcome.error_category == IngestionTerminated.category:
                    break
                continue
            previous = None
            run_id = None
            if not options.dry_run:
                previous, run_id = self._start_persisted_run(
                    source=source_name,
                    started_at=started,
                    stale_after_seconds=options.ingestion_stale_run_seconds,
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
                self._check_cancellation()
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
                    self._check_cancellation()
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
                        error_type=_error_type(error),
                        work_pending=True,
                    )
                )
                if category == IngestionTerminated.category:
                    break
        return RunOutcome(
            tuple(outcomes),
            exit_code=0 if all(item.status in {"success", "dry_run"} for item in outcomes) else 1,
        )
