from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa

from signals.api.app import create_app
from signals.api.config import ApiConfig

ROOT = Path(__file__).resolve().parents[1]
NGINX_DIR = ROOT / "ops" / "nginx"

PUBLIC_ASGI_ROUTES = frozenset(
    {
        ("GET", "/a/{token}"),
        ("POST", "/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/password-reset/confirm"),
        ("POST", "/auth/password-reset/request"),
        ("POST", "/auth/signup"),
        ("DELETE", "/billing/plan"),
        ("GET", "/billing/plans"),
        ("GET", "/billing/status"),
        ("POST", "/billing/checkout"),
        ("POST", "/billing/plan"),
        ("POST", "/billing/portal"),
        ("GET", "/companies"),
        ("GET", "/companies/{company_key}"),
        ("POST", "/companies/{company_key}/contact"),
        ("PUT", "/companies/{company_key}/note"),
        ("GET", "/me"),
        ("PATCH", "/me"),
        ("GET", "/notification-preferences"),
        ("PATCH", "/notification-preferences"),
        ("GET", "/signals"),
        ("GET", "/signals/{signal_key}"),
        ("GET", "/signals/{signal_key}/feedback"),
        ("GET", "/signals/{signal_key}/note"),
        ("POST", "/signals/{signal_key}/contacted"),
        ("PUT", "/signals/{signal_key}/feedback"),
        ("PUT", "/signals/{signal_key}/note"),
        ("GET", "/target-icps"),
        ("GET", "/target-icps/{target_icp_id}"),
        ("PATCH", "/target-icps/{target_icp_id}"),
        ("POST", "/target-icps"),
        ("POST", "/webhooks/instantly"),
        ("POST", "/webhooks/stripe"),
    }
)

PRIVATE_ASGI_ROUTES = frozenset(
    {
        ("GET", "/openapi.json"),
        ("GET", "/internal/commercial-cockpit"),
        ("GET", "/internal/acquisition-ops/health"),
        ("GET", "/internal/acquisition-ops/readiness"),
        ("GET", "/internal/acquisition-ops/incidents"),
        ("GET", "/internal/acquisition-ops/dead-letters"),
    }
)

EXPECTED_PROXY_SELECTORS = frozenset(
    {
        "~ ^/(auth|me|target-icps|signals|companies|billing|notification-preferences)(/|$)",
        "= /auth/login",
        "= /auth/signup",
        "= /auth/password-reset/request",
        "= /auth/password-reset/confirm",
        "= /webhooks/stripe",
        "= /webhooks/instantly",
        "^~ /a/",
    }
)


@dataclass(frozen=True)
class LocationBlock:
    selector: str
    body: str


@dataclass(frozen=True)
class ServerBlock:
    body: str


def _asgi_route_inventory() -> frozenset[tuple[str, str]]:
    app = create_app(
        sa.create_engine("sqlite+pysqlite:///:memory:", future=True),
        ApiConfig(),
    )

    def walk(routes: list[object], prefix: str = ""):
        for route in routes:
            original_router = getattr(route, "original_router", None)
            include_context = getattr(route, "include_context", None)
            if original_router is not None and include_context is not None:
                yield from walk(
                    original_router.routes,
                    prefix + include_context.prefix,
                )
                continue
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if path is None or methods is None:
                continue
            # HEAD/OPTIONS are framework-generated transport variants; the
            # reviewed inventory records the application operation once.
            for method in methods - {"HEAD", "OPTIONS"}:
                yield method, prefix + path

    return frozenset(walk(app.routes))


def _location_blocks(text: str) -> tuple[LocationBlock, ...]:
    lines = text.splitlines()
    blocks: list[LocationBlock] = []
    index = 0
    while index < len(lines):
        code = lines[index].split("#", 1)[0].strip()
        match = re.fullmatch(r"location\s+(.+?)\s*\{", code)
        if match is None:
            index += 1
            continue
        selector = match.group(1)
        depth = 1
        body: list[str] = []
        index += 1
        while index < len(lines) and depth:
            line = lines[index]
            uncommented = line.split("#", 1)[0]
            depth += uncommented.count("{") - uncommented.count("}")
            if depth:
                body.append(line)
            index += 1
        if depth:
            raise AssertionError(f"unterminated nginx location: {selector}")
        blocks.append(LocationBlock(selector=selector, body="\n".join(body)))
    return tuple(blocks)


