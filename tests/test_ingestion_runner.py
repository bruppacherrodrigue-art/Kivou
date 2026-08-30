from __future__ import annotations

import datetime as dt
import json
import pathlib

import httpx
import pytest
import sqlalchemy as sa
from feed_helpers import LINKED_BOAMP, LINKED_DECP

from signals.connectors.decp import DecpBatch, DecpClient, DecpWindowLimitError
from signals.connectors.ted import NoticeRef, TedClient
from signals.connectors.ted.errors import TedHttpError
from signals.ingestion import runner as runner_module
from signals.ingestion.cli import summarize
from signals.ingestion.pipeline import IngestionPipeline, PipelineFailure, PipelineResult
from signals.ingestion.runner import IngestionRunner, RunOptions
from signals.ingestion.sources import (
    AcquisitionFailure,
    AcquisitionResult,
    BoampSource,
    DecpAcquisitionBatch,
    DecpSource,
    SourceWindow,
    TedSource,
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
TED_FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "ted"


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

    def acquire_batch(
        self,
        window,
        *,
        retrieved_at,
        offset,
        expected_total,
        batch_size,
    ):
        acquisition = self.acquire(window, retrieved_at=retrieved_at)
        return DecpAcquisitionBatch(
            acquisition=acquisition,
            next_offset=1,
            window_total=1,
            day_complete=True,
            reset=False,
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


def test_ted_dry_run_does_not_multiply_the_client_retry_budget(tmp_path):
    engine = _engine(tmp_path)
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        source = TedSource(
            TedClient(
                client=http_client,
                request_interval_seconds=0,
                max_attempts=4,
                max_retry_seconds=30,
                sleep=lambda _: None,
            )
        )
        result = IngestionRunner(
            engine,
            sources={"ted": source},
            pipeline=PipelineStub(),
            clock=lambda: NOW,
            sleep=lambda _: None,
        ).run(RunOptions(sources=("ted",), max_records=1, dry_run=True))

    assert attempts == 4
    assert result.exit_code == 1
    assert result.outcomes[0].error_category == "server_error"


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


class _TedUnitClient:
    def __init__(
        self,
        publication_numbers,
        *,
        fail_once_on: str | None = None,
        after_fetch=None,
    ):
        self.publication_numbers = tuple(publication_numbers)
        self.fail_once_on = fail_once_on
        self.after_fetch = after_fetch
        self.search_calls = []
        self.fetch_calls = []

    def search(self, query, *, limit=25, page=1):
        self.search_calls.append((limit, page))
        start = (page - 1) * limit
        selected = self.publication_numbers[start : start + limit]
        return [NoticeRef(number) for number in selected], len(self.publication_numbers)

    def fetch_notice_xml(self, publication_number):
        self.fetch_calls.append(publication_number)
        if self.fail_once_on == publication_number:
            self.fail_once_on = None
            raise TedHttpError("limited", status_code=429, category="rate_limited")
        if self.after_fetch is not None:
            self.after_fetch(publication_number)
        return (TED_FIXTURES / f"{publication_number}.xml").read_bytes()


def test_ted_search_page_is_durable_before_a_download_429(tmp_path) -> None:
    engine = _engine(tmp_path)
    client = _TedUnitClient(("565942-2026", "550374-2026"), fail_once_on="565942-2026")

    result = IngestionRunner(
        engine,
        sources={"ted": TedSource(client, page_size=2)},
        pipeline=IngestionPipeline(engine),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("ted",), ted_max_records_per_run=10))

    assert result.exit_code == 1
    assert result.outcomes[0].status == "rate_limited"
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="ted")
        run = connection.execute(sa.select(ingestion_run)).one()
    assert checkpoint is not None
    assert checkpoint.cursor is not None
    assert checkpoint.cursor["pending_publication_numbers"] == [
        "565942-2026",
        "550374-2026",
    ]
    assert checkpoint.cursor["next_index"] == 0
    assert checkpoint.window_end is None
    assert run.records_fetched == 2
    assert run.rate_limited_count == 1


