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
    assert main(["report", "--census-id", census_id, "--public-aggregate",
                 "--forecast-low", "0.1", "--forecast-central", "0.2",
                 "--forecast-high", "0.3",
                 "--forecast-source", "synthetic-scenario"]) == 1
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


def test_bootstrap_reports_zero_cost_blockers_without_secrets(monkeypatch, capsys) -> None:
    monkeypatch.delenv("KIVOU_DATABASE_URL", raising=False)
    monkeypatch.delenv("MILOMAIL_CENSUS_APOLLO_API_KEY", raising=False)
    monkeypatch.setenv("KIVOU_SUPPRESSION_HMAC_KEY", "synthetic-secret-must-not-leak")
    assert main(["bootstrap", "--program-config", str(EXAMPLE)]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["phase"] == "COVERAGE"
    assert result["partitions_planned"] == 9
    assert result["checks"]["database"] == "DATABASE_URL_MISSING"
    assert result["checks"]["apollo_key"] == "CREDENTIAL_MISSING"
    assert result["checks"]["operation_cost"] == "ORG_SEARCH_REQUIRES_CREDIT"
    assert result["caps"]["credits"] == 0
    assert result["caps"]["cost_chf"] == "0"
    assert result["instantly_mutation_allowed"] is False
    assert result["contact_enrichment_allowed"] is False
    assert result["execution_authorized"] is False
    assert "synthetic-secret-must-not-leak" not in output


def test_preflight_coverage_phase_rejects_paid_search(tmp_path, monkeypatch, capsys) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'coverage.sqlite'}"
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
    assert main(["plan", "--program-config", str(EXAMPLE),
                 "--database-authorization", str(authorization)]) == 0
    census_id = json.loads(capsys.readouterr().out)["census_id"]
    assert main(["preflight", "--phase", "COVERAGE", "--census-id", census_id,
                 "--database-authorization", str(authorization)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["checks"]["operation_cost"] == "ORG_SEARCH_REQUIRES_CREDIT"
    assert result["checks"]["partitions"] == "READY"
    assert not result["execution_authorized"]
    assert result["instantly_mutation_allowed"] is False


def test_a0_cli_is_coverage_only_and_remains_gate_protected(
    tmp_path, monkeypatch, capsys,
) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'a0.sqlite'}"
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
    assert main(["plan", "--program-config", str(EXAMPLE),
                 "--database-authorization", str(authorization)]) == 0
    census_id = json.loads(capsys.readouterr().out)["census_id"]
    assert main(["run", "--phase", "COVERAGE", "--a0", "--census-id", census_id,
                 "--program-config", str(EXAMPLE)]) == 1
    assert capsys.readouterr().err == "status=ERROR code=ValueError\n"


def test_public_report_rejects_unattributed_forecast_and_redacts_small_locations(
    tmp_path, monkeypatch, capsys,
) -> None:
    # The authorization identifier includes the SQLite path and has a 128-char cap.
    url = f"sqlite+pysqlite:///{tmp_path.parent / 'r.sqlite'}"
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
    assert main(["plan", "--program-config", str(EXAMPLE),
                 "--database-authorization", str(authorization)]) == 0
    census_id = json.loads(capsys.readouterr().out)["census_id"]
    assert main(["report", "--census-id", census_id, "--public-aggregate",
                 "--forecast-low", "0.1", "--forecast-central", "0.2",
                 "--forecast-high", "0.3"]) == 1
    assert capsys.readouterr().err == "status=ERROR code=ValueError\n"
    assert main(["report", "--census-id", census_id, "--public-aggregate"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["by_location"] == {}
    assert output["estimated_professional_addresses"] is None
    assert "candidates" not in output


def test_bootstrap_does_not_call_stale_price_verified(tmp_path, monkeypatch, capsys) -> None:
    from test_milomail_census_readiness import _setup

    engine, _store, _census_id, _auth, pricing = _setup()
    engine.dispose()
    stale = pricing.model_copy(update={
        "verified_at": dt.datetime.now(dt.UTC) - dt.timedelta(days=31),
    })
    path = tmp_path / "stale-pricing.json"
    path.write_text(stale.model_dump_json())
    monkeypatch.delenv("KIVOU_DATABASE_URL", raising=False)
    assert main(["bootstrap", "--program-config", str(EXAMPLE),
                 "--pricing", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["pricing"] == "UNVERIFIED"
    assert not report["execution_authorized"]


def test_bootstrap_keeps_supplied_program_check_separate_from_persisted_run(
    tmp_path, monkeypatch, capsys,
) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'bootstrap.sqlite'}"
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
    assert main(["plan", "--program-config", str(EXAMPLE),
                 "--database-authorization", str(authorization)]) == 0
    census_id = json.loads(capsys.readouterr().out)["census_id"]
    unsafe = json.loads(EXAMPLE.read_text())
    unsafe["enabled"] = True
    unsafe_path = tmp_path / "unsafe-program.json"
    unsafe_path.write_text(json.dumps(unsafe))
    assert main(["bootstrap", "--program-config", str(unsafe_path),
                 "--database-authorization", str(authorization),
                 "--census-id", census_id]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["program"] == "PROGRAM_NOT_DISABLED_SHADOW"
    assert report["checks"]["database"] == "NON_POSTGRESQL_DATABASE"
    assert report["checks"]["persisted_program"] == "READY"
