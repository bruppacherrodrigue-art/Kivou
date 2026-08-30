# Kivou Production Runtime Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the prepared production host baseline, then add reproducible production-only systemd, nginx, off-host backup and ingestion diagnostics assets without publishing DNS, starting application timers or authorizing provider mutations.

**Architecture:** Preserve every existing staging asset and add a distinct `ops/systemd/production` runtime that reads `/etc/kivou/production.env`. Keep nginx same-origin and route-equivalent to staging while using production placeholders and pre-HSTS security fragments. Extend the verified local PostgreSQL dump with a fail-closed restic upload, and expose only a sanitized exception type in ingestion summaries so TED failures are actionable without logging payloads.

**Tech Stack:** GitHub CLI and Actions, Python 3.12, pytest, Ruff, Bash, systemd, nginx 1.24, PostgreSQL 16 tools, restic, uv.

---

## Scope and file map

PR `#109` is integrated first. Its three host-policy commits and the approved
go-live design are rebased onto current `main`; no application code is added to
that PR.

The follow-up runtime-foundations branch changes only these responsibilities:

- Create `ops/systemd/kivou-ingest-simap.service` and `.timer`: version the
  audited staging SIMAP units exactly.
- Create `ops/systemd/kivou-ingest-boamp.service` and `.timer`: version the
  audited staging BOAMP units exactly.
- Create `ops/systemd/production/kivou-api.service`: production API on loopback.
- Create `ops/systemd/production/kivou-alerts.service` and `.timer`: production
  transactional alert worker.
- Create `ops/systemd/production/kivou-backup.service` and `.timer`: verified
  local dump followed by encrypted off-host upload.
- Create `ops/systemd/production/kivou-ingest@.service`: one production
  ingestion template with a shared host lock.
- Create four `ops/systemd/production/kivou-ingest-*.timer` files: staggered,
  independently observable source schedules.
- Create `ops/nginx/kivou-production.conf`: production same-origin site.
- Create `ops/nginx/kivou-production-www.conf`: HTTP/HTTPS `www` redirect to the
  canonical origin.
- Create `ops/nginx/kivou-production-default-deny.conf`: reject unknown Host
  names and TLS SNI before they reach the application.
- Create `ops/nginx/kivou-production-security-headers.conf`: pre-HSTS ordinary
  headers.
- Create `ops/nginx/kivou-production-sensitive-link-security-headers.conf`:
  pre-HSTS sensitive-link headers.
- Create `ops/bin/kivou-restic-upload.sh`: upload only the newest freshly
  verified local dump and apply off-host retention only after success.
- Modify `src/signals/ingestion/runner.py`: retain a sanitized root exception
  type in each failed source outcome.
- Modify `src/signals/ingestion/cli.py`: print the safe type token, never the
  exception message.
- Create `tests/test_ops_production_runtime.py`: cross-environment, systemd,
  nginx and no-secret invariants.
- Create `tests/test_ops_restic_runtime.py`: fake-restic offline runtime tests.
- Modify `tests/test_ingestion_cli.py` and `tests/test_ingestion_runner.py`:
  diagnostic redaction tests.
- Create `ops/production/README.md`: installation, manual proof, disabled-by-
  default policy and rollback commands for Release 2.

No production host file, DNS record, certificate, Stripe object, SMTP message,
provider object, database or active service is changed by this plan.
The Acquisition Engine remains outside this branch; its production
`SHADOW/READ_ONLY` contract and every later authority increase belong to the
separate Release 3 specification and plan.

### Task 1: Rebase, revalidate and merge foundation PR #109

**Files:**
- Existing branch: `ops/production-vps-readiness`
- Existing PR: `#109`
- Existing remote head: `0a42c184cea20977c969145959593b7f0b7194af`
- Local documentation commit: `7120e07`

- [ ] **Step 1: Re-read GitHub state and current main**

Run:

```bash
gh api repos/bruppacherrodrigue-art/Kivou/pulls/109 \
  --jq '{state,merged,base_sha:.base.sha,head_sha:.head.sha,mergeable,mergeable_state}'
gh api repos/bruppacherrodrigue-art/Kivou/commits/main --jq .sha
git status --short --branch
```

Expected: PR `#109` is open and unmerged; its remote head is exactly
`0a42c184cea20977c969145959593b7f0b7194af`; the worktree is clean and only
ahead by the approved documentation commits.

- [ ] **Step 2: Rebase onto the freshly fetched main**

Run:

```bash
git fetch origin main ops/production-vps-readiness
git rebase origin/main
git status --short --branch
git diff --check origin/main...HEAD
```

Expected: rebase succeeds; the worktree is clean; `git diff --check` has no
output. If there is any conflict, abort the rebase and inspect it before making
a change.

- [ ] **Step 3: Prove the rebased scope**

Run:

```bash
git diff --name-only origin/main...HEAD | sort
uv run pytest -q tests/test_ops_host_runtime.py
uv run ruff check tests/test_ops_host_runtime.py
```

Expected: the diff contains only the two production design documents, host
implementation plan, `ops/host/*`, and `tests/test_ops_host_runtime.py`; the
focused tests and Ruff pass.

- [ ] **Step 4: Push with an exact lease and wait for exact-head CI**

Run:

```bash
git push --force-with-lease=refs/heads/ops/production-vps-readiness:0a42c184cea20977c969145959593b7f0b7194af \
  origin HEAD:ops/production-vps-readiness
KIVOU_PR109_HEAD=$(git rev-parse HEAD)
gh pr checks 109 --repo bruppacherrodrigue-art/Kivou --watch
test "$(gh api repos/bruppacherrodrigue-art/Kivou/pulls/109 --jq .head.sha)" = \
  "$KIVOU_PR109_HEAD"
```

Expected: both backend and frontend jobs complete with `SUCCESS` for
`KIVOU_PR109_HEAD`.

- [ ] **Step 5: Re-read mergeability and squash-merge**

Run:

```bash
gh api repos/bruppacherrodrigue-art/Kivou/pulls/109 \
  --jq '{state,merged,head_sha:.head.sha,base_sha:.base.sha,mergeable,mergeable_state}'
gh pr merge 109 --repo bruppacherrodrigue-art/Kivou --squash --delete-branch=false
gh api repos/bruppacherrodrigue-art/Kivou/pulls/109 \
  --jq '{state,merged,merge_sha:.merge_commit_sha}'
```

Expected before the mutation: open, unmerged, exact reviewed head, mergeable
and clean. Expected after: merged with one recorded squash SHA.

- [ ] **Step 6: Verify the resulting main tree and successor CI**

Run:

```bash
KIVOU_FOUNDATION_MAIN_SHA=$(gh api repos/bruppacherrodrigue-art/Kivou/commits/main --jq .sha)
git fetch origin main
test "$(git rev-parse origin/main)" = "$KIVOU_FOUNDATION_MAIN_SHA"
gh run list --repo bruppacherrodrigue-art/Kivou --branch main \
  --commit "$KIVOU_FOUNDATION_MAIN_SHA" --workflow CI --limit 5
```

Wait conditionally for the successor run, then watch it:

```bash
KIVOU_FOUNDATION_RUN_ID=
for KIVOU_RUN_LOOKUP_ATTEMPT in $(seq 1 60); do
  KIVOU_FOUNDATION_RUN_ID=$(gh api \
    'repos/bruppacherrodrigue-art/Kivou/actions/runs?branch=main&event=push&per_page=20' \
    --jq ".workflow_runs[] | select(.head_sha == \"$KIVOU_FOUNDATION_MAIN_SHA\" and .name == \"CI\") | .id" |
    head -n 1)
  test -n "$KIVOU_FOUNDATION_RUN_ID" && break
  sleep 5
done
test -n "$KIVOU_FOUNDATION_RUN_ID"
gh run watch "$KIVOU_FOUNDATION_RUN_ID" \
  --repo bruppacherrodrigue-art/Kivou --exit-status
```

Expected: backend and frontend succeed for the exact resulting `main` SHA.

### Task 2: Create an isolated runtime-foundations worktree

**Files:**
- Create worktree branch: `ops/production-runtime-foundations`

- [ ] **Step 1: Create the worktree from verified main**

Invoke `superpowers:using-git-worktrees`, then run from the repository root:

```bash
KIVOU_RUNTIME_WORKTREE=/home/jaybe/.config/superpowers/worktrees/Kivou/production-runtime-foundations
test ! -e "$KIVOU_RUNTIME_WORKTREE"
git show-ref --verify --quiet refs/heads/ops/production-runtime-foundations && exit 69 || true
git worktree add "$KIVOU_RUNTIME_WORKTREE" \
  -b ops/production-runtime-foundations origin/main
git -C "$KIVOU_RUNTIME_WORKTREE" status --short --branch
```

Expected: `git rev-parse HEAD`, `git rev-parse origin/main` and the verified
foundation main SHA are identical; `git status --porcelain` is empty.

- [ ] **Step 2: Run the focused baseline before edits**

Run:

```bash
uv sync --locked
uv run pytest -q tests/test_ops_host_runtime.py tests/test_ops_ingestion_runtime.py \
  tests/test_ops_backup_runtime.py tests/test_ops_nginx_routes.py
uv run ruff check tests/test_ops_host_runtime.py tests/test_ops_ingestion_runtime.py \
  tests/test_ops_backup_runtime.py tests/test_ops_nginx_routes.py
```

Expected: all selected tests and Ruff pass before new work.

### Task 3: Version staging source units and add production systemd contracts

**Files:**
- Create: `tests/test_ops_production_runtime.py`
- Create: `ops/systemd/kivou-ingest-simap.service`
- Create: `ops/systemd/kivou-ingest-simap.timer`
- Create: `ops/systemd/kivou-ingest-boamp.service`
- Create: `ops/systemd/kivou-ingest-boamp.timer`
- Create: `ops/systemd/production/kivou-api.service`
- Create: `ops/systemd/production/kivou-alerts.service`
- Create: `ops/systemd/production/kivou-alerts.timer`
- Create: `ops/systemd/production/kivou-backup.service`
- Create: `ops/systemd/production/kivou-backup.timer`
- Create: `ops/systemd/production/kivou-ingest@.service`
- Create: `ops/systemd/production/kivou-ingest-simap.timer`
- Create: `ops/systemd/production/kivou-ingest-boamp.timer`
- Create: `ops/systemd/production/kivou-ingest-decp.timer`
- Create: `ops/systemd/production/kivou-ingest-ted.timer`

- [ ] **Step 1: Write failing production asset tests**

Create `tests/test_ops_production_runtime.py` with:

```python
from pathlib import Path


ROOT = Path(__file__).parents[1]
SYSTEMD = ROOT / "ops" / "systemd"
PRODUCTION = SYSTEMD / "production"
NGINX = ROOT / "ops" / "nginx"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_audited_staging_fast_source_units_are_versioned() -> None:
    expected = {
        "kivou-ingest-simap.timer": "OnCalendar=*-*-* 00/2:05:00",
        "kivou-ingest-boamp.timer": "OnCalendar=*-*-* 00/2:15:00",
    }
    for filename, schedule in expected.items():
        timer = read(SYSTEMD / filename)
        service = read(SYSTEMD / filename.replace(".timer", ".service"))
        source = filename.removeprefix("kivou-ingest-").removesuffix(".timer")
        assert schedule in timer
        assert "Persistent=true" in timer
        assert "EnvironmentFile=/etc/kivou/staging.env" in service
        assert "/run/kivou-ingestion.lock" in service
        assert f"-m signals.ingestion run --source {source}" in service


def test_production_units_never_reference_staging_or_acquisition() -> None:
    paths = tuple(PRODUCTION.glob("*"))
    assert paths
    combined = "\n".join(read(path) for path in paths)
    assert "staging" not in combined.lower()
    assert "apollo" not in combined.lower()
    assert "acquisition" not in combined.lower()
    assert "EnvironmentFile=/etc/kivou/production.env" in combined


def test_production_api_is_loopback_only_and_hardened() -> None:
    body = read(PRODUCTION / "kivou-api.service")
    for expected in (
        "User=kivou",
        "Group=kivou",
        "WorkingDirectory=/srv/kivou/app",
        "--host 127.0.0.1 --port 8000 --workers 2",
        "--forwarded-allow-ips 127.0.0.1",
        "--no-server-header --no-access-log",
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "MemoryDenyWriteExecute=true",
    ):
        assert expected in body


def test_production_ingestion_uses_one_shared_lock_and_exact_sources() -> None:
    service = read(PRODUCTION / "kivou-ingest@.service")
    assert "/run/kivou-ingestion.lock" in service
    assert "-m signals.ingestion run --source %i" in service
    schedules = {
        "simap": "OnCalendar=*-*-* 00/2:05:00",
        "boamp": "OnCalendar=*-*-* 00/2:15:00",
        "decp": "OnCalendar=*-*-* *:20:00",
        "ted": "OnCalendar=*-*-* 00/2:30:00",
    }
    for source, schedule in schedules.items():
        body = read(PRODUCTION / f"kivou-ingest-{source}.timer")
        assert schedule in body
        assert "Persistent=true" in body
        assert "RandomizedDelaySec=60" in body
        assert f"Unit=kivou-ingest@{source}.service" in body


def test_production_backup_requires_local_then_offsite_success() -> None:
    body = read(PRODUCTION / "kivou-backup.service")
    local = "ExecStart=/srv/kivou/app/ops/bin/kivou-backup.sh"
    offsite = "ExecStart=/srv/kivou/app/ops/bin/kivou-restic-upload.sh"
    assert "EnvironmentFile=/etc/kivou/production.env" in body
    assert "EnvironmentFile=/etc/kivou/swiss-backup.env" in body
    assert body.index(local) < body.index(offsite)
    assert "ReadWritePaths=/srv/kivou/backups" in body
```

- [ ] **Step 2: Run tests to prove the assets are missing**

Run:

```bash
uv run pytest -q tests/test_ops_production_runtime.py
```

Expected: failures identify the missing staging fast-source and production
systemd files.

- [ ] **Step 3: Add the audited staging SIMAP and BOAMP units**

Create `ops/systemd/kivou-ingest-simap.service` with:

```ini
[Unit]
Description=Kivou — ingestion SIMAP
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=oneshot
User=kivou
Group=kivou
WorkingDirectory=/srv/kivou/app
EnvironmentFile=/etc/kivou/staging.env
ExecStart=/usr/bin/flock --exclusive --timeout 300 --conflict-exit-code 0 /run/kivou-ingestion.lock /srv/kivou/app/.venv/bin/python -m signals.ingestion run --source simap
TimeoutStartSec=30min
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kivou-ingest-simap
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/run/kivou-ingestion.lock
```

Create `ops/systemd/kivou-ingest-boamp.service` with:

```ini
[Unit]
Description=Kivou — ingestion BOAMP
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=oneshot
User=kivou
Group=kivou
WorkingDirectory=/srv/kivou/app
EnvironmentFile=/etc/kivou/staging.env
ExecStart=/usr/bin/flock --exclusive --timeout 300 --conflict-exit-code 0 /run/kivou-ingestion.lock /srv/kivou/app/.venv/bin/python -m signals.ingestion run --source boamp
TimeoutStartSec=30min
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kivou-ingest-boamp
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/run/kivou-ingestion.lock
```

Create `ops/systemd/kivou-ingest-simap.timer`:

```ini
[Unit]
Description=Kivou — déclenche l'ingestion SIMAP

[Timer]
OnCalendar=*-*-* 00/2:05:00
Persistent=true
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
```

Create `ops/systemd/kivou-ingest-boamp.timer`:

```ini
[Unit]
Description=Kivou — déclenche l'ingestion BOAMP

[Timer]
OnCalendar=*-*-* 00/2:15:00
Persistent=true
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: Create the production ingestion template**

Create `ops/systemd/production/kivou-ingest@.service`:

```ini
[Unit]
Description=Kivou production — ingestion %i bornée
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=oneshot
User=kivou
Group=kivou
WorkingDirectory=/srv/kivou/app
EnvironmentFile=/etc/kivou/production.env
ExecStart=/usr/bin/flock --exclusive --timeout 300 --conflict-exit-code 0 /run/kivou-ingestion.lock /srv/kivou/app/.venv/bin/python -m signals.ingestion run --source %i
TimeoutStartSec=30min
TimeoutStopSec=90s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kivou-ingest-%i
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths=/run/kivou-ingestion.lock
```

Create `ops/systemd/production/kivou-ingest-simap.timer`:

```ini
[Unit]
Description=Kivou production — déclenche l'ingestion SIMAP

[Timer]
OnCalendar=*-*-* 00/2:05:00
Persistent=true
RandomizedDelaySec=60
AccuracySec=60
Unit=kivou-ingest@simap.service

[Install]
WantedBy=timers.target
```

Create `ops/systemd/production/kivou-ingest-boamp.timer`:

```ini
[Unit]
Description=Kivou production — déclenche l'ingestion BOAMP

[Timer]
OnCalendar=*-*-* 00/2:15:00
Persistent=true
RandomizedDelaySec=60
AccuracySec=60
Unit=kivou-ingest@boamp.service

[Install]
WantedBy=timers.target
```

Create `ops/systemd/production/kivou-ingest-decp.timer`:

```ini
[Unit]
Description=Kivou production — déclenche l'ingestion DECP

[Timer]
OnCalendar=*-*-* *:20:00
Persistent=true
RandomizedDelaySec=60
AccuracySec=60
Unit=kivou-ingest@decp.service

[Install]
WantedBy=timers.target
```

Create `ops/systemd/production/kivou-ingest-ted.timer`:

```ini
[Unit]
Description=Kivou production — déclenche l'ingestion TED

[Timer]
OnCalendar=*-*-* 00/2:30:00
Persistent=true
RandomizedDelaySec=60
AccuracySec=60
Unit=kivou-ingest@ted.service

[Install]
WantedBy=timers.target
```

- [ ] **Step 5: Create production API, alerts and backup units**

Create `ops/systemd/production/kivou-api.service`:

```ini
[Unit]
Description=Kivou production API (FastAPI/uvicorn)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=exec
User=kivou
Group=kivou
WorkingDirectory=/srv/kivou/app
EnvironmentFile=/etc/kivou/production.env
ExecStart=/srv/kivou/app/.venv/bin/uvicorn signals.api.asgi:app --host 127.0.0.1 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-server-header --no-access-log --timeout-keep-alive 20
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kivou-api
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/srv/kivou/run
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true

[Install]
WantedBy=multi-user.target
```

Create `ops/systemd/production/kivou-alerts.service` and timer:

```ini
[Unit]
Description=Kivou production — alertes transactionnelles
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=kivou
Group=kivou
WorkingDirectory=/srv/kivou/app
EnvironmentFile=/etc/kivou/production.env
ExecStart=/usr/bin/flock --verbose --nonblock --conflict-exit-code 0 /srv/kivou/run/alerts.lock /srv/kivou/app/.venv/bin/python -m signals.alerts
TimeoutStartSec=20min
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kivou-alerts
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectControlGroups=true
ProtectKernelModules=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths=/srv/kivou/run
```

```ini
[Unit]
Description=Kivou production — déclenchement horaire des alertes

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=300
AccuracySec=60
Unit=kivou-alerts.service

[Install]
WantedBy=timers.target
```

Create `ops/systemd/production/kivou-backup.service`:

```ini
[Unit]
Description=Kivou production — sauvegarde PostgreSQL locale et hors hôte
After=network-online.target postgresql.service

[Service]
Type=oneshot
User=kivou
Group=kivou
EnvironmentFile=/etc/kivou/production.env
EnvironmentFile=/etc/kivou/swiss-backup.env
ExecStart=/srv/kivou/app/ops/bin/kivou-backup.sh
ExecStart=/srv/kivou/app/ops/bin/kivou-restic-upload.sh
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kivou-backup
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
ReadWritePaths=/srv/kivou/backups
```

Create `ops/systemd/production/kivou-backup.timer`:

```ini
[Unit]
Description=Kivou production — sauvegarde quotidienne

[Timer]
OnCalendar=*-*-* 03:17:00
Persistent=true
RandomizedDelaySec=600
Unit=kivou-backup.service