def _server_blocks(text: str) -> tuple[ServerBlock, ...]:
    lines = text.splitlines()
    blocks: list[ServerBlock] = []
    index = 0
    while index < len(lines):
        code = lines[index].split("#", 1)[0].strip()
        if code != "server {":
            index += 1
            continue
        depth = 1
        body: list[str] = []
        index += 1
        while index < len(lines) and depth:
            line = lines[index]
            uncommented = line.split("#", 1)[0]
            depth += uncommented.count("{") - uncommented.count("}")
            if depth:
                body.append(line)
            index += 1
        if depth:
            raise AssertionError("unterminated nginx server")
        blocks.append(ServerBlock(body="\n".join(body)))
    return tuple(blocks)


def _sample_path(route_path: str) -> str:
    return re.sub(r"\{[^}]+\}", "synthetic", route_path)


def _matches(selector: str, path: str) -> bool:
    if selector.startswith("= "):
        return path == selector.removeprefix("= ")
    if selector.startswith("^~ "):
        return path.startswith(selector.removeprefix("^~ "))
    if selector.startswith("~ "):
        return re.search(selector.removeprefix("~ "), path) is not None
    return path.startswith(selector)


def _site_text() -> str:
    return (NGINX_DIR / "kivou-staging.conf").read_text()


def _only_server(listen_directive: str) -> ServerBlock:
    matching = [
        block
        for block in _server_blocks(_site_text())
        if listen_directive in block.body
    ]
    assert len(matching) == 1, (
        f"expected one nginx server with {listen_directive!r}, got {len(matching)}"
    )
    return matching[0]


def _proxy_locations() -> tuple[LocationBlock, ...]:
    https = _only_server("listen 443 ssl http2;")
    return tuple(
        block for block in _location_blocks(https.body) if "proxy_pass" in block.body
    )


def _only_location(server: ServerBlock, selector: str) -> LocationBlock:
    matching = [
        block
        for block in _location_blocks(server.body)
        if block.selector == selector
    ]
    assert len(matching) == 1, (
        f"expected one nginx location {selector!r}, got {len(matching)}"
    )
    return matching[0]


def _directives(text: str) -> tuple[str, ...]:
    return tuple(
        code
        for line in text.splitlines()
        if (code := line.split("#", 1)[0].strip())
    )


def _header_directives(path: Path) -> tuple[str, ...]:
    return tuple(
        directive
        for directive in _directives(path.read_text())
        if directive.startswith("add_header ")
    )


def _directives_starting_with(text: str, prefix: str) -> tuple[str, ...]:
    return tuple(
        directive
        for directive in _directives(text)
        if directive.startswith(prefix)
    )


def _direct_server_directives(text: str) -> tuple[str, ...]:
    depth = 0
    directives: list[str] = []
    for line in text.splitlines():
        code = line.split("#", 1)[0].strip()
        if not code:
            continue
        if depth == 0 and code.endswith(";"):
            directives.append(code)
        depth += code.count("{") - code.count("}")
    return tuple(directives)


def _log_format_body(text: str, name: str) -> str:
    match = re.search(
        rf"log_format\s+{re.escape(name)}\s+escape=json\s+(.+?);",
        text,
        flags=re.DOTALL,
    )
    assert match is not None, f"missing nginx log format {name}"
    return match.group(1)


def _map_directives(text: str, source: str, destination: str) -> tuple[str, ...]:
    match = re.search(
        rf"map\s+{re.escape(source)}\s+{re.escape(destination)}\s*"
        r"\{(?P<body>.*?)\}",
        text,
        flags=re.DOTALL,
    )
    assert match is not None, f"missing nginx map {source} -> {destination}"
    return _directives(match.group("body"))


