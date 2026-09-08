from __future__ import annotations

import json
import sys

import pytest

from signals.qa import discovery_grants as cli


@pytest.mark.parametrize("generic_url", [None, "sqlite:///must-not-be-used.db"])
@pytest.mark.parametrize(
    ("arguments", "dry_run", "expected_audit"),
    [([], True, None), (["--dry-run"], True, None),
     (["--apply", "--expected-audit", "reviewed-audit"], False, "reviewed-audit")],
)
def test_cli_uses_runtime_database_configuration(
    monkeypatch, capsys, generic_url, arguments, dry_run, expected_audit,
) -> None:
    monkeypatch.setenv("KIVOU_DATABASE_URL", "sqlite:///:memory:")
    if generic_url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", generic_url)
    monkeypatch.setattr(sys, "argv", ["discovery_grants", "--account-id", "qa-account", *arguments])
    calls = []

    def reconcile(engine, **kwargs):
        # Engine construction must not open a connection or migrate the database.
        assert str(engine.url) == "sqlite:///:memory:"
        calls.append(kwargs)
        return {"dry_run": kwargs["dry_run"]}

    monkeypatch.setattr(cli, "reconcile_discovery_grants", reconcile)
    cli.main()

    assert len(calls) == 1
    assert calls[0]["account_id"] == "qa-account"
    assert calls[0]["dry_run"] is dry_run
    assert calls[0]["expected_audit"] == expected_audit
    assert calls[0]["now"].tzinfo is not None
    assert json.loads(capsys.readouterr().out) == {"dry_run": dry_run}


def test_cli_refuses_missing_runtime_configuration_without_fallback(monkeypatch, capsys) -> None:
    monkeypatch.delenv("KIVOU_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///must-not-be-created.db")
    monkeypatch.setattr(sys, "argv", ["discovery_grants", "--account-id", "qa-account"])

    def forbidden(*args, **kwargs):
        pytest.fail("No engine or reconciliation without explicit runtime configuration")

    monkeypatch.setattr(cli.sa, "create_engine", forbidden)
    monkeypatch.setattr(cli, "reconcile_discovery_grants", forbidden)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert "KIVOU_DATABASE_URL" in output.err
    assert "must-not-be-created" not in output.err
    assert output.out == ""