[Install]
WantedBy=timers.target
```

Do not create a production acquisition unit.

- [ ] **Step 6: Verify and commit systemd contracts**

Run:

```bash
uv run pytest -q tests/test_ops_production_runtime.py tests/test_ops_ingestion_runtime.py
uv run ruff check tests/test_ops_production_runtime.py
systemd-analyze verify ops/systemd/production/*.service ops/systemd/production/*.timer
git diff --check
git add ops/systemd tests/test_ops_production_runtime.py
git commit -m "ops: add isolated production systemd contracts"
```

Expected: tests, Ruff, systemd syntax and whitespace checks pass. Warnings caused
only by repository paths not existing as host runtime paths must be reviewed;
unknown directives or invalid unit syntax are failures.

### Task 4: Add the production nginx candidate without premature HSTS

**Files:**
- Modify: `tests/test_ops_production_runtime.py`
- Create: `ops/nginx/kivou-production.conf`
- Create: `ops/nginx/kivou-production-www.conf`
- Create: `ops/nginx/kivou-production-default-deny.conf`
- Create: `ops/nginx/kivou-production-security-headers.conf`
- Create: `ops/nginx/kivou-production-sensitive-link-security-headers.conf`

- [ ] **Step 1: Add failing route-equivalence and HSTS tests**

Append:

```python
def active_nginx(path: Path) -> tuple[str, ...]:
    return tuple(
        code
        for line in read(path).splitlines()
        if (code := line.split("#", 1)[0].strip())
    )


def test_production_nginx_is_route_equivalent_with_distinct_identity() -> None:
    staging = "\n".join(active_nginx(NGINX / "kivou-staging.conf"))
    production = "\n".join(active_nginx(NGINX / "kivou-production.conf"))
    normalized = (
        production.replace("PRODUCTION_HOST", "STAGING_HOST")
        .replace("kivou-production-security-headers.conf", "kivou-security-headers.conf")
        .replace(
            "kivou-production-sensitive-link-security-headers.conf",
            "kivou-sensitive-link-security-headers.conf",
        )
    )
    assert normalized == staging


def test_production_headers_are_strict_but_defer_hsts() -> None:
    for filename in (
        "kivou-production-security-headers.conf",
        "kivou-production-sensitive-link-security-headers.conf",
    ):
        body = read(NGINX / filename)
        assert "Content-Security-Policy" in body
        assert "script-src 'self'" in body
        assert "unsafe-eval" not in body
        assert "X-Content-Type-Options" in body
        assert "X-Frame-Options" in body
        assert "Strict-Transport-Security" not in body


def test_production_site_contains_no_staging_or_prototype_host() -> None:
    body = "\n".join(
        read(NGINX / filename)
        for filename in (
            "kivou-production.conf",
            "kivou-production-www.conf",
            "kivou-production-default-deny.conf",
        )
    )
    assert "STAGING_HOST" not in body
    assert "staging.kivou.eu" not in body
    assert "chatgpt.site" not in body
    assert "server_name PRODUCTION_HOST;" in body


def test_www_redirects_to_canonical_and_unknown_hosts_are_denied() -> None:
    www = read(NGINX / "kivou-production-www.conf")
    deny = read(NGINX / "kivou-production-default-deny.conf")
    assert www.count("server_name PRODUCTION_WWW_HOST;") == 2
    assert www.count("return 301 https://PRODUCTION_HOST$request_uri;") == 2
    assert "proxy_pass" not in www
    assert "listen 80 default_server;" in deny
    assert "listen 443 ssl default_server;" in deny
    assert "return 444;" in deny
    assert "ssl_reject_handshake on;" in deny
```

- [ ] **Step 2: Run the new tests and verify missing files fail**

Run `uv run pytest -q tests/test_ops_production_runtime.py`.

Expected: failures name the five missing production nginx files.

- [ ] **Step 3: Derive the production site exactly**

Copy `ops/nginx/kivou-staging.conf` to `ops/nginx/kivou-production.conf`, then
apply only these active-directive substitutions:

```text
STAGING_HOST -> PRODUCTION_HOST
/etc/nginx/kivou-security-headers.conf -> /etc/nginx/kivou-production-security-headers.conf
/etc/nginx/kivou-sensitive-link-security-headers.conf -> /etc/nginx/kivou-production-sensitive-link-security-headers.conf
```

Change the introductory comment from staging to production and point it to
`ops/production/README.md`. Do not change a route selector, rate limit, proxy
target, cache rule, sensitive-link gate or TLS protocol directive.

- [ ] **Step 4: Create canonical redirects and the unknown-host sink**

Create `ops/nginx/kivou-production-www.conf`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name PRODUCTION_WWW_HOST;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://PRODUCTION_HOST$request_uri; }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name PRODUCTION_WWW_HOST;
    ssl_certificate /etc/letsencrypt/live/PRODUCTION_HOST/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/PRODUCTION_HOST/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/PRODUCTION_HOST/chain.pem;
    include /etc/nginx/kivou-production-security-headers.conf;
    return 301 https://PRODUCTION_HOST$request_uri;
}
```

Create `ops/nginx/kivou-production-default-deny.conf`:

```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    return 444;
}

server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;
    ssl_reject_handshake on;
}
```

- [ ] **Step 5: Create pre-HSTS production header fragments**

Copy the ordinary and sensitive staging header fragments to their production
names and remove only the final `Strict-Transport-Security` directive and its
HSTS explanatory comment block. Retain CSP, `nosniff`, referrer policy,
`X-Frame-Options`, `Permissions-Policy` and the Stripe form-action allowlist.

- [ ] **Step 6: Run focused tests and commit**

Run:

```bash
uv run pytest -q tests/test_ops_nginx_routes.py tests/test_ops_production_runtime.py
uv run ruff check tests/test_ops_production_runtime.py tests/test_ops_nginx_routes.py
git diff --check
git add ops/nginx tests/test_ops_production_runtime.py
git commit -m "ops: add production nginx candidate"
```

Expected: existing staging route tests still pass, production active directives
are equivalent after the three reviewed substitutions, and production emits no
HSTS yet.

### Task 5: Add fail-closed encrypted off-host backup upload

**Files:**
- Create: `tests/test_ops_restic_runtime.py`
- Create: `ops/bin/kivou-restic-upload.sh`

- [ ] **Step 1: Write failing fake-restic tests**

Create `tests/test_ops_restic_runtime.py`:

```python
from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "ops" / "bin" / "kivou-restic-upload.sh"


class Runtime:
    restic_password = "invented-restic-password"
    swift_password = "invented-swift-password"

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.backups = tmp_path / "backups"
        self.backups.mkdir()
        self.latest = self.backups / "kivou-20260830T120000Z.dump"
        self.latest.write_bytes(b"verified-dump")
        self.latest.chmod(0o600)
        self.restic_log = tmp_path / "restic.calls"
        self.restore_log = tmp_path / "pg_restore.calls"
        self._write_fake(
            "restic",
            f"""
            printf '%s\\n' "$*" >> {self.restic_log}
            if [ "$1" = backup ] && [ "${{FAKE_RESTIC_BACKUP_EXIT:-0}}" -ne 0 ]; then
                exit "$FAKE_RESTIC_BACKUP_EXIT"
            fi
            """,
        )
        self._write_fake(
            "pg_restore",
            f"""
            printf '%s\\n' "$*" >> {self.restore_log}
            exit "${{FAKE_PG_RESTORE_EXIT:-0}}"
            """,
        )

    def _write_fake(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\nset -eu\n" + body)
        path.chmod(0o755)

    def run(self, **extra: str) -> subprocess.CompletedProcess[str]:
        environment = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "KIVOU_BACKUP_DIR": str(self.backups),
            "KIVOU_BACKUP_MAX_AGE_SECONDS": "7200",
            "KIVOU_RESTIC_BIN": "restic",
            "KIVOU_PG_RESTORE": "pg_restore",
            "RESTIC_REPOSITORY": "swift:kivou-production:/postgresql",
            "RESTIC_PASSWORD": self.restic_password,
            "OS_PASSWORD": self.swift_password,
        }
        environment.update(extra)
        return subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=10,
        )

    def calls(self) -> list[str]:
        return self.restic_log.read_text().splitlines() if self.restic_log.exists() else []

    def restore_calls(self) -> list[str]:
        return self.restore_log.read_text().splitlines() if self.restore_log.exists() else []


@pytest.fixture
def runtime(tmp_path: Path) -> Runtime:
    return Runtime(tmp_path)


def test_upload_verifies_then_backs_up_then_applies_retention(runtime):
    result = runtime.run()
    assert result.returncode == 0, result.stderr
    assert runtime.calls() == [
        "backup --tag kivou-postgresql --host kivou-production-01 -- " + str(runtime.latest),
        "forget --tag kivou-postgresql --keep-daily 30 --keep-monthly 12 "
        "--keep-yearly 3 --prune",
    ]
    assert "--list " + str(runtime.latest) in runtime.restore_calls()


def test_failed_upload_never_runs_forget_or_deletes_local_dump(runtime):
    result = runtime.run(FAKE_RESTIC_BACKUP_EXIT="1")
    assert result.returncode != 0
    assert all(not call.startswith("forget ") for call in runtime.calls())
    assert runtime.latest.exists()


def test_missing_dump_is_rejected(runtime):
    runtime.latest.unlink()
    assert runtime.run().returncode != 0
    assert runtime.calls() == []


def test_stale_dump_is_rejected(runtime):
    os.utime(runtime.latest, (0, 0))
    assert runtime.run().returncode != 0
    assert runtime.calls() == []


def test_symlinked_dump_is_rejected(runtime):
    target = runtime.backups / "retained.dump"
    target.write_bytes(b"verified-dump")
    target.chmod(0o600)
    runtime.latest.unlink()
    runtime.latest.symlink_to(target)
    assert runtime.run().returncode != 0
    assert runtime.calls() == []


def test_non_private_dump_is_rejected(runtime):
    runtime.latest.chmod(0o644)
    assert stat.S_IMODE(runtime.latest.stat().st_mode) == 0o644
    assert runtime.run().returncode != 0
    assert runtime.calls() == []


def test_output_never_contains_repository_password_or_swift_password(runtime):
    result = runtime.run()
    assert runtime.restic_password not in result.stdout + result.stderr
    assert runtime.swift_password not in result.stdout + result.stderr
```

- [ ] **Step 2: Run the tests and verify the script is missing**

Run `uv run pytest -q tests/test_ops_restic_runtime.py`.

Expected: `FileNotFoundError` or exit 127 identifies the missing upload script.

- [ ] **Step 3: Implement the upload script**

Create `ops/bin/kivou-restic-upload.sh` with this algorithm and no `set -x`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

KIVOU_OFFSITE_BACKUP_DIR=${KIVOU_BACKUP_DIR:-/srv/kivou/backups}
KIVOU_OFFSITE_MAX_AGE=${KIVOU_BACKUP_MAX_AGE_SECONDS:-7200}
KIVOU_RESTIC=${KIVOU_RESTIC_BIN:-restic}
KIVOU_PG_RESTORE=${KIVOU_PG_RESTORE:-pg_restore}

for KIVOU_REQUIRED_NAME in RESTIC_REPOSITORY RESTIC_PASSWORD; do
  test -n "${!KIVOU_REQUIRED_NAME:-}" || {
    printf 'kivou_offsite_backup=configuration_missing name=%s\n' \
      "$KIVOU_REQUIRED_NAME" >&2
    exit 64
  }
done
command -v "$KIVOU_RESTIC" >/dev/null 2>&1 || exit 69
command -v "$KIVOU_PG_RESTORE" >/dev/null 2>&1 || exit 69

shopt -s nullglob
KIVOU_LATEST_DUMP=
for KIVOU_DUMP_CANDIDATE in "$KIVOU_OFFSITE_BACKUP_DIR"/kivou-*.dump; do
  if [[ -z "$KIVOU_LATEST_DUMP" || \
        "$KIVOU_DUMP_CANDIDATE" -nt "$KIVOU_LATEST_DUMP" ]]; then
    KIVOU_LATEST_DUMP=$KIVOU_DUMP_CANDIDATE
  fi
done
test -n "$KIVOU_LATEST_DUMP" || exit 66
test -f "$KIVOU_LATEST_DUMP" && test ! -L "$KIVOU_LATEST_DUMP" || exit 65
test "$(stat -c %a "$KIVOU_LATEST_DUMP")" = 600 || exit 65
KIVOU_DUMP_AGE=$(( $(date +%s) - $(stat -c %Y "$KIVOU_LATEST_DUMP") ))
test "$KIVOU_DUMP_AGE" -ge 0 && \
  test "$KIVOU_DUMP_AGE" -le "$KIVOU_OFFSITE_MAX_AGE" || exit 75
"$KIVOU_PG_RESTORE" --list "$KIVOU_LATEST_DUMP" >/dev/null
"$KIVOU_RESTIC" backup --tag kivou-postgresql \
  --host kivou-production-01 -- "$KIVOU_LATEST_DUMP"
"$KIVOU_RESTIC" forget --tag kivou-postgresql \
  --keep-daily 30 --keep-monthly 12 --keep-yearly 3 --prune
printf 'kivou_offsite_backup=accepted file=%s\n' \
  "$(basename "$KIVOU_LATEST_DUMP")"
```

The fake runtime supplies invented `RESTIC_PASSWORD`, `OS_PASSWORD` and
`RESTIC_REPOSITORY` values only in its subprocess environment. No test or
script prints them.

- [ ] **Step 4: Run backup suites and commit**

Run:

```bash
chmod 755 ops/bin/kivou-restic-upload.sh
uv run pytest -q tests/test_ops_backup_runtime.py tests/test_ops_restic_runtime.py \
  tests/test_ops_production_runtime.py
uv run ruff check tests/test_ops_backup_runtime.py tests/test_ops_restic_runtime.py \
  tests/test_ops_production_runtime.py
git diff --check
git add ops/bin/kivou-restic-upload.sh tests/test_ops_restic_runtime.py
git commit -m "ops: add verified Swiss Backup upload"
```

Expected: local and off-host backup tests pass; a failed upload cannot run
retention or delete a local dump.

### Task 6: Make TED failures typed but payload-free in journals

**Files:**
- Modify: `src/signals/ingestion/runner.py`
- Modify: `src/signals/ingestion/cli.py`
- Modify: `tests/test_ingestion_runner.py`
- Modify: `tests/test_ingestion_cli.py`

- [ ] **Step 1: Add failing redaction tests**

Add to `tests/test_ingestion_cli.py`:

```python
def test_structured_failure_summary_exposes_type_without_message() -> None:
    outcome = SourceOutcome(
        source="ted",
        status="failed",
        counters=IngestionCounters(),
        duration_seconds=0.1,
        error_category="unexpected",
        error_type="TypeError",
        work_pending=True,
    )

    summary = summarize(outcome)

    assert "error=unexpected error_type=TypeError" in summary
    assert "private-payload-marker" not in summary
```

Add `summarize` to the existing imports in `tests/test_ingestion_runner.py`, then
add:

```python
def test_failed_source_exposes_only_the_typed_root_cause(tmp_path) -> None:
    engine = _engine(tmp_path)
    marker = "private-payload-marker"
    partial = AcquisitionResult(
        source="boamp",
        publications=(),
        fetched=0,
        accepted=0,
        rejected=0,
        complete=False,
        cursor_after={},
    )
    source = SourceStub(
        "boamp",
        error=AcquisitionFailure(TypeError(marker), partial=partial),
    )

    result = IngestionRunner(
        engine,
        sources={"boamp": source},
        pipeline=PipelineStub(),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("boamp",)))

    outcome = result.outcomes[0]
    assert outcome.error_category == "unexpected"
    assert outcome.error_type == "TypeError"
    assert marker not in summarize(outcome)
```

- [ ] **Step 2: Run the tests and verify the missing field fails**

Run:

```bash
uv run pytest -q tests/test_ingestion_cli.py tests/test_ingestion_runner.py \
  -k 'error_type or structured_failure'
```

Expected: failure because `SourceOutcome` does not yet accept or expose
`error_type`.

- [ ] **Step 3: Add a safe root exception type**

In `runner.py`, add `error_type: str | None = None` after `error_category` in
`SourceOutcome`. Add:

```python
def _error_type(error: BaseException) -> str:
    current = error
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        cause = getattr(current, "cause", None)
        if not isinstance(cause, BaseException):
            break
        current = cause
    name = type(current).__name__
    return name if name.isidentifier() and len(name) <= 64 else "Exception"
```

Pass `error_type=_error_type(error)` in all three failure construction paths:
TED, DECP and the generic source isolation block. Do not add the exception
message to `SourceOutcome`.

In `cli.py`, change the start of `summarize()` to:

```python
def summarize(outcome: SourceOutcome) -> str:
    counters = outcome.counters
    error = f" error={outcome.error_category}" if outcome.error_category else ""
    error_type = f" error_type={outcome.error_type}" if outcome.error_type else ""
    return (
        f"source={outcome.source} fetched={counters.records_fetched} "
        f"persisted={counters.records_persisted} linked={counters.representations_linked} "
        f"materialized={counters.signals_materialized} skipped={counters.records_rejected} "
        f"conflicts={counters.opportunity_conflicts} "
        f"rate_limited={counters.rate_limited_count} status={outcome.status}{error}{error_type} "
        f"pending={int(outcome.work_pending)} "
        f"duration={outcome.duration_seconds:.3f}s"
    )
```

Keep the stored database error message unchanged for protected operator
diagnosis.

- [ ] **Step 4: Run ingestion tests and commit**

Run:

```bash
uv run pytest -q tests/test_ingestion_cli.py tests/test_ingestion_runner.py \
  tests/test_ingestion_sources.py tests/test_ted_client.py
uv run ruff check src/signals/ingestion/runner.py src/signals/ingestion/cli.py \
  tests/test_ingestion_cli.py tests/test_ingestion_runner.py
git diff --check
git add src/signals/ingestion/runner.py src/signals/ingestion/cli.py \
  tests/test_ingestion_cli.py tests/test_ingestion_runner.py
git commit -m "fix(ingestion): expose safe typed failure diagnostics"
```

Expected: tests and Ruff pass; no provider payload or exception message is
printed by the summary.

### Task 7: Write the production installation and rollback runbook

**Files:**
- Create: `ops/production/README.md`
- Modify: `tests/test_ops_production_runtime.py`

- [ ] **Step 1: Add failing runbook contract tests**

Append a test requiring the runbook to contain, in order:

```python
def test_production_runbook_is_disabled_first_and_gate_ordered() -> None:
    body = read(ROOT / "ops" / "production" / "README.md")
    required = (
        "git ls-remote --exit-code",
        "systemd-analyze verify",
        "nginx -t",
        "/etc/kivou/production.env",
        "/etc/kivou/swiss-backup.env",
        "systemctl disable --now",
        "pg_restore --list",
        "restic restore latest",
        "kivou-ingest@simap.service",
        "kivou-ingest@boamp.service",
        "kivou-ingest@decp.service",
        "kivou-ingest@ted.service",
        "readlink -f /srv/kivou/app",
        "readlink -f /srv/kivou/frontend",
        "mv -Tf",
    )
    for value in required:
        assert value in body
    assert body.index("systemctl start kivou-ingest@simap.service") < body.index(
        "systemctl enable --now kivou-ingest-simap.timer"
    )
    assert "source /etc/kivou/production.env" not in body
    assert "systemctl enable --now kivou-acquisition" not in body
    assert "certbot --nginx" not in body
```

- [ ] **Step 2: Run the test and verify the runbook is missing**

Run `uv run pytest -q tests/test_ops_production_runtime.py`.

Expected: failure names `ops/production/README.md`.

- [ ] **Step 3: Write exact Release 2 preparation commands**

Create `ops/production/README.md` with the safety boundary and these executable
blocks. The first block validates the exact SHA without reading a secret:

```bash
set -euo pipefail
: "${KIVOU_PRODUCTION_RELEASE_SHA:?set the reviewed 40-hex main SHA}"
printf '%s\n' "$KIVOU_PRODUCTION_RELEASE_SHA" | grep -Eq '^[0-9a-f]{40}$'
KIVOU_PRODUCTION_REMOTE=git@github.com:bruppacherrodrigue-art/Kivou.git
KIVOU_PRODUCTION_DEPLOY_KEY=/srv/kivou/.ssh/github_deploy
KIVOU_PRODUCTION_KNOWN_HOSTS=/etc/kivou/github-known-hosts
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_PRODUCTION_DEPLOY_KEY")" = kivou:kivou:600
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_PRODUCTION_KNOWN_HOSTS")" = root:root:644
KIVOU_PRODUCTION_SSH_COMMAND="/usr/bin/ssh -F /dev/null -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KIVOU_PRODUCTION_KNOWN_HOSTS -o GlobalKnownHostsFile=/dev/null -i $KIVOU_PRODUCTION_DEPLOY_KEY"
KIVOU_PRODUCTION_REMOTE_MAIN=$(sudo -u kivou /usr/bin/env -i \
  HOME=/srv/kivou PATH=/usr/bin:/bin GIT_CONFIG_GLOBAL=/dev/null \
  GIT_CONFIG_NOSYSTEM=1 GIT_SSH_COMMAND="$KIVOU_PRODUCTION_SSH_COMMAND" \
  /usr/bin/git ls-remote --exit-code "$KIVOU_PRODUCTION_REMOTE" refs/heads/main |
  awk '$2 == "refs/heads/main" {print $1}')
test "$KIVOU_PRODUCTION_REMOTE_MAIN" = "$KIVOU_PRODUCTION_RELEASE_SHA"
```

The clean backend checkout and deterministic build block is:

```bash
KIVOU_PRODUCTION_RELEASE_UTC=$(date -u +%Y%m%dT%H%M%SZ)
KIVOU_PRODUCTION_RELEASE_SHORT=${KIVOU_PRODUCTION_RELEASE_SHA:0:12}
KIVOU_PRODUCTION_BACKEND=/srv/kivou/releases/backend-$KIVOU_PRODUCTION_RELEASE_UTC-$KIVOU_PRODUCTION_RELEASE_SHORT
sudo install -o kivou -g kivou -m 755 -d /srv/kivou/releases
sudo test ! -e "$KIVOU_PRODUCTION_BACKEND"
sudo -u kivou /usr/bin/git init --quiet --initial-branch=main "$KIVOU_PRODUCTION_BACKEND"
sudo -u kivou /usr/bin/git -C "$KIVOU_PRODUCTION_BACKEND" remote add origin \
  "$KIVOU_PRODUCTION_REMOTE"
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
  GIT_SSH_COMMAND="$KIVOU_PRODUCTION_SSH_COMMAND" \
  /usr/bin/git -C "$KIVOU_PRODUCTION_BACKEND" fetch --no-tags origin \
  +refs/heads/main:refs/kivou-rollout/reviewed-main
sudo -u kivou /usr/bin/git -C "$KIVOU_PRODUCTION_BACKEND" checkout --detach \
  "$KIVOU_PRODUCTION_RELEASE_SHA"
test "$(sudo -u kivou git -C "$KIVOU_PRODUCTION_BACKEND" rev-parse HEAD)" = \
  "$KIVOU_PRODUCTION_RELEASE_SHA"
test -z "$(sudo -u kivou git -C "$KIVOU_PRODUCTION_BACKEND" status --porcelain)"
sudo -u kivou /usr/bin/env --chdir="$KIVOU_PRODUCTION_BACKEND" \
  /usr/local/bin/uv sync --frozen --extra server --extra postgres
sudo -u kivou /usr/bin/env --chdir="$KIVOU_PRODUCTION_BACKEND" \
  /usr/local/bin/uv run pytest -q
sudo -u kivou /usr/bin/env --chdir="$KIVOU_PRODUCTION_BACKEND" \
  /usr/local/bin/uv run ruff check .
sudo -u kivou /usr/bin/env --chdir="$KIVOU_PRODUCTION_BACKEND/frontend" npm ci
sudo -u kivou /usr/bin/env --chdir="$KIVOU_PRODUCTION_BACKEND/frontend" npm test -- --run
sudo -u kivou /usr/bin/env --chdir="$KIVOU_PRODUCTION_BACKEND/frontend" npm run build
sudo -u kivou /usr/bin/env --chdir="$KIVOU_PRODUCTION_BACKEND/frontend" npx tsc -b
sudo -u kivou /usr/bin/env --chdir="$KIVOU_PRODUCTION_BACKEND/frontend" npm run lint
test -z "$(sudo -u kivou git -C "$KIVOU_PRODUCTION_BACKEND" status --porcelain)"
```

Before installing any unit, validate protected files and disable every timer:

```bash
for KIVOU_PROTECTED_FILE in \
  /etc/kivou/production.env /etc/kivou/swiss-backup.env; do
  sudo test -f "$KIVOU_PROTECTED_FILE"
  sudo test ! -L "$KIVOU_PROTECTED_FILE"
  test "$(sudo stat -c '%U:%G:%a' "$KIVOU_PROTECTED_FILE")" = root:root:600
done
sudo systemctl disable --now kivou-alerts.timer kivou-backup.timer \
  kivou-ingest-simap.timer kivou-ingest-boamp.timer \
  kivou-ingest-decp.timer kivou-ingest-ted.timer 2>/dev/null || true
sudo systemd-analyze verify "$KIVOU_PRODUCTION_BACKEND"/ops/systemd/production/*.service \
  "$KIVOU_PRODUCTION_BACKEND"/ops/systemd/production/*.timer
for KIVOU_UNIT_SOURCE in "$KIVOU_PRODUCTION_BACKEND"/ops/systemd/production/*; do
  KIVOU_UNIT_NAME=$(basename "$KIVOU_UNIT_SOURCE")
  sudo install -o root -g root -m 644 "$KIVOU_UNIT_SOURCE" \
    "/etc/systemd/system/$KIVOU_UNIT_NAME.new"
  sudo mv -f "/etc/systemd/system/$KIVOU_UNIT_NAME.new" \
    "/etc/systemd/system/$KIVOU_UNIT_NAME"
done
sudo systemctl daemon-reload
```

The backup and isolated restore proof is:

```bash
sudo systemctl start kivou-backup.service
sudo systemctl is-failed --quiet kivou-backup.service && exit 1 || true
KIVOU_LOCAL_DUMP=$(sudo find /srv/kivou/backups -maxdepth 1 -type f \
  -name 'kivou-*.dump' -printf '%T@ %p\n' | sort -nr | awk 'NR == 1 {$1=""; sub(/^ /, ""); print}')
case "$KIVOU_LOCAL_DUMP" in /srv/kivou/backups/kivou-*.dump) ;; *) exit 69 ;; esac
sudo pg_restore --list "$KIVOU_LOCAL_DUMP" >/dev/null
KIVOU_RESTORE_DIR=$(sudo mktemp -d /srv/kivou/validation/restore.XXXXXX)
sudo chmod 700 "$KIVOU_RESTORE_DIR"
sudo systemd-run --wait --pipe --collect \
  --property=EnvironmentFile=/etc/kivou/swiss-backup.env \
  /usr/bin/restic restore latest --tag kivou-postgresql --target "$KIVOU_RESTORE_DIR"
KIVOU_RESTORED_DUMP=$(sudo find "$KIVOU_RESTORE_DIR" -type f \
  -name 'kivou-*.dump' -print -quit)
case "$KIVOU_RESTORED_DUMP" in "$KIVOU_RESTORE_DIR"/*/kivou-*.dump) ;; *) exit 69 ;; esac
sudo pg_restore --list "$KIVOU_RESTORED_DUMP" >/dev/null
KIVOU_RESTORE_DB=kivou_restore_$(date -u +%Y%m%d%H%M%S)_$$
printf '%s\n' "$KIVOU_RESTORE_DB" | grep -Eq '^kivou_restore_[0-9]{14}_[0-9]+$'
sudo -u postgres createdb "$KIVOU_RESTORE_DB"
sudo -u postgres pg_restore --exit-on-error --no-owner --no-privileges \
  --dbname "$KIVOU_RESTORE_DB" "$KIVOU_RESTORED_DUMP"
