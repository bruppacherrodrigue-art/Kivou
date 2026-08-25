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
        ("GET", "/companies/{company_key}"),
        ("GET", "/me"),
        ("GET", "/notification-preferences"),
        ("PATCH", "/notification-preferences"),
        ("GET", "/signals"),
        ("GET", "/signals/{signal_key}"),
        ("GET", "/signals/{signal_key}/feedback"),
        ("POST", "/signals/{signal_key}/contacted"),
        ("PUT", "/signals/{signal_key}/feedback"),
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


def _proxy_locations() -> tuple[LocationBlock, ...]:
    return tuple(block for block in _location_blocks(_site_text()) if "proxy_pass" in block.body)


def _only_location(selector: str) -> LocationBlock:
    matching = [block for block in _location_blocks(_site_text()) if block.selector == selector]
    assert len(matching) == 1, f"expected one nginx location {selector!r}, got {len(matching)}"
    return matching[0]


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
        assert "proxy_pass http://127.0.0.1:8000;" in block.body
        assert "include /etc/nginx/kivou-proxy-params.conf;" in block.body
        assert "try_files" not in block.body


def test_instantly_and_attribution_use_exact_reviewed_locations_and_limits() -> None:
    instantly = _only_location("= /webhooks/instantly")
    attribution = _only_location("^~ /a/")

    assert "limit_req zone=kivou_hook burst=100 nodelay;" in instantly.body
    assert "limit_req zone=kivou_api burst=40 nodelay;" in attribution.body


def test_nginx_allowlist_includes_companies_but_not_internal_or_stale_health() -> None:
    proxy_selectors = frozenset(block.selector for block in _proxy_locations())
    grouped = next(selector for selector in proxy_selectors if selector.startswith("~ "))

    assert "companies" in grouped
    assert "internal" not in grouped
    assert "health" not in grouped
    assert all("/internal" not in selector for selector in proxy_selectors)


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
