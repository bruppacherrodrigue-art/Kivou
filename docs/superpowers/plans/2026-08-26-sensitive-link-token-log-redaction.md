# Sensitive Link Token Log Redaction Implementation Plan

Status: implementation complete; local validation passed; PR pending

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent attribution and password-reset bearer tokens from entering nginx or Uvicorn logs while preserving public routing, operational evidence, atomic staging rollout, and a security-preserving rollback.

**Architecture:** Nginx becomes the sole public access-log authority. An HTTP-scope map and JSON log format retain only a normalized safe path and bounded transport metadata; dedicated sensitive locations suppress unsafe error logging and enforce `Referrer-Policy: no-referrer`; Uvicorn access logging is disabled in the versioned API unit. A root-owned include acts as a fail-closed gate for all sensitive locations, and the runbook switches the API blue/green while never rolling the safe logging floor back.

**Tech Stack:** nginx 1.24-compatible configuration, systemd 255-compatible units, Python 3.12, pytest, Ruff, Git, curl.

---

## File map

- Modify `tests/test_ops_nginx_routes.py`: server-aware nginx parsing and all safe-log, sensitive-location, header-parity, gate, routing, and port-template contracts.
- Modify `ops/nginx/kivou-limits.conf`: HTTP-scope safe-path map and `escape=json` access-log format.
- Modify `ops/nginx/kivou-staging.conf`: explicit safe access log in both servers, four sensitive locations, and the reviewed `KIVOU_API_PORT` template token.
- Create `ops/nginx/kivou-sensitive-link-security-headers.conf`: HTTPS security headers matching the standard fragment except for `no-referrer`.
- Create `ops/nginx/kivou-sensitive-links-open.conf`: inert gate candidate.
- Create `ops/nginx/kivou-sensitive-links-closed.conf`: exact fail-closed `return 503;` candidate.
- Create `tests/test_ops_api_runtime.py`: reproducible API systemd contract.
- Create `ops/systemd/kivou-api.service`: the audited staging API unit with exactly one `--no-access-log` addition.
- Create `tests/test_sensitive_link_logging_runbook.py`: executable rollout, marker-proof, and security-floor rollback architecture tests.
- Modify `ops/README.md`: exact candidate rendering, blue/green deployment, synthetic validation, gate operation, and safe rollback commands.
- Modify `docs/superpowers/specs/2026-08-26-attribution-token-log-redaction-design.md`: mark implementation delivered only after every final verification passes.

### Task 1: Make nginx access evidence safe by construction

**Files:**
- Modify: `tests/test_ops_nginx_routes.py`
- Modify: `ops/nginx/kivou-limits.conf`
- Modify: `ops/nginx/kivou-staging.conf`

- [ ] **Step 1: Add server-aware test helpers before changing nginx**

Add a `ServerBlock` dataclass and parser beside `LocationBlock`:

```python
@dataclass(frozen=True)
class ServerBlock:
    body: str


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
```

Change `_proxy_locations()` to inspect only `_only_server("listen 443 ssl http2;").body`, and update existing `_only_location` calls to pass that HTTPS server. This characterizes the current proxy inventory while allowing duplicate sensitive selectors in the HTTP server later.

- [ ] **Step 2: Add failing access-log tests**

Add these tests before editing either nginx file:

```python
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
        assert server.body.count(expected) == 1
        assert server.body.count(snapshot) == 1
        assert server.body.index(snapshot) < server.body.index(expected)
        assert " combined;" not in server.body
        assert all(
            "access_log" not in location.body
            for location in _location_blocks(server.body)
        )
```

- [ ] **Step 3: Run RED and record the expected failure**

Run:

```bash
uv run pytest -q tests/test_ops_nginx_routes.py
```

Expected: the new tests fail because `kivou_safe_json`, the safe-path map, and the two explicit server access logs do not exist. Existing routing tests must still pass.

- [ ] **Step 4: Add the minimal safe map and access format**

Append this HTTP-scope configuration to `ops/nginx/kivou-limits.conf`:

```nginx
map $uri $kivou_safe_path_map {
    ~^/a/ /a/[redacted];
    /reset-password /reset-password;
    default $uri;
}

log_format kivou_safe_json escape=json '{"remote_addr":"$remote_addr","time":"$time_iso8601","method":"$request_method","path":"$kivou_safe_request_path","protocol":"$server_protocol","status":$status,"bytes":$body_bytes_sent,"duration":$request_time}';
```

Keep `log_format` on one physical line: the existing tracked-template syntax
test intentionally requires each active line to end in `;`, `{`, or `}`.

Add these directives exactly once, in this order, inside each `server` block in
`ops/nginx/kivou-staging.conf`:

```nginx
set $kivou_safe_request_path $kivou_safe_path_map;
access_log /var/log/nginx/access.log kivou_safe_json;
```

The `set` forces the non-volatile map to cache the original normalized safe
path before location processing. Do not add `volatile`, a location-level access
log, or `combined` as a second destination.

- [ ] **Step 5: Run GREEN and commit the cycle**

Run:

```bash
uv run pytest -q tests/test_ops_nginx_routes.py
uv run ruff check tests/test_ops_nginx_routes.py
```

Expected: all nginx contract tests pass and Ruff exits 0.

```bash
git add tests/test_ops_nginx_routes.py ops/nginx/kivou-limits.conf \
  ops/nginx/kivou-staging.conf
git commit -m "fix(ops): sanitize public nginx access logs"
```

### Task 2: Close every sensitive response, referer, and error-log path

**Files:**
- Modify: `tests/test_ops_nginx_routes.py`
- Modify: `ops/nginx/kivou-staging.conf`
- Create: `ops/nginx/kivou-sensitive-link-security-headers.conf`
- Create: `ops/nginx/kivou-sensitive-links-open.conf`
- Create: `ops/nginx/kivou-sensitive-links-closed.conf`

- [ ] **Step 1: Add failing sensitive-location and gate tests**

Reuse `_directives` from Task 1 and add the ordered `add_header` helper:

```python
def _header_directives(path: Path) -> tuple[str, ...]:
    return tuple(
        directive
        for directive in _directives(path.read_text())
        if directive.startswith("add_header ")
    )
```

Then add these contracts:

```python
def test_sensitive_header_fragment_only_strengthens_referrer_policy() -> None:
    ordinary = _header_directives(NGINX_DIR / "kivou-security-headers.conf")
    sensitive = _header_directives(
        NGINX_DIR / "kivou-sensitive-link-security-headers.conf"
    )
    expected_sensitive = tuple(
        'add_header Referrer-Policy "no-referrer" always;'
        if item.startswith("add_header Referrer-Policy ")
        else item
        for item in ordinary
    )

    assert sensitive == expected_sensitive
    assert ordinary.count(
        'add_header Referrer-Policy "strict-origin-when-cross-origin" always;'
    ) == 1
    assert sensitive.count(
        'add_header Referrer-Policy "no-referrer" always;'
    ) == 1


def test_all_sensitive_locations_share_the_same_fail_closed_gate() -> None:
    gate = "include /etc/nginx/kivou-sensitive-links-gate.conf;"
    for server in (
        _only_server("listen 80;"),
        _only_server("listen 443 ssl http2;"),
    ):
        for selector in ("^~ /a/", "= /reset-password"):
            location = _only_location(server, selector)
            assert location.body.count(gate) == 1
            assert _directives(location.body)[0] == gate

    assert _directives(
        (NGINX_DIR / "kivou-sensitive-links-open.conf").read_text()
    ) == ()
    assert _directives(
        (NGINX_DIR / "kivou-sensitive-links-closed.conf").read_text()
    ) == ("return 503;",)


def test_http_sensitive_locations_redirect_without_proxying_or_static_fallback() -> None:
    server = _only_server("listen 80;")
    for selector in ("^~ /a/", "= /reset-password"):
        body = _only_location(server, selector).body
        assert 'add_header Referrer-Policy "no-referrer" always;' in body
        assert "error_log /dev/null crit;" in body
        assert "return 301 https://STAGING_HOST$request_uri;" in body
        assert "proxy_pass" not in body
        assert "try_files" not in body


def test_https_attribution_is_proxied_with_safe_headers_and_error_policy() -> None:
    body = _only_location(
        _only_server("listen 443 ssl http2;"), "^~ /a/"
    ).body

    assert "limit_req zone=kivou_api burst=40 nodelay;" in body
    assert "proxy_pass http://127.0.0.1:8000;" in body
    assert "include /etc/nginx/kivou-proxy-params.conf;" in body
    assert "proxy_hide_header Referrer-Policy;" in body
    assert "include /etc/nginx/kivou-sensitive-link-security-headers.conf;" in body
    assert "error_log /dev/null crit;" in body
    assert "try_files" not in body


def test_https_reset_entry_serves_only_non_cached_spa_with_safe_headers() -> None:
    body = _only_location(
        _only_server("listen 443 ssl http2;"), "= /reset-password"
    ).body

    assert "include /etc/nginx/kivou-sensitive-link-security-headers.conf;" in body
    assert 'add_header Cache-Control "no-cache" always;' in body
    assert "error_log /dev/null crit;" in body
    assert "try_files /index.html =404;" in body
    assert "proxy_pass" not in body
    assert "try_files $uri $uri/ /index.html;" not in body


def test_each_sensitive_location_emits_exactly_one_no_referrer_policy() -> None:
    sensitive_headers = _header_directives(
        NGINX_DIR / "kivou-sensitive-link-security-headers.conf"
    )
    no_referrer = 'add_header Referrer-Policy "no-referrer" always;'

    for server in (
        _only_server("listen 80;"),
        _only_server("listen 443 ssl http2;"),
    ):
        for selector in ("^~ /a/", "= /reset-password"):
            location = _only_location(server, selector)
            directives = list(_directives(location.body))
            assert "include /etc/nginx/kivou-security-headers.conf;" not in directives
            if "include /etc/nginx/kivou-sensitive-link-security-headers.conf;" in directives:
                directives.extend(sensitive_headers)
            assert directives.count(no_referrer) == 1

    attribution = _only_location(
        _only_server("listen 443 ssl http2;"), "^~ /a/"
    )
    assert attribution.body.count("proxy_hide_header Referrer-Policy;") == 1


def test_ordinary_static_and_spa_routes_keep_their_exact_contracts() -> None:
    http = _only_server("listen 80;")
    https = _only_server("listen 443 ssl http2;")

    assert "root /var/www/certbot;" in _only_location(
        http, "/.well-known/acme-challenge/"
    ).body
    assert "return 301 https://STAGING_HOST$request_uri;" in _only_location(
        http, "/"
    ).body
    assert "try_files $uri =404;" in _only_location(https, "/assets/").body
    assert "max-age=31536000, immutable" in _only_location(
        https, "/assets/"
    ).body
    assert "try_files $uri =404;" in _only_location(https, "/brand/").body
    assert "max-age=2592000" in _only_location(https, "/brand/").body
    assert 'add_header Cache-Control "no-cache" always;' in _only_location(
        https, "= /index.html"
    ).body
    assert "try_files $uri $uri/ /index.html;" in _only_location(
        https, "/"
    ).body
    for location in _proxy_locations():
        if location.selector == "^~ /a/":
            continue
        assert "kivou-sensitive-link" not in location.body
        assert "error_log /dev/null" not in location.body
```

Also retain the existing route-inventory assertions so HTTPS `/a/` remains the only new FastAPI proxy and neither HTTP sensitive location becomes a backend route.

- [ ] **Step 2: Run RED and verify the missing boundary is the cause**

Run:

```bash
uv run pytest -q tests/test_ops_nginx_routes.py
```

Expected: failures report the three missing fragments, missing HTTP sensitive locations, missing reset HTTPS location, and missing hardened directives.

- [ ] **Step 3: Create the exact header and gate fragments**

