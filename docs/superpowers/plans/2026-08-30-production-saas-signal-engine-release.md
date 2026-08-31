# Kivou Production SaaS and Signal Engine Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Deploy the exact green main SHA to the production VPS, create a fresh production database, prove backup recovery, publish the SaaS safely, and activate each Signal Engine source only after its own bounded smoke succeeds.

**Architecture:** Reuse the versioned fail-closed runbook in ops/production/README.md. Build immutable backend and frontend releases from one reviewed SHA, keep nginx as the only public listener, PostgreSQL on loopback, and all timers disabled until their stop gates pass. Release 2 never copies staging state and never activates Acquisition, Apollo, Instantly, Hermes, a Stripe payment, or an unapproved tax setting.

**Tech Stack:** Ubuntu 24.04, systemd, nginx 1.24, PostgreSQL 16, Python 3.12, uv 0.12.5, Node 24, npm, Alembic, restic/Swiss Backup, Certbot, GitHub Actions, Playwright.

---

## Fixed evidence and current blockers

- Release 1 PR: #128.
- Reviewed PR head: e015a955d3dd849b9752de7be79e2f8cdaf42a59.
- Squash/main SHA: 5e0e7e29df8db75089e51bce845343c1f88c565e.
- PR CI: 33329955439, backend and frontend successful.
- Main CI: 33331502374, backend and frontend successful.
- Production host: kivou-production, 179.237.105.52.
- Host baseline already verified: 4 vCPU, 8 GiB RAM, 160 GB disk, 4 GiB swap, UFW deny-in with only 22/80/443, key-only SSH, fail2ban, PostgreSQL loopback, unattended upgrades, valid current nginx syntax.
- Currently absent: production GitHub deploy key, pinned GitHub known_hosts, production.env, swiss-backup.env, acquisition production files, Kivou TLS certificate, apex/www DNS, Kivou systemd units and active app/frontend links.

Missing protected provider credentials are a stop gate, not permission to request them in chat. The operator must enter them through the provider console or a protected root TTY. Commands and reports expose only metadata and counters.

### Task 1: Reconfirm exact authority and freeze production scope

**Files:**
- Read: ops/production/README.md
- Read: docs/superpowers/specs/2026-08-30-production-go-live-design.md
- Create remotely after mutation approval: /srv/kivou/validation/release2-<UTC>/

- [ ] **Step 1: Re-read GitHub authority**

```bash
git fetch origin main
test "$(git rev-parse origin/main)" = 5e0e7e29df8db75089e51bce845343c1f88c565e
gh run view 33331502374 --repo bruppacherrodrigue-art/Kivou \
  --json headSha,status,conclusion
```

Expected: exact SHA, completed, success. If main moved, stop and repeat exact-SHA review and CI; never deploy a superseded SHA.

- [ ] **Step 2: Re-run the read-only VPS audit**

```bash
ssh -o BatchMode=yes kivou-production \
  'hostnamectl; nproc; free -h; df -hT /; sudo systemctl --failed --no-pager; \
  sudo ss -lntup; sudo ufw status verbose; sudo nginx -t; \
  systemctl list-unit-files "kivou-*" --no-pager'
```

Expected: hostname kivou-production-01, no failed units, only SSH public before nginx activation, PostgreSQL on 127.0.0.1:5432, UFW active, nginx syntax valid, no Kivou units installed.

- [ ] **Step 3: Record explicit exclusions**

Record in the execution log: staging untouched; no DNS mutation yet; no Stripe payment; no SMTP message; no Acquisition/Apollo/Instantly/Hermes call; no staging database, secret, account or deploy key copied.

### Task 2: Create a production-only read-only GitHub deploy identity

**Files:**
- Create remotely: /srv/kivou/.ssh/github_deploy
- Create remotely: /srv/kivou/.ssh/github_deploy.pub
- Create remotely: /etc/nginx/kivou-github-known-hosts
- Mutate on GitHub: one read-only deploy key for bruppacherrodrigue-art/Kivou

- [ ] **Step 1: Generate the key on the production host**

```bash
ssh -tt kivou-production 'sudo bash -se' <<'REMOTE'
set -Eeuo pipefail
test ! -e /srv/kivou/.ssh/github_deploy
install -o kivou -g kivou -m 700 -d /srv/kivou/.ssh
sudo -u kivou ssh-keygen -q -t ed25519 -N '' \
  -C kivou-production-01-read-only -f /srv/kivou/.ssh/github_deploy
chown kivou:kivou /srv/kivou/.ssh/github_deploy*
chmod 600 /srv/kivou/.ssh/github_deploy
chmod 644 /srv/kivou/.ssh/github_deploy.pub
REMOTE
```

