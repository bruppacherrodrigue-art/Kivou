from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa

from signals.alerts import cli
from signals.alerts.cli import main
from signals.alerts.job import AlertOutcome, CycleReport
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 23, 10, 0, tzinfo=dt.UTC)


@pytest.fixture
def migrated_url(tmp_path) -> str:
    url = f"sqlite+pysqlite:///{tmp_path / 'alerts-cli.db'}"
    migrate_to_latest(create_database_engine(url))
    return url


@pytest.fixture
def configured_runtime(monkeypatch, migrated_url) -> None:
    values = {
        "KIVOU_DATABASE_URL": migrated_url,
        "KIVOU_ALLOWED_ORIGIN": "https://staging.kivou.test",
        "KIVOU_PUBLIC_APP_URL": "https://staging.kivou.test",
        "SMTP_HOST": "smtp.kivou.test",
        "SMTP_PORT": "587",
        "SMTP_FROM_EMAIL": "no-reply@kivou.eu",
        "SMTP_TLS_MODE": "starttls",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    for name in (
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "STRIPE_SECRET_KEY",
        "KIVOU_ATTRIBUTION_HMAC_KEY",
        "KIVOU_ATTRIBUTION_HMAC_KEY_VERSION",
    ):
        monkeypatch.delenv(name, raising=False)


def test_cli_reads_database_url_only_from_environment(configured_runtime) -> None:
    assert main(["--now", NOW.isoformat(), "--dry-run"]) == 0


def test_database_url_argument_is_rejected_without_echoing_its_value(
    configured_runtime, capsys
) -> None:
    private_url = "postgresql://user:" + "private-db-value@db.invalid/kivou"

    with pytest.raises(SystemExit) as stopped:
        main(["--database-url", private_url, "--dry-run"])

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    assert private_url not in rendered
    assert "private-db-value" not in rendered


def test_already_running_is_a_successful_noop(
    monkeypatch, configured_runtime, capsys
) -> None:
    report = CycleReport(
        accounts_considered=0,
        outcomes=(),
        execution_status="already_running",
    )
    monkeypatch.setattr(cli, "run_alert_cycle", lambda *args, **kwargs: report)

    assert main(["--now", NOW.isoformat()]) == 0
    assert "already_running" in capsys.readouterr().out


def test_only_current_execution_incidents_return_nonzero(
    monkeypatch, configured_runtime
) -> None:
    clean = CycleReport(accounts_considered=1, outcomes=())
    failed = CycleReport(
        accounts_considered=1,
        outcomes=(AlertOutcome("acc_test", "daily", "failed", 1, "smtp_451"),),
    )
    monkeypatch.setattr(cli, "run_alert_cycle", lambda *args, **kwargs: clean)
    assert main(["--now", NOW.isoformat()]) == 0
    monkeypatch.setattr(cli, "run_alert_cycle", lambda *args, **kwargs: failed)
    assert main(["--now", NOW.isoformat()]) == 1

    inconsistent_refusal = CycleReport(
        accounts_considered=1,
        outcomes=(
            AlertOutcome(
                "acc_test",
                "daily",
                "failed",
                1,
                "smtp_recipient_refused",
                True,
                1,
            ),
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_alert_cycle",
        lambda *args, **kwargs: inconsistent_refusal,
    )
    assert main(["--now", NOW.isoformat()]) == 1


@pytest.mark.parametrize(
    "outcome",
    [
        AlertOutcome("acc_test", "daily", "blocked", 1, "public_app_url_missing"),
        AlertOutcome(
            "acc_test",
            "daily",
            "failed",
            1,
            "smtp_recipient_refused",
            False,
            1,
        ),
        AlertOutcome(
            "acc_test",
            "daily",
            "recipient_refused",
            0,
            "smtp_recipient_refused",
            False,
            0,
        ),
    ],
)
def test_controlled_block_and_permanent_refusal_exit_zero(
    monkeypatch, configured_runtime, outcome
) -> None:
    monkeypatch.setattr(
        cli,
        "run_alert_cycle",
        lambda *args, **kwargs: CycleReport(1, (outcome,)),
    )

    assert main(["--now", NOW.isoformat()]) == 0


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (
            AlertOutcome(
                "acc_test", "daily", "failed", 1, "smtp_450", True, 1
            ),
            1,
        ),
        (
            AlertOutcome(
                "acc_test",
                "daily",
                "unknown_delivery_state",
                1,
                "unknown_delivery_state",
                True,
                1,
            ),
            3,
        ),
        (
            AlertOutcome(
                "acc_test",
                "daily",
                "persistence_failed",
                1,
                "delivery_state_persistence_failed",
                True,
                1,
            ),
            4,
        ),
    ],
)
def test_current_delivery_incident_categories_have_distinct_nonzero_statuses(
    monkeypatch, configured_runtime, outcome, expected
) -> None:
    monkeypatch.setattr(
        cli,
        "run_alert_cycle",
        lambda *args, **kwargs: CycleReport(1, (outcome,)),
    )

    assert main(["--now", NOW.isoformat()]) == expected


def test_missing_configuration_fails_closed_with_a_safe_code(
    monkeypatch, configured_runtime, capsys
) -> None:
    monkeypatch.delenv("SMTP_HOST")

    assert main(["--now", NOW.isoformat()]) == 2
    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    assert "configuration_invalid" in rendered
    assert "smtp.kivou.test" not in rendered


def test_database_failure_is_persistence_and_never_prints_sensitive_values(
    monkeypatch, configured_runtime, capsys
) -> None:
    smtp_secret = "smtp-" + "private-value"
    recipient = "private-user" + "@kivou.test"
    monkeypatch.setenv("SMTP_USERNAME", "smtp-user")
    monkeypatch.setenv("SMTP_PASSWORD", smtp_secret)

    def fail(*_args, **_kwargs):
        raise sa.exc.OperationalError(
            "SELECT",
            {},
            RuntimeError(f"database unavailable for {recipient} using {smtp_secret}"),
        )

    monkeypatch.setattr(cli, "run_alert_cycle", fail)

    assert main(["--now", NOW.isoformat()]) == 4
    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    assert "persistence_failed" in rendered
    assert recipient not in rendered
    assert smtp_secret not in rendered
    assert "OperationalError" not in rendered


def test_runtime_failure_is_distinct_and_never_prints_sensitive_values(
    monkeypatch, configured_runtime, capsys
) -> None:
    private_value = "private-runtime-value"

    def fail(*_args, **_kwargs):
        raise RuntimeError(private_value)

    monkeypatch.setattr(cli, "run_alert_cycle", fail)

    assert main(["--now", NOW.isoformat()]) == 5
    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    assert "runtime_failed" in rendered
    assert private_value not in rendered
    assert "RuntimeError" not in rendered


def test_invalid_now_is_reported_without_echoing_input(configured_runtime, capsys) -> None:
    private_value = "invalid-private-instant"

    assert main(["--now", private_value]) == 2
    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    assert "configuration_invalid" in rendered
    assert private_value not in rendered