sudo -u postgres psql --no-psqlrc --tuples-only --no-align \
  --dbname "$KIVOU_RESTORE_DB" --command 'select version_num from alembic_version;'
sudo -u postgres dropdb "$KIVOU_RESTORE_DB"
```

The nginx candidate is rendered only after the certificate files exist:

```bash
KIVOU_PRODUCTION_HOST=kivou.eu
KIVOU_PRODUCTION_API_PORT=8001
test -f /etc/letsencrypt/live/kivou.eu/fullchain.pem
test -f /etc/letsencrypt/live/kivou.eu/privkey.pem
test -f /etc/letsencrypt/live/kivou.eu/chain.pem
sudo install -o root -g root -m 644 \
  "$KIVOU_PRODUCTION_BACKEND/ops/nginx/kivou-limits.conf" \
  /etc/nginx/conf.d/kivou-limits.conf.new
sudo install -o root -g root -m 644 \
  "$KIVOU_PRODUCTION_BACKEND/ops/nginx/kivou-proxy-params.conf" \
  "$KIVOU_PRODUCTION_BACKEND/ops/nginx/kivou-production-security-headers.conf" \
  "$KIVOU_PRODUCTION_BACKEND/ops/nginx/kivou-production-sensitive-link-security-headers.conf" \
  "$KIVOU_PRODUCTION_BACKEND/ops/nginx/kivou-production-default-deny.conf" \
  "$KIVOU_PRODUCTION_BACKEND/ops/nginx/kivou-sensitive-links-open.conf" \
  "$KIVOU_PRODUCTION_BACKEND/ops/nginx/kivou-sensitive-links-closed.conf" \
  /etc/nginx/
