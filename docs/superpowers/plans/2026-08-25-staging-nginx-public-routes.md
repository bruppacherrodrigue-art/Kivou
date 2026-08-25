# Staging nginx Public Routes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the versioned staging runtime relay the existing Instantly webhook and attribution routes to FastAPI, and compose the webhook ingress locally and fail-closed without enabling response ingestion or provider I/O.

**Architecture:** Keep nginx as an explicit public allowlist and add only `location = /webhooks/instantly` plus `location ^~ /a/`, while restoring the complete versioned staging templates synchronized with the current API route inventory. Extend `ApiConfig` with one all-or-nothing Instantly ingress configuration group, then have the production ASGI factory build `InstantlyWebhookService` with local keyrings and `ResponseIngressCapability.NONE`; an absent group keeps the service off and any partial group refuses startup using names-only diagnostics.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, pytest, Ruff, nginx 1.24-compatible configuration.

---

## File map

- Modify `src/signals/api/config.py`: parse and validate the six-value Instantly ingress group and keep all secret bytes out of `repr`.
- Modify `src/signals/api/asgi.py`: compose `InstantlyWebhookService` from the engine and validated config without queries, workers, subscriptions, or network access.
- Modify `tests/test_api_runtime.py`: prove absent/partial/complete configuration, expurgation, production composition, durable acceptance/replay, refusal paths, and no network I/O.
- Create `tests/test_ops_nginx_routes.py`: explicit FastAPI public/private route inventory plus a small nginx location parser and template invariants.
- Create `ops/nginx/kivou-staging.conf`: staging reverse proxy with the current public API groups, exact webhook routes, attribution prefix, and SPA fallback.
- Create `ops/nginx/kivou-limits.conf`: existing auth/reset/API/webhook zones and 429 overflow behavior.
- Create `ops/nginx/kivou-proxy-params.conf`: shared proxy headers and timeouts.
- Create `ops/nginx/kivou-security-headers.conf`: shared security headers and CSP.
- Modify `tests/test_conversion_attribution_api.py`: make JSON 404/no-cookie/no-SPA behavior explicit alongside the existing 303/cookie proof.
- Modify `.env.example`: document the four additional key/version variables and the all-or-nothing ingress boundary.
- Modify `ops/README.md`: document atomic install, `nginx -t`, reload, and recoverable rollback.

No persistence schema or migration changes are needed.

### Task 1: Fail-closed Instantly ingress configuration

**Files:**
- Modify: `tests/test_api_runtime.py`
- Modify: `src/signals/api/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Write configuration tests before production changes**

Add constants for all six environment names to the fixture cleanup and tests equivalent to:

```python
INSTANTLY_ENV = {
    "KIVOU_INSTANTLY_WEBHOOK_SECRET": "synthetic-webhook-secret",
    "KIVOU_INSTANTLY_WORKSPACE_REF": "workspace:test",
    "KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY": "synthetic-webhook-fingerprint-key",
    "KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY_VERSION": "webhook-key-v1",
    "KIVOU_SUPPRESSION_IDENTITY_KEY": "synthetic-suppression-identity-key",
    "KIVOU_SUPPRESSION_IDENTITY_KEY_VERSION": "suppression-key-v1",
}

def test_absent_instantly_group_keeps_ingress_disabled(base_environment):
    config = ApiConfig.from_environment()
    assert config.instantly_webhook_configured is False
    assert config.instantly_webhook_secret is None

@pytest.mark.parametrize("present_name", tuple(INSTANTLY_ENV))
def test_partial_instantly_group_refuses_startup_without_values(
    base_environment, monkeypatch, present_name
):
    monkeypatch.setenv(present_name, INSTANTLY_ENV[present_name])
    with pytest.raises(ValueError) as captured:
        ApiConfig.from_environment()
    rendered = str(captured.value)
    assert "configuration webhook Instantly incomplète" in rendered
    assert INSTANTLY_ENV[present_name] not in rendered

def test_complete_instantly_group_is_repr_safe(base_environment, monkeypatch):
    for name, value in INSTANTLY_ENV.items():
        monkeypatch.setenv(name, value)
    config = ApiConfig.from_environment()
    assert config.instantly_webhook_configured is True
    rendered = repr(config)
    assert "synthetic-webhook-secret" not in rendered
    assert "synthetic-webhook-fingerprint-key" not in rendered
    assert "synthetic-suppression-identity-key" not in rendered