Create `ops/nginx/kivou-sensitive-link-security-headers.conf` by copying every `add_header` directive from `kivou-security-headers.conf` and changing only:

```nginx
add_header Referrer-Policy "no-referrer" always;
```

Create `ops/nginx/kivou-sensitive-links-open.conf` as a comment-only inert file:

```nginx
# Intentionally empty: sensitive links are open.
```

Create `ops/nginx/kivou-sensitive-links-closed.conf` with exactly:

```nginx
return 503;
```

- [ ] **Step 4: Add the four explicit sensitive locations**

Before the generic HTTP `/` redirect, add:

```nginx
location ^~ /a/ {
    include /etc/nginx/kivou-sensitive-links-gate.conf;
    add_header Referrer-Policy "no-referrer" always;
    error_log /dev/null crit;
    return 301 https://STAGING_HOST$request_uri;
}

location = /reset-password {
    include /etc/nginx/kivou-sensitive-links-gate.conf;
    add_header Referrer-Policy "no-referrer" always;
    error_log /dev/null crit;
    return 301 https://STAGING_HOST$request_uri;
}
```

Replace the HTTPS attribution block with:

```nginx
location ^~ /a/ {
    include /etc/nginx/kivou-sensitive-links-gate.conf;
    limit_req zone=kivou_api burst=40 nodelay;
    proxy_hide_header Referrer-Policy;
    include /etc/nginx/kivou-sensitive-link-security-headers.conf;
    error_log /dev/null crit;
    proxy_pass http://127.0.0.1:8000;
    include /etc/nginx/kivou-proxy-params.conf;
}
```

Before `location = /index.html`, add:

```nginx
location = /reset-password {
    include /etc/nginx/kivou-sensitive-links-gate.conf;
    include /etc/nginx/kivou-sensitive-link-security-headers.conf;
    add_header Cache-Control "no-cache" always;
    error_log /dev/null crit;
    try_files /index.html =404;
}
```

- [ ] **Step 5: Run GREEN, inspect retained behavior, and commit**

Run:

```bash
uv run pytest -q tests/test_ops_nginx_routes.py
uv run ruff check tests/test_ops_nginx_routes.py
git diff --check
```

Expected: all tests pass; the grouped API, auth/reset APIs, webhooks, assets, brand, index, and SPA contracts remain unchanged.

```bash
git add tests/test_ops_nginx_routes.py ops/nginx
git commit -m "fix(ops): isolate sensitive link routing and headers"
```

### Task 3: Version the audited API runtime without duplicate access logs

**Files:**
- Create: `tests/test_ops_api_runtime.py`
- Create: `ops/systemd/kivou-api.service`

- [ ] **Step 1: Write the failing service contract**

Create `tests/test_ops_api_runtime.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "ops" / "systemd" / "kivou-api.service"


def test_api_service_versions_the_audited_staging_runtime() -> None:
    body = SERVICE.read_text(encoding="utf-8")

    for expected in (
        "Type=exec",
        "User=kivou",
        "Group=kivou",
        "WorkingDirectory=/srv/kivou/app",
        "EnvironmentFile=/etc/kivou/staging.env",
        "ExecStart=/srv/kivou/app/.venv/bin/uvicorn signals.api.asgi:app",
        "--host 127.0.0.1",
        "--port 8000",
        "--workers 2",
        "--proxy-headers",
        "--forwarded-allow-ips 127.0.0.1",
        "--no-server-header",
        "--timeout-keep-alive 20",
        "Restart=on-failure",
        "RestartSec=5s",
        "StandardOutput=journal",
        "StandardError=journal",
        "SyslogIdentifier=kivou-api",
        "WantedBy=multi-user.target",
    ):
        assert expected in body


def test_api_service_disables_only_uvicorn_access_logging() -> None:
    body = SERVICE.read_text(encoding="utf-8")

    assert body.count("--no-access-log") == 1
    for forbidden in (
        "--log-level critical",
        "--log-config",
        "StandardOutput=null",
        "StandardError=null",
        "KIVOU_DATABASE_URL=",
        "SMTP_PASSWORD=",
    ):
        assert forbidden not in body


def test_api_service_preserves_the_deployed_hardening_contract() -> None:
    body = SERVICE.read_text(encoding="utf-8")

    for directive in (
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
    ):
        assert directive in body
```