def test_ted_resume_keeps_completed_notices_and_creates_no_duplicates(tmp_path) -> None:
    engine = _engine(tmp_path)
    client = _TedUnitClient(("565942-2026", "550374-2026"), fail_once_on="550374-2026")
    source = TedSource(client, page_size=2)

    first = IngestionRunner(
        engine,
        sources={"ted": source},
        pipeline=IngestionPipeline(engine),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("ted",), ted_max_records_per_run=10))
    with engine.connect() as connection:
        after_failure = load_checkpoint(connection, source="ted")
        first_count = connection.execute(
            sa.select(sa.func.count()).select_from(source_event)
        ).scalar_one()

    second = IngestionRunner(
        engine,
        sources={"ted": source},
        pipeline=IngestionPipeline(engine),
        clock=lambda: NOW + dt.timedelta(hours=1),
    ).run(RunOptions(sources=("ted",), ted_max_records_per_run=10))

    assert first.exit_code == 1
    assert after_failure is not None
    assert after_failure.cursor["next_index"] == 1
    assert first_count == 1
    assert second.exit_code == 0
    assert client.search_calls == [(2, 1)]
    assert client.fetch_calls == ["565942-2026", "550374-2026", "550374-2026"]
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="ted")
        event_count = connection.execute(
            sa.select(sa.func.count()).select_from(source_event)
        ).scalar_one()
        distinct_events = connection.execute(
            sa.select(sa.func.count(sa.distinct(source_event.c.source_notice_id)))
            .where(source_event.c.source_system == "ted")
        ).scalar_one()
    assert checkpoint is not None
    assert checkpoint.cursor["complete"] is True
    assert checkpoint.window_end == NOW + dt.timedelta(hours=1)
    assert event_count == distinct_events == 2


def test_ted_record_budget_is_a_successful_resumable_pass(tmp_path) -> None:
    engine = _engine(tmp_path)
    client = _TedUnitClient(("565942-2026", "550374-2026"))

    result = IngestionRunner(
        engine,
        sources={"ted": TedSource(client, page_size=2)},
        pipeline=IngestionPipeline(engine),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("ted",), ted_max_records_per_run=1))

    assert result.exit_code == 0
    assert result.outcomes[0].status == "success"
    assert result.outcomes[0].work_pending is True
    assert result.outcomes[0].counters.records_accepted == 1
    assert client.fetch_calls == ["565942-2026"]
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="ted")
    assert checkpoint is not None
    assert checkpoint.cursor["next_index"] == 1
    assert checkpoint.window_end is None


def test_ted_time_budget_checkpoints_the_last_completed_notice(tmp_path) -> None:
    engine = _engine(tmp_path)
    expired = False

    def expire_after_fetch(_publication_number) -> None:
        nonlocal expired
        expired = True

    client = _TedUnitClient(
        ("565942-2026", "550374-2026"),
        after_fetch=expire_after_fetch,
    )
    result = IngestionRunner(
        engine,
        sources={"ted": TedSource(client, page_size=2)},
        pipeline=IngestionPipeline(engine),
        clock=lambda: NOW,
        monotonic=lambda: 6.0 if expired else 0.0,
    ).run(
        RunOptions(
            sources=("ted",),
            ted_max_records_per_run=10,
            ted_time_budget_seconds=5,
        )
    )

    assert result.exit_code == 0
    assert result.outcomes[0].work_pending is True
    assert client.fetch_calls == ["565942-2026"]
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="ted")
    assert checkpoint is not None
    assert checkpoint.cursor["next_index"] == 1


def test_ted_sigterm_after_a_notice_checkpoints_then_terminalizes(tmp_path) -> None:
    engine = _engine(tmp_path)
    cancelled = False

    def cancel_after_fetch(_publication_number) -> None:
        nonlocal cancelled
        cancelled = True

    client = _TedUnitClient(
        ("565942-2026", "550374-2026"),
        after_fetch=cancel_after_fetch,
    )
    result = IngestionRunner(
        engine,
        sources={"ted": TedSource(client, page_size=2)},
        pipeline=IngestionPipeline(engine),
        clock=lambda: NOW,
        cancel_requested=lambda: cancelled,
    ).run(RunOptions(sources=("ted",), ted_max_records_per_run=10))

    assert result.exit_code == 1
    assert result.outcomes[0].error_category == "terminated"
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="ted")
        run = connection.execute(sa.select(ingestion_run)).one()
    assert checkpoint is not None
    assert checkpoint.cursor["next_index"] == 1
    assert run.status == "failed"
    assert run.finished_at is not None


