"""Operator commands are fail closed before any Apollo transport is made."""

import datetime as dt
import json
from pathlib import Path

import pytest

from signals.acquisition_programs.census_cli import main
from signals.acquisition_programs.census_readiness import DatabaseAuthorization, database_identity
from signals.persistence.database import create_database_engine, migrate_to_latest

EXAMPLE = Path(__file__).resolve().parents[1] / "ops/examples/milomail-acquisition.json.example"


def test_plan_status_report_and_run_without_explicit_gate(tmp_path, monkeypatch, capsys) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'census.sqlite'}"
    engine = create_database_engine(url)
    migrate_to_latest(engine)
    authorization = tmp_path / "database-authorization.json"
    authorization.write_text(DatabaseAuthorization(
        database_id=database_identity(engine)[0], environment="test",
        issued_by_reference="synthetic-cli-test",
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
    ).model_dump_json())
    engine.dispose()
    monkeypatch.setenv("KIVOU_DATABASE_URL", url)
    monkeypatch.delenv("MILOMAIL_CENSUS_APOLLO_API_KEY", raising=False)
    monkeypatch.delenv("MILOMAIL_CENSUS_ENABLED", raising=False)

    with pytest.raises(SystemExit) as denied:
        main(["plan", "--program-config", str(EXAMPLE)])
    assert denied.value.code == 2
    assert capsys.readouterr().err == "status=INVALID_ARGUMENTS\n"
    assert main(["plan", "--program-config", str(EXAMPLE),
                 "--database-authorization", str(authorization)]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["partitions"] == 9
    assert planned["credits_spent"] == planned["apollo_calls"] == 0
    census_id = planned["census_id"]

    assert main(["status", "--census-id", census_id]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "PLANNED"
    assert status["credits_reserved"] == 0

    assert main(["preflight", "--census-id", census_id]) == 0
    pre = json.loads(capsys.readouterr().out)
    assert not pre["technically_ready"]
    assert not pre["execution_authorized"]
    assert pre["checks"]["apollo_key"] == "CREDENTIAL_MISSING"
    assert pre["caps"]["credits"] == 0
    assert pre["instantly_mutation_allowed"] is False

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

    usage_args = [
        "reconcile-usage", "--census-id", census_id,
        "--actual-credits", "0", "--actual-cost-chf", "0",
        "--usage-evidence-ref", "synthetic-invoice-001",
        "--database-authorization", str(authorization),
    ]
    assert main(usage_args) == 1
    assert capsys.readouterr().err == "status=ERROR code=ValueError\n"
    assert main([*usage_args, "--acknowledge-exclusive-attribution"]) == 0
    usage = json.loads(capsys.readouterr().out)
    assert usage["apollo_credits_actual"] == 0
    assert usage["cost_chf_actual"] == "0.0000"


def test_cli_error_redacts_provider_and_secret_text(monkeypatch, capsys) -> None:
    def fail_engine():
        raise RuntimeError("founder@example.fr api_key=synthetic-secret")

    monkeypatch.setattr("signals.acquisition_programs.census_cli.create_database_engine", fail_engine)
    assert main(["status", "--census-id", "synthetic"]) == 1
    assert capsys.readouterr().err == "status=ERROR code=RuntimeError\n"