- [ ] **Step 2: Run RED**

Run:

```bash
uv run pytest -q tests/test_ops_api_runtime.py
```

Expected: `FileNotFoundError` because the API unit is not yet versioned on this branch.

- [ ] **Step 3: Add the reviewed unit with one minimal command change**

Create `ops/systemd/kivou-api.service` from the audited staging unit. Keep every deployed directive and add `--no-access-log` between `--no-server-header` and `--timeout-keep-alive 20` in `ExecStart`. Do not add a migration command, environment value, alternate logger, timer, socket unit, or second API service.

- [ ] **Step 4: Run GREEN and commit**

Run:

```bash
uv run pytest -q tests/test_ops_api_runtime.py
uv run ruff check tests/test_ops_api_runtime.py
```

Expected: 3 tests pass and Ruff exits 0.

```bash
git add tests/test_ops_api_runtime.py ops/systemd/kivou-api.service
git commit -m "fix(ops): disable duplicate uvicorn access logs"
```

### Task 4: Make the staging transition and rollback executable

**Files:**
- Modify: `tests/test_ops_nginx_routes.py`
- Create: `tests/test_sensitive_link_logging_runbook.py`
- Modify: `ops/nginx/kivou-staging.conf`
- Modify: `ops/README.md`

- [ ] **Step 1: Write failing port-template and runbook tests**

Change both the generic HTTPS proxy-loop assertion and the dedicated HTTPS
attribution assertion in `tests/test_ops_nginx_routes.py` to require:

```python
assert "proxy_pass http://127.0.0.1:KIVOU_API_PORT;" in block.body
```

Create `tests/test_sensitive_link_logging_runbook.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "ops" / "README.md"


def _assert_in_order(body: str, *needles: str) -> None:
    cursor = -1
    for needle in needles:
        cursor = body.index(needle, cursor + 1)


def test_runbook_renders_host_port_includes_and_open_gate_into_one_candidate() -> None:
    body = RUNBOOK.read_text(encoding="utf-8")

    for required in (
        "KIVOU_API_PORT=8001",
        '(*[!0-9]*|\'\')',
        "s/KIVOU_API_PORT/$KIVOU_API_PORT/g",
        "kivou-sensitive-link-security-headers.conf",
        "kivou-sensitive-links-open.conf",
        "kivou-sensitive-links-gate.conf",
        "nginx -t -c",
    ):
        assert required in body


def test_runbook_performs_one_blue_green_public_transition_before_port_8000_restart() -> None:
    body = RUNBOOK.read_text(encoding="utf-8")

    _assert_in_order(
        body,
        "uv sync --frozen --extra server --extra postgres",
        "--unit=kivou-api-green",
        "--port 8001",
        'http://127.0.0.1:8001/openapi.json',
        'http://127.0.0.1:8001/me',
        "sudo systemctl reload nginx",
        "sudo mv -Tf /srv/kivou/app.next /srv/kivou/app",
        "sudo systemctl restart kivou-api.service",
        'http://127.0.0.1:8000/openapi.json',
        "KIVOU_API_PORT=8000",
        "sudo systemctl stop kivou-api-green.service",
    )
    assert "--property=EnvironmentFile=/etc/kivou/staging.env" in body
    assert "--no-access-log" in body


def test_runbook_proves_markers_before_any_valid_sensitive_token() -> None:
    body = RUNBOOK.read_text(encoding="utf-8")

    _assert_in_order(
        body,
        "KIVOU_SYNTHETIC_ATTRIBUTION_MARKER=",
        "KIVOU_SYNTHETIC_RESET_MARKER=",
        "Referrer-Policy: no-referrer",
        "marker_occurrences=0",
        "separately authorized valid attribution proof",
    )
    assert "reset e-mail" in body
    assert "KIVOU_VALID_ATTRIBUTION_TOKEN=" not in body


def test_rollback_keeps_safe_nginx_api_unit_and_can_close_sensitive_routes() -> None:
    body = RUNBOOK.read_text(encoding="utf-8")

    for required in (
        "kivou-sensitive-links-closed.conf",
        "return 503;",
        "security floor",
        "--no-access-log",
        "previous application release",
        "Never restore the old nginx access format or the old API unit.",
    ):
        assert required in body
```

