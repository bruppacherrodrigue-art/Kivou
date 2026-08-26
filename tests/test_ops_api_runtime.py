from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "ops" / "systemd"
SERVICE = SYSTEMD / "kivou-api.service"
ASGI_TARGET = "signals.api.asgi:app"

UNIT_DIRECTIVES = (
    "Description=Kivou API (FastAPI/uvicorn)",
    "Documentation=https://github.com/bruppacherrodrigue-art/Kivou",
    "After=network-online.target postgresql.service",
    "Wants=network-online.target",
)

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


def _active_sections(source: Path = SERVICE) -> dict[str, tuple[str, ...]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            assert current not in sections, f"duplicate systemd section: {current}"
            sections[current] = []
            continue
        assert current is not None, f"directive outside a section: {line}"
        sections[current].append(line)
    return {name: tuple(directives) for name, directives in sections.items()}


def _systemd_artifacts(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(root.rglob("*")))


def _assert_api_runtime_artifacts(
    artifacts: tuple[Path, ...], *, expected_service: Path
) -> None:
    drop_ins = tuple(
        path for path in artifacts if "kivou-api.service.d" in path.parts
    )
    assert not drop_ins, f"versioned API drop-in is forbidden: {drop_ins}"

    launchers = tuple(
        path
        for path in artifacts
        if path.is_file() and ASGI_TARGET in path.read_text(encoding="utf-8")
    )
    assert launchers == (expected_service,), (
        f"expected {expected_service} as the only ASGI launcher, got {launchers}"
    )


def test_api_service_versions_exactly_the_audited_staging_runtime() -> None:
    sections = _active_sections()

    assert tuple(sections) == ("Unit", "Service", "Install")
    assert sections["Unit"] == UNIT_DIRECTIVES
    assert sections["Service"] == RUNTIME_DIRECTIVES + HARDENING_DIRECTIVES
    assert sections["Install"] == ("WantedBy=multi-user.target",)


def test_systemd_parser_preserves_inline_hash_and_ignores_only_full_line_comments(
    tmp_path: Path,
) -> None:
    source = tmp_path / "inline-hash.service"
    source.write_text(
        "[Service]\n"
        "Environment=KIVOU_LABEL=value#literal\n"
        "  # full-line hash comment\n"
        "; full-line semicolon comment\n",
        encoding="utf-8",
    )

    assert _active_sections(source) == {
        "Service": ("Environment=KIVOU_LABEL=value#literal",)
    }


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
    hardening = tuple(
        directive for directive in service if directive in HARDENING_DIRECTIVES
    )

    assert hardening == HARDENING_DIRECTIVES


def test_api_service_is_the_only_versioned_asgi_launcher_and_has_no_drop_ins() -> None:
    _assert_api_runtime_artifacts(
        _systemd_artifacts(SYSTEMD), expected_service=SERVICE
    )


def test_api_runtime_inventory_rejects_a_differently_named_second_launcher(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "kivou-api.service"
    primary.write_text(f"ExecStart=/usr/bin/uvicorn {ASGI_TARGET}\n", encoding="utf-8")
    alternate = tmp_path / "unrelated-name.service"
    alternate.write_text(f"ExecStart=/usr/bin/uvicorn {ASGI_TARGET}\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="only ASGI launcher"):
        _assert_api_runtime_artifacts(
            _systemd_artifacts(tmp_path), expected_service=primary
        )


def test_api_runtime_inventory_rejects_a_versioned_drop_in(tmp_path: Path) -> None:
    primary = tmp_path / "kivou-api.service"
    primary.write_text(f"ExecStart=/usr/bin/uvicorn {ASGI_TARGET}\n", encoding="utf-8")
    drop_in = tmp_path / "kivou-api.service.d" / "override.conf"
    drop_in.parent.mkdir()
    drop_in.write_text("[Service]\nRestart=always\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="drop-in"):
        _assert_api_runtime_artifacts(
            _systemd_artifacts(tmp_path), expected_service=primary
        )
