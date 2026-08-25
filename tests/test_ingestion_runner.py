from __future__ import annotations

import datetime as dt
import json
import pathlib

import httpx
import pytest
import sqlalchemy as sa
from feed_helpers import LINKED_BOAMP, LINKED_DECP

from signals.connectors.decp import DecpClient, DecpWindowLimitError
from signals.connectors.ted.errors import TedHttpError
from signals.ingestion.pipeline import IngestionPipeline, PipelineFailure, PipelineResult
from signals.ingestion.runner import IngestionRunner, RunOptions
from signals.ingestion.sources import (
    AcquisitionFailure,
    AcquisitionResult,
    BoampSource,
    DecpSource,
    SourceWindow,
)
from signals.ingestion.state import advance_checkpoint, load_checkpoint, load_run, start_run
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import (
    contract_award,
    ingestion_checkpoint,
    ingestion_run,
    opportunity_representation,
    source_event,
)

NOW = dt.datetime(2026, 8, 19, 12, tzinfo=dt.UTC)


class SourceStub:
    def __init__(self, source, *, error=None):
        self.source = source
        self.error = error
        self.windows = []

    def acquire(self, window, *, retrieved_at, max_records=None, should_stop=None):
        self.windows.append(window)
        if should_stop is not None:
            should_stop()
        if self.error:
            raise self.error
        return AcquisitionResult(
            source=self.source,
            publications=(),
            fetched=1,
            accepted=1,
            rejected=0,
            complete=True,
            cursor_after={"window_end": window.until.isoformat()},
        )


class PipelineStub:
    def process(self, publication, *, as_of, persisted_at):
        return PipelineResult(records_persisted=1, signals_materialized=1)


def _engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'runner.db'}")
    migrate_to_latest(engine)
    return engine


def test_rate_limited_ted_does_not_block_or_roll_back_other_sources(tmp_path):
    engine = _engine(tmp_path)
    old_end = NOW - dt.timedelta(days=1)
    with engine.begin() as connection:
        start_run(connection, source="ted", started_at=old_end, dry_run=False, run_id="seed")
        advance_checkpoint(
            connection,
            source="ted",
            cursor={"page": 4},
            window_end=old_end,
            completed_at=old_end,
        )
    sources = {
        "simap": SourceStub("simap"),
        "boamp": SourceStub("boamp"),
        "decp": SourceStub("decp"),
        "ted": SourceStub("ted", error=TedHttpError("limited", status_code=429)),
    }

    result = IngestionRunner(
        engine,
        sources=sources,
        pipeline=PipelineStub(),
        clock=lambda: NOW,
        sleep=lambda seconds: None,
    ).run(RunOptions())

    assert result.exit_code == 1
    assert [item.status for item in result.outcomes] == [
        "success",
        "success",
        "success",
        "rate_limited",
    ]
    with engine.connect() as connection:
        ted = load_checkpoint(connection, source="ted")
        successes = {
            row.source: row.status
            for row in connection.execute(sa.select(ingestion_checkpoint)).all()
        }
        ted_run = connection.execute(
            sa.select(ingestion_run).where(
                ingestion_run.c.source == "ted",
                ingestion_run.c.status == "rate_limited",
            )
        ).one()
    assert ted is not None
    assert ted.window_end == old_end
    assert ted_run.checkpoint_before["window_end"] == old_end.isoformat()
    assert ted_run.checkpoint_after["window_end"] == old_end.isoformat()
    assert successes == {"simap": "success", "boamp": "success", "decp": "success", "ted": "failed"}


def test_restart_reuses_the_durable_checkpoint_with_overlap(tmp_path):
    engine = _engine(tmp_path)
    first_source = SourceStub("boamp")
    IngestionRunner(
        engine, sources={"boamp": first_source}, pipeline=PipelineStub(), clock=lambda: NOW
    ).run(RunOptions(sources=("boamp",)))

    restarted_at = NOW + dt.timedelta(hours=2)
    second_source = SourceStub("boamp")
    result = IngestionRunner(
        engine,
        sources={"boamp": second_source},
        pipeline=PipelineStub(),
        clock=lambda: restarted_at,
    ).run(RunOptions(sources=("boamp",)))

    assert result.exit_code == 0
    assert second_source.windows[0].since == NOW.date() - dt.timedelta(days=7)
    with engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(ingestion_run)).scalar() == 2


