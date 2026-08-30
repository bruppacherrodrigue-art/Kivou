from __future__ import annotations

import pathlib
import re
import shlex
import subprocess

import pytest

REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
SYSTEMD = REPOSITORY / "ops/systemd"
PRODUCTION = SYSTEMD / "production"
PRODUCTION_RUNBOOK = REPOSITORY / "ops/production/README.md"
NGINX = REPOSITORY / "ops/nginx"
PRODUCTION_NGINX = NGINX / "kivou-production.conf"
PRODUCTION_WWW_NGINX = NGINX / "kivou-production-www.conf"
PRODUCTION_DEFAULT_DENY_NGINX = NGINX / "kivou-production-default-deny.conf"
PRODUCTION_SECURITY_HEADERS = NGINX / "kivou-production-security-headers.conf"
PRODUCTION_SENSITIVE_SECURITY_HEADERS = (
    NGINX / "kivou-production-sensitive-link-security-headers.conf"
)
SAFE_PRODUCTION_PATH_SET = "set $kivou_safe_request_path $kivou_safe_path_map;"
SAFE_PRODUCTION_ACCESS_LOG = (
    "access_log /var/log/nginx/kivou_access.log kivou_safe_json;"
)

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
    PRODUCTION / "kivou-backup-local.service",
    PRODUCTION / "kivou-backup.service",
    PRODUCTION / "kivou-ingest@.service",
)
ExpectedDirectives = dict[tuple[str, str], str | tuple[str, ...]]
ParsedUnit = dict[str, dict[str, list[str]]]


def runbook_shell_blocks(body: str) -> tuple[str, ...]:
    return tuple(re.findall(r"^```bash\n(.*?)^```$", body, flags=re.MULTILINE | re.DOTALL))


def assert_fragments_in_order(body: str, *fragments: str) -> None:
    offset = 0
    for fragment in fragments:
        position = body.find(fragment, offset)
        assert position >= 0, f"missing or out-of-order runbook fragment: {fragment}"
        offset = position + len(fragment)


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def runbook_immutability_find_commands(body: str) -> tuple[str, ...]:
    return tuple(
        re.findall(r"(?:sudo )?find [^\n]* -perm /222 -print -quit", body)
    )


def run_immutability_find_command(
    command: str,
    *,
    backend: pathlib.Path,
    frontend: pathlib.Path,
    unit_capture: pathlib.Path,
    rollback: pathlib.Path,
) -> subprocess.CompletedProcess[str]:
    assignments = {
        "KIVOU_BACKEND_RELEASE_DIR": backend,
        "KIVOU_FRONTEND_RELEASE_DIR": frontend,
        "KIVOU_PREVIOUS_APP_TARGET": backend,
        "KIVOU_PREVIOUS_FRONTEND_TARGET": frontend,
        "KIVOU_UNIT_CAPTURE_DIR": unit_capture,
        "KIVOU_ROLLBACK_DIR": rollback,
    }
    script = "\n".join(
        (
            "set -euo pipefail",
            'sudo() { command "$@"; }',
            *(f"{name}={shlex.quote(str(path))}" for name, path in assignments.items()),
            command,
        )
    )
    return subprocess.run(
        ["bash"], input=script, text=True, capture_output=True, check=False
    )


def prepare_immutable_symlink_artifacts(
    root: pathlib.Path,
) -> dict[str, pathlib.Path]:
    backend = root / "backend-release"
    backend_lib = backend / ".venv/lib"
    backend_lib.mkdir(parents=True)
    (backend / ".venv/lib64").symlink_to("lib", target_is_directory=True)

    frontend = root / "frontend-release"
    frontend_bin = frontend / "node_modules/.bin"
    frontend_tool = frontend / "node_modules/vite/bin/vite.js"
    frontend_bin.mkdir(parents=True)
    frontend_tool.parent.mkdir(parents=True)
    frontend_tool.write_text("vite\n", encoding="utf-8")
    (frontend_bin / "vite").symlink_to("../vite/bin/vite.js")

    rollback = root / "rollback"
    nginx_capture = rollback / "nginx"
    nginx_capture.mkdir(parents=True)
    nginx_target = root / "nginx/sites-available/kivou"
    nginx_target.parent.mkdir(parents=True)
    nginx_target.write_text("server {}\n", encoding="utf-8")
    (nginx_capture / "etc__nginx__sites-enabled__kivou.saved").symlink_to(
        nginx_target
    )
    nginx_absent = nginx_capture / "etc__nginx__sites-enabled__default.ABSENT"
    nginx_absent.write_text("", encoding="utf-8")

    unit_capture = rollback / "systemd"
    unit_capture.mkdir()
    (unit_capture / "kivou-api.service.saved").write_text(
        "[Service]\n", encoding="utf-8"
    )

    for path in (
        backend_lib,
        backend / ".venv",
        backend,
        frontend_tool,
        frontend_tool.parent,
        frontend / "node_modules/vite",
        frontend_bin,
        frontend / "node_modules",
        frontend,
        nginx_target,
        nginx_target.parent,
        nginx_target.parent.parent,
        nginx_absent,
        nginx_capture,
        unit_capture / "kivou-api.service.saved",
        unit_capture,
        rollback,
    ):
        path.chmod(0o555 if path.is_dir() else 0o444)

    return {
        "backend": backend,
        "frontend": frontend,
        "rollback": rollback,
        "nginx_capture": nginx_capture,
        "nginx_absent": nginx_absent,
        "unit_capture": unit_capture,
    }


def nginx_active_directives(body: str) -> tuple[str, ...]:
    return tuple(
        directive
        for raw_line in body.splitlines()
        if (directive := raw_line.split("#", 1)[0].strip())
    )


def nginx_server_blocks(body: str) -> tuple[tuple[str, ...], ...]:
    lines = body.splitlines()
    blocks: list[tuple[str, ...]] = []
    index = 0
    while index < len(lines):
        directive = lines[index].split("#", 1)[0].strip()
        if directive != "server {":
            index += 1
            continue
        depth = 1
        block: list[str] = []
        index += 1
        while index < len(lines) and depth:
            directive = lines[index].split("#", 1)[0].strip()
            if directive:
                depth += directive.count("{") - directive.count("}")
                if depth:
                    block.append(directive)
            index += 1
        assert depth == 0, "unterminated nginx server block"
        blocks.append(tuple(block))
    return tuple(blocks)


def assert_production_www_contract(body: str) -> None:
    assert nginx_active_directives(body) == (
        "server {",
        "listen 80;",
        "listen [::]:80;",
        "server_name PRODUCTION_WWW_HOST;",
        SAFE_PRODUCTION_PATH_SET,
        SAFE_PRODUCTION_ACCESS_LOG,
        "location /.well-known/acme-challenge/ {",
        "root /var/www/certbot;",
        "}",
        "location / {",
        "return 301 https://PRODUCTION_HOST$request_uri;",
        "}",
        "}",
        "server {",
        "listen 443 ssl http2;",
        "listen [::]:443 ssl http2;",
        "server_name PRODUCTION_WWW_HOST;",
        SAFE_PRODUCTION_PATH_SET,
        SAFE_PRODUCTION_ACCESS_LOG,
        "ssl_certificate /etc/letsencrypt/live/PRODUCTION_HOST/fullchain.pem;",
        "ssl_certificate_key /etc/letsencrypt/live/PRODUCTION_HOST/privkey.pem;",
        "ssl_trusted_certificate /etc/letsencrypt/live/PRODUCTION_HOST/chain.pem;",
        "include /etc/nginx/kivou-production-security-headers.conf;",
        "return 301 https://PRODUCTION_HOST$request_uri;",
        "}",
    )


def parse_active_directives(body: str) -> ParsedUnit:
    logical_lines: list[str] = []
    continued = ""
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.endswith("\\"):
            continued += line[:-1].rstrip() + " "
            continue
        logical_lines.append(continued + line)
        continued = ""
    assert not continued, "unterminated continued directive"

    parsed: ParsedUnit = {}
    section: str | None = None
    for line in logical_lines:
        if line.startswith("["):
            assert line.endswith("]"), f"invalid section header: {line}"
            section = line[1:-1]
            assert section, "empty section header"
            parsed.setdefault(section, {})
            continue
        assert section is not None, f"directive outside a section: {line}"
        key, separator, value = line.partition("=")
        assert separator and key, f"invalid directive: {line}"
        parsed[section].setdefault(key, []).append(value)
    return parsed


def assert_unit_contract(
    body: str,
    expected: ExpectedDirectives,
    *,
    repeatable: frozenset[tuple[str, str]] = frozenset(),
) -> None:
    parsed = parse_active_directives(body)
    for section, directives in parsed.items():
        for key, values in directives.items():
            location = (section, key)
            assert len(values) == 1 or location in repeatable, (
                f"unexpected duplicate directive {section}.{key}: {values}"
            )

    for (section, key), expected_value in expected.items():
        misplaced = {
            other_section: directives[key]
            for other_section, directives in parsed.items()
            if other_section != section and key in directives
        }
        assert not misplaced, f"directive {key} also appears in wrong sections: {misplaced}"
        expected_values = (
            (expected_value,) if isinstance(expected_value, str) else expected_value
        )
        actual_values = tuple(parsed.get(section, {}).get(key, ()))
        assert actual_values == expected_values, (
            f"unexpected {section}.{key}: {actual_values}, expected {expected_values}"
        )


def staging_services_using_the_shared_runtime() -> tuple[pathlib.Path, ...]:
    paths: list[pathlib.Path] = []
    for path in sorted(SYSTEMD.glob("*.service")):
        runtime_directories = parse_active_directives(read(path)).get("Service", {}).get(
            "RuntimeDirectory", []
        )
        if "kivou" in runtime_directories:
            paths.append(path)
    return tuple(paths)


@pytest.mark.parametrize(
    "path",
    staging_services_using_the_shared_runtime(),
    ids=lambda path: path.name,
)
def test_every_staging_service_using_the_shared_runtime_preserves_it(
    path: pathlib.Path,
) -> None:
    service = parse_active_directives(read(path))["Service"]

    assert service.get("RuntimeDirectoryPreserve") == ["yes"]


def test_contract_ignores_commented_directives() -> None:
    body = "[Service]\n# RuntimeDirectoryPreserve=yes\n"

    with pytest.raises(AssertionError):
        assert_unit_contract(body, {("Service", "RuntimeDirectoryPreserve"): "yes"})


def test_contract_rejects_a_directive_in_the_wrong_section() -> None:
    body = "[Unit]\nTimeoutStartSec=6h\n[Service]\nType=oneshot\n"

    with pytest.raises(AssertionError):
        assert_unit_contract(body, {("Service", "TimeoutStartSec"): "6h"})


def test_contract_rejects_duplicate_or_contradictory_singleton_directives() -> None:
    body = "[Service]\nProtectSystem=strict\nProtectSystem=false\n"

    with pytest.raises(AssertionError):
        assert_unit_contract(body, {("Service", "ProtectSystem"): "strict"})


def test_contract_rejects_an_expected_directive_duplicated_in_another_section() -> None:
    body = "[Unit]\nUser=root\n[Service]\nUser=kivou\n"

    with pytest.raises(AssertionError):
        assert_unit_contract(body, {("Service", "User"): "kivou"})


def test_contract_allows_explicitly_repeatable_directives_in_order() -> None:
    body = "[Service]\nType=oneshot\nExecStart=/bin/one\nExecStart=/bin/two\n"

    assert_unit_contract(
        body,
        {
            ("Service", "Type"): "oneshot",
            ("Service", "ExecStart"): ("/bin/one", "/bin/two"),
        },
        repeatable=frozenset({("Service", "ExecStart")}),
    )


