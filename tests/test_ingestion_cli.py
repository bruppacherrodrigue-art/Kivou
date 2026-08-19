from __future__ import annotations

import datetime as dt

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
        "skipped=3 conflicts=0 rate_limited=0 status=success duration=2.500s"
    )


def test_cli_dispatches_selected_sources_and_returns_runner_exit_code(monkeypatch, capsys):
    captured = {}

    class RunnerStub:
        def __init__(self, engine, *, sources, pipeline):
            captured["sources"] = sources

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
    monkeypatch.setattr("signals.ingestion.cli.production_sources", lambda: {"ted": object()})
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