Expected: a new production-only key. Never copy the staging deploy key. Do not print the private key.

- [ ] **Step 2: Add only the public half as a read-only GitHub deploy key**

```bash
KIVOU_DEPLOY_PUBLIC=$(ssh kivou-production \
  'sudo cat /srv/kivou/.ssh/github_deploy.pub')
gh api repos/bruppacherrodrigue-art/Kivou/keys \
  -f title=kivou-production-01-read-only \
  -f key="$KIVOU_DEPLOY_PUBLIC" -F read_only=true \
  --jq '{id,title,read_only}'
unset KIVOU_DEPLOY_PUBLIC
```

Expected: read_only true. If a same-title key exists, compare its public fingerprint and reuse only an exact match; never create duplicates blindly.

- [ ] **Step 3: Install and verify GitHub's reviewed Ed25519 host key**

Use the current official GitHub fingerprint authority:
https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints

Expected Ed25519 fingerprint: SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU.

```bash
ssh -tt kivou-production 'sudo bash -se' <<'REMOTE'
set -Eeuo pipefail
umask 077
KIVOU_KNOWN_HOSTS_NEW=$(mktemp /etc/nginx/kivou-github-known-hosts.new.XXXXXX)
printf '%s\n' \
  'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' \
  >"$KIVOU_KNOWN_HOSTS_NEW"
test "$(ssh-keygen -lf "$KIVOU_KNOWN_HOSTS_NEW" -E sha256 | awk '{print $2}')" = \
  'SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU'
chown root:root "$KIVOU_KNOWN_HOSTS_NEW"
chmod 644 "$KIVOU_KNOWN_HOSTS_NEW"
mv -Tf "$KIVOU_KNOWN_HOSTS_NEW" /etc/nginx/kivou-github-known-hosts
REMOTE
```

Then run the exact `ls-remote` command from runbook section 1. The returned
`refs/heads/main` must equal the approved SHA.

### Task 3: Create the fresh database and minimal fail-closed production environment

**Files:**
- Create remotely: PostgreSQL role kivou_app
- Create remotely: PostgreSQL database kivou
- Create remotely: /etc/kivou/production.env
- Do not create: acquisition-production.env or acquisition-production.json

- [ ] **Step 1: Prove the database and role are absent**

```bash
ssh kivou-production \
  "sudo -u postgres psql -Atqc \"select rolname from pg_roles where rolname='kivou_app';\"; \
   sudo -u postgres psql -Atqc \"select datname from pg_database where datname='kivou';\""
```

Expected: empty. Any existing object requires an ownership/schema audit before continuing.

- [ ] **Step 2: Create credentials only in host memory and persist them only in the protected env file**

In one root shell with history disabled and xtrace off:

```bash
set -Eeuo pipefail
set +x
set +o history
umask 077
KIVOU_DB_PASSWORD=$(openssl rand -hex 32)
printf "CREATE ROLE kivou_app LOGIN PASSWORD '%s' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;\n" \
  "$KIVOU_DB_PASSWORD" | sudo -u postgres psql -v ON_ERROR_STOP=1
sudo -u postgres createdb --template=template0 --encoding=UTF8 \
  --owner=kivou_app kivou
KIVOU_ENV_NEW=$(mktemp /etc/kivou/production.env.new.XXXXXX)
printf '%s\n' \
  "KIVOU_DATABASE_URL=postgresql+psycopg://kivou_app:$KIVOU_DB_PASSWORD@127.0.0.1:5432/kivou" \
  "KIVOU_ALLOWED_ORIGIN=https://kivou.eu" \
  "KIVOU_COOKIE_SECURE=1" \
  "KIVOU_PUBLIC_APP_URL=https://kivou.eu" \
  "KIVOU_STRIPE_MODE=live" \
  "STRIPE_AUTOMATIC_TAX_ENABLED=0" \
  "KIVOU_DECP_MAX_WINDOWS_PER_RUN=2" \
  "KIVOU_DECP_BATCH_SIZE=100" \
  "KIVOU_DECP_TIME_BUDGET_SECONDS=1200" \
  "KIVOU_DECP_OVERLAP_DAYS=30" \
  "KIVOU_TED_REQUEST_INTERVAL_SECONDS=1" \
  "KIVOU_TED_MAX_ATTEMPTS=4" \
  "KIVOU_TED_MAX_RETRY_SECONDS=120" \
  "KIVOU_TED_MAX_RECORDS_PER_RUN=500" \
  "KIVOU_TED_TIME_BUDGET_SECONDS=1200" \
  >"$KIVOU_ENV_NEW"
chown root:root "$KIVOU_ENV_NEW"
chmod 600 "$KIVOU_ENV_NEW"
mv -Tf "$KIVOU_ENV_NEW" /etc/kivou/production.env
unset KIVOU_DB_PASSWORD
```

