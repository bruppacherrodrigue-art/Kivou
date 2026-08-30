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
ExpectedDirectives = dict[tuple[str, str], str | tuple[str, ...]]
ParsedUnit = dict[str, dict[str, list[str]]]


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


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

        environment: str | tuple[str, ...] = "/etc/kivou/production.env"
        repeatable: frozenset[tuple[str, str]] = frozenset()
        if path.name == "kivou-backup.service":
            environment = (
                "/etc/kivou/production.env",
                "/etc/kivou/swiss-backup.env",
            )
            repeatable = frozenset(
                {("Service", "EnvironmentFile"), ("Service", "ExecStart")}
            )
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
            repeatable=repeatable,
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


def test_production_backup_has_a_six_hour_start_timeout() -> None:
    assert_unit_contract(
        read(PRODUCTION / "kivou-backup.service"),
        {("Service", "TimeoutStartSec"): "6h"},
        repeatable=frozenset(
            {("Service", "EnvironmentFile"), ("Service", "ExecStart")}
        ),
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


def test_production_backup_runs_local_then_offsite_with_narrow_write_access() -> None:
    service = read(PRODUCTION / "kivou-backup.service")
    timer = read(PRODUCTION / "kivou-backup.timer")

    assert_unit_contract(
        service,
        {
            ("Unit", "After"): "network-online.target postgresql.service",
            ("Service", "Type"): "oneshot",
            ("Service", "User"): "kivou",
            ("Service", "Group"): "kivou",
            ("Service", "EnvironmentFile"): (
                "/etc/kivou/production.env",
                "/etc/kivou/swiss-backup.env",
            ),
            ("Service", "ExecStart"): (
                "/srv/kivou/app/ops/bin/kivou-backup.sh",
                "/srv/kivou/app/ops/bin/kivou-restic-upload.sh",
            ),
            ("Service", "TimeoutStartSec"): "6h",
            ("Service", "StandardOutput"): "journal",
            ("Service", "StandardError"): "journal",
            ("Service", "ReadWritePaths"): "/srv/kivou/backups",
        },
        repeatable=frozenset(
            {("Service", "EnvironmentFile"), ("Service", "ExecStart")}
        ),
    )
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