```

- [ ] **Step 2: Run the new tests and capture the expected RED**

Run:

```bash
uv run pytest -q \
  tests/test_api_runtime.py::test_absent_instantly_group_keeps_ingress_disabled \
  tests/test_api_runtime.py::test_partial_instantly_group_refuses_startup_without_values \
  tests/test_api_runtime.py::test_complete_instantly_group_is_repr_safe
```

Expected: failure because the four new environment variables, the group validation, and `instantly_webhook_configured` do not exist; the current webhook secret also appears in `ApiConfig.__repr__`.

- [ ] **Step 3: Implement the smallest all-or-nothing config group**

Add environment constants and dataclass fields equivalent to:

```python
INSTANTLY_WEBHOOK_FINGERPRINT_KEY_ENV = "KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY"
INSTANTLY_WEBHOOK_FINGERPRINT_KEY_VERSION_ENV = (
    "KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY_VERSION"
)
SUPPRESSION_IDENTITY_KEY_ENV = "KIVOU_SUPPRESSION_IDENTITY_KEY"
SUPPRESSION_IDENTITY_KEY_VERSION_ENV = "KIVOU_SUPPRESSION_IDENTITY_KEY_VERSION"

instantly_webhook_secret: str | None = dataclasses.field(default=None, repr=False)
instantly_webhook_workspace_ref: str | None = None
instantly_webhook_fingerprint_key: bytes | None = dataclasses.field(default=None, repr=False)
instantly_webhook_fingerprint_key_version: str | None = None
suppression_identity_key: bytes | None = dataclasses.field(default=None, repr=False)
suppression_identity_key_version: str | None = None

@property
def instantly_webhook_configured(self) -> bool:
    return all(
        value is not None
        for value in (
            self.instantly_webhook_secret,
            self.instantly_webhook_workspace_ref,
            self.instantly_webhook_fingerprint_key,
            self.instantly_webhook_fingerprint_key_version,
            self.suppression_identity_key,
            self.suppression_identity_key_version,
        )
    )
```

Read the six values once. If all are absent, return all `None`; if some are absent, raise a names-only `ValueError`; require secret key byte strings to be at least 16 bytes and versions/workspace to be bounded non-empty values. Do not include the supplied values in any error. Document that all six variables are required together in `.env.example`.

- [ ] **Step 4: Run focused and baseline tests GREEN**

Run:

```bash
uv run pytest -q tests/test_api_runtime.py
uv run ruff check src/signals/api/config.py tests/test_api_runtime.py
```

Expected: all runtime tests pass and Ruff exits 0.

- [ ] **Step 5: Commit the green cycle**

```bash
git add src/signals/api/config.py tests/test_api_runtime.py .env.example
git commit -m "fix(api): fail closed on partial Instantly ingress config"
```

### Task 2: Compose the production webhook service locally

**Files:**
- Modify: `tests/test_api_runtime.py`
- Modify: `src/signals/api/asgi.py`

- [ ] **Step 1: Write production-composition tests**

Add tests that use `build_application()` rather than injecting the service manually:

```python
def test_absent_instantly_group_returns_service_unavailable(base_environment):
    app = importlib.import_module(MODULE).build_application()
    assert app.state.instantly_webhook_service is None
    response = TestClient(app).post("/webhooks/instantly", json={})
    assert response.status_code == 503
    assert response.json()["code"] == "instantly_webhook_unavailable"

def test_complete_instantly_group_wires_none_capability_without_network(
    base_environment, monkeypatch
):
    _configure_instantly(monkeypatch)
    monkeypatch.setattr(
        "socket.socket.connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("production composition attempted network I/O")
        ),
    )
    app = importlib.import_module(MODULE).build_application()
    assert isinstance(app.state.instantly_webhook_service, InstantlyWebhookService)
    assert app.state.instantly_webhook_service._response_capability is ResponseIngressCapability.NONE
    assert app.state.instantly_webhook_service._response_ingress is None
