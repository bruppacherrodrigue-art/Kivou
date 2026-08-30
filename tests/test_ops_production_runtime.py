from __future__ import annotations

import pathlib

import pytest

REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
SYSTEMD = REPOSITORY / "ops/systemd"
PRODUCTION = SYSTEMD / "production"

STAGING_SOURCES = {
    "simap": "*-*-* 00/2:05:00",
    "boamp": "*-*-* 00/2:15:00",
}
PRODUCTION_TIMERS = {
    "simap": "*-*-* 00/2:05:00",
    "boamp": "*-*-* 00/2:15:00",
    "decp": "*-*-* *:20:00",
    "ted": "*-*-* 00/2:30:00",
}
PRODUCTION_SERVICES = (
    PRODUCTION / "kivou-api.service",
    PRODUCTION / "kivou-alerts.service",
    PRODUCTION / "kivou-backup.service",
    PRODUCTION / "kivou-ingest@.service",
)


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(("source", "schedule"), STAGING_SOURCES.items())
def test_staging_ingestion_service_matches_the_audited_contract(
    source: str, schedule: str
) -> None:
    service = read(SYSTEMD / f"kivou-ingest-{source}.service")
    timer = read(SYSTEMD / f"kivou-ingest-{source}.timer")

    for directive in (
        "Type=oneshot",
        "User=kivou",
        "Group=kivou",
        "WorkingDirectory=/srv/kivou/app",
        "EnvironmentFile=/etc/kivou/staging.env",
        "RuntimeDirectory=kivou",
        "RuntimeDirectoryMode=0700",
        "TimeoutStartSec=30min",
        "StandardOutput=journal",
        "StandardError=journal",
        f"SyslogIdentifier=kivou-ingest-{source}",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ReadWritePaths=/run/kivou",
    ):
        assert directive in service
    assert (
        "ExecStart=/usr/bin/flock --verbose --exclusive --timeout 300 "
        "--conflict-exit-code 0 /run/kivou/ingestion.lock "
        "/srv/kivou/app/.venv/bin/python -m signals.ingestion run "
        f"--source {source}"
    ) in service

    for directive in (
        f"OnCalendar={schedule}",
        "Persistent=true",
        "RandomizedDelaySec=60",
        f"Unit=kivou-ingest-{source}.service",
        "WantedBy=timers.target",
    ):
        assert directive in timer


def test_production_services_are_isolated_from_staging_and_acquisition() -> None:
    for path in PRODUCTION_SERVICES:
        body = read(path)
        lowered = body.lower()

        assert "staging" not in lowered
        assert "apollo" not in lowered
        assert "acquisition" not in lowered
        assert "EnvironmentFile=/etc/kivou/production.env" in body
        assert "InaccessiblePaths=/srv/kivou/.ssh" in body
        assert "ReadOnlyPaths=/srv/kivou/releases /srv/kivou/app" in body
        for directive in (
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "PrivateDevices=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "ProtectKernelTunables=true",
            "ProtectKernelModules=true",
            "ProtectControlGroups=true",
            "RestrictSUIDSGID=true",
            "LockPersonality=true",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        ):
            assert directive in body


def test_production_directory_contains_no_acquisition_unit() -> None:
    assert not list(PRODUCTION.glob("*acquisition*"))


def test_production_api_runs_only_behind_the_local_proxy() -> None:
    body = read(PRODUCTION / "kivou-api.service")

    for directive in (
        "Type=exec",
        "After=network-online.target postgresql.service",
        "Wants=network-online.target",
        "User=kivou",
        "Group=kivou",
        "WorkingDirectory=/srv/kivou/app",
        "EnvironmentFile=/etc/kivou/production.env",
        "Restart=on-failure",
        "RestartSec=5s",
        "StandardOutput=journal",
        "StandardError=journal",
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "MemoryDenyWriteExecute=true",
        "RestrictNamespaces=true",
        "ReadWritePaths=/srv/kivou/run",
        "WantedBy=multi-user.target",
    ):
        assert directive in body
    assert (
        "ExecStart=/srv/kivou/app/.venv/bin/uvicorn signals.api.asgi:app "
        "--host 127.0.0.1 --port 8000 --workers 2 --proxy-headers "
        "--forwarded-allow-ips 127.0.0.1 --no-server-header --no-access-log "
        "--timeout-keep-alive 20"
    ) in body