def test_direct_server_directives_ignore_nested_blocks_and_comments() -> None:
    body = """
        # access_log /tmp/commented.log;
        set $safe_path $safe_path_map;
        location / {
            access_log /tmp/location.log;
            if ($request_method = POST) {
                set $nested_path /nested;
            }
        }
        if ($request_method = GET) {
            set $conditional_path /conditional;
        }
        access_log /var/log/nginx/access.log safe_json;
    """

    assert _direct_server_directives(body) == (
        "set $safe_path $safe_path_map;",
        "access_log /var/log/nginx/access.log safe_json;",
    )


def test_directives_starting_with_collect_all_active_matches_in_order() -> None:
    body = """
        # set $safe_path /commented;
        set $safe_path $safe_path_map;
        location / {
            set $safe_path /location;
            if ($request_method = POST) {
                set $safe_path $request_uri;
            }
        }
        if ($request_method = GET) {
            set $safe_path $args;
        }
        set $safe_path_suffix /not-the-same-variable;
    """

    assert _directives_starting_with(body, "set $safe_path ") == (
        "set $safe_path $safe_path_map;",
        "set $safe_path /location;",
        "set $safe_path $request_uri;",
        "set $safe_path $args;",
    )


def test_fastapi_routes_are_all_explicitly_public_or_private() -> None:
    assert PUBLIC_ASGI_ROUTES.isdisjoint(PRIVATE_ASGI_ROUTES)
    assert _asgi_route_inventory() == PUBLIC_ASGI_ROUTES | PRIVATE_ASGI_ROUTES


def test_tracked_nginx_templates_have_balanced_directive_syntax() -> None:
    for path in sorted(NGINX_DIR.glob("*.conf")):
        depth = 0
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            code = line.split("#", 1)[0].strip()
            if not code:
                continue
            assert code.endswith((";", "{", "}")), f"{path}:{line_number}: {code}"
            depth += code.count("{") - code.count("}")
            assert depth >= 0, f"{path}:{line_number}: unexpected closing brace"
        assert depth == 0, f"{path}: unbalanced directive block"


def test_sensitive_headers_change_only_the_referrer_policy() -> None:
    ordinary_path = NGINX_DIR / "kivou-security-headers.conf"
    sensitive_path = NGINX_DIR / "kivou-sensitive-link-security-headers.conf"
    assert sensitive_path.is_file(), f"missing nginx fragment: {sensitive_path}"

    ordinary = _header_directives(ordinary_path)
    sensitive = _header_directives(sensitive_path)
    ordinary_policy = (
        'add_header Referrer-Policy "strict-origin-when-cross-origin" always;'
    )
    sensitive_policy = 'add_header Referrer-Policy "no-referrer" always;'

    assert _directives(sensitive_path.read_text()) == sensitive
    assert ordinary.count(ordinary_policy) == 1
    assert ordinary.count(sensitive_policy) == 0
    assert sensitive.count(ordinary_policy) == 0
    assert sensitive.count(sensitive_policy) == 1
    assert sensitive == tuple(
        sensitive_policy
        if directive.startswith("add_header Referrer-Policy ")
        else directive
        for directive in ordinary
    )


def test_sensitive_link_gate_candidates_are_inert_or_fail_closed() -> None:
    candidates = (
        ("kivou-sensitive-links-open.conf", ()),
        ("kivou-sensitive-links-closed.conf", ("return 503;",)),
    )

    for filename, expected in candidates:
        path = NGINX_DIR / filename
        assert path.is_file(), f"missing nginx fragment: {path}"
        assert _directives(path.read_text()) == expected


def test_both_servers_gate_explicit_sensitive_locations_first() -> None:
    gate = "include /etc/nginx/kivou-sensitive-links-gate.conf;"

    for listen_directive in ("listen 80;", "listen 443 ssl http2;"):
        server = _only_server(listen_directive)
        for selector in ("^~ /a/", "= /reset-password"):
            location = _only_location(server, selector)
            directives = _directives(location.body)

            assert directives.count(gate) == 1
            assert directives[0] == gate


