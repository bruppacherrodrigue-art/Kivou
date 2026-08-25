from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).parents[1]
SERVICE = ROOT / "ops/systemd/kivou-acquisition.service"
TIMER = ROOT / "ops/systemd/kivou-acquisition.timer"


def test_acquisition_service_is_one_bounded_shadow_orchestrator() -> None:
    service = SERVICE.read_text(encoding="utf-8")

    assert "User=kivou" in service
    assert "Group=kivou" in service
    assert "WorkingDirectory=/srv/kivou/app" in service
    assert "EnvironmentFile=/etc/kivou/staging.env" in service
    assert "EnvironmentFile=/etc/kivou/acquisition-runtime.env" in service
    assert service.count("ExecStart=") == 1
    assert (
        "ExecStart=/usr/bin/flock --verbose --nonblock --conflict-exit-code 0 "
        "/run/kivou/acquisition.lock /srv/kivou/app/.venv/bin/python -m "
        "signals.acquisition_runtime run-once"
    ) in service
    assert "RuntimeDirectory=kivou" in service
    assert "TimeoutStartSec=25min" in service
    assert "TimeoutStopSec=90s" in service
    assert "UMask=0077" in service
    assert "NoNewPrivileges=true" in service
    assert "ProtectSystem=strict" in service
    assert "ProtectHome=true" in service
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in service
    assert "ReadWritePaths=/run/kivou /var/lib/kivou/hermes-shadow" in service
    assert "--allow-qa-provider-mutations" not in service


def test_acquisition_timer_is_persistent_and_non_overlapping() -> None:
    timer = TIMER.read_text(encoding="utf-8")

    assert "OnCalendar=hourly" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=300" in timer
    assert "AccuracySec=60" in timer
    assert "Unit=kivou-acquisition.service" in timer
    assert "WantedBy=timers.target" in timer