def test_production_ingestion_template_uses_one_shared_lock() -> None:
    body = read(PRODUCTION / "kivou-ingest@.service")

    for directive in (
        "Type=oneshot",
        "User=kivou",
        "Group=kivou",
        "WorkingDirectory=/srv/kivou/app",
        "EnvironmentFile=/etc/kivou/production.env",
        "RuntimeDirectory=kivou",
        "RuntimeDirectoryMode=0700",
        "TimeoutStartSec=30min",
        "TimeoutStopSec=90s",
        "UMask=0077",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "PrivateDevices=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ProtectKernelTunables=true",
        "ProtectKernelModules=true",
        "ProtectControlGroups=true",
        "RestrictSUIDSGID=true",
        "LockPersonality=true",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "ReadWritePaths=/run/kivou",
    ):
        assert directive in body
    assert (
        "ExecStart=/usr/bin/flock --verbose --exclusive --timeout 300 "
        "--conflict-exit-code 0 /run/kivou/ingestion.lock "
        "/srv/kivou/app/.venv/bin/python -m signals.ingestion run --source %i"
    ) in body


@pytest.mark.parametrize(("source", "schedule"), PRODUCTION_TIMERS.items())
def test_production_ingestion_timers_are_exact(source: str, schedule: str) -> None:
    body = read(PRODUCTION / f"kivou-ingest-{source}.timer")

    for directive in (
        f"OnCalendar={schedule}",
        "Persistent=true",
        "RandomizedDelaySec=60",
        "AccuracySec=60",
        f"Unit=kivou-ingest@{source}.service",
        "WantedBy=timers.target",
    ):
        assert directive in body


def test_production_alerts_have_a_bounded_non_overlapping_hourly_cycle() -> None:
    service = read(PRODUCTION / "kivou-alerts.service")
    timer = read(PRODUCTION / "kivou-alerts.timer")

    for directive in (
        "Type=oneshot",
        "After=network-online.target",
        "Wants=network-online.target",
        "User=kivou",
        "Group=kivou",
        "WorkingDirectory=/srv/kivou/app",
        "EnvironmentFile=/etc/kivou/production.env",
        "TimeoutStartSec=20min",
        "StandardOutput=journal",
        "StandardError=journal",
        "UMask=0077",
        "PrivateDevices=true",
        "ProtectKernelTunables=true",
        "ProtectKernelModules=true",
        "ProtectControlGroups=true",
        "RestrictSUIDSGID=true",
        "LockPersonality=true",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "ReadWritePaths=/srv/kivou/run",
    ):
        assert directive in service
    assert (
        "ExecStart=/usr/bin/flock --verbose --nonblock --conflict-exit-code 0 "
        "/srv/kivou/run/alerts.lock /srv/kivou/app/.venv/bin/python -m signals.alerts"
    ) in service

    for directive in (
        "OnCalendar=hourly",
        "Persistent=true",
        "RandomizedDelaySec=300",
        "AccuracySec=60",
        "Unit=kivou-alerts.service",
        "WantedBy=timers.target",
    ):
        assert directive in timer


def test_production_backup_runs_local_then_offsite_with_narrow_write_access() -> None:
    service = read(PRODUCTION / "kivou-backup.service")
    timer = read(PRODUCTION / "kivou-backup.timer")

    for directive in (
        "Type=oneshot",
        "After=network-online.target postgresql.service",
        "User=kivou",
        "Group=kivou",
        "EnvironmentFile=/etc/kivou/production.env",
        "EnvironmentFile=/etc/kivou/swiss-backup.env",
        "StandardOutput=journal",
        "StandardError=journal",
        "ReadWritePaths=/srv/kivou/backups",
    ):
        assert directive in service
    local = "ExecStart=/srv/kivou/app/ops/bin/kivou-backup.sh"
    offsite = "ExecStart=/srv/kivou/app/ops/bin/kivou-restic-upload.sh"
    assert service.index(local) < service.index(offsite)

    for directive in (
        "OnCalendar=*-*-* 03:17:00",
        "Persistent=true",
        "RandomizedDelaySec=600",
        "Unit=kivou-backup.service",
        "WantedBy=timers.target",
    ):
        assert directive in timer