@pytest.mark.parametrize(("source", "schedule"), STAGING_SOURCES.items())
def test_staging_ingestion_service_matches_the_audited_contract(
    source: str, schedule: str
) -> None:
    service = read(SYSTEMD / f"kivou-ingest-{source}.service")
    timer = read(SYSTEMD / f"kivou-ingest-{source}.timer")

    assert_unit_contract(
        service,
        {
            ("Service", "Type"): "oneshot",
            ("Service", "User"): "kivou",
            ("Service", "Group"): "kivou",
            ("Service", "WorkingDirectory"): "/srv/kivou/app",
            ("Service", "EnvironmentFile"): "/etc/kivou/staging.env",
            ("Service", "RuntimeDirectory"): "kivou",
            ("Service", "RuntimeDirectoryMode"): "0700",
            ("Service", "RuntimeDirectoryPreserve"): "yes",
            ("Service", "ExecStart"): (
                "/usr/bin/flock --verbose --exclusive --timeout 300 "
                "--conflict-exit-code 0 /run/kivou/ingestion.lock "
                "/srv/kivou/app/.venv/bin/python -m signals.ingestion run "
                f"--source {source}"
            ),
            ("Service", "TimeoutStartSec"): "30min",
            ("Service", "StandardOutput"): "journal",
            ("Service", "StandardError"): "journal",
            ("Service", "SyslogIdentifier"): f"kivou-ingest-{source}",
            ("Service", "NoNewPrivileges"): "true",
            ("Service", "PrivateTmp"): "true",
            ("Service", "ProtectSystem"): "strict",
            ("Service", "ProtectHome"): "true",
            ("Service", "ReadWritePaths"): "/run/kivou",
        },
    )
    assert_unit_contract(
        timer,
        {
            ("Timer", "OnCalendar"): schedule,
            ("Timer", "Persistent"): "true",
            ("Timer", "RandomizedDelaySec"): "60",
            ("Timer", "Unit"): f"kivou-ingest-{source}.service",
            ("Install", "WantedBy"): "timers.target",
        },
    )


def test_production_services_are_isolated_from_staging_and_acquisition() -> None:
    for path in PRODUCTION_SERVICES:
        body = read(path)
        parsed = parse_active_directives(body)
        active = "\n".join(
            f"{key}={value}"
            for directives in parsed.values()
            for key, values in directives.items()
            for value in values
        ).lower()
        for forbidden in ("staging", "apollo", "acquisition"):
            assert forbidden not in active

        environment = "/etc/kivou/production.env"
        if path.name == "kivou-backup.service":
            environment = "/etc/kivou/swiss-backup.env"
        assert_unit_contract(
            body,
            {
                ("Service", "EnvironmentFile"): environment,
                ("Service", "InaccessiblePaths"): "/srv/kivou/.ssh",
                ("Service", "ReadOnlyPaths"): "/srv/kivou/releases /srv/kivou/app",
                ("Service", "NoNewPrivileges"): "true",
                ("Service", "PrivateTmp"): "true",
                ("Service", "PrivateDevices"): "true",
                ("Service", "ProtectSystem"): "strict",
                ("Service", "ProtectHome"): "true",
                ("Service", "ProtectKernelTunables"): "true",
                ("Service", "ProtectKernelModules"): "true",
                ("Service", "ProtectControlGroups"): "true",
                ("Service", "RestrictSUIDSGID"): "true",
                ("Service", "LockPersonality"): "true",
                ("Service", "RestrictAddressFamilies"): "AF_UNIX AF_INET AF_INET6",
            },
        )


def test_production_directory_contains_no_acquisition_unit() -> None:
    assert not list(PRODUCTION.glob("*acquisition*"))


@pytest.mark.parametrize(
    "path",
    (
        SYSTEMD / "kivou-ingest-simap.service",
        SYSTEMD / "kivou-ingest-boamp.service",
        PRODUCTION / "kivou-ingest@.service",
    ),
)
def test_shared_ingestion_runtime_directory_survives_each_oneshot(path: pathlib.Path) -> None:
    assert_unit_contract(
        read(path),
        {
            ("Service", "RuntimeDirectory"): "kivou",
            ("Service", "RuntimeDirectoryPreserve"): "yes",
        },
    )
    command = parse_active_directives(read(path))["Service"]["ExecStart"][0]
    assert "/run/kivou/ingestion.lock" in command


@pytest.mark.parametrize(
    "path",
    (
        PRODUCTION / "kivou-alerts.service",
        PRODUCTION / "kivou-ingest@.service",
    ),
)
def test_production_jobs_are_ordered_after_postgres(path: pathlib.Path) -> None:
    assert_unit_contract(
        read(path),
        {("Unit", "After"): "network-online.target postgresql.service"},
    )


def test_production_backup_timeouts_bound_local_dump_and_offsite_upload() -> None:
    assert_unit_contract(
        read(PRODUCTION / "kivou-backup-local.service"),
        {("Service", "TimeoutStartSec"): "2h"},
    )
    assert_unit_contract(
        read(PRODUCTION / "kivou-backup.service"),
        {("Service", "TimeoutStartSec"): "6h"},
    )


def test_production_api_has_no_runtime_write_allowlist() -> None:
    parsed = parse_active_directives(read(PRODUCTION / "kivou-api.service"))

    assert "ReadWritePaths" not in parsed["Service"]


def test_production_api_runs_only_behind_the_local_proxy() -> None:
    body = read(PRODUCTION / "kivou-api.service")

    assert_unit_contract(
        body,
        {
            ("Unit", "After"): "network-online.target postgresql.service",
            ("Unit", "Wants"): "network-online.target",
            ("Service", "Type"): "exec",
            ("Service", "User"): "kivou",
            ("Service", "Group"): "kivou",
            ("Service", "WorkingDirectory"): "/srv/kivou/app",
            ("Service", "EnvironmentFile"): "/etc/kivou/production.env",
            ("Service", "ExecStart"): (
                "/srv/kivou/app/.venv/bin/uvicorn signals.api.asgi:app "
                "--host 127.0.0.1 --port 8000 --workers 2 --proxy-headers "
                "--forwarded-allow-ips 127.0.0.1 --no-server-header --no-access-log "
                "--timeout-keep-alive 20"
            ),
            ("Service", "Restart"): "on-failure",
            ("Service", "RestartSec"): "5s",
            ("Service", "StandardOutput"): "journal",
            ("Service", "StandardError"): "journal",
            ("Service", "NoNewPrivileges"): "true",
            ("Service", "ProtectSystem"): "strict",
            ("Service", "MemoryDenyWriteExecute"): "true",
            ("Service", "RestrictNamespaces"): "true",
            ("Install", "WantedBy"): "multi-user.target",
        },
    )


def test_production_ingestion_template_uses_one_shared_lock() -> None:
    body = read(PRODUCTION / "kivou-ingest@.service")

    assert_unit_contract(
        body,
        {
            ("Unit", "After"): "network-online.target postgresql.service",
            ("Service", "Type"): "oneshot",
            ("Service", "User"): "kivou",
            ("Service", "Group"): "kivou",
            ("Service", "WorkingDirectory"): "/srv/kivou/app",
            ("Service", "EnvironmentFile"): "/etc/kivou/production.env",
            ("Service", "RuntimeDirectory"): "kivou",
            ("Service", "RuntimeDirectoryMode"): "0700",
            ("Service", "RuntimeDirectoryPreserve"): "yes",
            ("Service", "ExecStart"): (
                "/usr/bin/flock --verbose --exclusive --timeout 300 "
                "--conflict-exit-code 0 /run/kivou/ingestion.lock "
                "/srv/kivou/app/.venv/bin/python -m signals.ingestion run --source %i"
            ),
            ("Service", "TimeoutStartSec"): "30min",
            ("Service", "TimeoutStopSec"): "90s",
            ("Service", "UMask"): "0077",
            ("Service", "NoNewPrivileges"): "true",
            ("Service", "PrivateTmp"): "true",
            ("Service", "PrivateDevices"): "true",
            ("Service", "ProtectSystem"): "strict",
            ("Service", "ProtectHome"): "true",
            ("Service", "ProtectKernelTunables"): "true",
            ("Service", "ProtectKernelModules"): "true",
            ("Service", "ProtectControlGroups"): "true",
            ("Service", "RestrictSUIDSGID"): "true",
            ("Service", "LockPersonality"): "true",
            ("Service", "RestrictAddressFamilies"): "AF_UNIX AF_INET AF_INET6",
            ("Service", "ReadWritePaths"): "/run/kivou",
        },
    )


@pytest.mark.parametrize(("source", "schedule"), PRODUCTION_TIMERS.items())
def test_production_ingestion_timers_are_exact(source: str, schedule: str) -> None:
    body = read(PRODUCTION / f"kivou-ingest-{source}.timer")

    assert_unit_contract(
        body,
        {
            ("Timer", "OnCalendar"): schedule,
            ("Timer", "Persistent"): "true",
            ("Timer", "RandomizedDelaySec"): "60",
            ("Timer", "AccuracySec"): "60",
            ("Timer", "Unit"): f"kivou-ingest@{source}.service",
            ("Install", "WantedBy"): "timers.target",
        },
    )


def test_production_alerts_have_a_bounded_non_overlapping_hourly_cycle() -> None:
    service = read(PRODUCTION / "kivou-alerts.service")
    timer = read(PRODUCTION / "kivou-alerts.timer")

    assert_unit_contract(
        service,
        {
            ("Unit", "After"): "network-online.target postgresql.service",
            ("Unit", "Wants"): "network-online.target",
            ("Service", "Type"): "oneshot",
            ("Service", "User"): "kivou",
            ("Service", "Group"): "kivou",
            ("Service", "WorkingDirectory"): "/srv/kivou/app",
            ("Service", "EnvironmentFile"): "/etc/kivou/production.env",
            ("Service", "ExecStart"): (
                "/usr/bin/flock --verbose --nonblock --conflict-exit-code 0 "
                "/srv/kivou/run/alerts.lock /srv/kivou/app/.venv/bin/python "
                "-m signals.alerts"
            ),
            ("Service", "TimeoutStartSec"): "20min",
            ("Service", "StandardOutput"): "journal",
            ("Service", "StandardError"): "journal",
            ("Service", "UMask"): "0077",
            ("Service", "PrivateDevices"): "true",
            ("Service", "ProtectKernelTunables"): "true",
            ("Service", "ProtectKernelModules"): "true",
            ("Service", "ProtectControlGroups"): "true",
            ("Service", "RestrictSUIDSGID"): "true",
            ("Service", "LockPersonality"): "true",
            ("Service", "RestrictAddressFamilies"): "AF_UNIX AF_INET AF_INET6",
            ("Service", "ReadWritePaths"): "/srv/kivou/run",
        },
    )
    assert_unit_contract(
        timer,
        {
            ("Timer", "OnCalendar"): "hourly",
            ("Timer", "Persistent"): "true",
            ("Timer", "RandomizedDelaySec"): "300",
            ("Timer", "AccuracySec"): "60",
            ("Timer", "Unit"): "kivou-alerts.service",
            ("Install", "WantedBy"): "timers.target",
        },
    )


def test_production_backup_runs_local_then_offsite_with_separated_secrets() -> None:
    local = read(PRODUCTION / "kivou-backup-local.service")
    offsite = read(PRODUCTION / "kivou-backup.service")
    timer = read(PRODUCTION / "kivou-backup.timer")

    assert_unit_contract(
        local,
        {
            ("Unit", "After"): "network-online.target postgresql.service",
            ("Service", "Type"): "oneshot",
            ("Service", "User"): "kivou",
            ("Service", "Group"): "kivou",
            ("Service", "EnvironmentFile"): "/etc/kivou/production.env",
            ("Service", "ExecStart"): "/srv/kivou/app/ops/bin/kivou-backup.sh",
            ("Service", "TimeoutStartSec"): "2h",
            ("Service", "StandardOutput"): "journal",
            ("Service", "StandardError"): "journal",
            ("Service", "ReadWritePaths"): "/srv/kivou/backups",
        },
    )
    assert_unit_contract(
        offsite,
        {
            ("Unit", "Requires"): "kivou-backup-local.service",
            ("Unit", "After"): "network-online.target kivou-backup-local.service",
            ("Service", "Type"): "oneshot",
            ("Service", "User"): "kivou",
            ("Service", "Group"): "kivou",
            ("Service", "EnvironmentFile"): "/etc/kivou/swiss-backup.env",
            ("Service", "Environment"): "RESTIC_CACHE_DIR=/var/cache/kivou-restic",
            ("Service", "CacheDirectory"): "kivou-restic",
            ("Service", "CacheDirectoryMode"): "0700",
            ("Service", "ExecStart"): (
                "/srv/kivou/app/ops/bin/kivou-restic-upload.sh"
            ),
            ("Service", "TimeoutStartSec"): "6h",
            ("Service", "StandardOutput"): "journal",
            ("Service", "StandardError"): "journal",
            ("Service", "ProtectSystem"): "strict",
            ("Service", "ReadWritePaths"): "/srv/kivou/backups",
        },
    )
    assert "/etc/kivou/swiss-backup.env" not in local
    assert "/etc/kivou/production.env" not in offsite
    assert_unit_contract(
        timer,
        {
            ("Timer", "OnCalendar"): "*-*-* 03:17:00",
            ("Timer", "Persistent"): "true",
            ("Timer", "RandomizedDelaySec"): "600",
            ("Timer", "Unit"): "kivou-backup.service",
            ("Install", "WantedBy"): "timers.target",
        },
    )