def test_http_sensitive_locations_redirect_without_leaking_referrers_or_errors() -> None:
    http = _only_server("listen 80;")
    gate = "include /etc/nginx/kivou-sensitive-links-gate.conf;"
    no_referrer = 'add_header Referrer-Policy "no-referrer" always;'
    suppressed_error_log = "error_log /dev/null crit;"
    canonical_redirect = "return 301 https://STAGING_HOST$request_uri;"

    for selector in ("^~ /a/", "= /reset-password"):
        location = _only_location(http, selector)
        directives = _directives(location.body)

        for expected in (
            gate,
            no_referrer,
            suppressed_error_log,
            canonical_redirect,
        ):
            assert directives.count(expected) == 1
        assert not any(
            directive.startswith(("proxy_pass ", "try_files "))
            for directive in directives
        )


def test_https_attribution_is_sensitive_and_preserves_its_proxy_contract() -> None:
    https = _only_server("listen 443 ssl http2;")
    attribution = _only_location(https, "^~ /a/")
    directives = _directives(attribution.body)

    for expected in (
        "include /etc/nginx/kivou-sensitive-links-gate.conf;",
        "limit_req zone=kivou_api burst=40 nodelay;",
        "include /etc/nginx/kivou-sensitive-link-security-headers.conf;",
        "error_log /dev/null crit;",
        "proxy_pass http://127.0.0.1:KIVOU_API_PORT;",
        "include /etc/nginx/kivou-proxy-params.conf;",
    ):
        assert directives.count(expected) == 1
    assert _directives_starting_with(
        attribution.body, "proxy_hide_header "
    ) == ("proxy_hide_header Referrer-Policy;",)
    assert _directives_starting_with(attribution.body, "proxy_pass ") == (
        "proxy_pass http://127.0.0.1:KIVOU_API_PORT;",
    )
    assert not any(
        directive.startswith("try_files ") for directive in directives
    )


def test_https_reset_page_is_sensitive_no_cache_and_not_a_generic_spa_route() -> None:
    https = _only_server("listen 443 ssl http2;")
    reset = _only_location(https, "= /reset-password")
    directives = _directives(reset.body)

    for expected in (
        "include /etc/nginx/kivou-sensitive-links-gate.conf;",
        "include /etc/nginx/kivou-sensitive-link-security-headers.conf;",
        'add_header Cache-Control "no-cache" always;',
        "error_log /dev/null crit;",
    ):
        assert directives.count(expected) == 1
    assert _directives_starting_with(reset.body, "try_files ") == (
        "try_files /index.html =404;",
    )
    assert not any(
        directive.startswith("proxy_pass ") for directive in directives
    )
    assert "include /etc/nginx/kivou-proxy-params.conf;" not in directives


def test_sensitive_locations_have_one_effective_no_referrer_policy() -> None:
    sensitive_path = NGINX_DIR / "kivou-sensitive-link-security-headers.conf"
    assert sensitive_path.is_file(), f"missing nginx fragment: {sensitive_path}"

    sensitive_include = (
        "include /etc/nginx/kivou-sensitive-link-security-headers.conf;"
    )
    ordinary_include = "include /etc/nginx/kivou-security-headers.conf;"
    sensitive_headers = _header_directives(sensitive_path)
    expected_policy = 'add_header Referrer-Policy "no-referrer" always;'
    locations: list[LocationBlock] = []

    for listen_directive in ("listen 80;", "listen 443 ssl http2;"):
        server = _only_server(listen_directive)
        locations.extend(
            _only_location(server, selector)
            for selector in ("^~ /a/", "= /reset-password")
        )

    for location in locations:
        directives = _directives(location.body)
        effective_headers = tuple(
            directive
            for directive in directives
            if directive.startswith("add_header ")
        )
        if sensitive_include in directives:
            effective_headers += sensitive_headers
        policies = tuple(
            directive
            for directive in effective_headers
            if directive.startswith("add_header Referrer-Policy ")
        )

        assert ordinary_include not in directives
        assert policies == (expected_policy,)

    https = _only_server("listen 443 ssl http2;")
    attribution = _only_location(https, "^~ /a/")
    assert _directives_starting_with(
        attribution.body, "proxy_hide_header Referrer-Policy"
    ) == ("proxy_hide_header Referrer-Policy;",)