Expected: production.env is a regular non-symlink root:root 0600. Stripe has explicit live identity but no key, so billing stays unavailable rather than falling back to TEST. SMTP remains unavailable and alerts stay disabled. Acquisition remains UNCONFIGURED.

- [ ] **Step 3: Prove protected-file isolation**

Before building, require `production.env` to be a regular, non-symlink
`root:root 0600` file and confirm that the acquisition files remain absent.
The typed configuration and database connection are checked from the exact
candidate in Task 4. Never print `repr(config)` or environment values.

### Task 4: Build the exact immutable candidate and migrate the fresh database

**Files:**
- Create remotely: /srv/kivou/releases/backend-<UTC>-5e0e7e29df8d
- Create remotely: /srv/kivou/releases/frontend-<UTC>-5e0e7e29df8d
- Modify remotely: fresh production database schema only

- [ ] **Step 1: Execute runbook sections 1 and 2 exactly**

Run the complete fenced Bash blocks under:

- 1. Vérifier et extraire le SHA exact de main
- 2. Construire les releases verrouillées et immuables

Enter only 5e0e7e29df8db75089e51bce845343c1f88c565e at the reviewed-SHA prompt.

Expected: detached clean checkout at the exact SHA; backend and frontend tests/lint/build pass; immutable root-owned releases exist; no active symlink changed.

- [ ] **Step 2: Back up and restore-check the still-empty database**

Before the first migration, run `ops/bin/kivou-backup.sh` from the exact
candidate in a transient `kivou` unit with `production.env`,
`InaccessiblePaths=/srv/kivou/.ssh`, `ReadWritePaths=/srv/kivou/backups` and
`TimeoutStartSec=2h`. First prove that the public schema has zero tables, then
set `Environment=KIVOU_BACKUP_MIN_BYTES=1` only for this empty-database dump:
the normal 4 KiB floor deliberately rejects PostgreSQL's valid 871-byte empty
custom archive. Require a new regular `kivou:kivou 0600` dump, validate it with
`pg_restore --list`, restore a protected temporary copy into a uniquely named
temporary PostgreSQL database and prove that the restored public schema is
empty. Drop only that temporary restore database and remove only its protected
copy after the proof; retain the source pre-migration dump. All post-migration
and scheduled backups use the normal 4 KiB minimum unchanged.

- [ ] **Step 3: Apply migrations through a bounded transient systemd unit**

```bash
sudo systemd-run --wait --pipe --collect --unit=kivou-migrate-release2 \
  --property=Type=oneshot --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_BACKEND_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/production.env \
  --property=UMask=0077 --property=NoNewPrivileges=yes \
  --property=TimeoutStartSec=10min \
  --property=ProtectSystem=strict --property=ProtectHome=yes \
  --property=InaccessiblePaths=/srv/kivou/.ssh \
  --property=ReadOnlyPaths="$KIVOU_BACKEND_RELEASE_DIR" \
  -- "$KIVOU_BACKEND_RELEASE_DIR/.venv/bin/python" -c '
from signals.persistence.database import create_database_engine, migrate_to_latest
engine = create_database_engine(pool_pre_ping=True)
try:
    migrate_to_latest(engine)
finally:
    engine.dispose()
'
```

Expected: zero exit. This repository deliberately has no `alembic.ini`; the
standalone Alembic CLI is not a valid migration entry point. Query
`alembic_version` through another protected transient unit and require the exact
reviewed head `0027_signal_notes`. No migration downgrade is permitted.
If migration fails, do not retry in place: stop all candidates, rename the
partial database to `kivou_failed_<UTC>` for forensics, recreate a fresh
`kivou` owned by `kivou_app`, restore the retained pre-migration dump and prove
the restored empty schema. No failed database or dump is deleted.