def test_dry_run_normalizes_without_writing_runtime_or_business_state(tmp_path):
    engine = _engine(tmp_path)
    result = IngestionRunner(
        engine,
        sources={"decp": SourceStub("decp")},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("decp",), max_records=2, dry_run=True))

    assert result.exit_code == 0
    assert result.outcomes[0].status == "dry_run"
    with engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(ingestion_run)).scalar() == 0
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(ingestion_checkpoint)).scalar()
            == 0
        )


def test_the_runner_never_imports_or_invokes_the_alert_job():
    source = pathlib.Path("src/signals/ingestion/runner.py").read_text(encoding="utf-8")
    assert "signals.alerts" not in source
    assert "smtp" not in source.lower()


def test_ted_accepted_but_not_ready_is_a_bounded_transient_failure(tmp_path):
    engine = _engine(tmp_path)
    sleeps = []
    result = IngestionRunner(
        engine,
        sources={
            "ted": SourceStub(
                "ted", error=TedHttpError("XML not ready", status_code=202)
            )
        },
        pipeline=PipelineStub(),
        clock=lambda: NOW,
        sleep=sleeps.append,
    ).run(RunOptions(sources=("ted",)))

    assert sleeps == [1.0, 2.0]
    assert result.exit_code == 1
    assert result.outcomes[0].error_category == "server_error"
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="ted")
    assert checkpoint is not None
    assert checkpoint.window_end is None


def test_invalid_source_window_is_isolated_and_later_sources_are_attempted(tmp_path):
    engine = _engine(tmp_path)
    sources = {"boamp": SourceStub("boamp"), "decp": SourceStub("decp")}

    result = IngestionRunner(
        engine,
        sources=sources,
        pipeline=PipelineStub(),
        clock=lambda: NOW,
    ).run(
        RunOptions(
            sources=("boamp", "decp"),
            since=NOW.date() + dt.timedelta(days=1),
            until=NOW,
        )
    )

    assert result.exit_code == 1
    assert [item.status for item in result.outcomes] == ["failed", "failed"]
    assert sources["boamp"].windows == []
    assert sources["decp"].windows == []
    with engine.connect() as connection:
        assert connection.execute(sa.select(ingestion_run.c.status)).scalars().all() == [
            "failed",
            "failed",
        ]


def test_future_until_is_rejected_before_any_runtime_state_is_written(tmp_path):
    engine = _engine(tmp_path)
    with pytest.raises(ValueError, match="future"):
        IngestionRunner(
            engine,
            sources={"boamp": SourceStub("boamp")},
            pipeline=PipelineStub(),
            clock=lambda: NOW,
        ).run(RunOptions(sources=("boamp",), until=NOW + dt.timedelta(seconds=1)))

    with engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(ingestion_run)).scalar() == 0
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(ingestion_checkpoint)).scalar()
            == 0
        )


def test_partial_acquisition_and_pipeline_progress_are_kept_in_the_run_audit(tmp_path):
    engine = _engine(tmp_path)
    partial = AcquisitionResult(
        source="ted",
        publications=(),
        fetched=7,
        accepted=2,
        rejected=1,
        complete=False,
        cursor_after={"window_end": NOW.date().isoformat()},
    )
    source = SourceStub(
        "ted",
        error=AcquisitionFailure(
            TedHttpError("limited", status_code=429), partial=partial
        ),
    )

    result = IngestionRunner(
        engine,
        sources={"ted": source},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("ted",)))

    assert result.outcomes[0].counters.records_fetched == 7
    assert result.outcomes[0].counters.records_accepted == 2
    assert result.outcomes[0].counters.records_rejected == 1

    class PipelineFailureStub:
        def process(self, publication, *, as_of, persisted_at):
            raise PipelineFailure(
                RuntimeError("matching unavailable"),
                partial=PipelineResult(records_persisted=2, signals_materialized=1),
            )

    publication = object()
    successful_acquisition = AcquisitionResult(
        source="boamp",
        publications=(publication,),
        fetched=2,
        accepted=2,
        rejected=0,
        complete=True,
        cursor_after={"window_end": NOW.date().isoformat()},
    )

    class SuccessfulSource(SourceStub):
        def acquire(self, window, *, retrieved_at, max_records=None):
            return successful_acquisition

    pipeline_result = IngestionRunner(
        engine,
        sources={"boamp": SuccessfulSource("boamp")},
        pipeline=PipelineFailureStub(),
        clock=lambda: NOW + dt.timedelta(minutes=1),
    ).run(RunOptions(sources=("boamp",)))

    assert pipeline_result.outcomes[0].counters.records_persisted == 2
    assert pipeline_result.outcomes[0].counters.signals_materialized == 1