Keep the exact string literals aligned with the final French runbook; if wording is French, retain the machine tokens above and use explicit English guard sentences exactly where asserted.

- [ ] **Step 2: Run RED**

Run:

```bash
uv run pytest -q \
  tests/test_ops_nginx_routes.py \
  tests/test_sensitive_link_logging_runbook.py
```

Expected: failures because the proxy uses literal port 8000 and the existing #84 runbook lacks the sensitive bundle, blue/green API transition, marker proof, gate, and security-floor rollback.

- [ ] **Step 3: Parameterize only the reviewed API destination**

Replace every reviewed backend destination in `ops/nginx/kivou-staging.conf` with:

```nginx
proxy_pass http://127.0.0.1:KIVOU_API_PORT;
```

Do not change selectors, rate limits, proxy parameters, or add a catch-all proxy. `STAGING_HOST` and `KIVOU_API_PORT` are the only site-template substitutions.

- [ ] **Step 4: Replace the #84 operations section with the exact safe procedure**

The rewritten `ops/README.md` section must contain executable command blocks for all of these ordered operations:

1. Validate `KIVOU_STAGING_HOST` and a numeric `KIVOU_API_PORT` of `8001` or `8000`.
2. Copy all six immutable nginx fragments into a root-only candidate directory; copy the open fragment to the candidate name `kivou-sensitive-links-gate.conf`.
3. Render `STAGING_HOST`, `KIVOU_API_PORT`, and each candidate include path into the candidate site without placing a secret in an argument.
4. Run isolated candidate `nginx -t` with limits and the rendered site.
5. Build an explicit reviewed SHA into `/srv/kivou/releases/backend-<UTC>-<short-sha>` as user `kivou` using `uv sync --frozen --extra server --extra postgres`.
6. Start `kivou-api-green` on loopback 8001 using `systemd-run`, `/etc/kivou/staging.env`, the new release, the normal hardening properties, two workers, and `--no-access-log`.
7. Require 200 from `http://127.0.0.1:8001/openapi.json` and 401 from `http://127.0.0.1:8001/me`.
8. Snapshot active nginx files, active gate, current `/srv/kivou/app` target, and API unit in a root-only unique directory.
9. Install safe includes and the open gate through same-directory `.new` files and `mv -f`, run live `nginx -t`, then perform the single public reload to green.
10. Monitor public `/me` and require only 401 while atomically switching `/srv/kivou/app.next`, installing `ops/systemd/kivou-api.service`, reloading systemd, and restarting the normal 8000 API.
11. Require 200/401 from normal 8000, render and validate the final nginx candidate at `KIVOU_API_PORT=8000`, publish it, reload, verify public traffic, then stop/collect green.
12. Exercise HTTP and HTTPS attribution/reset URLs with unique synthetic markers, make an asset request carrying the synthetic reset URL as `Referer`, and inspect nginx access/error logs plus `journalctl -u kivou-api` from the recorded boundary. Emit only counts and require `marker_occurrences=0`; require sanitized `/a/[redacted]` and `/reset-password` access evidence and exactly one `Referrer-Policy: no-referrer` per sensitive response.
13. State that the separately authorized valid attribution proof runs only after synthetic PASS and keeps the real token entirely in process memory. State that #93 needs no new reset e-mail.
14. To close sensitive routes, atomically install the closed fragment as the active gate, run `nginx -t`, and reload. Reopening does the same with the inert open fragment.
15. For application rollback, keep safe nginx and the versioned `--no-access-log` unit, switch only to the recorded previous application release while green carries traffic, validate port 8000, then repoint safe nginx.
16. If safe routing cannot be retained, close the gate and keep the rest of staging available. Never restore the old nginx access format or old API unit; label those artifacts evidence only and the new boundary the `security floor`.

