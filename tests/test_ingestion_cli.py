from __future__ import annotations

import datetime as dt
import signal

import pytest

from signals.ingestion.cli import main, summarize
from signals.ingestion.model import IngestionCounters
from signals.ingestion.runner import RunOutcome, SourceOutcome


def test_structured_summary_is_concise_and_contains_required_counters():
    outcome = SourceOutcome(
        source="boamp",
        status="success",
        counters=IngestionCounters(
            records_fetched=52,
            records_rejected=3,
            records_persisted=49,
            representations_linked=4,
            signals_materialized=17,
        ),
        duration_seconds=2.5,
    )
    assert summarize(outcome) == (
        "source=boamp fetched=52 persisted=49 linked=4 materialized=17 "
        "skipped=3 conflicts=0 rate_limited=0 status=success pending=0 duration=2.500s"
    )


def test_cli_dispatches_selected_sources_and_returns_runner_exit_code(monkeypatch, capsys):
    captured = {}

    class RunnerStub:
        def __init__(self, engine, *, sources, pipeline, **kwargs):
            captured["sources"] = sources
            captured["runner_kwargs"] = kwargs

        def run(self, options):
            captured["options"] = options
            outcome = SourceOutcome(
                source="ted",
                status="rate_limited",
                counters=IngestionCounters(rate_limited_count=1),
                duration_seconds=0.1,
                error_category="rate_limited",
            )
            return RunOutcome((outcome,), exit_code=1)

    monkeypatch.setattr("signals.ingestion.cli.create_database_engine", lambda: object())
    monkeypatch.setattr(
        "signals.ingestion.cli.production_sources", lambda **kwargs: {"ted": object()}
    )
    monkeypatch.setattr("signals.ingestion.cli.IngestionPipeline", lambda engine, linker: object())
    monkeypatch.setattr("signals.ingestion.cli.IngestionRunner", RunnerStub)

    code = main(
        [
            "run",
            "--source",
            "ted",
            "--since",
            "2026-08-18",
            "--until",
            "2026-08-19T10:00:00+00:00",
            "--max-records",
            "5",
        ]
    )
    assert code == 1
    assert captured["options"].sources == ("ted",)
    assert captured["options"].since == dt.date(2026, 8, 18)
    assert captured["options"].max_records == 5
    assert "source=ted" in capsys.readouterr().out


def test_decp_runtime_limits_come_from_positive_environment_values(monkeypatch):
    captured = {}

    class RunnerStub:
        def __init__(self, engine, *, sources, pipeline, **kwargs):
            captured["runner_kwargs"] = kwargs

        def run(self, options):
            captured["options"] = options
            return RunOutcome((), exit_code=0)

    monkeypatch.setenv("KIVOU_DECP_MAX_WINDOWS_PER_RUN", "4")
    monkeypatch.setenv("KIVOU_DECP_BATCH_SIZE", "75")
    monkeypatch.setenv("KIVOU_DECP_TIME_BUDGET_SECONDS", "900")
    monkeypatch.setenv("KIVOU_DECP_OVERLAP_DAYS", "14")
    monkeypatch.setenv("KIVOU_INGESTION_STALE_RUN_SECONDS", "7200")
    monkeypatch.setattr("signals.ingestion.cli.create_database_engine", lambda: object())
    monkeypatch.setattr(
        "signals.ingestion.cli.production_sources", lambda **kwargs: {"decp": object()}
    )
    monkeypatch.setattr("signals.ingestion.cli.IngestionPipeline", lambda engine, linker: object())
    monkeypatch.setattr("signals.ingestion.cli.IngestionRunner", RunnerStub)

    assert main(["run", "--source", "decp"]) == 0
    options = captured["options"]
    assert options.decp_max_windows_per_run == 4
    assert options.decp_batch_size == 75
    assert options.decp_time_budget_seconds == 900
    assert options.decp_overlap_days == 14
    assert options.ingestion_stale_run_seconds == 7200
    assert callable(captured["runner_kwargs"]["cancel_requested"])


def test_cli_decp_limits_override_the_environment(monkeypatch):
    captured = {}

    class RunnerStub:
        def __init__(self, engine, *, sources, pipeline, **kwargs):
            pass

        def run(self, options):
            captured["options"] = options
            return RunOutcome((), exit_code=0)

    for name in (
        "KIVOU_DECP_MAX_WINDOWS_PER_RUN",
        "KIVOU_DECP_BATCH_SIZE",
        "KIVOU_DECP_TIME_BUDGET_SECONDS",
        "KIVOU_DECP_OVERLAP_DAYS",
        "KIVOU_INGESTION_STALE_RUN_SECONDS",
    ):
        monkeypatch.setenv(name, "99")
    monkeypatch.setattr("signals.ingestion.cli.create_database_engine", lambda: object())
    monkeypatch.setattr(
        "signals.ingestion.cli.production_sources", lambda **kwargs: {"decp": object()}
    )
    monkeypatch.setattr("signals.ingestion.cli.IngestionPipeline", lambda engine, linker: object())
    monkeypatch.setattr("signals.ingestion.cli.IngestionRunner", RunnerStub)

    assert (
        main(
            [
                "run",
                "--source",
                "decp",
                "--decp-max-windows-per-run",
                "3",
                "--decp-batch-size",
                "50",
                "--decp-time-budget-seconds",
                "600",
                "--decp-overlap-days",
                "7",
                "--ingestion-stale-run-seconds",
                "1800",
            ]
        )
        == 0
    )
    options = captured["options"]
    assert options.decp_max_windows_per_run == 3
    assert options.decp_batch_size == 50
    assert options.decp_time_budget_seconds == 600
    assert options.decp_overlap_days == 7
    assert options.ingestion_stale_run_seconds == 1800