sudo install -o root -g root -m 600 \
  "$KIVOU_PRODUCTION_BACKEND/ops/nginx/kivou-sensitive-links-closed.conf" \
  /etc/nginx/kivou-sensitive-links-gate.conf
sed -e "s/PRODUCTION_HOST/$KIVOU_PRODUCTION_HOST/g" \
  -e "s/KIVOU_API_PORT/$KIVOU_PRODUCTION_API_PORT/g" \
  "$KIVOU_PRODUCTION_BACKEND/ops/nginx/kivou-production.conf" |
  sudo tee /etc/nginx/sites-available/kivou.new >/dev/null
sudo chown root:root /etc/nginx/sites-available/kivou.new
sudo chmod 644 /etc/nginx/sites-available/kivou.new
KIVOU_PRODUCTION_WWW_HOST=www.kivou.eu
sed -e "s/PRODUCTION_WWW_HOST/$KIVOU_PRODUCTION_WWW_HOST/g" \
  -e "s/PRODUCTION_HOST/$KIVOU_PRODUCTION_HOST/g" \
  "$KIVOU_PRODUCTION_BACKEND/ops/nginx/kivou-production-www.conf" |
sudo tee /etc/nginx/sites-available/kivou-www.new >/dev/null
sudo chown root:root /etc/nginx/sites-available/kivou-www.new
sudo chmod 644 /etc/nginx/sites-available/kivou-www.new
KIVOU_NGINX_CANDIDATE=$(sudo mktemp -d /etc/nginx/.kivou-production-candidate.XXXXXX)
sudo chmod 700 "$KIVOU_NGINX_CANDIDATE"
sudo tee "$KIVOU_NGINX_CANDIDATE/nginx.conf" >/dev/null <<EOF
pid $KIVOU_NGINX_CANDIDATE/nginx.pid;
error_log stderr;
events {}
http {
    include /etc/nginx/mime.types;
    include /etc/nginx/conf.d/kivou-limits.conf.new;
    include /etc/nginx/kivou-production-default-deny.conf;
    include /etc/nginx/sites-available/kivou.new;
    include /etc/nginx/sites-available/kivou-www.new;
}
EOF
sudo chmod 644 "$KIVOU_NGINX_CANDIDATE/nginx.conf"
sudo nginx -t -c "$KIVOU_NGINX_CANDIDATE/nginx.conf"
```

The runbook captures both old targets before any atomic switch:

```bash
KIVOU_PREVIOUS_APP=ABSENT
KIVOU_PREVIOUS_FRONTEND=ABSENT
sudo test -L /srv/kivou/app && KIVOU_PREVIOUS_APP=$(sudo readlink -f /srv/kivou/app)
sudo test -L /srv/kivou/frontend && KIVOU_PREVIOUS_FRONTEND=$(sudo readlink -f /srv/kivou/frontend)
case "$KIVOU_PREVIOUS_APP" in ABSENT|/srv/kivou/releases/backend-*) ;; *) exit 69 ;; esac
case "$KIVOU_PREVIOUS_FRONTEND" in ABSENT|/srv/kivou/releases/frontend-*) ;; *) exit 69 ;; esac
KIVOU_APP_NEXT_DIR=$(sudo mktemp -d /srv/kivou/.app-next.XXXXXX)
sudo ln -s "$KIVOU_PRODUCTION_BACKEND" "$KIVOU_APP_NEXT_DIR/app.next"
sudo mv -Tf "$KIVOU_APP_NEXT_DIR/app.next" /srv/kivou/app
```

Manual source proof and enablement remains ordered and source-local:

```bash
sudo systemctl start kivou-ingest@simap.service
sudo systemctl is-failed --quiet kivou-ingest@simap.service && exit 1 || true
sudo systemctl enable --now kivou-ingest-simap.timer
sudo systemctl start kivou-ingest@boamp.service
sudo systemctl is-failed --quiet kivou-ingest@boamp.service && exit 1 || true
sudo systemctl enable --now kivou-ingest-boamp.timer
sudo systemctl start kivou-ingest@decp.service
sudo systemctl is-failed --quiet kivou-ingest@decp.service && exit 1 || true
sudo systemctl enable --now kivou-ingest-decp.timer
sudo systemctl start kivou-ingest@ted.service
sudo systemctl is-failed --quiet kivou-ingest@ted.service && exit 1 || true
sudo systemctl enable --now kivou-ingest-ted.timer
```

Rollback disables the failed source and restores only captured immutable
targets. If a captured target is `ABSENT`, leave the corresponding service or
site disabled instead of creating a fake rollback:

```bash
sudo systemctl disable --now kivou-ingest-ted.timer
if [[ "$KIVOU_PREVIOUS_APP" != ABSENT ]]; then
  KIVOU_APP_ROLLBACK_DIR=$(sudo mktemp -d /srv/kivou/.app-rollback.XXXXXX)
  sudo ln -s "$KIVOU_PREVIOUS_APP" "$KIVOU_APP_ROLLBACK_DIR/app.next"
  sudo mv -Tf "$KIVOU_APP_ROLLBACK_DIR/app.next" /srv/kivou/app
  sudo systemctl restart kivou-api.service
