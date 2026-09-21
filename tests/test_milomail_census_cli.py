"""Operator commands are fail closed before any Apollo transport is made."""

import json
from pathlib import Path

from signals.acquisition_programs.census_cli import main
from signals.persistence.database import create_database_engine, migrate_to_latest

EXAMPLE = Path(__file__).resolve().parents[1] / "ops/examples/milomail-acquisition.json.example"


def test_plan_status_report_and_run_without_explicit_gate(tmp_path, monkeypatch, capsys) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'census.sqlite'}"
    engine = create_database_engine(url)
    migrate_to_latest(engine)
    engine.dispose()
    monkeypatch.setenv("KIVOU_DATABASE_URL", url)
    monkeypatch.delenv("MILOMAIL_CENSUS_APOLLO_API_KEY", raising=False)
    monkeypatch.delenv("MILOMAIL_CENSUS_ENABLED", raising=False)

    assert main(["plan", "--program-config", str(EXAMPLE)]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["partitions"] == 9
    assert planned["credits_spent"] == planned["apollo_calls"] == 0
    census_id = planned["census_id"]

    assert main(["status", "--census-id", census_id]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "PLANNED"
    assert status["credits_reserved"] == 0

    assert main(["run", "--census-id", census_id, "--program-config", str(EXAMPLE)]) == 1
    error = capsys.readouterr().err
    assert error == "status=ERROR code=ValueError\n"
    assert main([
        "resume", "--census-id", census_id, "--program-config", str(EXAMPLE),
        "--authorize-paid-apollo",
    ]) == 1
    assert capsys.readouterr().err == "status=ERROR code=ValueError\n"
    assert main(["report", "--census-id", census_id]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["organizations_found"] == report["apollo_credits_reserved_upper_bound"] == 0
    assert report["cost_chf_actual"] is None


def test_cli_error_redacts_provider_and_secret_text(monkeypatch, capsys) -> None:
    def fail_engine():
        raise RuntimeError("founder@example.fr api_key=synthetic-secret")

    monkeypatch.setattr("signals.acquisition_programs.census_cli.create_database_engine", fail_engine)
    assert main(["status", "--census-id", "synthetic"]) == 1
    assert capsys.readouterr().err == "status=ERROR code=RuntimeError\n"