def test_ted_replay_after_post_persistence_failure_is_idempotent(tmp_path) -> None:
    engine = _engine(tmp_path)
    client = _TedUnitClient(("550374-2026",))
    real_pipeline = IngestionPipeline(engine)

    class FailAfterFirstPersistence:
        def __init__(self) -> None:
            self.failed = False

        def process(self, publication, *, as_of, persisted_at):
            item = real_pipeline.process(
                publication,
                as_of=as_of,
                persisted_at=persisted_at,
            )
            if not self.failed:
                self.failed = True
                raise PipelineFailure(RuntimeError("after persistence"), partial=item)
            return item

    pipeline = FailAfterFirstPersistence()
    first = IngestionRunner(
        engine,
        sources={"ted": TedSource(client, page_size=1)},
        pipeline=pipeline,
        clock=lambda: NOW,
    ).run(RunOptions(sources=("ted",), ted_max_records_per_run=10))
    second = IngestionRunner(
        engine,
        sources={"ted": TedSource(client, page_size=1)},
        pipeline=pipeline,
        clock=lambda: NOW + dt.timedelta(hours=1),
    ).run(RunOptions(sources=("ted",), ted_max_records_per_run=10))

    assert first.exit_code == 1
    assert second.exit_code == 0
    assert client.search_calls == [(1, 1)]
    assert client.fetch_calls == ["550374-2026", "550374-2026"]
    with engine.connect() as connection:
        counts = tuple(
            connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            for table in (source_event, contract_award, opportunity_representation)
        )
    assert counts == (1, 1, 1)


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


def test_generic_source_failure_exposes_root_type_and_keeps_work_pending(tmp_path):
    marker = "private-boamp-marker"
    partial = AcquisitionResult(
        source="boamp",
        publications=(),
        fetched=3,
        accepted=1,
        rejected=0,
        complete=False,
        cursor_after={"window_end": NOW.date().isoformat()},
    )
    source = SourceStub(
        "boamp",
        error=AcquisitionFailure(TypeError(marker), partial=partial),
    )

    engine = _engine(tmp_path)
    result = IngestionRunner(
        engine,
        sources={"boamp": source},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("boamp",)))

    outcome = result.outcomes[0]
    assert outcome.error_category == "unexpected"
    assert outcome.error_type == "TypeError"
    assert outcome.work_pending is True
    assert "error=unexpected error_type=TypeError pending=1" in summarize(outcome)
    assert marker not in summarize(outcome)
    with engine.connect() as connection:
        run = connection.execute(sa.select(ingestion_run)).one()
    assert run.error_message == marker


def test_ted_failure_exposes_root_error_type(tmp_path):
    partial = AcquisitionResult(
        source="ted",
        publications=(),
        fetched=2,
        accepted=0,
        rejected=0,
        complete=False,
        cursor_after=None,
    )

    class FailingTedSource:
        source = "ted"
        page_size = 25

        def acquire_unit(self, cursor, *, retrieved_at):
            raise AcquisitionFailure(TypeError("private-ted-marker"), partial=partial)

    result = IngestionRunner(
        _engine(tmp_path),
        sources={"ted": FailingTedSource()},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("ted",)))

    assert result.outcomes[0].error_type == "TypeError"


def test_decp_failure_exposes_root_error_type(tmp_path):
    partial = AcquisitionResult(
        source="decp",
        publications=(),
        fetched=2,
        accepted=0,
        rejected=0,
        complete=False,
        cursor_after=None,
    )
    source = SourceStub(
        "decp",
        error=AcquisitionFailure(TypeError("private-decp-marker"), partial=partial),
    )

    result = IngestionRunner(
        _engine(tmp_path),
        sources={"decp": source},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("decp",)))

    assert result.outcomes[0].error_type == "TypeError"


def test_error_type_follows_only_explicit_nested_causes():
    root = TypeError("private-root-marker")
    middle = RuntimeError("middle")
    middle.cause = root
    outer = RuntimeError("outer")
    outer.cause = middle

    assert runner_module._error_type(outer) == "TypeError"

    python_chained = RuntimeError("python chained")
    python_chained.__cause__ = root
    assert runner_module._error_type(python_chained) == "RuntimeError"


def test_error_type_is_cycle_safe():
    outer = ValueError("outer")
    inner = TypeError("inner")
    outer.cause = inner
    inner.cause = outer

    assert runner_module._error_type(outer) == "TypeError"


@pytest.mark.parametrize(
    "unsafe_name",
    ("not an identifier", "E" * 65),
)
def test_error_type_rejects_unsafe_exception_class_names(unsafe_name):
    unsafe_error = type(unsafe_name, (Exception,), {})()

    assert runner_module._error_type(unsafe_error) == "Exception"


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
    def fetch_contract_batch(
        self, day, *, offset, expected_total, batch_size
    ):
        if offset:
            raise DecpWindowLimitError("later DECP child window changed")
        return DecpBatch(
            records=(LINKED_DECP,),
            next_offset=1,
            window_total=2,
            day_complete=False,
            reset=False,
        )