```

Add one migrated SQLite fixture built through the existing campaign test helpers, point `KIVOU_DATABASE_URL` at it, build the production app, then prove:

- wrong secret returns 401 and leaves `acquisition_provider_event` empty;
- a valid event returns 200 and persists exactly one event;
- redelivery returns 200 with `replayed: true` and still exactly one event;
- an authenticated unknown campaign/workspace returns 422 with no new event;
- no real socket/provider request is attempted.

- [ ] **Step 2: Run the tests and capture RED**

Run:

```bash
uv run pytest -q \
  tests/test_api_runtime.py::test_absent_instantly_group_returns_service_unavailable \
  tests/test_api_runtime.py::test_complete_instantly_group_wires_none_capability_without_network \
  tests/test_api_runtime.py::test_production_instantly_webhook_persists_and_replays_without_network
```

Expected: the absent case remains 503, while complete configuration still leaves `app.state.instantly_webhook_service` as `None`, so composition and valid-ingress assertions fail.

- [ ] **Step 3: Implement the minimal ASGI factory**

Add a pure constructor and pass it into `create_app`:

```python
def _instantly_webhook_service(
    engine: sa.Engine, config: ApiConfig
) -> InstantlyWebhookService | None:
    if not config.instantly_webhook_configured:
        return None
    assert config.instantly_webhook_workspace_ref is not None
    assert config.instantly_webhook_fingerprint_key is not None
    assert config.instantly_webhook_fingerprint_key_version is not None
    assert config.suppression_identity_key is not None
    assert config.suppression_identity_key_version is not None
    return InstantlyWebhookService(
        engine,
        provider_workspace_ref=config.instantly_webhook_workspace_ref,
        fingerprint_keyring=WebhookFingerprintKeyring(
            current_key_version=config.instantly_webhook_fingerprint_key_version,
            keys={
                config.instantly_webhook_fingerprint_key_version:
                    config.instantly_webhook_fingerprint_key
            },
        ),
        suppression_keyring=SuppressionIdentityKeyring(
            current_key_version=config.suppression_identity_key_version,
            keys={config.suppression_identity_key_version: config.suppression_identity_key},
        ),
        response_ingress_capability=ResponseIngressCapability.NONE,
    )
```

Build the engine once, pass the same engine to this factory and `create_app`, and do not construct an Instantly API adapter, response worker, response ingress, or webhook subscription.

- [ ] **Step 4: Run focused and neighboring tests GREEN**

Run:

```bash
uv run pytest -q tests/test_api_runtime.py tests/test_campaign_webhooks.py
uv run ruff check src/signals/api/asgi.py tests/test_api_runtime.py
```

Expected: production composition, persistent replay, route hardening, and existing campaign webhook tests all pass; Ruff exits 0.

- [ ] **Step 5: Commit the green cycle**

```bash
git add src/signals/api/asgi.py tests/test_api_runtime.py
git commit -m "fix(api): compose local Instantly webhook ingress"
```

### Task 3: Restore synchronized nginx templates with an explicit route inventory

**Files:**
- Create: `tests/test_ops_nginx_routes.py`
- Create: `ops/nginx/kivou-staging.conf`
- Create: `ops/nginx/kivou-limits.conf`
- Create: `ops/nginx/kivou-proxy-params.conf`
- Create: `ops/nginx/kivou-security-headers.conf`

- [ ] **Step 1: Write the route inventory and parser tests first**

In `tests/test_ops_nginx_routes.py`, recursively descend FastAPI `_IncludedRouter.original_router.routes`, apply every include prefix, and compare the exact `(method, path)` set against two explicit constants:

```python
PUBLIC_ASGI_ROUTES = frozenset({
    ("GET", "/a/{token}"),
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),
    ("POST", "/auth/password-reset/confirm"),
    ("POST", "/auth/password-reset/request"),
    ("POST", "/auth/signup"),
    # billing, companies, me, notification-preferences, signals,
    # target-icps, and the two exact webhooks are listed individually here.
})
PRIVATE_ASGI_ROUTES = frozenset({
    ("GET", "/openapi.json"),
    ("GET", "/internal/commercial-cockpit"),
    ("GET", "/internal/acquisition-ops/health"),
    ("GET", "/internal/acquisition-ops/readiness"),
    ("GET", "/internal/acquisition-ops/incidents"),
    ("GET", "/internal/acquisition-ops/dead-letters"),
})
```

Do not leave the abbreviated comment in the actual manifest: enumerate every route. Parse `location` blocks by brace depth and test that every public route maps to a proxy block, every private route maps to no proxy block, and every proxy block is represented by the reviewed public inventory.

Add exact structural assertions:

```python
assert_location(
    "= /webhooks/instantly",
    "limit_req zone=kivou_hook burst=100 nodelay;",
    "proxy_pass http://127.0.0.1:8000;",
)
assert_location(
    "^~ /a/",
    "limit_req zone=kivou_api burst=40 nodelay;",
    "proxy_pass http://127.0.0.1:8000;",
)
```

Also assert `/companies` is in the public API group, `/internal` is absent from all proxy selectors, proxy blocks contain `include /etc/nginx/kivou-proxy-params.conf` and never `try_files`, the four rate zones retain 5/3/120/300 requests per minute, overflow is 429, and shared proxy/security files retain the existing headers/timeouts/CSP/HSTS.

- [ ] **Step 2: Run the nginx tests and capture RED**

Run:

```bash
uv run pytest -q tests/test_ops_nginx_routes.py
```

Expected: failure because `ops/nginx/` is absent from the branch.

- [ ] **Step 3: Restore and resynchronize the four templates**

Use commit `31457e9` only as the behavioral reference. Restore its limits, proxy parameters, security headers, TLS/ACME/static/SPA behavior, then synchronize the backend allowlist with the current route inventory:

```nginx
location ~ ^/(auth|me|target-icps|signals|companies|billing|notification-preferences)(/|$) {
    limit_req zone=kivou_api burst=40 nodelay;
    proxy_pass http://127.0.0.1:8000;
    include /etc/nginx/kivou-proxy-params.conf;
}

