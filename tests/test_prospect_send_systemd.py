from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "ops" / "systemd"


def _directives(name: str) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in (SYSTEMD / name).read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def test_prospect_send_service_is_a_hardened_bounded_founder_worker() -> None:
    directives = _directives("kivou-prospect-send.service")

    for expected in (
        "Type=oneshot",
        "User=kivou",
        "Group=kivou",
        "WorkingDirectory=/srv/kivou/app",
        "EnvironmentFile=/etc/kivou/founder.env",
        "EnvironmentFile=/etc/kivou/production.env",
        "EnvironmentFile=/etc/kivou/acquisition-production.env",
        "TimeoutStartSec=20min",
        "SuccessExitStatus=75",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "PrivateDevices=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ProtectKernelTunables=true",
        "ProtectKernelModules=true",
        "ProtectControlGroups=true",
        "RestrictSUIDSGID=true",
        "RestrictNamespaces=true",
        "LockPersonality=true",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "ReadOnlyPaths=/srv/kivou/releases /srv/kivou/app",
        "ReadWritePaths=/run/kivou",
    ):
        assert expected in directives

    exec_start = next(value for value in directives if value.startswith("ExecStart="))
    assert exec_start == (
        "ExecStart=/usr/bin/flock --verbose --nonblock --conflict-exit-code 75 "
        "/run/kivou/prospect-send.lock /srv/kivou/app/.venv/bin/python "
        "-m signals.prospection_actions.worker --limit 25"
    )
    assert not any(value.startswith("IPAddressDeny=") for value in directives)


def test_prospect_send_timer_restarts_the_bounded_worker_after_each_batch() -> None:
    directives = _directives("kivou-prospect-send.timer")

    assert "OnBootSec=5s" in directives
    assert "OnUnitInactiveSec=5s" in directives
    assert "Persistent=true" in directives
    assert "AccuracySec=1s" in directives
    assert "Unit=kivou-prospect-send.service" in directives
    assert "WantedBy=timers.target" in directives