class _DecpReplayWithBoundaryDuplicate:
    def fetch_contract_batch(
        self, day, *, offset, expected_total, batch_size
    ):
        if offset == 1:
            assert expected_total == 2
            next_offset = 2
            window_total = 2
        else:
            assert offset == 0
            assert expected_total is None
            next_offset = 1
            window_total = 1
        return DecpBatch(
            records=(LINKED_DECP,),
            next_offset=next_offset,
            window_total=window_total,
            day_complete=True,
            reset=False,
        )


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
    assert stored == 0


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

    def acquire_batch(
        self,
        window,
        *,
        retrieved_at,
        offset,
        expected_total,
        batch_size,
    ):
        acquisition = self.acquire(window, retrieved_at=retrieved_at)
        return DecpAcquisitionBatch(
            acquisition=acquisition,
            next_offset=1,
            window_total=1,
            day_complete=True,
            reset=False,
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
        "version": 2,
        "cycle_end": "2026-08-19",
        "next_window_start": "2026-08-19",
        "offset": 0,
        "window_total": None,
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
    def fetch_contract_batch(
        self, day, *, offset, expected_total, batch_size
    ):
        assert offset == 0
        assert expected_total is None
        return DecpBatch(
            records=(LINKED_DECP,),
            next_offset=1,
            window_total=1,
            day_complete=True,
            reset=False,
        )


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


def test_decp_deadline_is_a_successful_bounded_pass_after_checkpointing_the_unit(
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
    assert checkpoint.cursor["next_window_start"] == "2026-08-19"
    assert checkpoint.window_end == dt.datetime(2026, 8, 18, tzinfo=dt.UTC)
    assert run.status == "success"


class _OversizedDayDecpClient:
    def __init__(self, *, cancel_after_fetch=None):
        self.offsets = []
        self.cancel_after_fetch = cancel_after_fetch

    def fetch_contract_batch(
        self,
        day,
        *,
        offset,
        expected_total,
        batch_size,
    ):
        assert batch_size == 1
        assert expected_total in (None, 3)
        self.offsets.append(offset)
        next_offset = offset + 1
        if self.cancel_after_fetch is not None:
            self.cancel_after_fetch()
        return DecpBatch(
            records=(LINKED_DECP,),
            next_offset=next_offset,
            window_total=3,
            day_complete=next_offset == 3,
            reset=False,
        )


class _OneBatchBudgetClock:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return 0.0 if self.calls <= 2 else 6.0


class _VariableBatchDecpClient:
    def __init__(self, *, total: int):
        self.total = total
        self.calls = []

    def fetch_contract_batch(
        self,
        day,
        *,
        offset,
        expected_total,
        batch_size,
    ):
        self.calls.append((day, offset, batch_size))
        count = min(batch_size, self.total - offset)
        next_offset = offset + count
        return DecpBatch(
            records=tuple(LINKED_DECP for _ in range(count)),
            next_offset=next_offset,
            window_total=self.total,
            day_complete=next_offset == self.total,
            reset=False,
        )


def test_decp_daily_quota_counts_completed_days_not_intra_day_batches(tmp_path):
    engine = _engine(tmp_path)
    client = _OversizedDayDecpClient()

    result = IngestionRunner(
        engine,
        sources={"decp": DecpSource(client)},
        pipeline=IngestionPipeline(engine),
        clock=lambda: NOW,
    ).run(
        RunOptions(
            sources=("decp",),
            decp_batch_size=1,
            decp_max_windows_per_run=1,
            decp_overlap_days=1,
        )
    )

    assert result.exit_code == 0
    assert result.outcomes[0].work_pending is True
    assert client.offsets == [0, 1, 2]
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="decp")
    assert checkpoint is not None
    assert checkpoint.cursor["next_window_start"] == NOW.date().isoformat()
    assert checkpoint.cursor["offset"] == 0


def test_decp_max_records_bounds_the_pass_and_shrinks_the_last_batch(tmp_path):
    engine = _engine(tmp_path)
    client = _VariableBatchDecpClient(total=5)

    result = IngestionRunner(
        engine,
        sources={"decp": DecpSource(client)},
        pipeline=IngestionPipeline(engine),
        clock=lambda: NOW,
    ).run(
        RunOptions(
            sources=("decp",),
            since=NOW.date(),
            until=NOW,
            max_records=3,
            decp_batch_size=2,
            decp_overlap_days=1,
        )
    )

    assert result.exit_code == 0
    assert result.outcomes[0].counters.records_fetched == 3
    assert result.outcomes[0].work_pending is True
    assert [(offset, size) for _, offset, size in client.calls] == [(0, 2), (2, 1)]
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="decp")
    assert checkpoint is not None
    assert checkpoint.cursor["next_window_start"] == NOW.date().isoformat()
    assert checkpoint.cursor["offset"] == 3
    assert checkpoint.cursor["window_total"] == 5