location = /webhooks/stripe {
    limit_req zone=kivou_hook burst=100 nodelay;
    proxy_pass http://127.0.0.1:8000;
    include /etc/nginx/kivou-proxy-params.conf;
}

location = /webhooks/instantly {
    limit_req zone=kivou_hook burst=100 nodelay;
    proxy_pass http://127.0.0.1:8000;
    include /etc/nginx/kivou-proxy-params.conf;
}

location ^~ /a/ {
    limit_req zone=kivou_api burst=40 nodelay;
    proxy_pass http://127.0.0.1:8000;
    include /etc/nginx/kivou-proxy-params.conf;
}
```

Keep exact auth/reset locations so nginx chooses the stricter limits. Do not add an `/internal` selector or a catch-all backend proxy. Malformed `/a/...` paths must reach FastAPI and return JSON 404 instead of the SPA.

- [ ] **Step 4: Run parser/inventory tests GREEN and syntax validation**

Run:

```bash
uv run pytest -q tests/test_ops_nginx_routes.py
uv run ruff check tests/test_ops_nginx_routes.py
```

Then, if `nginx` is installed, create a temporary prefix with dummy certificate files and the tracked includes, substitute `STAGING_HOST`, and run `nginx -t -p <temporary-prefix> -c <temporary-nginx.conf>`. If nginx is unavailable or TLS certificate parsing prevents an isolated check, record that explicitly and rely on the parser test plus `git diff 31457e9 -- ops/nginx` review; never mutate `/etc/nginx`.

- [ ] **Step 5: Commit the green cycle**

```bash
git add tests/test_ops_nginx_routes.py ops/nginx
git commit -m "fix(ops): relay reviewed public routes through nginx"
```

### Task 4: Strengthen public HTTP evidence and deployment documentation

**Files:**
- Modify: `tests/test_conversion_attribution_api.py`
- Modify: `ops/README.md`

- [ ] **Step 1: Tighten attribution assertions**

Extend the bad-token test before documentation changes:

```python
assert invalid.status_code == 404
assert invalid.headers["content-type"].startswith("application/json")
assert invalid.json()["code"] == "attribution_not_found"
assert "set-cookie" not in invalid.headers
assert "<!doctype html>" not in invalid.text.lower()
```

The existing valid-click test must continue to prove 303, fixed `/signup`, `no-store`, `HttpOnly`, `Secure`, `SameSite=lax`, and `Path=/auth/signup`.

- [ ] **Step 2: Run the HTTP evidence tests**

Run:

```bash
uv run pytest -q \
  tests/test_conversion_attribution_api.py::test_click_sets_bounded_http_only_context_and_redirects_cleanly \
  tests/test_conversion_attribution_api.py::test_bad_token_sets_no_cookie_and_token_grants_no_session \
  tests/test_campaign_webhooks.py::test_route_is_json_bounded_and_constant_time_secret_authenticated \
  tests/test_campaign_webhooks.py::test_webhook_ingress_never_calls_instantly_or_email_api