def test_sensitive_routes_leave_ordinary_location_contracts_unchanged() -> None:
    http = _only_server("listen 80;")
    https = _only_server("listen 443 ssl http2;")
    ordinary_include = "include /etc/nginx/kivou-security-headers.conf;"

    assert _directives(
        _only_location(http, "/.well-known/acme-challenge/").body
    ) == ("root /var/www/certbot;",)
    assert _directives(_only_location(http, "/").body) == (
        "return 301 https://STAGING_HOST$request_uri;",
    )
    assert _directives(_only_location(https, "/assets/").body) == (
        ordinary_include,
        'add_header Cache-Control "public, max-age=31536000, immutable" always;',
        "try_files $uri =404;",
    )
    assert _directives(_only_location(https, "/brand/").body) == (
        ordinary_include,
        'add_header Cache-Control "public, max-age=2592000" always;',
        "try_files $uri =404;",
    )
    assert _directives(_only_location(https, "= /index.html").body) == (
        ordinary_include,
        'add_header Cache-Control "no-cache" always;',
    )
    assert _directives(_only_location(https, "/").body) == (
        "try_files $uri $uri/ /index.html;",
    )

    for location in _proxy_locations():
        if location.selector == "^~ /a/":
            continue
        directives = _directives(location.body)
        assert not any(
            "kivou-sensitive-link" in directive for directive in directives
        )
        assert not any(
            directive.startswith("error_log /dev/null")
            for directive in directives
        )


def test_nginx_template_header_delegates_installation_to_atomic_runbook() -> None:
    header = "\n".join(_site_text().splitlines()[:20])

    assert "ops/README.md" in header
    assert "sudo tee /etc/nginx/sites-available/kivou" not in header


def test_http_redirect_uses_the_canonical_host_not_the_request_host() -> None:
    site = _site_text()

    assert "return 301 https://STAGING_HOST$request_uri;" in site
    assert "return 301 https://$host$request_uri;" not in site


def test_every_reviewed_public_route_reaches_fastapi_and_private_routes_do_not() -> None:
    proxy_locations = _proxy_locations()

    assert frozenset(block.selector for block in proxy_locations) == EXPECTED_PROXY_SELECTORS
    for _, route_path in PUBLIC_ASGI_ROUTES:
        sample = _sample_path(route_path)
        assert any(_matches(block.selector, sample) for block in proxy_locations), route_path
    for _, route_path in PRIVATE_ASGI_ROUTES:
        sample = _sample_path(route_path)
        assert not any(_matches(block.selector, sample) for block in proxy_locations), route_path
    for block in proxy_locations:
        assert any(
            _matches(block.selector, _sample_path(route_path))
            for _, route_path in PUBLIC_ASGI_ROUTES
        ), block.selector
        assert _directives_starting_with(block.body, "proxy_pass ") == (
            "proxy_pass http://127.0.0.1:KIVOU_API_PORT;",
        )
        assert "include /etc/nginx/kivou-proxy-params.conf;" in block.body
        assert "try_files" not in block.body


def test_instantly_and_attribution_use_exact_reviewed_locations_and_limits() -> None:
    https = _only_server("listen 443 ssl http2;")
    instantly = _only_location(https, "= /webhooks/instantly")
    attribution = _only_location(https, "^~ /a/")

    assert "limit_req zone=kivou_hook burst=100 nodelay;" in instantly.body
    assert "limit_req zone=kivou_api burst=40 nodelay;" in attribution.body


def test_nginx_allowlist_includes_companies_but_not_internal_or_stale_health() -> None:
    proxy_selectors = frozenset(block.selector for block in _proxy_locations())
    grouped = next(selector for selector in proxy_selectors if selector.startswith("~ "))

    assert "companies" in grouped
    assert "internal" not in grouped
    assert "health" not in grouped
    assert all("/internal" not in selector for selector in proxy_selectors)


