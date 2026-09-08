from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

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


def test_cli_dry_run_in_fresh_process_without_preloaded_api(tmp_path, monkeypatch) -> None:
    import test_discovery_landing_allocation as fixtures
    from engagement_helpers import make_engine

    from signals.accounts import service as accounts
    from signals.billing import discovery
    from signals.ingestion.backfill import materialize_landing_feed_in_transaction

    now = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(fixtures, "NOW", now)
    engine = make_engine(tmp_path)
    account_id, target, opportunities = fixtures.source_fixture(engine, count=5)
    with engine.begin() as connection:
        bait = materialize_landing_feed_in_transaction(
            connection, target_icp_id=target, opportunity_key=opportunities[0],
            as_of=now.date(), materialized_at=now,
        )
        accounts.record_landing_signal(
            connection, account_id=account_id, opportunity_key=opportunities[0],
            signal_key=bait, qa=True, now=now,
        )
        before = discovery.grants(connection, account_id=account_id)
    environment = dict(os.environ)
    environment.pop("DATABASE_URL", None)
    environment["KIVOU_DATABASE_URL"] = str(engine.url)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-m", "signals.qa.discovery_grants", "--account-id", account_id,
         "--dry-run"],
        env=environment, text=True, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    audit = json.loads(result.stdout)
    assert audit["dry_run"] is True
    assert audit["before"] == audit["after"]
    assert audit["bait_preserved"] is True
    assert len(audit["proposed_grants"]) == 3
    with engine.connect() as connection:
        assert discovery.grants(connection, account_id=account_id) == before
    engine.dispose()


@pytest.mark.parametrize(
    ("band", "expected"),
    [("strong", 3), ("promising", 2), ("weak", 1), (None, 0), ("unknown", 0)],
)
def test_shared_match_ranking_preserves_dashboard_order(band, expected) -> None:
    from signals.feed.ranking import match_band_rank

    assert match_band_rank(band) == expected