```

Expected: all four characterization tests pass without production changes; they explicitly pin the behavior that nginx must expose.

- [ ] **Step 3: Document atomic install, validation, reload, and rollback**

Add a dedicated nginx section to `ops/README.md` that:

- renders `STAGING_HOST` to a candidate file under a root-only temporary directory;
- copies includes to candidate names first and validates the full candidate with `sudo nginx -t`;
- snapshots the existing site and includes with restrictive permissions;
- installs using `sudo install`/atomic same-filesystem rename semantics;
- runs `sudo nginx -t` again before `sudo systemctl reload nginx`;
- verifies `/webhooks/instantly` with a deliberately wrong secret (401 JSON) and `/a/bogus-token` (404 JSON/no SPA), without a business-valid webhook or provider request;
- rolls back the snapshot, reruns `nginx -t`, then reloads;
- states that no migration or durable event deletion is part of rollback.

- [ ] **Step 4: Run focused validation and commit**

Run:

```bash
uv run pytest -q \
  tests/test_api_runtime.py \
  tests/test_campaign_webhooks.py \
  tests/test_conversion_attribution_api.py \
  tests/test_ops_nginx_routes.py
uv run ruff check \
  src/signals/api/config.py \
  src/signals/api/asgi.py \
  tests/test_api_runtime.py \
  tests/test_conversion_attribution_api.py \
  tests/test_ops_nginx_routes.py
```

Expected: all selected tests pass and Ruff exits 0.

```bash
git add tests/test_conversion_attribution_api.py ops/README.md
git commit -m "docs(ops): add atomic nginx deployment rollback"
```

### Task 5: Final verification and review

**Files:**
- Review: all files changed since base `7253c3a`

- [ ] **Step 1: Verify the complete scoped suite freshly**

Run:

```bash
uv run pytest -q \
  tests/test_api_runtime.py \
  tests/test_campaign_webhooks.py \
  tests/test_conversion_attribution_api.py \
  tests/test_ops_nginx_routes.py
uv run ruff check src/signals/api tests/test_api_runtime.py \
  tests/test_conversion_attribution_api.py tests/test_ops_nginx_routes.py
```

Run the isolated `nginx -t` command from Task 3 when available; otherwise rerun the parser tests and inspect:

```bash
git diff --check 7253c3a..HEAD
git diff --stat 7253c3a..HEAD
git log --oneline 7253c3a..HEAD
```

- [ ] **Step 2: Auto-review Critical and Important findings**

Review the complete diff for:

- any secret value in repr, exception, docs, fixture output, or tracked config;
- any partial configuration that starts instead of refusing;
- response ingress capability other than `NONE`, any response handler, provider adapter, subscription, worker, or startup I/O;
- any nginx selector that proxies `/internal`, omits `/companies`, uses SPA fallback for `/a/`, or fails to use an exact Instantly webhook location;
- any loss of rate limits, proxy headers, TLS/security headers, static cache behavior, or the SPA fallback;
- any migration/schema file change;
- any test that mocks away the production factory instead of exercising it.

Fix every Critical or Important finding with another RED/GREEN cycle and a focused commit, then rerun the full scoped verification.

- [ ] **Step 3: Prove branch state without external mutation**

Run:

```bash
git status --short --branch
git rev-parse HEAD
git log --oneline 7253c3a..HEAD
```

Expected: branch `fix/staging-nginx-public-routes`, no uncommitted changes, multiple small local commits, no push, no staging/provider/GitHub mutation, and no migration.