Use `install`, candidate files, and same-filesystem `mv`; never use a blanket repository replacement, destructive reset, secret argument, or production path.

- [ ] **Step 5: Run GREEN and commit**

Run:

```bash
uv run pytest -q \
  tests/test_ops_nginx_routes.py \
  tests/test_ops_api_runtime.py \
  tests/test_sensitive_link_logging_runbook.py
uv run ruff check \
  tests/test_ops_nginx_routes.py \
  tests/test_ops_api_runtime.py \
  tests/test_sensitive_link_logging_runbook.py
git diff --check
```

Expected: all focused tests pass, Ruff exits 0, and diff checking is clean.

```bash
git add ops/README.md ops/nginx/kivou-staging.conf \
  tests/test_ops_nginx_routes.py tests/test_sensitive_link_logging_runbook.py
git commit -m "docs(ops): version safe blue green API rollout"
```

### Task 5: Final verification, independent review, and delivery

**Files:**
- Modify: `docs/superpowers/specs/2026-08-26-attribution-token-log-redaction-design.md`
- Review: every file changed from `81f6b76ef447b23a4ba538d9a0fab95a5558d863`

- [ ] **Step 1: Run the focused behavior and regression suites freshly**

Run:

```bash
uv run pytest -q \
  tests/test_ops_nginx_routes.py \
  tests/test_ops_api_runtime.py \
  tests/test_sensitive_link_logging_runbook.py \
  tests/test_conversion_attribution_api.py \
  tests/test_api_runtime.py
uv run ruff check .
```

Expected: all selected tests pass and Ruff reports no errors.

- [ ] **Step 2: Validate systemd/nginx syntax in the environment that owns the executables**

On staging, before any publication, run the reviewed candidate validation from Task 4 and:

```bash
sudo systemd-analyze verify ops/systemd/kivou-api.service
```

Expected: exit 0. If local nginx is unavailable, do not claim local `nginx -t`; the root-only staging candidate check is mandatory before reload.

- [ ] **Step 3: Run the standard backend validation once on final HEAD**

Run:

```bash
uv run pytest
git diff --check
git status --short
```

Expected: full pytest passes, no whitespace errors, and only the intended branch changes are present. No frontend command is required because no frontend file changes.

- [ ] **Step 4: Complete independent spec and quality reviews**

Review the full diff against the approved specification and explicitly reject any change that:

- logs `$request`, `$request_uri`, `$args`, referer, cookies, arbitrary headers, or a sensitive marker;
- weakens existing rate limits, TLS, CSP, HSTS, API allowlisting, invalid attribution JSON 404, or SPA routing;
- disables Uvicorn/application error logs rather than only access logs;
- makes the open gate non-inert or the closed gate anything other than `return 503;`;
- restores the unsafe nginx format or API unit during rollback;
- changes Python application code, frontend code, migrations, providers, email sending, Stripe, pricing, or production.

All Critical and Important findings must be fixed and re-reviewed before delivery.

- [ ] **Step 5: Mark the design implemented and commit documentation**

Only after Steps 1–4 pass, change the design status to:

```text
Status: approved design; implementation complete in PR
```

Then commit:

```bash
git add docs/superpowers/specs/2026-08-26-attribution-token-log-redaction-design.md \
  docs/superpowers/plans/2026-08-26-sensitive-link-token-log-redaction.md
git commit -m "docs(ops): record sensitive link logging implementation"
```

- [ ] **Step 6: Push and open one focused PR**

Push without force and open a PR titled:

```text
fix(ops): redact sensitive link tokens from staging logs
```

The PR body must include `Closes #93` and `Refs #84`, the confirmed root cause, the exact security boundary, risks/rollback, RED/GREEN evidence, full validation, no-migration/no-provider/no-production statements, and the remaining separately authorized valid-token staging proof. Do not close #84 until its valid 303/cookie/persistence proof passes after deployment.
