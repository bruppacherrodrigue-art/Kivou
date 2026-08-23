from __future__ import annotations

import fcntl
import pathlib
import shutil
import subprocess

import pytest

REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
SERVICE = REPOSITORY / "ops/systemd/kivou-alerts.service"
TIMER = REPOSITORY / "ops/systemd/kivou-alerts.timer"
OPERATIONS = REPOSITORY / "ops/README.md"


def test_versioned_service_uses_the_audited_staging_runtime() -> None:
    body = SERVICE.read_text(encoding="utf-8")

    assert "Type=oneshot" in body
    assert "User=kivou" in body
    assert "Group=kivou" in body
    assert "WorkingDirectory=/srv/kivou/app" in body
    assert "EnvironmentFile=/etc/kivou/staging.env" in body
    assert (
        "ExecStart=/usr/bin/flock --verbose --nonblock --conflict-exit-code 0 "
        "/srv/kivou/run/alerts.lock /srv/kivou/app/.venv/bin/python -m signals.alerts"
        in body
    )
    assert "--database-url" not in body
    assert "TimeoutStartSec=20min" in body
    assert "Restart=" not in body


def test_service_hardening_preserves_only_required_network_and_lock_access() -> None:
    body = SERVICE.read_text(encoding="utf-8")

    for directive in (
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "PrivateDevices=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ProtectKernelTunables=true",
        "ProtectControlGroups=true",
        "RestrictSUIDSGID=true",
        "ReadWritePaths=/srv/kivou/run",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
    ):
        assert directive in body
    assert "PrivateNetwork=true" not in body
    assert "KIVOU_DATABASE_URL=" not in body
    assert "SMTP_PASSWORD=" not in body


def test_timer_is_hourly_persistent_and_jittered() -> None:
    body = TIMER.read_text(encoding="utf-8")

    assert "OnCalendar=hourly" in body
    assert "Persistent=true" in body
    assert "RandomizedDelaySec=300" in body
    assert "Unit=kivou-alerts.service" in body
    assert "WantedBy=timers.target" in body


def test_documented_dry_run_loads_the_same_environment_file_as_systemd() -> None:
    body = OPERATIONS.read_text(encoding="utf-8")

    assert "systemd-run" in body
    assert "--property=EnvironmentFile=/etc/kivou/staging.env" in body
    assert "source /etc/kivou/staging.env" not in body
    assert "--preserve-env=" not in body


@pytest.mark.skipif(shutil.which("flock") is None, reason="util-linux flock is required")
def test_host_lock_contention_is_a_successful_noop_without_child_execution(tmp_path) -> None:
    lock_path = tmp_path / "alerts.lock"
    marker = tmp_path / "child-ran"
    with lock_path.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            [
                shutil.which("flock") or "flock",
                "--verbose",
                "--nonblock",
                "--conflict-exit-code",
                "0",
                str(lock_path),
                shutil.which("touch") or "/usr/bin/touch",
                str(marker),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )

    assert result.returncode == 0
    assert not marker.exists()
