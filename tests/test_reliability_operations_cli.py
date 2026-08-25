from __future__ import annotations

import datetime as dt

from alembic import command
from test_policy_persistence import control

from signals.operations.cli import main
from signals.persistence.database import alembic_config, create_database_engine
from signals.policy.contracts import AutonomyMode
from signals.policy.store import PolicyStore

NOW = dt.datetime(2026, 8, 23, 12, tzinfo=dt.UTC)


def test_operator_cli_activates_append_only_kill_switch_without_external_io(
    tmp_path, monkeypatch, capsys
) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'ops-cli.db'}"
    engine = create_database_engine(url)
    command.upgrade(alembic_config(engine), "head")
    PolicyStore(engine).append_control(
        control(
            1,
            autonomy_mode=AutonomyMode.AUTONOMOUS_CAPPED,
            allowed_commands=("schedule_campaign", "pause_campaign", "generate_weekly_report"),
            effective_at=NOW - dt.timedelta(minutes=1),
        )
    )
    monkeypatch.setenv("KIVOU_DATABASE_URL", url)

    result = main(
        [
            "activate-kill-switch",
            "--reason-code",
            "OPERATOR_EMERGENCY_STOP",
        ],
        clock=lambda: NOW,
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "kill_switch=true" in output
    assert "read_only=true" in output
    current = PolicyStore(engine).get_effective_control(NOW)
    assert current.autonomy_mode is AutonomyMode.SHADOW
    assert current.kill_switch and current.read_only


def test_kill_switch_mutation_refuses_operator_database_and_clock_authority(
    tmp_path, monkeypatch, capsys
) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'ops-cli-authority.db'}"
    engine = create_database_engine(url)
    command.upgrade(alembic_config(engine), "head")
    PolicyStore(engine).append_control(
        control(
            1,
            autonomy_mode=AutonomyMode.ASSISTED,
            effective_at=NOW - dt.timedelta(minutes=1),
        )
    )
    monkeypatch.setenv("KIVOU_DATABASE_URL", url)

    result = main(
        [
            "--database-url",
            url,
            "--now",
            NOW.isoformat(),
            "activate-kill-switch",
            "--reason-code",
            "OPERATOR_EMERGENCY_STOP",
        ],
        clock=lambda: NOW,
    )

    assert result == 2
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "acquisition_kill_switch_invalid\n"
    assert PolicyStore(engine).get_effective_control(NOW).kill_switch is False


def test_operator_cli_health_is_bounded_and_never_prints_database_url(tmp_path, capsys) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'ops-health-secret-marker.db'}"
    engine = create_database_engine(url)
    command.upgrade(alembic_config(engine), "head")

    result = main(["--database-url", url, "--now", NOW.isoformat(), "health"])

    assert result == 1
    output = capsys.readouterr().out
    assert "status=NOT_READY" in output
    assert url not in output
    assert "ops-health-secret-marker" not in output