def test_decp_day_larger_than_each_budget_converges_by_offset_without_duplicates(
    tmp_path,
):
    engine = _engine(tmp_path)
    client = _OversizedDayDecpClient()
    outcomes = []
    cursors = []

    for _ in range(3):
        result = IngestionRunner(
            engine,
            sources={"decp": DecpSource(client)},
            pipeline=IngestionPipeline(engine),
            clock=lambda: NOW,
            monotonic=_OneBatchBudgetClock(),
        ).run(
            RunOptions(
                sources=("decp",),
                since=NOW.date(),
                until=NOW,
                decp_batch_size=1,
                decp_time_budget_seconds=5,
                decp_overlap_days=1,
            )
        )
        outcomes.append(result.outcomes[0])
        with engine.connect() as connection:
            checkpoint = load_checkpoint(connection, source="decp")
        assert checkpoint is not None
        cursors.append(checkpoint.cursor)

    assert [outcome.status for outcome in outcomes] == ["success", "success", "success"]
    assert [outcome.work_pending for outcome in outcomes] == [True, True, False]
    assert client.offsets == [0, 1, 2]
    assert [(cursor["next_window_start"], cursor["offset"]) for cursor in cursors] == [
        (NOW.date().isoformat(), 1),
        (NOW.date().isoformat(), 2),
        ((NOW.date() + dt.timedelta(days=1)).isoformat(), 0),
    ]
    with engine.connect() as connection:
        counts = tuple(
            connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            for table in (source_event, contract_award, opportunity_representation)
        )
        runs = connection.execute(sa.select(ingestion_run.c.status)).scalars().all()
    assert counts == (1, 1, 1)
    assert runs == ["success", "success", "success"]


def test_decp_sigterm_after_a_batch_checkpoints_that_batch_then_terminalizes(tmp_path):
    engine = _engine(tmp_path)
    cancelled = False

    def cancel() -> None:
        nonlocal cancelled
        cancelled = True

    client = _OversizedDayDecpClient(cancel_after_fetch=cancel)
    result = IngestionRunner(
        engine,
        sources={"decp": DecpSource(client)},
        pipeline=IngestionPipeline(engine),
        clock=lambda: NOW,
        cancel_requested=lambda: cancelled,
    ).run(
        RunOptions(
            sources=("decp",),
            since=NOW.date(),
            until=NOW,
            decp_batch_size=1,
            decp_overlap_days=1,
        )
    )

    assert result.exit_code == 1
    assert result.outcomes[0].error_category == "terminated"
    with engine.connect() as connection:
        checkpoint = load_checkpoint(connection, source="decp")
        run = connection.execute(sa.select(ingestion_run)).one()
        stored = connection.execute(
            sa.select(sa.func.count()).select_from(contract_award)
        ).scalar_one()
    assert checkpoint is not None
    assert checkpoint.cursor["offset"] == 1
    assert checkpoint.cursor["window_total"] == 3
    assert run.status == "failed"
    assert stored == 1


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


def test_sigterm_cancellation_also_terminalizes_a_non_decp_source(tmp_path):
    engine = _engine(tmp_path)
    cancelled = False

    class CancellingSource(SourceStub):
        def acquire(self, window, *, retrieved_at, max_records=None):
            nonlocal cancelled
            cancelled = True
            return super().acquire(
                window,
                retrieved_at=retrieved_at,
                max_records=max_records,
            )

    result = IngestionRunner(
        engine,
        sources={"boamp": CancellingSource("boamp")},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
        cancel_requested=lambda: cancelled,
    ).run(RunOptions(sources=("boamp",)))

    assert result.exit_code == 1
    assert result.outcomes[0].error_category == "terminated"
    with engine.connect() as connection:
        row = connection.execute(sa.select(ingestion_run)).one()
    assert row.status == "failed"
    assert row.finished_at is not None