def test_production_nginx_preserves_the_exact_staging_route_contract() -> None:
    staging = nginx_active_directives(read(NGINX / "kivou-staging.conf"))
    expected = tuple(
        directive.replace("STAGING_HOST", "PRODUCTION_HOST")
        .replace(
            "/etc/nginx/kivou-security-headers.conf",
            "/etc/nginx/kivou-production-security-headers.conf",
        )
        .replace(
            "/etc/nginx/kivou-sensitive-link-security-headers.conf",
            "/etc/nginx/kivou-production-sensitive-link-security-headers.conf",
        )
        for directive in staging
    )

    assert nginx_active_directives(read(PRODUCTION_NGINX)) == expected


def test_pre_hsts_production_nginx_does_not_claim_hsts_is_active() -> None:
    for path in (
        PRODUCTION_NGINX,
        PRODUCTION_WWW_NGINX,
        PRODUCTION_DEFAULT_DENY_NGINX,
        PRODUCTION_SECURITY_HEADERS,
        PRODUCTION_SENSITIVE_SECURITY_HEADERS,
    ):
        body = read(path)

        assert "hsts" not in body.lower(), path
        assert not any(
            "Strict-Transport-Security" in directive
            for directive in nginx_active_directives(body)
        ), path


@pytest.mark.parametrize(
    ("staging_path", "production_path"),
    (
        (NGINX / "kivou-security-headers.conf", PRODUCTION_SECURITY_HEADERS),
        (
            NGINX / "kivou-sensitive-link-security-headers.conf",
            PRODUCTION_SENSITIVE_SECURITY_HEADERS,
        ),
    ),
)
def test_production_headers_remove_only_staging_hsts(
    staging_path: pathlib.Path,
    production_path: pathlib.Path,
) -> None:
    hsts = (
        'add_header Strict-Transport-Security "max-age=31536000; '
        'includeSubDomains" always;'
    )
    staging = nginx_active_directives(read(staging_path))
    production_body = read(production_path)

    assert nginx_active_directives(production_body) == tuple(
        directive for directive in staging if directive != hsts
    )
    assert "strict-transport-security" not in production_body.lower()
    assert "hsts" not in production_body.lower()


@pytest.mark.parametrize(
    "path",
    (PRODUCTION_SECURITY_HEADERS, PRODUCTION_SENSITIVE_SECURITY_HEADERS),
)
def test_production_header_install_comments_use_production_paths(
    path: pathlib.Path,
) -> None:
    install_commands = tuple(
        line.strip()
        for line in read(path).splitlines()
        if line.strip().startswith("#   sudo cp ")
    )

    assert install_commands == (
        f"#   sudo cp ops/nginx/{path.name} /etc/nginx/{path.name}",
    )


@pytest.mark.parametrize(
    ("path", "referrer_policy"),
    (
        (PRODUCTION_SECURITY_HEADERS, "strict-origin-when-cross-origin"),
        (PRODUCTION_SENSITIVE_SECURITY_HEADERS, "no-referrer"),
    ),
)
def test_production_security_headers_keep_the_full_policy_without_hsts(
    path: pathlib.Path,
    referrer_policy: str,
) -> None:
    directives = nginx_active_directives(read(path))
    csp = tuple(
        directive
        for directive in directives
        if directive.startswith("add_header Content-Security-Policy ")
    )

    expected_csp = (
        'add_header Content-Security-Policy "default-src \'self\'; '
        "script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self' "
        "https://checkout.stripe.com https://billing.stripe.com; "
        'object-src \'none\'" always;'
    )
    assert csp == (expected_csp,)
    assert "unsafe-eval" not in "\n".join(directives)
    for expected in (
        'add_header X-Content-Type-Options "nosniff" always;',
        'add_header X-Frame-Options "DENY" always;',
        f'add_header Referrer-Policy "{referrer_policy}" always;',
        (
            'add_header Permissions-Policy "camera=(), microphone=(), '
            'geolocation=(), payment=()" always;'
        ),
    ):
        assert directives.count(expected) == 1


def test_production_sites_use_only_canonical_host_placeholders() -> None:
    production_sites = (
        PRODUCTION_NGINX,
        PRODUCTION_WWW_NGINX,
        PRODUCTION_DEFAULT_DENY_NGINX,
    )
    for path in production_sites:
        body = read(path)
        for forbidden in ("staging.kivou.eu", "chatgpt.site", "STAGING_HOST"):
            assert forbidden not in body

    canonical_servers = nginx_server_blocks(read(PRODUCTION_NGINX))
    assert len(canonical_servers) == 2
    for server in canonical_servers:
        assert server.count("server_name PRODUCTION_HOST;") == 1
    assert nginx_active_directives(read(PRODUCTION_NGINX)).count(
        "server_name PRODUCTION_HOST;"
    ) == 2


def test_production_www_redirects_http_and_https_to_the_canonical_host() -> None:
    body = read(PRODUCTION_WWW_NGINX)

    assert_production_www_contract(body)
    assert "proxy_pass" not in body



def test_production_www_contract_rejects_a_redirect_nested_under_acme() -> None:
    body = read(PRODUCTION_WWW_NGINX)
    separate_locations = """    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://PRODUCTION_HOST$request_uri;
    }"""
    redirect_nested_under_acme = """    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
        return 301 https://PRODUCTION_HOST$request_uri;
    }"""
    mutated = body.replace(
        separate_locations,
        redirect_nested_under_acme,
        1,
    )

    assert mutated != body
    with pytest.raises(AssertionError):
        assert_production_www_contract(mutated)


def test_production_www_certificate_sans_must_be_verified_before_activation() -> None:
    body = read(PRODUCTION_WWW_NGINX)

    assert "avant toute activation" in body.lower()
    assert "couvre exactement PRODUCTION_HOST et PRODUCTION_WWW_HOST" in body
    assert "openssl x509" in body
    assert "subjectAltName" in body


def test_production_default_site_rejects_unknown_http_and_tls_hosts() -> None:
    assert nginx_active_directives(read(PRODUCTION_DEFAULT_DENY_NGINX)) == (
        "server {",
        "listen 80 default_server;",
        "listen [::]:80 default_server;",
        "server_name _;",
        SAFE_PRODUCTION_PATH_SET,
        SAFE_PRODUCTION_ACCESS_LOG,
        "return 444;",
        "}",
        "server {",
        "listen 443 ssl default_server;",
        "listen [::]:443 ssl default_server;",
        "server_name _;",
        SAFE_PRODUCTION_PATH_SET,
        SAFE_PRODUCTION_ACCESS_LOG,
        "ssl_reject_handshake on;",
        "}",
    )


def test_release_one_runbook_is_explicitly_non_executing_and_fail_closed() -> None:
    body = read(PRODUCTION_RUNBOOK)
    commands = "\n".join(runbook_shell_blocks(body))

    assert "Release 1" in body
    assert "documentation uniquement" in body.lower()
    assert "ne pas exécuter" in body.lower()
    for excluded in ("DNS", "Stripe", "SMTP", "provider", "Acquisition"):
        assert excluded.lower() in body.lower()
    assert "aucune release" in body.lower()
    assert "aucune sauvegarde n'est supprimée manuellement" in body.lower()
    assert "rétention" in body.lower()
    assert "source /etc/kivou/" not in commands
    assert ". /etc/kivou/" not in commands
    assert "8001" not in commands
    assert "certbot --nginx" not in commands
    assert not re.search(r"systemctl\s+enable(?:\s+--now)?\s+\S*acquisition", commands)
    assert not re.search(r"rm\s+[^\n]*(?:/srv/kivou/releases|/srv/kivou/backups)", commands)


