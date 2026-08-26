from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "ops" / "systemd"
SERVICE = SYSTEMD / "kivou-api.service"

EXEC_START = (
    "ExecStart=/srv/kivou/app/.venv/bin/uvicorn signals.api.asgi:app "
    "--host 127.0.0.1 --port 8000 --workers 2 --proxy-headers "
    "--forwarded-allow-ips 127.0.0.1 --no-server-header --no-access-log "
    "--timeout-keep-alive 20"
)
RUNTIME_DIRECTIVES = (
    "Type=exec",
    "User=kivou",
    "Group=kivou",
    "WorkingDirectory=/srv/kivou/app",
    "EnvironmentFile=/etc/kivou/staging.env",
    EXEC_START,
    "Restart=on-failure",
    "RestartSec=5s",
    "StandardOutput=journal",
    "StandardError=journal",
    "SyslogIdentifier=kivou-api",
)
HARDENING_DIRECTIVES = (
    "NoNewPrivileges=true",
    "PrivateTmp=true",
    "ProtectSystem=strict",
    "ProtectHome=true",
    "ReadWritePaths=/srv/kivou/run",
    "ProtectKernelTunables=true",
    "ProtectKernelModules=true",
    "ProtectControlGroups=true",
    "RestrictSUIDSGID=true",
    "RestrictNamespaces=true",
    "LockPersonality=true",
    "MemoryDenyWriteExecute=true",
)


def _active_sections() -> dict[str, tuple[str, ...]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in SERVICE.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            assert current not in sections, f"duplicate systemd section: {current}"
            sections[current] = []
            continue
        assert current is not None, f"directive outside a section: {line}"
        sections[current].append(line)
    return {name: tuple(directives) for name, directives in sections.items()}


def test_api_service_versions_exactly_the_audited_staging_runtime() -> None:
    sections = _active_sections()

    assert tuple(sections) == ("Unit", "Service", "Install")
    assert len(sections["Unit"]) == 1
    assert sections["Unit"][0].startswith("Description=")
    assert sections["Service"] == RUNTIME_DIRECTIVES + HARDENING_DIRECTIVES
    assert sections["Install"] == ("WantedBy=multi-user.target",)


def test_api_service_disables_only_uvicorn_access_logging() -> None:
    body = SERVICE.read_text(encoding="utf-8")
    sections = _active_sections()
    service = sections["Service"]
    exec_starts = tuple(
        directive for directive in service if directive.startswith("ExecStart=")
    )

    assert exec_starts == (EXEC_START,)
    assert exec_starts[0].count("--no-access-log") == 1
    assert body.count("--no-access-log") == 1
    assert exec_starts[0].index("--no-server-header") < exec_starts[0].index(
        "--no-access-log"
    )
    assert exec_starts[0].index("--no-access-log") < exec_starts[0].index(
        "--timeout-keep-alive 20"
    )

    for forbidden in (
        "--access-log",
        "--log-level critical",
        "--log-config",
        "--reload",
        "ExecStartPre=",
        "ExecStartPost=",
        "alembic",
        "StandardOutput=null",
        "StandardError=null",
        "KIVOU_DATABASE_URL=",
        "SMTP_PASSWORD=",
    ):
        assert forbidden not in body

    assert tuple(SYSTEMD.glob("kivou-api*.service")) == (SERVICE,)
    assert not (SYSTEMD / "kivou-api.timer").exists()
    assert not (SYSTEMD / "kivou-api.socket").exists()


def test_api_service_preserves_exactly_the_deployed_hardening_contract() -> None:
    service = _active_sections()["Service"]
    hardening = tuple(directive for directive in service if directive in HARDENING_DIRECTIVES)

    assert hardening == HARDENING_DIRECTIVES