class _BoampRecordClient:
    def __init__(self, record):
        self.record = record

    def fetch_awards_since(self, since, *, until=None, max_records=None):
        yield self.record


class _BoampRecordsClient:
    def __init__(self, records):
        self.records = records

    def fetch_awards_since(self, since, *, until=None, max_records=None):
        yield from self.records


def test_safe_terminal_skip_allows_boamp_checkpoint_to_advance(tmp_path):
    engine = _engine(tmp_path)
    source = BoampSource(
        _BoampRecordsClient(
            [
                {
                    "idweb": "26-dsp-safe-skip",
                    "donnees": json.dumps(
                        {"DSP": {"nature": "delegation_service_public"}}
                    ),
                },
                LINKED_BOAMP,
            ]
        )
    )

    result = IngestionRunner(
        engine,
        sources={"boamp": source},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("boamp",)))

    assert result.exit_code == 0
    assert result.outcomes[0].counters.records_rejected == 1
    assert result.outcomes[0].counters.records_accepted == 1
    assert result.outcomes[0].counters.records_persisted == 1
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="boamp")
    assert checkpoint is not None
    assert checkpoint.window_end == NOW


def test_malformed_boamp_retains_the_previous_successful_checkpoint(tmp_path):
    engine = _engine(tmp_path)
    previous_end = NOW - dt.timedelta(days=1)
    with engine.begin() as connection:
        start_run(
            connection,
            source="boamp",
            started_at=previous_end,
            dry_run=False,
            run_id="boamp-seed",
        )
        advance_checkpoint(
            connection,
            source="boamp",
            cursor={"window_end": previous_end.date().isoformat()},
            window_end=previous_end,
            completed_at=previous_end,
        )
    source = BoampSource(
        _BoampRecordClient({"idweb": "malformed", "donnees": "{not-json"})
    )

    result = IngestionRunner(
        engine,
        sources={"boamp": source},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("boamp",)))

    assert result.exit_code == 1
    assert result.outcomes[0].error_category == "malformed"
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="boamp")
    assert checkpoint is not None
    assert checkpoint.window_end == previous_end


class _DecpFailureAfterDurableCandidate:
    def fetch_contracts_since(
        self, since, *, until=None, max_records=None, should_stop=None
    ):
        if should_stop is not None:
            should_stop()
        yield LINKED_DECP
        raise DecpWindowLimitError("later DECP child window changed")


class _DecpReplayWithBoundaryDuplicate:
    def fetch_contracts_since(
        self, since, *, until=None, max_records=None, should_stop=None
    ):
        if should_stop is not None:
            should_stop()
        yield LINKED_DECP
        yield LINKED_DECP


def test_decp_later_slice_failure_retains_checkpoint_and_rerun_is_idempotent(tmp_path):
    engine = _engine(tmp_path)
    previous_end = NOW - dt.timedelta(days=1)
    with engine.begin() as connection:
        start_run(
            connection,
            source="decp",
            started_at=previous_end,
            dry_run=False,
            run_id="decp-partition-seed",
        )
        advance_checkpoint(
            connection,
            source="decp",
            cursor={"window_end": previous_end.date().isoformat()},
            window_end=previous_end,
            completed_at=previous_end,
        )

    failed = IngestionRunner(
        engine,
        sources={"decp": DecpSource(_DecpFailureAfterDurableCandidate())},
        pipeline=IngestionPipeline(engine),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("decp",)))

    assert failed.exit_code == 1
    assert failed.outcomes[0].error_category == "source_limit"
    assert failed.outcomes[0].counters.records_persisted == 1
    with engine.connect() as connection:
        checkpoint_after_failure = load_checkpoint(connection, source="decp")
        counts_after_failure = tuple(
            connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            for table in (source_event, contract_award, opportunity_representation)
        )
    assert checkpoint_after_failure is not None
    assert checkpoint_after_failure.window_end == previous_end
    assert counts_after_failure == (1, 1, 1)

    restarted_at = NOW + dt.timedelta(hours=1)
    recovered = IngestionRunner(
        engine,
        sources={"decp": DecpSource(_DecpReplayWithBoundaryDuplicate())},
        pipeline=IngestionPipeline(engine),
        clock=lambda: restarted_at,
    ).run(RunOptions(sources=("decp",)))

    assert recovered.exit_code == 0
    with engine.connect() as connection:
        checkpoint_after_recovery = load_checkpoint(connection, source="decp")
        counts_after_recovery = tuple(
            connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            for table in (source_event, contract_award, opportunity_representation)
        )
    assert checkpoint_after_recovery is not None
    assert checkpoint_after_recovery.window_end == restarted_at
    assert counts_after_recovery == counts_after_failure == (1, 1, 1)