def test_safe_access_log_uses_only_allowlisted_transport_variables() -> None:
    limits = (NGINX_DIR / "kivou-limits.conf").read_text()
    body = _log_format_body(limits, "kivou_safe_json")
    variables = set(re.findall(r"\$[a-zA-Z0-9_]+", body))

    assert variables == {
        "$remote_addr",
        "$time_iso8601",
        "$request_method",
        "$kivou_safe_request_path",
        "$server_protocol",
        "$status",
        "$body_bytes_sent",
        "$request_time",
    }
    for forbidden in (
        "$request",
        "$request_uri",
        "$args",
        "$http_referer",
        "$http_user_agent",
        "$http_cookie",
    ):
        assert forbidden not in variables
    assert not any(
        variable.startswith(("$http_", "$upstream_http_"))
        for variable in variables
    )


def test_safe_path_map_redacts_attribution_and_uses_normalized_uri_elsewhere() -> None:
    limits = (NGINX_DIR / "kivou-limits.conf").read_text()

    assert _map_directives(
        limits, "$uri", "$kivou_safe_path_map"
    ) == (
        "~^/a/ /a/[redacted];",
        "/reset-password /reset-password;",
        "default $uri;",
    )
    assert "volatile;" not in limits
    assert "$request_uri" not in limits


def test_both_public_servers_select_one_safe_access_log() -> None:
    site = _site_text()
    snapshot = "set $kivou_safe_request_path $kivou_safe_path_map;"
    expected = "access_log /var/log/nginx/access.log kivou_safe_json;"

    assert site.count(expected) == 2
    assert site.count(snapshot) == 2
    for server in (
        _only_server("listen 80;"),
        _only_server("listen 443 ssl http2;"),
    ):
        direct = _direct_server_directives(server.body)
        safe_path_assignments = _directives_starting_with(
            server.body, "set $kivou_safe_request_path "
        )
        access_logs = tuple(
            directive
            for directive in _directives(server.body)
            if re.match(r"access_log(?:\s|;)", directive)
        )

        assert direct.count(snapshot) == 1
        assert direct.count(expected) == 1
        assert direct.index(snapshot) < direct.index(expected)
        assert safe_path_assignments == (snapshot,)
        assert access_logs == (expected,)


def test_nginx_keeps_existing_rate_proxy_and_security_contracts() -> None:
    limits = (NGINX_DIR / "kivou-limits.conf").read_text()
    proxy = (NGINX_DIR / "kivou-proxy-params.conf").read_text()
    security = (NGINX_DIR / "kivou-security-headers.conf").read_text()
    site = _site_text()

    for expected in (
        "zone=kivou_auth:10m  rate=5r/m;",
        "zone=kivou_reset:10m rate=3r/m;",
        "zone=kivou_api:10m   rate=120r/m;",
        "zone=kivou_hook:10m  rate=300r/m;",
        "limit_req_status 429;",
        "limit_conn_status 429;",
    ):
        assert expected in limits
    for expected in (
        "proxy_http_version 1.1;",
        "proxy_set_header Host              $host;",
        "proxy_set_header X-Real-IP         $remote_addr;",
        "proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;",
        "proxy_set_header X-Forwarded-Proto $scheme;",
        "proxy_set_header X-Forwarded-Host  $host;",
        "proxy_set_header Origin            $http_origin;",
        "proxy_connect_timeout 5s;",
        "proxy_send_timeout    30s;",
        "proxy_read_timeout    30s;",
        "proxy_buffering off;",
        "proxy_redirect off;",
    ):
        assert expected in proxy
    for expected in (
        'add_header X-Content-Type-Options "nosniff" always;',
        'add_header Referrer-Policy "strict-origin-when-cross-origin" always;',
        'add_header X-Frame-Options "DENY" always;',
        "add_header Permissions-Policy",
        "add_header Content-Security-Policy",
        "add_header Strict-Transport-Security",
    ):
        assert expected in security
    for expected in (
        "listen 443 ssl http2;",
        "client_max_body_size 1m;",
        "client_body_timeout 15s;",
        "client_header_timeout 15s;",
        "include /etc/nginx/kivou-security-headers.conf;",
        "location /assets/ {",
        "location /brand/ {",
        "location = /index.html {",
        "try_files $uri $uri/ /index.html;",
    ):
        assert expected in site
