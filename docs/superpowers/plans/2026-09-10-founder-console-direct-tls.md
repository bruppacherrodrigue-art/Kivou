# Founder Console Direct TLS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Cloudflare Access/Tunnel boundary with direct DNS, Let's Encrypt TLS, nginx Basic Auth and the existing origin-secret boundary for `control.kivou.eu`.

**Architecture:** A dedicated public nginx vhost terminates TLS, challenges Basic Auth once for every Founder resource, serves only the Founder SPA and proxies only the Founder API to loopback port 8011. nginx injects a trusted short username and origin secret; FastAPI validates both while retaining the existing email-shaped session response as display metadata.

**Tech Stack:** nginx 1.24, Certbot webroot, Apache `htpasswd` bcrypt, FastAPI/Python, pytest, versioned operations documentation, `kivou-deploy.sh`.

---

### Task 1: Replace the Founder API Cloudflare identity boundary

**Files:**
- Modify: `tests/founder_api/test_access.py`
- Modify: `tests/founder_api/test_read_models.py`
- Modify: `src/signals/founder_api/access.py`
- Modify: `src/signals/founder_api/config.py`
- Modify: `ops/examples/founder-console.env.example`

- [ ] Change the access tests to send `X-Kivou-Founder-User: rodrigue` and the origin secret, require both values, reject any other username, and assert that no Cloudflare assertion is required.
- [ ] Run `uv run pytest -q tests/founder_api/test_access.py tests/founder_api/test_read_models.py` and confirm the new tests fail against the Cloudflare implementation.
- [ ] Add mandatory `KIVOU_FOUNDER_ALLOWED_USER`, validate its normalized short username, replace the Cloudflare headers with `X-Kivou-Founder-User`, and retain the configured email only for the session response.
- [ ] Update the example environment with `KIVOU_FOUNDER_ALLOWED_USER=rodrigue` and remove all Cloudflare wording.
- [ ] Re-run `uv run pytest -q tests/founder_api/test_access.py tests/founder_api/test_read_models.py` and expect all tests to pass.

### Task 2: Publish the Founder vhost directly with TLS and Basic Auth

**Files:**
- Modify: `tests/test_ops_nginx_routes.py`
- Modify: `ops/nginx/kivou-founder-control.conf`

- [ ] Add structural nginx tests requiring one public port-80 server and one public TLS server, ACME webroot handling, HTTPS redirect, explicit Let's Encrypt paths, server-wide Basic Auth, `/etc/kivou/founder.htpasswd`, and trusted username/origin-secret header replacement.
- [ ] Add negative assertions for loopback port 8081, Cloudflare headers and customer/API route exposure.
- [ ] Run `uv run pytest -q tests/test_ops_nginx_routes.py` and confirm the new assertions fail.
- [ ] Rewrite the vhost as the tested HTTP/TLS pair while retaining the existing Founder frontend root, API proxy, security headers, limits and fail-closed route selectors.
- [ ] Re-run `uv run pytest -q tests/test_ops_nginx_routes.py` and expect it to pass.

### Task 3: Remove Cloudflare artifacts and publish the real runbook

**Files:**
- Delete: `ops/examples/cloudflared-founder.yml.example`
- Modify: `docs/FOUNDER_CONSOLE.md`
- Test: repository-wide text scan

- [ ] Delete the Cloudflared example.
- [ ] Replace the operator, security, repository-layout, setup, smoke-test and delivery sections with the approved DNS A, Certbot webroot, `htpasswd -B`, one-time password handling, origin secret, nginx activation and authenticated verification procedure.
- [ ] State the DNS handoff exactly as `control.kivou.eu` / `A` / `179.237.105.52` and keep the unit, port, read-only role, frontend directory and deploy script unchanged.
- [ ] Run `rg -n -i "cloudflare|cloudflared|tunnel|cf-access|127\.0\.0\.1:8081" docs/FOUNDER_CONSOLE.md ops/examples ops/nginx/kivou-founder-control.conf src/signals/founder_api tests/founder_api/test_access.py tests/founder_api/test_read_models.py` and expect no retired-boundary matches.

### Task 4: Final verification

**Files:**
- Review all modified files

- [ ] Run `uv run pytest -q tests/founder_api/test_access.py tests/founder_api/test_read_models.py tests/test_ops_nginx_routes.py`.
- [ ] Run `uv run ruff check src/signals/founder_api tests/founder_api`.
- [ ] Run `git diff --check` and inspect `git diff --stat` plus the full focused diff.
- [ ] Confirm the Cloudflared example is absent, no credential or generated password is tracked, and unrelated user-owned working-tree changes remain untouched.