@pytest.mark.parametrize("final_total", [0, 2])
def test_decp_count_fetch_drift_is_source_limit_and_does_not_advance_checkpoint(
    tmp_path, final_total: int
):
    engine = _engine(tmp_path)
    previous_end = NOW - dt.timedelta(days=1)
    with engine.begin() as connection:
        start_run(
            connection,
            source="decp",
            started_at=previous_end,
            dry_run=False,
            run_id="decp-drift-seed",
        )
        advance_checkpoint(
            connection,
            source="decp",
            cursor={"window_end": previous_end.date().isoformat()},
            window_end=previous_end,
            completed_at=previous_end,
        )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={"total_count": 1, "results": [{"id": "count-probe"}]},
            )
        if calls == 2:
            return httpx.Response(
                200,
                json={"total_count": 1, "results": [LINKED_DECP]},
            )
        return httpx.Response(
            200,
            json={
                "total_count": final_total,
                "results": [] if final_total == 0 else [{"id": "final-count"}],
            },
        )

    source = DecpSource(
        DecpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    )
    result = IngestionRunner(
        engine,
        sources={"decp": source},
        pipeline=IngestionPipeline(engine),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("decp",)))

    assert result.exit_code == 1
    assert result.outcomes[0].error_category == "source_limit"
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="decp")
        stored = connection.execute(
            sa.select(sa.func.count()).select_from(contract_award)
        ).scalar_one()
    assert checkpoint is not None
    assert checkpoint.window_end == previous_end
    assert stored == 1


class DailyDecpSourceStub:
    source = "decp"

    def __init__(self, *, fail_on: dt.date | None = None):
        self.fail_on = fail_on
        self.windows = []

    def acquire(
        self,
        window,
        *,
        retrieved_at,
        max_records=None,
        should_stop=None,
    ):
        self.windows.append(window)
        if should_stop is not None:
            should_stop()
        if window.since == self.fail_on:
            raise DecpWindowLimitError("daily window changed")
        return AcquisitionResult(
            source="decp",
            publications=(),
            fetched=1,
            accepted=1,
            rejected=0,
            complete=True,
            cursor_after={"window_end": window.until.isoformat()},
        )


def test_decp_quota_checkpoints_each_daily_unit_and_exits_successfully_with_pending_work(
    tmp_path,
):
    engine = _engine(tmp_path)
    source = DailyDecpSourceStub()

    result = IngestionRunner(
        engine,
        sources={"decp": source},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
    ).run(
        RunOptions(
            sources=("decp",),
            decp_max_windows_per_run=2,
            decp_overlap_days=2,
        )
    )

    assert result.exit_code == 0
    assert result.outcomes[0].status == "success"
    assert result.outcomes[0].work_pending is True
    assert source.windows == [
        SourceWindow(dt.date(2026, 8, 17), dt.date(2026, 8, 17)),
        SourceWindow(dt.date(2026, 8, 18), dt.date(2026, 8, 18)),
    ]
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="decp")
        run = connection.execute(sa.select(ingestion_run)).one()
    assert checkpoint is not None
    assert checkpoint.cursor == {
        "version": 1,
        "cycle_end": "2026-08-19",
        "next_window_start": "2026-08-19",
    }
    assert checkpoint.window_end == dt.datetime(2026, 8, 18, tzinfo=dt.UTC)
    assert run.status == "success"
    assert run.records_fetched == 2


def test_decp_failure_retains_the_checkpoint_from_the_previous_daily_unit(tmp_path):
    engine = _engine(tmp_path)
    source = DailyDecpSourceStub(fail_on=dt.date(2026, 8, 18))

    result = IngestionRunner(
        engine,
        sources={"decp": source},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
    ).run(
        RunOptions(
            sources=("decp",),
            decp_max_windows_per_run=3,
            decp_overlap_days=2,
        )
    )

    assert result.exit_code == 1
    assert result.outcomes[0].error_category == "source_limit"
    assert result.outcomes[0].counters.records_fetched == 1
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="decp")
        run = connection.execute(sa.select(ingestion_run)).one()
    assert checkpoint is not None
    assert checkpoint.cursor["next_window_start"] == "2026-08-18"
    assert checkpoint.window_end == dt.datetime(2026, 8, 17, tzinfo=dt.UTC)
    assert run.status == "failed"
    assert run.checkpoint_after["cursor"]["next_window_start"] == "2026-08-18"