def test_every_release_one_shell_block_is_strict_and_syntax_valid() -> None:
    blocks = runbook_shell_blocks(read(PRODUCTION_RUNBOOK))

    assert len(blocks) >= 10
    for index, block in enumerate(blocks, start=1):
        assert block.startswith("set -euo pipefail\n"), index
        result = subprocess.run(
            ["bash", "-n"],
            input=block,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"block {index}: {result.stderr}"


def test_runbook_fetches_only_the_reviewed_remote_main_commit() -> None:
    body = read(PRODUCTION_RUNBOOK)

    assert "^[0-9a-f]{40}$" in body
    assert "kivou:kivou:600" in body
    assert "root:root:644" in body
    assert "StrictHostKeyChecking=yes" in body
    assert "GIT_CONFIG_GLOBAL=/dev/null" in body
    assert "GIT_CONFIG_NOSYSTEM=1" in body
    assert_fragments_in_order(
        body,
        "git ls-remote --exit-code",
        'test "$KIVOU_REMOTE_MAIN_SHA" = "$KIVOU_RELEASE_SHA"',
        "fetch --no-tags origin",
        'checkout --detach "$KIVOU_RELEASE_SHA"',
        'rev-parse HEAD)" = "$KIVOU_RELEASE_SHA"',
        "status --porcelain",
    )


def test_runbook_builds_locked_separate_immutable_releases() -> None:
    body = read(PRODUCTION_RUNBOOK)

    assert "backend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT" in body
    assert "frontend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT" in body
    assert_fragments_in_order(
        body,
        "uv sync --frozen --extra server --extra postgres",
        "uv run pytest",
        "uv run ruff check .",
        "npm ci",
        "npm run test -- --run",
        "npm run build",
        "npm run typecheck",
        "npm run lint",
        "frontend/dist/index.html",
        "chown -R root:root",
        "chmod -R a-w",
    )
    assert (
        'find "$KIVOU_BACKEND_RELEASE_DIR" \\( -type f -o -type d \\) -perm /222'
        in body
    )
    assert (
        'find "$KIVOU_FRONTEND_RELEASE_DIR" \\( -type f -o -type d \\) -perm /222'
        in body
    )


def test_runbook_inspects_root_owned_release_with_isolated_root_git() -> None:
    body = read(PRODUCTION_RUNBOOK)
    after_root_ownership = body.split(
        'sudo chown -R root:root "$KIVOU_BACKEND_RELEASE_DIR"', maxsplit=1
    )[1]

    assert "GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1" in after_root_ownership
    assert "GIT_OPTIONAL_LOCKS=0" in after_root_ownership
    assert after_root_ownership.count("kivou_release_git") >= 3
    assert (
        'sudo -u kivou /usr/bin/git -C "$KIVOU_BACKEND_RELEASE_DIR"'
        not in after_root_ownership
    )


def test_every_immutability_guard_allows_real_release_and_capture_symlinks(
    tmp_path: pathlib.Path,
) -> None:
    body = read(PRODUCTION_RUNBOOK)
    commands = runbook_immutability_find_commands(body)
    artifacts = prepare_immutable_symlink_artifacts(tmp_path)

    assert len(commands) == 12
    assert all(
        r"\( -type f -o -type d \) -perm /222" in command
        for command in commands
    )
    for command in commands:
        result = run_immutability_find_command(
            command,
            backend=artifacts["backend"],
            frontend=artifacts["frontend"],
            unit_capture=artifacts["unit_capture"],
            rollback=artifacts["rollback"],
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout == "", f"{command} rejected {result.stdout.strip()}"


@pytest.mark.parametrize(
    ("command_variable", "writable_artifact"),
    (
        ("KIVOU_PREVIOUS_APP_TARGET", "backend"),
        ("KIVOU_PREVIOUS_FRONTEND_TARGET", "frontend"),
        ("KIVOU_ROLLBACK_DIR/nginx", "nginx"),
    ),
)
def test_immutability_guards_still_reject_writable_real_files_or_directories(
    tmp_path: pathlib.Path,
    command_variable: str,
    writable_artifact: str,
) -> None:
    commands = runbook_immutability_find_commands(read(PRODUCTION_RUNBOOK))
    artifacts = prepare_immutable_symlink_artifacts(tmp_path)
    writable_paths = {
        "backend": artifacts["backend"] / ".venv/lib",
        "frontend": artifacts["frontend"] / "node_modules/vite/bin/vite.js",
        "nginx": artifacts["nginx_absent"],
    }
    writable_path = writable_paths[writable_artifact]
    writable_path.chmod(0o755 if writable_path.is_dir() else 0o644)
    matching_commands = tuple(
        command for command in commands if command_variable in command
    )

    assert matching_commands
    for command in matching_commands:
        result = run_immutability_find_command(
            command,
            backend=artifacts["backend"],
            frontend=artifacts["frontend"],
            unit_capture=artifacts["unit_capture"],
            rollback=artifacts["rollback"],
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(writable_path)


def test_runbook_validates_secrets_and_units_before_atomic_install() -> None:
    body = read(PRODUCTION_RUNBOOK)

    for path in ("/etc/kivou/production.env", "/etc/kivou/swiss-backup.env"):
        assert path in body
    assert "root:root:600" in body
    assert_fragments_in_order(
        body,
        "systemd-analyze verify",
        "KIVOU_UNIT_STAGE_DIR",
        "KIVOU_UNIT_CAPTURE_DIR",
        "systemctl is-enabled",
        "systemctl is-active",
        "KIVOU_MUTATION_WINDOW_BEGIN",
        "systemctl disable --now",
        "chown root:root",
        "chmod 644",
        "mv -Tf",
        "systemctl daemon-reload",
    )
    before_mutation = body[: body.index("KIVOU_MUTATION_WINDOW_BEGIN")]
    assert "systemctl disable" not in "\n".join(runbook_shell_blocks(before_mutation))
    assert "systemctl stop" not in "\n".join(runbook_shell_blocks(before_mutation))
    assert not re.search(
        r"(?:install|mv)\s+[^\n]*/etc/systemd/system", before_mutation
    )


def test_runbook_exercises_local_offsite_and_real_restore_without_side_effects() -> None:
    body = read(PRODUCTION_RUNBOOK)

    assert_fragments_in_order(
        body,
        "systemd-run --wait --pipe --collect --unit=kivou-backup-local-preflight",
        "pg_restore --list",
        "systemd-run --wait --pipe --collect --unit=kivou-backup-offsite-preflight",
        "trap kivou_restore_cleanup EXIT",
        "restic restore latest",
        "chown -R postgres:postgres",
        "createdb",
        "pg_restore --exit-on-error",
        "SELECT version_num FROM alembic_version",
    )
    assert "dropdb" in body
    restore = body[body.index("## 6. Prévalider la sauvegarde"):body.index("## 7.")]
    assert "--host kivou-production-01" in restore
    assert "--tag kivou-postgresql" in restore
    assert "KIVOU_RESTORE_DB" in restore
    assert "provider" not in "\n".join(runbook_shell_blocks(restore)).lower()


def test_runbook_proves_certificate_and_nginx_candidate_before_publication() -> None:
    body = read(PRODUCTION_RUNBOOK)

    assert "KIVOU_PRODUCTION_HOST=kivou.eu" in body
    assert "KIVOU_PRODUCTION_WWW_HOST=www.kivou.eu" in body
    assert "KIVOU_API_PORT=8000" in body
    assert "openssl x509" in body
    assert "-ext subjectAltName" in body
    assert "PRODUCTION_HOST|PRODUCTION_WWW_HOST|KIVOU_API_PORT" in body
    assert "kivou-production-default-deny.conf" in body
    assert_fragments_in_order(
        body,
        'readlink -f "$KIVOU_SITE_LINK"',
        "openssl x509",
        "kivou-production-default-deny.conf",
        'nginx -t -c "$KIVOU_NGINX_CANDIDATE/nginx.conf"',
        'mv -Tf "$KIVOU_APP_LINK_NEW" /srv/kivou/app',
    )


def test_runbook_switches_both_releases_then_publishes_nginx() -> None:
    body = read(PRODUCTION_RUNBOOK)

    assert "readlink -f /srv/kivou/app" in body
    assert "readlink -f /srv/kivou/frontend" in body
    assert "ABSENT" in body
    assert_fragments_in_order(
        body,
        'ln -s "$KIVOU_BACKEND_RELEASE_DIR"',
        'mv -Tf "$KIVOU_APP_LINK_NEW" /srv/kivou/app',
        'ln -s "$KIVOU_FRONTEND_RELEASE_DIR"',
        'mv -Tf "$KIVOU_FRONTEND_LINK_NEW" /srv/kivou/frontend',
        "systemctl enable --now kivou-api.service",
        "kivou-api-readiness.sh kivou-api.service 8000",
        "sites-enabled",
        "nginx -t",
        "systemctl reload nginx",
        "KIVOU_HTTPS_HEALTH_URL=https://kivou.eu/",
    )


def test_all_fallible_prevalidations_and_captures_precede_the_mutation_window() -> None:
    body = read(PRODUCTION_RUNBOOK)
    first_mutation = min(
        body.index('mv -Tf "$KIVOU_APP_LINK_NEW" /srv/kivou/app'),
        body.index('mv -Tf "$KIVOU_FRONTEND_LINK_NEW" /srv/kivou/frontend'),
        body.index("systemctl enable --now kivou-api.service"),
    )

    for required_prevalidation in (
        "pg_restore --list",
        "restic restore latest",
        "pg_restore --exit-on-error",
        "SELECT version_num FROM alembic_version",
        "openssl x509",
        'nginx -t -c "$KIVOU_NGINX_CANDIDATE/nginx.conf"',
        "KIVOU_NGINX_STAGE_DIR",
        "KIVOU_NGINX_CAPTURE_PATHS=(",
        'readlink -f "$KIVOU_SITE_LINK"',
        "KIVOU_UNIT_CAPTURE_DIR",
        "KIVOU_NGINX_WAS_ENABLED",
        "KIVOU_NGINX_WAS_ACTIVE",
        'chmod -R a-w "$KIVOU_UNIT_CAPTURE_DIR" "$KIVOU_ROLLBACK_DIR/nginx"',
    ):
        assert body.index(required_prevalidation) < first_mutation, required_prevalidation

    first_runtime_mutation = body.index("KIVOU_FIRST_RUNTIME_MUTATION=1")
    assert first_runtime_mutation < first_mutation
    for long_preflight in (
        "systemd-analyze verify",
        "systemd-run --wait --pipe --collect --unit=kivou-backup-local-preflight",
        "systemd-run --wait --pipe --collect --unit=kivou-backup-offsite-preflight",
        "restic restore latest",
        "openssl x509",
        'nginx -t -c "$KIVOU_NGINX_CANDIDATE/nginx.conf"',
        "KIVOU_NGINX_CAPTURE_COMPLETE=1",
    ):
        assert body.index(long_preflight) < first_runtime_mutation
    first_rollout_lock = body.index("flock --exclusive 9")
    manual_recovery = body.index("## 11. Rollback immédiat autonome")
    assert body[:manual_recovery].count('exec 9<>"$KIVOU_ROLLOUT_LOCK"') == 1
    assert body[manual_recovery:].count('exec 9<>"$KIVOU_ROLLOUT_LOCK"') == 1
    assert first_rollout_lock < body.index("KIVOU_UNIT_CAPTURE_DIR")
    assert first_rollout_lock < body.index("restic restore latest")


def test_all_previous_targets_and_nginx_state_are_captured_before_switches() -> None:
    body = read(PRODUCTION_RUNBOOK)

    first_mutation = body.index("KIVOU_FIRST_RUNTIME_MUTATION=1")
    for capture in (
        "KIVOU_UNIT_CAPTURE_DIR",
        "systemctl is-enabled",
        "systemctl is-active",
        "readlink -f /srv/kivou/app",
        "readlink -f /srv/kivou/frontend",
        "KIVOU_NGINX_CAPTURE_PATHS=(",
        'readlink -f "$KIVOU_SITE_LINK"',
        "/etc/nginx/sites-enabled/default",
        "KIVOU_UNKNOWN_ENABLED_SITE",
    ):
        assert body.index(capture) < first_mutation, capture
    assert first_mutation < body.index('mv -Tf "$KIVOU_APP_LINK_NEW" /srv/kivou/app')
    assert first_mutation < body.index(
        'mv -Tf "$KIVOU_FRONTEND_LINK_NEW" /srv/kivou/frontend'
    )


def test_backup_preflight_uses_the_exact_candidate_before_any_switch() -> None:
    body = read(PRODUCTION_RUNBOOK)
    first_switch = body.index('mv -Tf "$KIVOU_APP_LINK_NEW" /srv/kivou/app')
    before_switch = body[:first_switch]

    assert "systemctl start kivou-backup.service" not in before_switch
    assert "/srv/kivou/app/ops/bin/kivou-backup.sh" not in before_switch
    assert "/srv/kivou/app/ops/bin/kivou-restic-upload.sh" not in before_switch

    local_start = before_switch.index(
        "systemd-run --wait --pipe --collect --unit=kivou-backup-local-preflight"
    )
    offsite_start = before_switch.index(
        "systemd-run --wait --pipe --collect --unit=kivou-backup-offsite-preflight"
    )
    restore_start = before_switch.index(
        "systemd-run --wait --collect --unit=kivou-restore-drill"
    )
    assert local_start < offsite_start < restore_start

    local = before_switch[local_start:offsite_start]
    offsite = before_switch[offsite_start:restore_start]
    assert "/etc/kivou/production.env" in local
    assert "/etc/kivou/swiss-backup.env" not in local
    assert '"$KIVOU_BACKEND_RELEASE_DIR/ops/bin/kivou-backup.sh"' in local
    assert "/etc/kivou/swiss-backup.env" in offsite
    assert "/etc/kivou/production.env" not in offsite
    assert '"$KIVOU_BACKEND_RELEASE_DIR/ops/bin/kivou-restic-upload.sh"' in offsite
    assert "CacheDirectory=kivou-restic" in offsite
    assert "RESTIC_CACHE_DIR=/var/cache/kivou-restic" in offsite
    for transient in (local, offsite):
        for hardening in (
            "--property=User=kivou",
            "--property=Group=kivou",
            "--property=NoNewPrivileges=yes",
            "--property=PrivateTmp=yes",
            "--property=PrivateDevices=yes",
            "--property=ProtectSystem=strict",
            'ReadOnlyPaths="$KIVOU_BACKEND_RELEASE_DIR"',
            "--property=ReadWritePaths=/srv/kivou/backups",
        ):
            assert hardening in transient


def test_real_backup_smoke_occurs_only_after_switch_and_before_timer() -> None:
    body = read(PRODUCTION_RUNBOOK)

    assert_fragments_in_order(
        body,
        "KIVOU_PREVIOUS_APP_TARGET=ABSENT",
        'mv -Tf "$KIVOU_APP_LINK_NEW" /srv/kivou/app',
        "systemctl start kivou-backup.service",
        "systemctl is-failed --quiet kivou-backup-local.service",
        "systemctl is-failed --quiet kivou-backup.service",
        "systemctl enable --now kivou-backup.timer",
    )
    assert_fragments_in_order(
        body,
        "KIVOU_PREVIOUS_APP_TARGET=ABSENT",
        'case "$KIVOU_PREVIOUS_APP_TARGET" in',
        "(ABSENT)",
        "KIVOU_FIRST_RUNTIME_MUTATION=1",
    )


def test_runbook_activates_only_proven_ingestion_and_smoked_job_timers() -> None:
    body = read(PRODUCTION_RUNBOOK)
    mutation = body[
        body.index("KIVOU_MUTATION_WINDOW_BEGIN") : body.index(
            "KIVOU_MUTATION_WINDOW_END"
        )
    ]
    grouped_timers = (
        "kivou-ingest-simap.timer",
        "kivou-ingest-boamp.timer",
        "kivou-ingest-decp.timer",
        "kivou-ingest-ted.timer",
    )
    group_position = mutation.rindex(
        "kivou-ingest-simap.timer kivou-ingest-boamp.timer"
    )
    for source in ("simap", "boamp", "decp", "ted"):
        assert_fragments_in_order(
            mutation,
            "systemctl disable --now",
            f"systemctl start kivou-ingest@{source}.service",
            f"systemctl is-failed --quiet kivou-ingest@{source}.service",
        )
        assert mutation.index(
            f"systemctl is-failed --quiet kivou-ingest@{source}.service"
        ) < group_position
        assert f"systemctl enable --now kivou-ingest-{source}.timer" not in body
    assert "systemctl enable --now" in mutation[group_position - 40 : group_position]
    grouped_command = mutation[group_position - 40 : group_position + 180]
    assert all(timer in grouped_command for timer in grouped_timers)
    assert_fragments_in_order(
        mutation,
        "systemctl start kivou-backup.service",
        "systemctl enable --now kivou-backup.timer",
    )
    assert "systemctl disable --now kivou-alerts.timer kivou-alerts.service" in body
    assert "systemctl start kivou-alerts.service" not in body
    assert "systemctl enable --now kivou-alerts.timer" not in body
    assert "autorisation SMTP séparée" in body


def test_runbook_rollback_uses_only_captured_targets_and_preserves_artifacts() -> None:
    body = read(PRODUCTION_RUNBOOK)
    rollback = body[body.index("## 11. Rollback immédiat") :]
    window = body[
        body.index("KIVOU_MUTATION_WINDOW_BEGIN") : body.index(
            "KIVOU_MUTATION_WINDOW_END"
        )
    ]

    assert_fragments_in_order(
        rollback,
        "flock --exclusive",
        "kivou_recovery_rollback",
    )
    assert_fragments_in_order(
        window,
        "systemctl disable --now",
        "KIVOU_PREVIOUS_APP_TARGET",
        "KIVOU_PREVIOUS_FRONTEND_TARGET",
        "mv -Tf",
        "KIVOU_UNIT_CAPTURE_DIR",
        "nginx -t",
        "systemctl reload nginx",
    )
    assert "ABSENT" in window
    assert "chmod -R a-w" in body
    assert not re.search(r"rm\s+[^\n]*(?:/srv/kivou/releases|/srv/kivou/backups)", rollback)


def test_rollback_restores_links_before_optional_nginx_capture() -> None:
    body = read(PRODUCTION_RUNBOOK)
    rollback = body[
        body.index("# KIVOU_ROLLBACK_ENGINE_BEGIN") : body.index(
            "# KIVOU_ROLLBACK_ENGINE_END"
        )
    ]

    assert_fragments_in_order(
        rollback,
        "kivou_rollback_stop_phase()",
        "systemctl disable --now",
        "kivou_rollback_app_phase()",
        'case "$KIVOU_PREVIOUS_APP_TARGET" in',
        "kivou_rollback_frontend_phase()",
        'case "$KIVOU_PREVIOUS_FRONTEND_TARGET" in',
        "kivou_rollback_units_phase()",
        "kivou_rollback_nginx_phase()",
        "KIVOU_NGINX_CAPTURE_VALID=0",
        'if [ "$KIVOU_NGINX_CAPTURE_VALID" = 1 ]; then',
        "kivou_publish_captured_nginx_bundle",
    )
    app_restore = rollback.index('case "$KIVOU_PREVIOUS_APP_TARGET" in')
    frontend_restore = rollback.index('case "$KIVOU_PREVIOUS_FRONTEND_TARGET" in')
    nginx_probe = rollback.index("KIVOU_NGINX_CAPTURE_VALID=0")
    assert app_restore < frontend_restore < nginx_probe
    assert 'sudo test -d "$KIVOU_ROLLBACK_DIR/nginx"' not in rollback[:nginx_probe]


def test_mutation_window_is_locked_and_trapped_before_every_runtime_mutation() -> None:
    body = read(PRODUCTION_RUNBOOK)
    begin = body.index("KIVOU_MUTATION_WINDOW_BEGIN")
    window = body[begin : body.index("KIVOU_MUTATION_WINDOW_END", begin)]

    first_mutation = window.index("KIVOU_FIRST_RUNTIME_MUTATION=1")
    assert_fragments_in_order(
        window[:first_mutation],
        "kivou_rollout_rollback()",
        "kivou_rollout_on_err()",
        "KIVOU_ROLLOUT_RC=$?",
        "kivou_arm_rollout_traps()",
        "trap 'kivou_rollout_on_err' ERR",
        "flock --exclusive",
        "kivou_arm_rollout_traps",
    )
    assert "exit \"$KIVOU_ROLLOUT_RC\"" in window
    mutation_commands = window[
        first_mutation : window.rindex("kivou_disarm_rollout_traps")
    ]
    assert not re.search(r"(?:^|[;\s])exit\s+[0-9]+", mutation_commands)
    assert "kivou_fail 70" in mutation_commands
    assert_fragments_in_order(
        window[first_mutation:],
        "systemctl disable --now",
        'mv -Tf "$KIVOU_UNIT_NEW" "$KIVOU_UNIT_PATH"',
        "systemctl daemon-reload",
        'mv -Tf "$KIVOU_APP_LINK_NEW" /srv/kivou/app',
        "systemctl enable --now kivou-api.service",
    )


def test_nginx_activation_and_rollback_restore_the_captured_service_state() -> None:
    body = read(PRODUCTION_RUNBOOK)
    mutation = body[
        body.index("KIVOU_FIRST_RUNTIME_MUTATION=1") : body.index(
            "KIVOU_MUTATION_WINDOW_END"
        )
    ]
    rollback = body[
        body.index("# KIVOU_ROLLBACK_ENGINE_BEGIN") : body.index(
            "# KIVOU_ROLLBACK_ENGINE_END"
        )
    ]

    assert_fragments_in_order(
        body,
        'KIVOU_NGINX_WAS_ENABLED=$(sudo systemctl is-enabled nginx.service',
        'KIVOU_NGINX_WAS_ACTIVE=$(sudo systemctl is-active nginx.service',
        "KIVOU_MUTATION_WINDOW_BEGIN",
    )
    assert_fragments_in_order(
        mutation,
        "nginx -t",
        'if [ "$KIVOU_NGINX_WAS_ACTIVE" = active ]; then',
        "systemctl reload nginx",
        "systemctl enable --now nginx",
        "systemctl is-active --quiet nginx",
    )
    assert "systemctl disable nginx" in rollback
    assert "systemctl stop nginx" in rollback


def test_nginx_staging_is_outside_included_paths_and_default_is_transactional() -> None:
    body = read(PRODUCTION_RUNBOOK)
    before_mutation = body[: body.index("KIVOU_MUTATION_WINDOW_BEGIN")]
    before_commands = "\n".join(runbook_shell_blocks(before_mutation))

    assert "ln -s" not in "\n".join(
        line for line in before_commands.splitlines() if "/sites-enabled/" in line
    )
    assert not re.search(r"/etc/nginx/sites-enabled/[^\s]+\.new", before_commands)
    assert "KIVOU_NGINX_STAGE_DIR" in before_mutation
    assert "/etc/nginx/sites-enabled/default" in before_mutation
    assert "KIVOU_UNKNOWN_ENABLED_SITE" in before_mutation
    assert "default_server" in before_mutation
    assert "KIVOU_EXPECTED_DEFAULT_SERVER_DIRECTIVES" in before_mutation

    mutation = body[body.index("KIVOU_MUTATION_WINDOW_BEGIN") :]
    assert_fragments_in_order(
        mutation,
        "systemctl disable --now",
        "/etc/nginx/sites-enabled/default",
        "mv -Tf",
        "nginx -t",
    )


def test_backup_retention_claim_matches_versioned_scripts_and_success_order() -> None:
    body = read(PRODUCTION_RUNBOOK)
    local = read(REPOSITORY / "ops/bin/kivou-backup.sh")
    offsite = read(REPOSITORY / "ops/bin/kivou-restic-upload.sh")

    assert "aucune release n'est supprimée manuellement" in body.lower()
    assert "aucune sauvegarde n'est supprimée manuellement" in body.lower()
    assert "14 jours" in body.lower()
    assert "30 quotidiennes, 12 mensuelles et 3 annuelles" in body.lower()
    assert_fragments_in_order(local, "pg_restore", 'mv -f "${PARTIAL}" "${TARGET}"', "-delete")
    assert_fragments_in_order(
        offsite,
        '"${RESTIC}" backup',
        '"${RESTIC}" forget',
        "--keep-daily 30",
        "--keep-monthly 12",
        "--keep-yearly 3",
    )


def test_ingestion_timers_are_grouped_after_all_smokes_and_rollback_disables_all() -> None:
    body = read(PRODUCTION_RUNBOOK)
    window = body[
        body.index("KIVOU_MUTATION_WINDOW_BEGIN") : body.index(
            "KIVOU_MUTATION_WINDOW_END"
        )
    ]
    grouped_timers = (
        "kivou-ingest-simap.timer",
        "kivou-ingest-boamp.timer",
        "kivou-ingest-decp.timer",
        "kivou-ingest-ted.timer",
    )

    group_position = window.rindex(
        "kivou-ingest-simap.timer kivou-ingest-boamp.timer"
    )
    for source in ("simap", "boamp", "decp", "ted"):
        assert window.index(f"systemctl start kivou-ingest@{source}.service") < group_position
        assert (
            window.index(f"systemctl is-failed --quiet kivou-ingest@{source}.service")
            < group_position
        )
    rollback_function = window[: window.index("kivou_rollout_on_err()")]
    for timer in ("simap", "boamp", "decp", "ted"):
        assert f"kivou-ingest-{timer}.timer" in rollback_function
    assert "systemctl start kivou-alerts.service" not in body
    assert "systemctl enable --now kivou-alerts.timer" not in body
    assert "systemctl enable --now" in window[group_position - 40 : group_position]
    grouped_command = window[group_position - 40 : group_position + 180]
    assert all(timer in grouped_command for timer in grouped_timers)


def test_nginx_rollback_reverts_disk_bundle_when_candidate_restore_is_invalid() -> None:
    body = read(PRODUCTION_RUNBOOK)
    rollback = body[
        body.index("KIVOU_MUTATION_WINDOW_BEGIN") : body.index(
            "KIVOU_MUTATION_WINDOW_END"
        )
    ]
    manual = body[body.index("## 11. Rollback immédiat") :]

    assert_fragments_in_order(
        rollback,
        "kivou_capture_current_nginx_bundle()",
        "KIVOU_NGINX_CURRENT_BUNDLE",
        "kivou_publish_captured_nginx_bundle()",
    )
    publish = rollback[
        rollback.index("kivou_publish_captured_nginx_bundle()") : rollback.index(
            "kivou_restore_unit_states()"
        )
    ]
    assert_fragments_in_order(
        publish,
        "kivou_capture_current_nginx_bundle",
        "if ! sudo nginx -t; then",
        "kivou_restore_current_nginx_bundle",
        "return 71",
    )
    failed_test = rollback.index("if ! sudo nginx -t; then")
    restore_current = rollback.index("kivou_restore_current_nginx_bundle", failed_test)
    first_reload = rollback.find("systemctl reload nginx", failed_test)
    assert first_reload == -1 or restore_current < first_reload
    app_restore = rollback.index('case "$KIVOU_PREVIOUS_APP_TARGET" in')
    nginx_capture_probe = rollback.index("KIVOU_NGINX_CAPTURE_VALID=0")
    assert app_restore < nginx_capture_probe
    assert_fragments_in_order(manual, "flock --exclusive", "kivou_recovery_rollback")


def rollback_engine(body: str) -> str:
    begin = body.index("# KIVOU_ROLLBACK_ENGINE_BEGIN")
    end = body.index("# KIVOU_ROLLBACK_ENGINE_END", begin)
    return body[begin:end]


def autonomous_recovery_source(body: str) -> str:
    begin_marker = "# KIVOU_AUTONOMOUS_RECOVERY_SOURCE_BEGIN"
    end_marker = "# KIVOU_AUTONOMOUS_RECOVERY_SOURCE_END"
    begin = body.index(begin_marker) + len(begin_marker)
    end = body.index(end_marker, begin)
    return body[begin:end]


def test_rollback_aggregates_strict_independent_phase_failures() -> None:
    engine = rollback_engine(read(PRODUCTION_RUNBOOK))

    for phase in ("stop", "app", "frontend", "units", "nginx"):
        assert f"kivou_rollback_{phase}_phase()" in engine
        assert f"set -Eeuo pipefail; kivou_rollback_{phase}_phase" in engine
    assert "KIVOU_ROLLBACK_RC=0" in engine
    assert "KIVOU_PHASE_RC=$?" in engine
    assert "return \"$KIVOU_ROLLBACK_RC\"" in engine
    assert "if ! kivou_" not in engine

    script = "\n".join(
        (
            "set -Eeuo pipefail",
            engine,
            "kivou_rollback_stop_phase() { false; true; printf 'masked-failure\\n'; }",
            "kivou_rollback_app_phase() { printf 'continued-app\\n'; }",
            "kivou_rollback_frontend_phase() { return 17; }",
            "kivou_rollback_units_phase() { printf 'continued-units\\n'; }",
            "kivou_rollback_nginx_phase() { :; }",
            "set +e",
            "kivou_rollout_rollback",
            "KIVOU_TEST_ROLLBACK_RC=$?",
            "set -e",
            "printf 'rollback_rc=%s\\n' \"$KIVOU_TEST_ROLLBACK_RC\"",
            "test \"$KIVOU_TEST_ROLLBACK_RC\" -ne 0",
        )
    )
    result = subprocess.run(
        ["bash"], input=script, text=True, capture_output=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert "rollback_rc=1" in result.stdout
    assert "continued-app" in result.stdout
    assert "continued-units" in result.stdout
    assert "masked-failure" not in result.stdout


def test_err_handler_always_exits_with_the_original_nonzero_status() -> None:
    engine = rollback_engine(read(PRODUCTION_RUNBOOK))
    script = f"""\
set -Eeuo pipefail
{engine}
kivou_rollback_stop_phase() {{ false; true; }}
kivou_rollback_app_phase() {{ :; }}
    kivou_rollback_frontend_phase() {{ :; }}
    kivou_rollback_units_phase() {{ :; }}
    kivou_rollback_nginx_phase() {{ :; }}
KIVOU_ROLLOUT_STATUS=/nonexistent
KIVOU_MUTATION_STARTED=1
KIVOU_COMMITTED=0
KIVOU_ROLLBACK_RUNNING=0
kivou_arm_rollout_traps
(exit 23)
printf 'handler-continued-success\n'
"""
    result = subprocess.run(
        ["bash"], input=script, text=True, capture_output=True, check=False
    )

    assert result.returncode == 23, result.stderr
    assert "handler-continued-success" not in result.stdout
    assert "rollback_failed=" in result.stderr


def test_alerts_are_inactive_before_the_first_runtime_mutation() -> None:
    body = read(PRODUCTION_RUNBOOK)
    gate = body[body.index("## 9. Dernier gate") : body.index("## 10.")]

    assert_fragments_in_order(
        gate,
        "systemctl is-enabled --quiet kivou-alerts.timer",
        "systemctl is-active --quiet kivou-alerts.timer",
        "systemctl is-active --quiet kivou-alerts.service",
    )
    assert "systemctl disable" not in gate
    assert "systemctl stop" not in gate
    assert body.index("systemctl is-active --quiet kivou-alerts.service") < body.index(
        "KIVOU_FIRST_RUNTIME_MUTATION=1"
    )


def test_nginx_candidate_counts_every_default_deny_listener() -> None:
    body = read(PRODUCTION_RUNBOOK)
    default_deny = read(PRODUCTION_DEFAULT_DENY_NGINX)
    expected = len(
        re.findall(r"^[^#\n]*listen\s+[^;]*default_server;", default_deny, re.MULTILINE)
    )

    assert expected == 4
    assert f"KIVOU_EXPECTED_DEFAULT_SERVER_DIRECTIVES={expected}" in body


def test_nginx_stop_gate_describes_all_four_http_https_ipv4_ipv6_listeners() -> None:
    body = read(PRODUCTION_RUNBOOK)

    assert (
        "les quatre directives `default_server` du default deny "
        "(HTTP et HTTPS, IPv4 et IPv6)"
    ) in body


def test_root_shell_gate_precedes_every_preflight_and_lock_open() -> None:
    body = read(PRODUCTION_RUNBOOK)
    first_block = runbook_shell_blocks(body)[0]

    assert "sudo -i" in body[: body.index("## 1.")]
    assert_fragments_in_order(
        first_block,
        "set -euo pipefail",
        'test "$(id -u)" -eq 0',
        "git ls-remote --exit-code",
    )
    assert body.index('test "$(id -u)" -eq 0') < body.index(
        'exec 9<>"$KIVOU_ROLLOUT_LOCK"'
    )


@pytest.mark.parametrize(
    ("event", "expected_status"),
    (
        ("false", 1),
        ("kill -HUP $$", 129),
        ("kill -INT $$", 130),
        ("kill -TERM $$", 143),
        ("exit 23", 23),
    ),
)
def test_session_loss_rolls_back_once_and_preserves_status(
    event: str, expected_status: int, tmp_path: pathlib.Path
) -> None:
    engine = rollback_engine(read(PRODUCTION_RUNBOOK))
    trace = tmp_path / "rollback.trace"
    missing_status = tmp_path / "missing.status"
    script = f"""\
set -Eeuo pipefail
{engine}
kivou_rollback_stop_phase() {{ printf 'rollback\\n' >>"$KIVOU_TEST_TRACE"; }}
kivou_rollback_app_phase() {{ :; }}
kivou_rollback_frontend_phase() {{ :; }}
kivou_rollback_units_phase() {{ :; }}
kivou_rollback_nginx_phase() {{ :; }}
KIVOU_TEST_TRACE={trace}
KIVOU_ROLLOUT_STATUS={missing_status}
KIVOU_MUTATION_STARTED=1
KIVOU_COMMITTED=0
KIVOU_ROLLBACK_RUNNING=0
kivou_arm_rollout_traps
{event}
printf 'continued-after-event\\n'
"""
    result = subprocess.run(
        ["bash"], input=script, text=True, capture_output=True, check=False
    )

    assert result.returncode == expected_status, result.stderr
    assert trace.read_text(encoding="utf-8").splitlines() == ["rollback"]
    assert "continued-after-event" not in result.stdout


def test_committed_success_skips_session_loss_rollback(tmp_path: pathlib.Path) -> None:
    engine = rollback_engine(read(PRODUCTION_RUNBOOK))
    trace = tmp_path / "rollback.trace"
    committed_status = tmp_path / "rollout.status"
    committed_status.write_text("COMMITTED\n", encoding="utf-8")
    script = f"""\
set -Eeuo pipefail
{engine}
kivou_rollback_stop_phase() {{ printf 'rollback\\n' >>"$KIVOU_TEST_TRACE"; }}
kivou_rollback_app_phase() {{ :; }}
kivou_rollback_frontend_phase() {{ :; }}
kivou_rollback_units_phase() {{ :; }}
kivou_rollback_nginx_phase() {{ :; }}
KIVOU_TEST_TRACE={trace}
KIVOU_ROLLOUT_STATUS={committed_status}
KIVOU_MUTATION_STARTED=1
KIVOU_COMMITTED=1
KIVOU_ROLLBACK_RUNNING=0
kivou_arm_rollout_traps
exit 0
"""
    result = subprocess.run(
        ["bash"], input=script, text=True, capture_output=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert not trace.exists()


def test_session_loss_rollback_reentrancy_guard_preserves_status(
    tmp_path: pathlib.Path,
) -> None:
    engine = rollback_engine(read(PRODUCTION_RUNBOOK))
    trace = tmp_path / "rollback.trace"
    script = f"""\
set -Eeuo pipefail
{engine}
kivou_rollout_rollback() {{ printf 'rollback\\n' >>"$KIVOU_TEST_TRACE"; }}
KIVOU_TEST_TRACE={trace}
KIVOU_ROLLOUT_STATUS={tmp_path / "missing.status"}
KIVOU_MUTATION_STARTED=1
KIVOU_COMMITTED=0
KIVOU_ROLLBACK_RUNNING=1
kivou_arm_rollout_traps
exit 31
"""
    result = subprocess.run(
        ["bash"], input=script, text=True, capture_output=True, check=False
    )

    assert result.returncode == 31, result.stderr
    assert not trace.exists()


def test_durable_recovery_is_published_before_mutation_and_is_autonomous() -> None:
    body = read(PRODUCTION_RUNBOOK)
    engine = rollback_engine(body)
    first_mutation = body.index("KIVOU_FIRST_RUNTIME_MUTATION=1")
    manual = body[body.index("## 11. Rollback immédiat") :]

    for durable in (
        "KIVOU_ROLLBACK_DIR=/srv/kivou/rollbacks/rollout-",
        "KIVOU_ROLLOUT_STATUS",
        "PREPARED",
        "/srv/kivou/rollbacks/current",
        "chown root:root",
        "chmod 600",
        "mv -Tf",
    ):
        assert body.index(durable) < first_mutation, durable

    assert "kivou_mark_rollout_status ROLLED_BACK" in engine

    assert 'test "$(id -u)" -eq 0' in manual
    assert "readlink -f /srv/kivou/rollbacks/current" in manual
    assert "/srv/kivou/rollbacks/rollout-*" in manual
    assert "PREPARED" in manual
    assert "COMMITTED" in manual
    assert "source " not in manual
    assert "eval " not in manual
    for recovery_contract in (
        "KIVOU_PREVIOUS_APP_TARGET",
        "KIVOU_PREVIOUS_FRONTEND_TARGET",
        "KIVOU_SYSTEMD_UNIT_ROOT=/etc/systemd/system",
        "$KIVOU_SYSTEMD_UNIT_ROOT/$KIVOU_UNIT",
        "KIVOU_NGINX_CAPTURE_PATHS",
        "kivou_rollback_stop_phase",
        "kivou_rollback_app_phase",
        "kivou_rollback_frontend_phase",
        "kivou_rollback_units_phase",
        "kivou_rollback_nginx_phase",
    ):
        assert recovery_contract in manual


def test_rollback_readiness_asset_is_immutable_before_mutation() -> None:
    body = read(PRODUCTION_RUNBOOK)
    before_mutation = body[: body.index("KIVOU_FIRST_RUNTIME_MUTATION=1")]

    assert_fragments_in_order(
        before_mutation,
        "KIVOU_ROLLBACK_READINESS=$KIVOU_ROLLBACK_DIR/kivou-api-readiness.sh",
        'ops/bin/kivou-api-readiness.sh" "$KIVOU_ROLLBACK_READINESS"',
        'test ! -L "$KIVOU_ROLLBACK_READINESS"',
        'stat -c \'%U:%G:%a\' "$KIVOU_ROLLBACK_READINESS"',
        "root:root:555",
    )


def test_automatic_rollback_requires_previous_api_readiness_before_nginx() -> None:
    body = read(PRODUCTION_RUNBOOK)
    engine = rollback_engine(body)
    units = engine[
        engine.index("kivou_rollback_units_phase()") : engine.index(
            "kivou_rollback_nginx_phase()"
        )
    ]
    nginx = engine[
        engine.index("kivou_rollback_nginx_phase()") : engine.index(
            "kivou_rollout_rollback()"
        )
    ]

    assert_fragments_in_order(
        units,
        "kivou_restore_unit_states",
        "kivou_verify_rollback_api_readiness",
    )
    assert '"$KIVOU_ROLLBACK_READINESS" kivou-api.service 8000' in body[
        body.index("kivou_verify_rollback_api_readiness()") : body.index(
            "kivou_require_rollback_api_readiness()"
        )
    ]
    assert_fragments_in_order(
        nginx,
        "kivou_require_rollback_api_readiness",
        "KIVOU_NGINX_CAPTURE_VALID=0",
        "kivou_publish_captured_nginx_bundle",
    )
    assert body.index("kivou_verify_rollback_api_readiness", body.index("# KIVOU_ROLLBACK_ENGINE_BEGIN")) < body.index(
        "kivou_mark_rollout_status ROLLED_BACK"
    )
    assert "if ! kivou_rollback_api_readiness_required" not in body
    assert "KIVOU_READINESS_REQUIRED_RC=$?" in body


def test_autonomous_recovery_requires_previous_api_readiness_before_nginx() -> None:
    body = read(PRODUCTION_RUNBOOK)
    manual = body[body.index("## 11. Rollback immédiat") :]
    units = manual[
        manual.index("kivou_rollback_units_phase()") : manual.index(
            "kivou_rollback_nginx_phase()"
        )
    ]
    nginx = manual[
        manual.index("kivou_rollback_nginx_phase()") : manual.index(
            "kivou_recovery_rollback()"
        )
    ]

    assert_fragments_in_order(
        units,
        "kivou_recovery_restore_unit_states",
        "kivou_verify_rollback_api_readiness",
    )
    verify = manual[
        manual.index("kivou_verify_rollback_api_readiness()") : manual.index(
            "kivou_require_rollback_api_readiness()"
        )
    ]
    assert '"$KIVOU_ROLLBACK_READINESS" kivou-api.service 8000' in verify
    assert_fragments_in_order(
        nginx,
        "kivou_require_rollback_api_readiness",
        'test -d "$KIVOU_ROLLBACK_DIR/nginx"',
        "kivou_recovery_capture_nginx",
        "nginx -t",
        "systemctl reload nginx",
    )
    assert manual.index("kivou_verify_rollback_api_readiness") < manual.index(
        "printf '%s\\n' ROLLED_BACK"
    )


def test_autonomous_recovery_uses_a_unique_retry_safe_attempt_directory() -> None:
    body = read(PRODUCTION_RUNBOOK)
    manual = body[body.index("## 11. Rollback immédiat") :]

    assert 'mktemp -d "$KIVOU_ROLLBACK_DIR/recovery-attempt.XXXXXX"' in manual
    assert 'trap \'kivou_recovery_on_exit $?\' EXIT' in manual
    for signal, status in (("HUP", 129), ("INT", 130), ("TERM", 143)):
        assert f"trap 'kivou_recovery_request_exit {status}' {signal}" in manual
    assert_fragments_in_order(
        manual,
        "kivou_recovery_validate_attempt_dir()",
        'case "$KIVOU_CLEANUP_ATTEMPT_DIR" in',
        '"$KIVOU_ROLLBACK_DIR"/recovery-attempt.??????',
    )
    assert "/srv/kivou/app.recovery" not in manual
    assert "/srv/kivou/frontend.recovery" not in manual
    assert "KIVOU_APP_RECOVERY_NEW=$KIVOU_RECOVERY_ATTEMPT_DIR/app-link.new" in manual
    assert (
        "KIVOU_FRONTEND_RECOVERY_NEW="
        "$KIVOU_RECOVERY_ATTEMPT_DIR/frontend-link.new"
    ) in manual
    assert "$KIVOU_UNIT_PATH.recovery-new" not in manual
    assert "$KIVOU_NGINX_PATH.recovery-new" not in manual
    assert 'test ! -e "$KIVOU_UNIT_RECOVERY_NEW"' not in manual
    assert 'test ! -e "$KIVOU_NGINX_NEW"' not in manual
    assert 'mv -Tf "$KIVOU_UNIT_RECOVERY_NEW" "$KIVOU_UNIT_STALE"' in manual
    assert 'mv -Tf "$KIVOU_NGINX_NEW" "$KIVOU_NGINX_STALE"' in manual
    assert "KIVOU_RECOVERY_ATTEMPT_ID" in manual
    assert (
        '"$KIVOU_ROLLBACK_DIR"/nginx|'
        '"$KIVOU_RECOVERY_ATTEMPT_DIR"/nginx-current'
    ) in manual
    assert '"$KIVOU_RECOVERY_ATTEMPT_DIR"/nginx-*' in manual
    assert "/srv/kivou/rollbacks/recovery-*" not in manual
    assert manual.index("kivou_recovery_rollback") < manual.index(
        "printf '%s\\n' ROLLED_BACK"
    )


def prepare_autonomous_recovery_fixture(
    root: pathlib.Path, readiness_rc: int
) -> dict[str, pathlib.Path]:
    runtime = root / "runtime"
    backend_old = runtime / "releases/backend-old"
    backend_new = runtime / "releases/backend-new"
    frontend_old = runtime / "releases/frontend-old"
    frontend_new = runtime / "releases/frontend-new"
    for release in (backend_old, backend_new, frontend_old, frontend_new):
        release.mkdir(parents=True, exist_ok=True)

    backend_lib = backend_old / ".venv/lib"
    backend_lib.mkdir(parents=True)
    (backend_old / ".venv/lib64").symlink_to("lib", target_is_directory=True)
    frontend_bin = frontend_old / "node_modules/.bin"
    frontend_tool = frontend_old / "node_modules/vite/bin/vite.js"
    frontend_bin.mkdir(parents=True)
    frontend_tool.parent.mkdir(parents=True)
    frontend_tool.write_text("vite\n", encoding="utf-8")
    (frontend_bin / "vite").symlink_to("../vite/bin/vite.js")

    for path in (
        backend_lib,
        backend_old / ".venv",
        frontend_tool,
        frontend_tool.parent,
        frontend_old / "node_modules/vite",
        frontend_bin,
        frontend_old / "node_modules",
    ):
        path.chmod(0o555 if path.is_dir() else 0o444)
    for release in (backend_old, backend_new, frontend_old, frontend_new):
        release.chmod(0o555)
    (runtime / "app").symlink_to(backend_new, target_is_directory=True)
    (runtime / "frontend").symlink_to(frontend_new, target_is_directory=True)

    rollout = root / "rollout-test"
    unit_capture = rollout / "systemd"
    nginx_capture = rollout / "nginx"
    unit_capture.mkdir(parents=True)
    nginx_capture.mkdir()
    status = rollout / "rollout.status"
    status.write_text("PREPARED\n", encoding="utf-8")
    (unit_capture / "kivou-api.service.saved").write_text(
        "old-unit\n", encoding="utf-8"
    )
    (unit_capture / "kivou-api.service.enabled").write_text(
        "disabled\n", encoding="utf-8"
    )
    (unit_capture / "kivou-api.service.active").write_text(
        "active\n", encoding="utf-8"
    )

    unit_root = root / "systemd-active"
    unit_root.mkdir()
    (unit_root / "kivou-api.service").write_text("new-unit\n", encoding="utf-8")
    nginx_root = root / "nginx-active"
    nginx_path = nginx_root / "sites-available/kivou"
    nginx_path.parent.mkdir(parents=True)
    nginx_path.write_text("new-nginx\n", encoding="utf-8")
    capture_name = str(nginx_path).removeprefix("/").replace("/", "__")
    nginx_saved = nginx_capture / f"{capture_name}.saved"
    nginx_saved.write_text("old-nginx\n", encoding="utf-8")
    (nginx_capture / "etc__nginx__sites-enabled__kivou.saved").symlink_to(
        nginx_saved.name
    )
    for capture in (unit_capture, nginx_capture):
        for child in capture.iterdir():
            child.chmod(0o400)
        capture.chmod(0o500)

    trace = root / "recovery.trace"
    trace.write_text("", encoding="utf-8")
    readiness_status = root / "readiness.rc"
    readiness_status.write_text(f"{readiness_rc}\n", encoding="utf-8")
    readiness = rollout / "kivou-api-readiness.sh"
    readiness.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'readiness\\n' >>{shlex.quote(str(trace))}\n"
        f"read -r KIVOU_TEST_RC <{shlex.quote(str(readiness_status))}\n"
        "exit \"$KIVOU_TEST_RC\"\n",
        encoding="utf-8",
    )
    readiness.chmod(0o555)
    api_state = root / "api.state"
    nginx_state = root / "nginx.state"
    cleanup_mv_status = root / "cleanup-mv.rc"
    api_state.write_text("active\n", encoding="utf-8")
    nginx_state.write_text("active\n", encoding="utf-8")
    cleanup_mv_status.write_text("0\n", encoding="utf-8")
    return {
        "runtime": runtime,
        "backend_old": backend_old,
        "frontend_old": frontend_old,
        "rollout": rollout,
        "status": status,
        "unit_capture": unit_capture,
        "unit_root": unit_root,
        "nginx_root": nginx_root,
        "nginx_path": nginx_path,
        "readiness": readiness,
        "trace": trace,
        "api_state": api_state,
        "nginx_state": nginx_state,
        "cleanup_mv_status": cleanup_mv_status,
    }


def autonomous_recovery_harness(
    source: str, fixture: dict[str, pathlib.Path], *, interrupt_at: str | None
) -> str:
    quoted = {key: shlex.quote(str(value)) for key, value in fixture.items()}
    return f"""\
set -Eeuo pipefail
KIVOU_RUNTIME_ROOT={quoted["runtime"]}
KIVOU_SYSTEMD_UNIT_ROOT={quoted["unit_root"]}
KIVOU_NGINX_ROOT={quoted["nginx_root"]}
KIVOU_ROLLBACK_DIR={quoted["rollout"]}
KIVOU_ROLLOUT_STATUS={quoted["status"]}
KIVOU_UNIT_CAPTURE_DIR={quoted["unit_capture"]}
KIVOU_ROLLBACK_READINESS={quoted["readiness"]}
KIVOU_PREVIOUS_APP_TARGET={quoted["backend_old"]}
KIVOU_PREVIOUS_FRONTEND_TARGET={quoted["frontend_old"]}
KIVOU_UNIT_NAMES=(kivou-api.service)
KIVOU_ROLLOUT_UNITS=(kivou-api.service)
KIVOU_NGINX_CAPTURE_PATHS=({quoted["nginx_path"]})
KIVOU_NGINX_SITE_LINKS=()
KIVOU_NGINX_WAS_ENABLED=enabled
KIVOU_NGINX_WAS_ACTIVE=active
KIVOU_TEST_TRACE={quoted["trace"]}
KIVOU_TEST_API_STATE={quoted["api_state"]}
KIVOU_TEST_NGINX_STATE={quoted["nginx_state"]}
KIVOU_TEST_CLEANUP_MV_STATUS={quoted["cleanup_mv_status"]}
KIVOU_TEST_INTERRUPT_AT={shlex.quote(interrupt_at or "none")}
KIVOU_TEST_PARENT_PID=$$

chown() {{ :; }}
stat() {{
  if [ "$1:$2" = "-c:%U:%G:%a" ]; then
    printf 'root:root:%s\n' "$(command stat -c %a "$3")"
  else
    command stat "$@"
  fi
}}
install() {{
  test "$1:$2:$3:$4:$5:$6:$7" = "-o:root:-g:root:-m:700:-d"
  /usr/bin/install -m 700 -d "$8"
}}
systemctl() {{
  printf 'systemctl %s\n' "$*" >>"$KIVOU_TEST_TRACE"
  KIVOU_TEST_ACTION=$1
  shift
  KIVOU_TEST_UNIT=${{@: -1}}
  case "$KIVOU_TEST_UNIT" in
    (kivou-api.service) KIVOU_TEST_STATE=$KIVOU_TEST_API_STATE ;;
    (nginx) KIVOU_TEST_STATE=$KIVOU_TEST_NGINX_STATE ;;
    (*) KIVOU_TEST_STATE= ;;
  esac
  case "$KIVOU_TEST_ACTION" in
    (is-enabled) return 1 ;;
    (is-active) [ -n "$KIVOU_TEST_STATE" ] && [ "$(sed -n '1p' "$KIVOU_TEST_STATE")" = active ] ;;
    (stop) [ -z "$KIVOU_TEST_STATE" ] || printf 'inactive\n' >"$KIVOU_TEST_STATE" ;;
    (start) [ -z "$KIVOU_TEST_STATE" ] || printf 'active\n' >"$KIVOU_TEST_STATE" ;;
    (disable)
      case " $* " in (*' --now '*) [ -z "$KIVOU_TEST_STATE" ] || printf 'inactive\n' >"$KIVOU_TEST_STATE" ;; esac
      ;;
    (enable|mask|daemon-reload|reload) ;;
    (*) return 64 ;;
  esac
}}
cp() {{
  command cp "$@"
  KIVOU_TEST_COPY_TARGET=${{@: -1}}
  if [ "$KIVOU_TEST_INTERRUPT_AT" = nginx-temp ]; then
    case "$KIVOU_TEST_COPY_TARGET" in
      ("$KIVOU_NGINX_ROOT"/*.recovery-??????-new)
        printf 'interrupt-nginx-temp\n' >>"$KIVOU_TEST_TRACE"
        kill -TERM "$KIVOU_TEST_PARENT_PID"
        return 143
        ;;
    esac
  fi
}}
mv() {{
  KIVOU_TEST_MOVE_SOURCE=$1
  KIVOU_TEST_MOVE_TARGET=${{@: -1}}
  case "$KIVOU_TEST_MOVE_TARGET" in
    (*/recovery-attempt.??????/cleanup-external-*)
      printf 'cleanup-external-mv %s\n' "$KIVOU_TEST_MOVE_SOURCE" >>"$KIVOU_TEST_TRACE"
      read -r KIVOU_TEST_CLEANUP_RC <"$KIVOU_TEST_CLEANUP_MV_STATUS"
      if [ "$KIVOU_TEST_CLEANUP_RC" = TERM ]; then
        kill -TERM "$KIVOU_TEST_PARENT_PID"
        return 143
      fi
      if [ "$KIVOU_TEST_CLEANUP_RC" -ne 0 ]; then return "$KIVOU_TEST_CLEANUP_RC"; fi
      ;;
  esac
  command mv "$@"
}}
nginx() {{
  if /usr/bin/find "$KIVOU_NGINX_ROOT" -name '*.recovery-*-new' -print -quit | grep -q .; then
    printf 'nginx-duplicate-temp\n' >>"$KIVOU_TEST_TRACE"
    return 76
  fi
  printf 'nginx-test\n' >>"$KIVOU_TEST_TRACE"
}}
find() {{
  if [ "$KIVOU_TEST_INTERRUPT_AT" = frontend ] && [ "$1" = "$KIVOU_PREVIOUS_FRONTEND_TARGET" ]; then
    printf 'interrupt-frontend\n' >>"$KIVOU_TEST_TRACE"
    printf 'interrupt-frontend\n'
    kill -TERM "$KIVOU_TEST_PARENT_PID"
    return 143
  fi
  command find "$@"
}}
{source}
kivou_run_autonomous_recovery
"""


def test_real_autonomous_recovery_retries_after_interruption(
    tmp_path: pathlib.Path,
) -> None:
    body = read(PRODUCTION_RUNBOOK)
    source = autonomous_recovery_source(body)
    assert "kivou_recovery_rollback()" in source
    assert "kivou_run_autonomous_recovery()" in source
    fixture = prepare_autonomous_recovery_fixture(tmp_path, readiness_rc=0)

    interrupted = subprocess.run(
        ["bash"],
        input=autonomous_recovery_harness(source, fixture, interrupt_at="frontend"),
        text=True,
        capture_output=True,
        check=False,
    )
    assert interrupted.returncode == 143, interrupted.stderr
    assert fixture["status"].read_text(encoding="utf-8") == "PREPARED\n"
    assert (fixture["runtime"] / "app").resolve() == fixture["backend_old"]
    assert (fixture["runtime"] / "frontend").resolve().name == "frontend-new"
    assert not tuple(fixture["rollout"].glob("recovery-attempt.*"))

    fixture["trace"].write_text("", encoding="utf-8")
    completed = subprocess.run(
        ["bash"],
        input=autonomous_recovery_harness(source, fixture, interrupt_at=None),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert fixture["status"].read_text(encoding="utf-8") == "ROLLED_BACK\n"
    assert (fixture["runtime"] / "frontend").resolve() == fixture["frontend_old"]
    assert (fixture["unit_root"] / "kivou-api.service").read_text() == "old-unit\n"
    assert fixture["nginx_path"].read_text(encoding="utf-8") == "old-nginx\n"
    trace = fixture["trace"].read_text(encoding="utf-8")
    assert_fragments_in_order(trace, "readiness", "nginx-test", "systemctl reload nginx")
    assert not tuple(fixture["nginx_root"].glob("**/*.recovery-*-new"))
    assert not tuple(fixture["unit_root"].glob("*.recovery-*-new"))
    assert not tuple(fixture["rollout"].glob("recovery-attempt.*"))


def test_real_autonomous_recovery_readiness_failure_blocks_nginx(
    tmp_path: pathlib.Path,
) -> None:
    source = autonomous_recovery_source(read(PRODUCTION_RUNBOOK))
    fixture = prepare_autonomous_recovery_fixture(tmp_path, readiness_rc=75)

    result = subprocess.run(
        ["bash"],
        input=autonomous_recovery_harness(source, fixture, interrupt_at=None),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 75, result.stderr
    assert fixture["status"].read_text(encoding="utf-8") == "PREPARED\n"
    trace = fixture["trace"].read_text(encoding="utf-8")
    assert "readiness" in trace
    assert "nginx-test" not in trace
    assert "systemctl reload nginx" not in trace
    assert not tuple(fixture["rollout"].glob("recovery-attempt.*"))


def test_autonomous_recovery_registers_every_external_temp_before_creation() -> None:
    source = autonomous_recovery_source(read(PRODUCTION_RUNBOOK))

    assert "KIVOU_RECOVERY_EXTERNAL_TEMPS=" in source
    assert "kivou_recovery_validate_external_temp()" in source
    assert "kivou_recovery_register_external_temp()" in source
    validator = source[
        source.index("kivou_recovery_validate_external_temp()") : source.index(
            "kivou_recovery_register_external_temp()"
        )
    ]
    assert "KIVOU_EXTERNAL_TEMP_PARENT=" in validator
    assert 'readlink -f "$KIVOU_EXTERNAL_TEMP_PARENT"' in validator
    assert 'test "$KIVOU_EXTERNAL_TEMP_PARENT_REAL"' in validator
    assert_fragments_in_order(
        source,
        "kivou_recovery_cleanup_attempt()",
        'while IFS= read -r KIVOU_EXTERNAL_TEMP',
        'kivou_recovery_validate_external_temp "$KIVOU_EXTERNAL_TEMP" "$KIVOU_CLEANUP_ATTEMPT_ID"',
        'mv -Tf "$KIVOU_EXTERNAL_TEMP" "$KIVOU_EXTERNAL_TEMP_EVAC"',
    )
    for temp, creation in (
        ("$KIVOU_NGINX_NEW", 'cp -a "$KIVOU_BUNDLE/'),
        ("$KIVOU_UNIT_RECOVERY_NEW", 'cp -a "$KIVOU_UNIT_CAPTURE_DIR/'),
    ):
        register = source.index(f'kivou_recovery_register_external_temp "{temp}"')
        create = source.index(creation, register)
        assert register < create
    cleanup = source[
        source.index("kivou_recovery_cleanup_attempt()") : source.index(
            "kivou_recovery_resume_pending_attempts()"
        )
    ]
    assert "rm " not in cleanup
    assert "recovery-*-new" not in cleanup


def test_real_recovery_cleans_interrupted_nginx_temp_before_retry(
    tmp_path: pathlib.Path,
) -> None:
    source = autonomous_recovery_source(read(PRODUCTION_RUNBOOK))
    fixture = prepare_autonomous_recovery_fixture(tmp_path, readiness_rc=0)
    unregistered = fixture["unit_root"] / "unregistered.recovery-OTHER1-new"
    unregistered.write_text("keep\n", encoding="utf-8")
    canonical_sentinel = fixture["nginx_root"] / "canonical-keep.conf"
    canonical_sentinel.write_text("keep\n", encoding="utf-8")

    interrupted = subprocess.run(
        ["bash"],
        input=autonomous_recovery_harness(
            source, fixture, interrupt_at="nginx-temp"
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    assert interrupted.returncode == 143, interrupted.stderr
    assert fixture["status"].read_text(encoding="utf-8") == "PREPARED\n"
    assert "interrupt-nginx-temp" in fixture["trace"].read_text(encoding="utf-8")
    assert not tuple(fixture["nginx_root"].glob("**/*.recovery-*-new"))
    assert not tuple(fixture["rollout"].glob("recovery-attempt.*"))
    assert unregistered.read_text(encoding="utf-8") == "keep\n"
    assert canonical_sentinel.read_text(encoding="utf-8") == "keep\n"

    fixture["trace"].write_text("", encoding="utf-8")
    completed = subprocess.run(
        ["bash"],
        input=autonomous_recovery_harness(source, fixture, interrupt_at=None),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert fixture["status"].read_text(encoding="utf-8") == "ROLLED_BACK\n"
    trace = fixture["trace"].read_text(encoding="utf-8")
    assert_fragments_in_order(trace, "readiness", "nginx-test", "systemctl reload nginx")
    assert "nginx-duplicate-temp" not in trace
    assert not tuple(fixture["nginx_root"].glob("**/*.recovery-*-new"))
    assert not tuple(fixture["rollout"].glob("recovery-attempt.*"))
    assert unregistered.read_text(encoding="utf-8") == "keep\n"
    assert canonical_sentinel.read_text(encoding="utf-8") == "keep\n"


@pytest.mark.parametrize("cleanup_failure", ("77", "TERM"))
def test_real_recovery_preserves_failed_cleanup_evidence_then_resumes(
    tmp_path: pathlib.Path, cleanup_failure: str
) -> None:
    source = autonomous_recovery_source(read(PRODUCTION_RUNBOOK))
    fixture = prepare_autonomous_recovery_fixture(tmp_path, readiness_rc=0)
    fixture["cleanup_mv_status"].write_text(
        f"{cleanup_failure}\n", encoding="utf-8"
    )
    unregistered = fixture["unit_root"] / "unregistered.recovery-OTHER1-new"
    unregistered.write_text("keep\n", encoding="utf-8")
    canonical_sentinel = fixture["nginx_root"] / "canonical-keep.conf"
    canonical_sentinel.write_text("keep\n", encoding="utf-8")

    interrupted = subprocess.run(
        ["bash"],
        input=autonomous_recovery_harness(
            source, fixture, interrupt_at="nginx-temp"
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    expected_interrupted_rc = -15 if cleanup_failure == "TERM" else 143
    assert interrupted.returncode == expected_interrupted_rc, interrupted.stderr
    assert fixture["status"].read_text(encoding="utf-8") == "PREPARED\n"
    attempts = tuple(fixture["rollout"].glob("recovery-attempt.*"))
    assert len(attempts) == 1
    manifest = attempts[0] / "external-temporaries.manifest"
    assert manifest.is_file()
    assert manifest.stat().st_mode & 0o777 == 0o600
    registered_temps = tuple(
        pathlib.Path(line)
        for line in manifest.read_text(encoding="utf-8").splitlines()
    )
    assert any(path.exists() for path in registered_temps)
    attempt_id = attempts[0].name.removeprefix("recovery-attempt.")
    registered_systemd = (
        fixture["unit_root"] / f"kivou-extra.service.recovery-{attempt_id}-new"
    )
    registered_systemd.write_text("registered\n", encoding="utf-8")
    with manifest.open("a", encoding="utf-8") as stream:
        stream.write(f"{registered_systemd}\n")

    fixture["cleanup_mv_status"].write_text("0\n", encoding="utf-8")
    fixture["trace"].write_text("", encoding="utf-8")
    completed = subprocess.run(
        ["bash"],
        input=autonomous_recovery_harness(source, fixture, interrupt_at=None),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert fixture["status"].read_text(encoding="utf-8") == "ROLLED_BACK\n"
    trace = fixture["trace"].read_text(encoding="utf-8")
    assert_fragments_in_order(
        trace,
        "cleanup-external-mv",
        "systemctl is-enabled --quiet kivou-api.service",
        "readiness",
        "nginx-test",
        "systemctl reload nginx",
    )
    assert "nginx-duplicate-temp" not in trace
    assert not tuple(fixture["rollout"].glob("recovery-attempt.*"))
    assert not tuple(fixture["nginx_root"].glob("**/*.recovery-*-new"))
    assert not registered_systemd.exists()
    assert unregistered.read_text(encoding="utf-8") == "keep\n"
    assert canonical_sentinel.read_text(encoding="utf-8") == "keep\n"


def test_real_recovery_fails_closed_when_old_cleanup_still_fails(
    tmp_path: pathlib.Path,
) -> None:
    source = autonomous_recovery_source(read(PRODUCTION_RUNBOOK))
    fixture = prepare_autonomous_recovery_fixture(tmp_path, readiness_rc=0)
    fixture["cleanup_mv_status"].write_text("77\n", encoding="utf-8")
    interrupted = subprocess.run(
        ["bash"],
        input=autonomous_recovery_harness(
            source, fixture, interrupt_at="nginx-temp"
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert interrupted.returncode == 143, interrupted.stderr

    fixture["trace"].write_text("", encoding="utf-8")
    blocked = subprocess.run(
        ["bash"],
        input=autonomous_recovery_harness(source, fixture, interrupt_at=None),
        text=True,
        capture_output=True,
        check=False,
    )

    assert blocked.returncode == 78, blocked.stderr
    assert fixture["status"].read_text(encoding="utf-8") == "PREPARED\n"
    assert "nginx-test" not in fixture["trace"].read_text(encoding="utf-8")
    attempts = tuple(fixture["rollout"].glob("recovery-attempt.*"))
    assert len(attempts) == 1
    assert (attempts[0] / "external-temporaries.manifest").is_file()


def test_autonomous_recovery_resumes_durable_cleanup_before_new_attempt() -> None:
    body = read(PRODUCTION_RUNBOOK)
    manual = body[body.index("## 11. Rollback immédiat") :]
    source = autonomous_recovery_source(body)

    assert "kivou_recovery_resume_pending_attempts()" in source
    assert_fragments_in_order(
        source,
        "kivou_recovery_resume_pending_attempts\n",
        'KIVOU_RECOVERY_ATTEMPT_DIR=$(mktemp -d "$KIVOU_ROLLBACK_DIR/recovery-attempt.XXXXXX")',
        "kivou_recovery_rollback()",
    )
    cleanup = source[
        source.index("kivou_recovery_cleanup_attempt()") : source.index(
            "kivou_recovery_resume_pending_attempts()"
        )
    ]
    assert 'test "$(stat -c \'%U:%G:%a\' "$KIVOU_CLEANUP_MANIFEST")" = root:root:600' in cleanup
    assert_fragments_in_order(
        cleanup,
        'mv -Tf "$KIVOU_EXTERNAL_TEMP" "$KIVOU_EXTERNAL_TEMP_EVAC"',
        'if test -e "$KIVOU_EXTERNAL_TEMP"',
        "then return 77",
        'find "$KIVOU_CLEANUP_ATTEMPT_DIR"',
    )
    assert 'find "$KIVOU_CLEANUP_ATTEMPT_DIR" -xdev -depth -delete' not in cleanup
    assert "KIVOU_PENDING_CLEANUP_FAILED=78" in source
    assert 'printf \'%s\\n\' ROLLED_BACK' in manual


def test_successful_nginx_publish_is_enabled_and_active_even_when_already_active() -> None:
    body = read(PRODUCTION_RUNBOOK)
    mutation = body[
        body.index("KIVOU_FIRST_RUNTIME_MUTATION=1") : body.index(
            "KIVOU_MUTATION_WINDOW_END"
        )
    ]

    assert_fragments_in_order(
        mutation,
        "nginx -t",
        'if [ "$KIVOU_NGINX_WAS_ACTIVE" = active ]; then',
        "systemctl enable nginx",
        "systemctl reload nginx",
        "systemctl enable --now nginx",
        "systemctl is-enabled --quiet nginx",
        "systemctl is-active --quiet nginx",
    )
