from __future__ import annotations

import pathlib

import pytest

REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
SYSTEMD = REPOSITORY / "ops/systemd"
PRODUCTION = SYSTEMD / "production"
NGINX = REPOSITORY / "ops/nginx"
PRODUCTION_NGINX = NGINX / "kivou-production.conf"
PRODUCTION_WWW_NGINX = NGINX / "kivou-production-www.conf"
PRODUCTION_DEFAULT_DENY_NGINX = NGINX / "kivou-production-default-deny.conf"
PRODUCTION_SECURITY_HEADERS = NGINX / "kivou-production-security-headers.conf"
PRODUCTION_SENSITIVE_SECURITY_HEADERS = (
    NGINX / "kivou-production-sensitive-link-security-headers.conf"
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
    PRODUCTION / "kivou-backup.service",
    PRODUCTION / "kivou-ingest@.service",
)
ExpectedDirectives = dict[tuple[str, str], str | tuple[str, ...]]
ParsedUnit = dict[str, dict[str, list[str]]]


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


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
    directives = nginx_active_directives(body)
    servers = nginx_server_blocks(body)

    assert len(servers) == 2
    assert directives.count("server_name PRODUCTION_WWW_HOST;") == 2
    assert directives.count("return 301 https://PRODUCTION_HOST$request_uri;") == 2
    assert "proxy_pass" not in body

    http, https = servers
    for expected in (
        "listen 80;",
        "listen [::]:80;",
        "server_name PRODUCTION_WWW_HOST;",
        "location /.well-known/acme-challenge/ {",
        "root /var/www/certbot;",
        "return 301 https://PRODUCTION_HOST$request_uri;",
    ):
        assert http.count(expected) == 1
    for expected in (
        "listen 443 ssl http2;",
        "listen [::]:443 ssl http2;",
        "server_name PRODUCTION_WWW_HOST;",
        "ssl_certificate /etc/letsencrypt/live/PRODUCTION_HOST/fullchain.pem;",
        "ssl_certificate_key /etc/letsencrypt/live/PRODUCTION_HOST/privkey.pem;",
        "ssl_trusted_certificate /etc/letsencrypt/live/PRODUCTION_HOST/chain.pem;",
        "include /etc/nginx/kivou-production-security-headers.conf;",
        "return 301 https://PRODUCTION_HOST$request_uri;",
    ):
        assert https.count(expected) == 1


def test_production_default_site_rejects_unknown_http_and_tls_hosts() -> None:
    assert nginx_active_directives(read(PRODUCTION_DEFAULT_DENY_NGINX)) == (
        "server {",
        "listen 80 default_server;",
        "listen [::]:80 default_server;",
        "server_name _;",
        "return 444;",
        "}",
        "server {",
        "listen 443 ssl default_server;",
        "listen [::]:443 ssl default_server;",
        "server_name _;",
        "ssl_reject_handshake on;",
        "}",
    )