- [ ] **Step 4: Validate typed configuration and the loopback candidate**

First run a protected one-shot Python process from the candidate release that
loads `ApiConfig.from_environment()` and prints only these booleans/identities:
secure cookie true, allowed/public origins equal `https://kivou.eu`, Stripe mode
live, Stripe key absent, alerts unconfigured and Acquisition environment
`UNCONFIGURED`. Then start the API candidate exactly as follows:
The configuration one-shot uses the same deploy-key isolation and a two-minute
timeout as the API candidate.

```bash
sudo systemd-run --unit=kivou-api-green.service --collect \
  --property=Type=simple --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_BACKEND_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/production.env \
  --property=UMask=0077 --property=NoNewPrivileges=yes \
  --property=TimeoutStartSec=2min \
  --property=RuntimeMaxSec=5min --property=TimeoutStopSec=30s \
  --property=ProtectSystem=strict --property=ProtectHome=yes \
  --property=InaccessiblePaths=/srv/kivou/.ssh \
  --property=ReadOnlyPaths="$KIVOU_BACKEND_RELEASE_DIR" \
  -- "$KIVOU_BACKEND_RELEASE_DIR/.venv/bin/uvicorn" signals.api.asgi:app \
  --host 127.0.0.1 --port 8001 --workers 2 --proxy-headers \
  --forwarded-allow-ips 127.0.0.1 --no-server-header --no-access-log \
  --timeout-keep-alive 20
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/bin/kivou-api-readiness.sh" \
  kivou-api-green.service 8001
curl --fail --silent --show-error --output /dev/null \
  http://127.0.0.1:8001/openapi.json
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  http://127.0.0.1:8001/me)" = 401
sudo systemctl stop kivou-api-green.service
sudo systemctl reset-failed kivou-api-green.service || true
```

Expected: readiness succeeds, database-backed app construction succeeds and
anonymous `/me` returns the expected protection. Inspect the candidate journal
for generic errors only, then stop it. No `0.0.0.0` listener is allowed.

### Task 5: Close protected external gates

**Files:**
- Create remotely through protected channel: /etc/kivou/swiss-backup.env
- Extend remotely through protected channel: /etc/kivou/production.env
- External configuration: Swiss Backup, Stripe LIVE, SMTP, DNS and TLS

- [ ] **Step 1: Swiss Backup gate**

The operator installs the dedicated production restic/Swift values directly through the Infomaniak protected interface or a root TTY, never chat. Require a regular non-symlink root:root 0600 swiss-backup.env. Execute runbook section 6 exactly and require: local dump valid, encrypted upload success, restore latest by host+tag, temporary PostgreSQL restore success, readable Alembic version, cleanup complete.

If credentials are unavailable, status is BLOCKED_SWISS_BACKUP and public activation stops.

- [ ] **Step 2: Stripe LIVE gate without payment**

Use a production-only restricted API key where the existing Checkout/Billing endpoints permit it; apply an IP restriction to 179.237.105.52 when compatible. Configure the webhook for https://kivou.eu/webhooks/stripe, LIVE products/prices, customer portal and return URLs. Store the key and webhook secret only in production.env through a protected root TTY.

Read-only verification must prove the intended Stripe account, livemode resources, webhook endpoint, portal configuration and plan mapping. Do not create a Customer, Checkout Session, PaymentIntent, Subscription, Invoice, charge or refund.

Keep STRIPE_AUTOMATIC_TAX_ENABLED=0. Enabling it requires the user's tax adviser decision, correct product tax code, head-office settings and active registrations; a Stripe account alone is not a tax registration.

If Stripe LIVE protected access or the exact account selection is unavailable, status is BLOCKED_STRIPE_LIVE and billing cannot be declared functional.

- [ ] **Step 3: SMTP gate**

Install production SMTP identity and password only through protected input. Validate configuration parsing and TLS connectivity without sending. A delivery smoke is allowed only to an already authorized non-personal Kivou QA mailbox; otherwise alerts remain disabled and status is BLOCKED_SMTP_DELIVERY.

- [ ] **Step 4: DNS and TLS go/no-go**

Do not change DNS until Tasks 1–5 local gates are green and rollback paths are captured. Require explicit record targets:

- apex A: 179.237.105.52
- www: CNAME to kivou.eu or A to the same IP

After authoritative resolution is observed from two public resolvers, obtain one certificate whose SAN includes kivou.eu and www.kivou.eu. Do not enable HSTS. Execute runbook section 7 and require the SAN proof.

If DNS mutation authority is not explicitly available, leave the host unpublished and report BLOCKED_DNS_AUTHORITY with these exact records.

### Task 6: Preflight rollback, backup and nginx without public activation

**Files:**
- Create remotely: /srv/kivou/rollbacks/rollout-<UTC>-5e0e7e29df8d
- Create remotely: /root/kivou-rollouts/production-runtime-<UTC>
- Do not change active app/frontend/systemd/nginx paths in this task

- [ ] **Step 1: Execute runbook sections 3 through 9 exactly**

Require every stop gate:

- protected env metadata;
- systemd candidate syntax;
- previous unit/link/nginx state captured;
- current rollback pointer PREPARED;
- backup and isolated restore proved;
- certificate SAN proved;
- hermetic nginx candidate passes with exactly four default_server directives;
- alert baseline remains disabled;
- exact SHA and immutable release checks pass.

- [ ] **Step 2: Run pre-activation Signal smokes while timers remain disabled**

For each source in order `simap`, `boamp`, `decp`, `ted`, run the candidate
ingestion through the same shared production lock while no timer is installed or
enabled:

```bash
for KIVOU_SOURCE in simap boamp decp ted; do
  case "$KIVOU_SOURCE" in (simap|boamp|decp|ted) ;; (*) exit 64 ;; esac
  sudo systemd-run --wait --pipe --collect \
    --unit="kivou-ingest-$KIVOU_SOURCE-preflight.service" \
    --property=Type=oneshot --property=User=kivou --property=Group=kivou \
    --property=WorkingDirectory="$KIVOU_BACKEND_RELEASE_DIR" \
    --property=EnvironmentFile=/etc/kivou/production.env \
    --property=RuntimeDirectory=kivou --property=RuntimeDirectoryMode=0700 \
    --property=UMask=0077 --property=NoNewPrivileges=yes \
    --property=TimeoutStartSec=30min \
    --property=ProtectSystem=strict --property=ProtectHome=yes \
    --property=InaccessiblePaths=/srv/kivou/.ssh \
    --property=ReadOnlyPaths="$KIVOU_BACKEND_RELEASE_DIR" \
    --property=ReadWritePaths=/run/kivou \
    -- /usr/bin/flock --verbose --exclusive --timeout 300 \
    --conflict-exit-code 0 /run/kivou/ingestion.lock \
    "$KIVOU_BACKEND_RELEASE_DIR/.venv/bin/python" \
    -m signals.ingestion run --source "$KIVOU_SOURCE"
done
```

After each run, query only these bounded counters from the latest row:

```sql
SELECT source, status, records_fetched, records_accepted, records_rejected,
       records_persisted, representations_linked, opportunity_conflicts,
       signals_materialized, rate_limited_count, error_category,
       started_at, finished_at
FROM ingestion_run
WHERE source = :source
ORDER BY started_at DESC
LIMIT 1;
```

Execute the query from a protected transient Python process using SQLAlchemy
parameter binding and `production.env`; do not interpolate an arbitrary value.
Also verify `ingestion_checkpoint` has no stale running state and
`last_completed_at` advances when the source reports a complete pass. Never
print `error_message` or source payload.

The current atomic runbook activates the four source timers as one reviewed
set. Therefore all four pre-smokes, including TED, must be green before Task 7.
If TED or another source fails, stop before public mutation and produce a small
reviewed runbook patch for partial activation; do not improvise commands during
the release window. The failure report may include only its typed sanitized
category and bounded counters.

### Task 7: Perform the single atomic activation window

**Files:**
- Modify remotely: active Kivou systemd units
- Modify remotely: /srv/kivou/app and /srv/kivou/frontend symlinks
- Modify remotely: Kivou nginx files and site links
- Preserve: all previous releases and rollback captures

- [ ] **Step 1: Keep an independent root recovery session available**

Open a second SSH session, verify sudo, and keep the autonomous recovery block from runbook section 11 available. Confirm rollout.status is PREPARED before mutation.

- [ ] **Step 2: Execute runbook section 10 in one uninterrupted root shell**

