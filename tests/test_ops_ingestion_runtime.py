from __future__ import annotations

import fcntl
import pathlib
import shutil
import subprocess

import pytest

REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
SERVICE = REPOSITORY / "ops/systemd/kivou-ingest-decp.service"
TIMER = REPOSITORY / "ops/systemd/kivou-ingest-decp.timer"
TED_SERVICE = REPOSITORY / "ops/systemd/kivou-ingest-ted.service"
TED_TIMER = REPOSITORY / "ops/systemd/kivou-ingest-ted.timer"
OPERATIONS = REPOSITORY / "ops/README.md"
ENVIRONMENT = REPOSITORY / ".env.example"


def test_decp_service_runs_the_bounded_checkout_command_with_a_clean_host_lock() -> None:
    body = SERVICE.read_text(encoding="utf-8")

    assert "Type=oneshot" in body
    assert "User=kivou" in body
    assert "Group=kivou" in body
    assert "WorkingDirectory=/srv/kivou/app" in body
    assert "EnvironmentFile=/etc/kivou/staging.env" in body
    assert "RuntimeDirectory=kivou" in body
    assert "RuntimeDirectoryMode=0700" in body
    assert (
        "ExecStart=/usr/bin/flock --verbose --nonblock --conflict-exit-code 0 "
        "/run/kivou/ingest-decp.lock /srv/kivou/app/.venv/bin/python "
        "-m signals.ingestion run --source decp"
        in body
    )
    assert "TimeoutStartSec=25min" in body
    assert "Restart=" not in body


def test_decp_service_hardening_keeps_network_database_and_runtime_access() -> None:
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
        "ReadWritePaths=/run/kivou",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
    ):
        assert directive in body
    assert "PrivateNetwork=true" not in body
    assert "KIVOU_DATABASE_URL=" not in body


def test_decp_timer_runs_often_enough_for_two_daily_windows_to_converge() -> None:
    body = TIMER.read_text(encoding="utf-8")

    assert "OnCalendar=hourly" in body
    assert "Persistent=true" in body
    assert "RandomizedDelaySec=300" in body
    assert "Unit=kivou-ingest-decp.service" in body
    assert "WantedBy=timers.target" in body


def test_application_budget_is_shorter_than_the_systemd_timeout() -> None:
    environment = ENVIRONMENT.read_text(encoding="utf-8")

    assert "KIVOU_DECP_MAX_WINDOWS_PER_RUN=2" in environment
    assert "KIVOU_DECP_BATCH_SIZE=100" in environment
    assert "KIVOU_DECP_TIME_BUDGET_SECONDS=1200" in environment
    assert "KIVOU_DECP_OVERLAP_DAYS=30" in environment
    assert "KIVOU_INGESTION_STALE_RUN_SECONDS=3600" in environment
    assert 1200 < 25 * 60


def test_decp_operations_document_install_manual_proof_and_rollback() -> None:
    body = OPERATIONS.read_text(encoding="utf-8")

    assert "kivou-ingest-decp.service" in body
    assert "kivou-ingest-decp.timer" in body
    assert "systemd-analyze verify" in body
    assert "systemctl start kivou-ingest-decp.service" in body
    assert "ingestion_checkpoint" in body
    assert "stale_run_reconciled" in body
    assert "offset intra-journée" in body
    assert "KIVOU_DECP_BATCH_SIZE" in body
    assert "systemctl disable --now kivou-ingest-decp.timer" in body
    assert "source /etc/kivou/staging.env" not in body


@pytest.mark.skipif(shutil.which("flock") is None, reason="util-linux flock is required")
def test_decp_host_lock_contention_is_a_successful_noop(tmp_path) -> None:
    lock_path = tmp_path / "ingest-decp.lock"
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


def test_ted_service_runs_one_bounded_cycle_with_a_clean_host_lock() -> None:
    body = TED_SERVICE.read_text(encoding="utf-8")

    assert "Type=oneshot" in body
    assert "User=kivou" in body
    assert "Group=kivou" in body
    assert "WorkingDirectory=/srv/kivou/app" in body
    assert "EnvironmentFile=/etc/kivou/staging.env" in body
    assert "RuntimeDirectory=kivou" in body
    assert "RuntimeDirectoryMode=0700" in body
    assert (
        "ExecStart=/usr/bin/flock --verbose --nonblock --conflict-exit-code 0 "
        "/run/kivou/ingest-ted.lock /srv/kivou/app/.venv/bin/python "
        "-m signals.ingestion run --source ted"
        in body
    )
    assert "TimeoutStartSec=25min" in body
    assert "Restart=" not in body


def test_ted_service_hardening_keeps_network_database_and_runtime_access() -> None:
    body = TED_SERVICE.read_text(encoding="utf-8")

    for directive in (
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "PrivateDevices=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ProtectKernelTunables=true",
        "ProtectControlGroups=true",
        "RestrictSUIDSGID=true",
        "ReadWritePaths=/run/kivou",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
    ):
        assert directive in body
    assert "PrivateNetwork=true" not in body
    assert "KIVOU_DATABASE_URL=" not in body


def test_ted_timer_is_persistent_but_requires_manual_success_before_enablement() -> None:
    timer = TED_TIMER.read_text(encoding="utf-8")
    operations = OPERATIONS.read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* 00/2:30:00" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=300" in timer
    assert "Unit=kivou-ingest-ted.service" in timer
    assert "WantedBy=timers.target" in timer
    manual = operations.index("systemctl start kivou-ingest-ted.service")
    enable = operations.index("systemctl enable --now kivou-ingest-ted.timer")
    assert manual < enable
    assert "Ne pas activer le timer avant" in operations


def test_ted_application_limits_are_bounded_below_the_host_timeout() -> None:
    environment = ENVIRONMENT.read_text(encoding="utf-8")

    assert "KIVOU_TED_REQUEST_INTERVAL_SECONDS=1" in environment
    assert "KIVOU_TED_MAX_ATTEMPTS=4" in environment
    assert "KIVOU_TED_MAX_RETRY_SECONDS=120" in environment
    assert "KIVOU_TED_MAX_RECORDS_PER_RUN=500" in environment
    assert "KIVOU_TED_TIME_BUDGET_SECONDS=1200" in environment
    assert 1200 + 120 < 25 * 60


def test_ted_operations_document_proof_enablement_health_and_rollback() -> None:
    body = OPERATIONS.read_text(encoding="utf-8")

    for expected in (
        "kivou-ingest-ted.service",
        "kivou-ingest-ted.timer",
        "systemd-analyze verify",
        "ingestion_checkpoint",
        "pending_publication_numbers",
        "Retry-After",
        "SIMAP",
        "BOAMP",
        "systemctl disable --now kivou-ingest-ted.timer",
    ):
        assert expected in body
    assert "source /etc/kivou/staging.env" not in body