@pytest.mark.parametrize(
    "name",
    [
        "KIVOU_DECP_MAX_WINDOWS_PER_RUN",
        "KIVOU_DECP_BATCH_SIZE",
        "KIVOU_DECP_TIME_BUDGET_SECONDS",
        "KIVOU_DECP_OVERLAP_DAYS",
        "KIVOU_INGESTION_STALE_RUN_SECONDS",
    ],
)
@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_decp_runtime_environment_rejects_non_positive_values(
    monkeypatch,
    name,
    value,
):
    monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit, match="must be a positive integer"):
        main(["run", "--source", "decp"])


@pytest.mark.parametrize("value", ["101", "1000"])
def test_decp_batch_size_rejects_values_above_the_provider_page_size(
    monkeypatch,
    value,
):
    monkeypatch.setenv("KIVOU_DECP_BATCH_SIZE", value)

    with pytest.raises(SystemExit, match="at most 100"):
        main(["run", "--source", "decp"])


def test_ted_runtime_limits_configure_the_client_and_runner(monkeypatch) -> None:
    captured = {}

    class RunnerStub:
        def __init__(self, engine, *, sources, pipeline, **kwargs):
            pass

        def run(self, options):
            captured["options"] = options
            return RunOutcome((), exit_code=0)

    def sources_factory(**kwargs):
        captured["source_options"] = kwargs
        return {"ted": object()}

    monkeypatch.setenv("KIVOU_TED_REQUEST_INTERVAL_SECONDS", "1.5")
    monkeypatch.setenv("KIVOU_TED_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("KIVOU_TED_MAX_RETRY_SECONDS", "90")
    monkeypatch.setenv("KIVOU_TED_MAX_RECORDS_PER_RUN", "400")
    monkeypatch.setenv("KIVOU_TED_TIME_BUDGET_SECONDS", "1000")
    monkeypatch.setattr("signals.ingestion.cli.create_database_engine", lambda: object())
    monkeypatch.setattr("signals.ingestion.cli.production_sources", sources_factory)
    monkeypatch.setattr("signals.ingestion.cli.IngestionPipeline", lambda engine, linker: object())
    monkeypatch.setattr("signals.ingestion.cli.IngestionRunner", RunnerStub)

    assert main(["run", "--source", "ted"]) == 0
    assert captured["source_options"] == {
        "ted_request_interval_seconds": 1.5,
        "ted_max_attempts": 5,
        "ted_max_retry_seconds": 90.0,
    }
    assert captured["options"].ted_max_records_per_run == 400
    assert captured["options"].ted_time_budget_seconds == 1000


@pytest.mark.parametrize(
    "name",
    (
        "KIVOU_TED_MAX_ATTEMPTS",
        "KIVOU_TED_MAX_RECORDS_PER_RUN",
        "KIVOU_TED_TIME_BUDGET_SECONDS",
    ),
)
@pytest.mark.parametrize("value", ("0", "-1", "invalid"))
def test_ted_integer_environment_rejects_non_positive_values(
    monkeypatch,
    name,
    value,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit, match="must be a positive integer"):
        main(["run", "--source", "ted"])


@pytest.mark.parametrize(
    "name",
    ("KIVOU_TED_REQUEST_INTERVAL_SECONDS", "KIVOU_TED_MAX_RETRY_SECONDS"),
)
@pytest.mark.parametrize("value", ("0", "-1", "invalid"))
def test_ted_float_environment_rejects_non_positive_values(
    monkeypatch,
    name,
    value,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit, match="must be a positive number"):
        main(["run", "--source", "ted"])


def test_cli_sigterm_requests_terminal_runner_cancellation_and_restores_handler(
    monkeypatch,
    capsys,
):
    handlers = []
    previous_handler = object()

    def install_handler(signum, handler):
        assert signum == signal.SIGTERM
        handlers.append(handler)
        return previous_handler

    class RunnerStub:
        def __init__(self, engine, *, sources, pipeline, cancel_requested):
            self.cancel_requested = cancel_requested

        def run(self, options):
            handlers[0](signal.SIGTERM, None)
            assert self.cancel_requested() is True
            return RunOutcome(
                (
                    SourceOutcome(
                        source="decp",
                        status="failed",
                        counters=IngestionCounters(),
                        duration_seconds=0,
                        error_category="terminated",
                        work_pending=True,
                    ),
                ),
                exit_code=1,
            )

    monkeypatch.setattr("signals.ingestion.cli.signal.signal", install_handler)
    monkeypatch.setattr("signals.ingestion.cli.create_database_engine", lambda: object())
    monkeypatch.setattr(
        "signals.ingestion.cli.production_sources", lambda **kwargs: {"decp": object()}
    )
    monkeypatch.setattr("signals.ingestion.cli.IngestionPipeline", lambda engine, linker: object())
    monkeypatch.setattr("signals.ingestion.cli.IngestionRunner", RunnerStub)

    assert main(["run", "--source", "decp"]) == 1
    output = capsys.readouterr()
    assert "error=terminated" in output.out
    assert "pending=1" in output.out
    assert output.err == ""
    assert handlers[-1] is previous_handler