class _SingleRecordDecpClient:
    def fetch_contracts_since(
        self, since, *, until=None, max_records=None, should_stop=None
    ):
        if should_stop is not None:
            should_stop()
        yield LINKED_DECP


def test_decp_daily_replay_is_idempotent_across_new_overlap_cycles(tmp_path):
    engine = _engine(tmp_path)
    source = DecpSource(_SingleRecordDecpClient())
    first_at = NOW
    second_at = NOW + dt.timedelta(days=1)

    first = IngestionRunner(
        engine,
        sources={"decp": source},
        pipeline=IngestionPipeline(engine),
        clock=lambda: first_at,
    ).run(
        RunOptions(
            sources=("decp",),
            decp_max_windows_per_run=2,
            decp_overlap_days=1,
        )
    )
    second = IngestionRunner(
        engine,
        sources={"decp": source},
        pipeline=IngestionPipeline(engine),
        clock=lambda: second_at,
    ).run(
        RunOptions(
            sources=("decp",),
            decp_max_windows_per_run=3,
            decp_overlap_days=1,
        )
    )

    assert first.exit_code == second.exit_code == 0
    with engine.connect() as connection:
        counts = tuple(
            connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            for table in (source_event, contract_award, opportunity_representation)
        )
        checkpoint = load_checkpoint(connection, source="decp")
    assert counts == (1, 1, 1)
    assert checkpoint is not None
    assert checkpoint.window_end == second_at


def test_decp_deadline_is_a_successful_bounded_pass_and_keeps_the_unit_for_replay(
    tmp_path,
):
    engine = _engine(tmp_path)
    source = DailyDecpSourceStub()
    instants = iter((0.0, 0.0, 6.0))

    result = IngestionRunner(
        engine,
        sources={"decp": source},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
        monotonic=lambda: next(instants),
    ).run(
        RunOptions(
            sources=("decp",),
            decp_time_budget_seconds=5,
            decp_overlap_days=1,
        )
    )

    assert result.exit_code == 0
    assert result.outcomes[0].status == "success"
    assert result.outcomes[0].work_pending is True
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="decp")
        run = connection.execute(sa.select(ingestion_run)).one()
    assert checkpoint is not None
    assert checkpoint.cursor["next_window_start"] == "2026-08-18"
    assert checkpoint.window_end is None
    assert run.status == "success"


def test_decp_termination_is_terminal_and_never_leaves_the_run_running(tmp_path):
    engine = _engine(tmp_path)

    result = IngestionRunner(
        engine,
        sources={"decp": DailyDecpSourceStub()},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
        cancel_requested=lambda: True,
    ).run(
        RunOptions(sources=("decp",), decp_overlap_days=1)
    )

    assert result.exit_code == 1
    assert result.outcomes[0].status == "failed"
    assert result.outcomes[0].error_category == "terminated"
    with engine.connect() as connection:
        run_id = connection.execute(sa.select(ingestion_run.c.run_id)).scalar_one()
        run = load_run(connection, run_id=run_id)
    assert run.status == "failed"
    assert run.finished_at == NOW
    assert run.error_category == "terminated"


def test_runner_reconciles_stale_decp_runs_immediately_before_starting(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        start_run(
            connection,
            source="decp",
            started_at=NOW - dt.timedelta(hours=2),
            dry_run=False,
            run_id="orphaned",
        )

    result = IngestionRunner(
        engine,
        sources={"decp": DailyDecpSourceStub()},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
    ).run(
        RunOptions(
            sources=("decp",),
            decp_max_windows_per_run=1,
            decp_overlap_days=1,
            ingestion_stale_run_seconds=3600,
        )
    )

    assert result.exit_code == 0
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(
                ingestion_run.c.run_id,
                ingestion_run.c.status,
                ingestion_run.c.error_category,
            ).order_by(ingestion_run.c.started_at)
        ).all()
    assert rows[0] == ("orphaned", "failed", "stale_run_reconciled")
    assert rows[1].status == "success"