Do not edit, omit or manually continue a failed command. The armed traps must restore services, links, units and nginx automatically on any error or signal. Require API readiness before nginx, nginx -t, HTTPS apex 200, www redirect, backup smoke, bounded source smokes, then the four timers. Runbook section 10 always leaves alerts disabled.

- [ ] **Step 3: Prove the served SHA**

Record exact readlink -f targets for /srv/kivou/app and /srv/kivou/frontend. Compare backend Git HEAD to 5e0e7e29df8db75089e51bce845343c1f88c565e. Prove an immutable frontend asset from the new release is served publicly. Verify ports 8000 and 5432 remain loopback-only and only nginx owns public 80/443.

- [ ] **Step 4: Roll back immediately on a critical failure**

Critical failures include authentication, API/data/paywall, essential routes, blocking JavaScript, unusable mobile, TLS, wrong served SHA or nginx/API readiness mismatch. If the automatic trap did not complete, execute runbook section 11 exactly from the independent root session. Require ROLLED_BACK and old API readiness before nginx recovery. Never delete a release, database fact, backup or rollback directory.

### Task 8: Validate SaaS, Signal Engine and operations

**Files:**
- No repository changes
- Create evidence only under /srv/kivou/validation/release2-<UTC>/

- [ ] **Step 1: Discover routes from the current router**

Inspect frontend/src routing and FastAPI routes from the deployed SHA. Build the FR/EN route matrix from code, not memory.

- [ ] **Step 2: Run public and anonymous validation**

Validate public page, sign-in, forgot password, reset rendering without consuming a token, private-route protection, API 404/405 behavior, health, security headers, Host rejection, www redirect and no unexpected public docs/debug endpoint.

- [ ] **Step 3: Run authenticated validation with a non-personal QA account**

Use an already authorized production QA mailbox through a protected credential path. Validate onboarding without dashboard sidebar/wordmark, /app, signal list/detail order, note persistence, editable targeting, company profile, settings, Billing and Notifications, login/logout/session persistence and paywall. Do not perform a Stripe payment or use personal data.

If no protected QA account exists, mark authenticated and real-data flows UNTESTED_BLOCKED_QA_ACCOUNT; do not invent a demo account with fake production claims.

- [ ] **Step 4: Run responsive/browser validation**

Use Playwright at 1440, 1024, 768, 390 and 320 pixels in French and English. Check console, failed network requests, blank pages, unexpected 404s, horizontal overflow, keyboard basics, readable text and mobile menu. Confirm no prototype/static Apollo data, no V2 commercial follow-up and no nonexistent action.

- [ ] **Step 5: Validate source timers and backups**

For every enabled source, require its last manual run and next scheduled run to succeed with coherent counters/checkpoint. Disable only a failing source timer. Require backup timer enabled, latest local dump valid, latest offsite snapshot current and the restore drill evidence retained.

- [ ] **Step 6: Enable alerts only after the separate SMTP delivery gate**

Keep `kivou-alerts.timer` and `kivou-alerts.service` disabled unless Task 5
completed an authorized QA delivery and the authenticated Notifications flow in
Step 3 passed. Only then enable the timer, start one bounded alert service smoke,
verify delivery state without printing recipient addresses or message bodies,
and require the unit to remain non-failed. Otherwise record alerts as
`BLOCKED_SMTP_DELIVERY`; this does not turn an untested email path into a success.

### Task 9: Close Release 2 and hand off Release 3

**Files:**
- Create execution report: docs/reports/2026-08-30-production-release2-execution.md

- [ ] **Step 1: Record factual evidence**

Record PR #128, reviewed head, deployed main SHA, CI run IDs, previous/new link targets, release paths, migration head, unit/timer states, listening sockets, certificate SAN, DNS state, backup/restore evidence, source outcomes, functional/browser results, rollback state and every untested/blocked path.

- [ ] **Step 2: Confirm boundaries**

Explicitly confirm staging was not modified; no staging data/secrets were copied; no payment occurred; no Apollo data was read/displayed; Acquisition providers were not called; old releases and rollback captures remain.

- [ ] **Step 3: Start Release 3 only after a separate reviewed plan**

Release 3 must implement and merge explicit PRODUCTION Acquisition authority, then start closed with read_only=true and kill_switch=true and prove zero provider mutations. It is not part of this Release 2 plan and cannot be simulated by reusing staging configuration.
