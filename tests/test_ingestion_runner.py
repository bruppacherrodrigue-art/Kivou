from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa

from signals.connectors.ted.errors import TedHttpError
from signals.ingestion.pipeline import PipelineFailure, PipelineResult
from signals.ingestion.runner import IngestionRunner, RunOptions
from signals.ingestion.sources import AcquisitionFailure, AcquisitionResult
from signals.ingestion.state import advance_checkpoint, load_checkpoint, start_run
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import ingestion_checkpoint, ingestion_run

NOW = dt.datetime(2026, 8, 19, 12, tzinfo=dt.UTC)


class SourceStub:
    def __init__(self, source, *, error=None):
        self.source = source
        self.error = error
        self.windows = []

    def acquire(self, window, *, retrieved_at, max_records=None):
        self.windows.append(window)
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