else
  sudo systemctl disable --now kivou-api.service
fi
if [[ "$KIVOU_PREVIOUS_FRONTEND" != ABSENT ]]; then
  KIVOU_FRONTEND_ROLLBACK_DIR=$(sudo mktemp -d /srv/kivou/.frontend-rollback.XXXXXX)
  sudo ln -s "$KIVOU_PREVIOUS_FRONTEND" "$KIVOU_FRONTEND_ROLLBACK_DIR/frontend.next"
  sudo mv -Tf "$KIVOU_FRONTEND_ROLLBACK_DIR/frontend.next" /srv/kivou/frontend
fi
sudo nginx -t
```

The prose around these blocks states that Release 1 does not execute them, old
releases and backups are never deleted, environment files are never sourced,
and DNS, Stripe, SMTP, provider and Acquisition Engine mutations are excluded.

- [ ] **Step 4: Verify and commit the runbook**

Run:

```bash
uv run pytest -q tests/test_ops_production_runtime.py tests/test_ops_nginx_routes.py \
  tests/test_ops_backup_runtime.py tests/test_ops_restic_runtime.py
uv run ruff check tests/test_ops_production_runtime.py tests/test_ops_restic_runtime.py
git diff --check
git add ops/production/README.md tests/test_ops_production_runtime.py
git commit -m "docs(ops): add production runtime activation runbook"
```

Expected: runbook contract, nginx and both backup suites pass.

### Task 8: Full verification, review, merge and main CI

**Files:**
- All files changed by Tasks 3–7

- [ ] **Step 1: Run the full backend and frontend gates**

Run:

```bash
uv sync --locked
uv run pytest -q
uv run ruff check .
cd frontend
npm ci
npm test -- --run
npm run build
npx tsc -b
npm run lint
```

Expected: all backend tests, Ruff, frontend tests, build, typecheck and lint pass.

- [ ] **Step 2: Run operations-specific syntax and secret scans**

From the repository root, run:

```bash
systemd-analyze verify ops/systemd/production/*.service ops/systemd/production/*.timer
git diff --check origin/main...HEAD
rg -n 'sk_live_|sk_test_|whsec_|SMTP_PASSWORD=.+|KIVOU_APOLLO_API_KEY=.+' \
  ops/systemd/production ops/nginx/kivou-production* ops/production \
  ops/bin/kivou-restic-upload.sh
```

Expected: systemd syntax succeeds, whitespace check is empty, and the secret
scan returns no matches. An `rg` exit code of 1 is the expected no-match result.

- [ ] **Step 3: Request code review and address only evidence-backed findings**

Invoke `superpowers:requesting-code-review`. Re-run the focused tests after each
accepted change and preserve the no-production-mutation boundary.

- [ ] **Step 4: Push and open the runtime-foundations PR**

Run:

```bash
git push -u origin ops/production-runtime-foundations
gh pr create --repo bruppacherrodrigue-art/Kivou \
  --base main --head ops/production-runtime-foundations \
  --title "Add isolated production runtime foundations" \
  --body-file docs/superpowers/specs/2026-08-30-production-go-live-design.md
```

Expected: the PR contains only the reviewed Release 1 files.

- [ ] **Step 5: Verify exact-head CI, squash-merge and verify exact-main CI**

Use the same exact-head, mergeability, squash-merge, resulting-main and
successor-CI procedure from Task 1. If `main` advanced, rebase, rerun the full
local gates and require CI for the new head. Never merge or deploy a superseded
SHA.

- [ ] **Step 6: Record Release 1 completion evidence**

Record the PR number, exact reviewed head, squash SHA, resulting `main` SHA, CI
run IDs, test counts, files added and explicit confirmation that no production
host, DNS, Stripe, SMTP, database, provider or acquisition state changed.

Release 1 is then complete. Write the separate Release 2 implementation plan
from `2026-08-30-production-go-live-design.md` before installing or activating
these assets on the production host.
