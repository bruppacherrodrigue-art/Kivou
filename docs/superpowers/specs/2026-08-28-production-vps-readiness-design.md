# Kivou production VPS readiness design

**Date:** 2026-08-28

**Reference branch:** `main`

**Reference SHA:** `2c525db6f88d11aca91292d60bdce2dbcf967f1c`

**Target host:** `kivou-production` (`179.237.105.52`)

**Target platform:** Infomaniak VPS Lite, Ubuntu 24.04 LTS, 4 vCPU, 8 GiB RAM, 160 GB NVMe

## 1. Objective

Prepare one production VPS to host the Kivou SaaS, Signal Engine and Acquisition
Engine with a reproducible, fail-closed operating model. Preparation must leave
the host ready for a later go/no-go without implicitly publishing DNS, enabling
Stripe LIVE, sending transactional messages, mutating acquisition providers or
contacting a prospect.

The production runtime must be derived from an exact reviewed `main` SHA. It
must not be created by copying the mutable staging checkout, staging secrets,
staging customer records or staging provider state.

## 2. Current facts and blocking gap

- GitHub `main` is `2c525db6f88d11aca91292d60bdce2dbcf967f1c` and CI run
  `33116044947` completed successfully for that SHA.
- Staging uses Ubuntu 24.04, Python 3.12, Node 24, npm, uv, nginx 1.24,
  PostgreSQL 16, systemd units and immutable releases below `/srv/kivou/releases`.
- Production is a fresh Ubuntu 24.04 host with only SSH exposed. Node, npm, uv,
  nginx and PostgreSQL are not installed. Swap and UFW policy are not configured.
- The Infomaniak cloud-init user script failed because `set -o pipefail` makes
  its optional-data-disk discovery pipeline fail when no additional disk is
  attached. The root filesystem is healthy and occupies the expected 160 GB disk.
- The checked-in API, backup, alert, ingestion and acquisition service files
  reference `/etc/kivou/staging.env`.
- The active SIMAP and BOAMP systemd units on staging are not present in
  `ops/systemd` on `main`, so a clean checkout cannot reproduce all four source
  timers.
- `src/signals/acquisition_runtime/config.py` accepts exactly
  `KIVOU_ACQUISITION_ENVIRONMENT=STAGING`; its public contracts also constrain
  the environment to `STAGING`. The existing acquisition service is a bounded
  QA/SHADOW runtime, not a production execution authority.

Consequently, host preparation, production operations assets and a real
production Acquisition Runtime are separate deliverables. A blind staging
clone would be neither reproducible nor safe.

## 3. Chosen architecture

Kivou will initially use one VPS because this matches the approved budget and
the measured staging load. Isolation is provided through OS users, protected
configuration files, systemd sandboxing, locks, resource accounting, loopback
bindings and staggered schedules.

The host contains:

1. nginx as the only public application listener on ports 80 and 443;
2. a static frontend release served from `/srv/kivou/frontend`;
3. two loopback-only Uvicorn workers served from `/srv/kivou/app`;
4. PostgreSQL 16 bound to loopback only;
5. four independently observable Signal Engine ingestion services;
6. the alert worker and backup worker;
7. the Acquisition Engine in a separate service and protected configuration;
8. local verified dumps plus encrypted off-host Swiss Backup snapshots.

The alternative multi-host design would improve fault isolation but adds cost
and operational complexity. A container migration is rejected for this launch
because it would introduce an unvalidated deployment model absent from staging
and the repository.

## 4. Delivery decomposition

### Phase A — Secure host baseline

This phase is independent of Kivou code and must complete before application
installation:

- set hostname `kivou-production-01` and retain UTC system time;
- apply current Ubuntu security updates without enabling unattended reboot;
- create a 4 GiB swap file with restrictive permissions and low swappiness;
- keep the `ubuntu` account as the sole interactive administrator;
- create a locked, non-login `kivou` service account;
- disable SSH passwords, keyboard-interactive login, root login, X11 forwarding
  and agent forwarding;
- reduce authentication attempts and login grace time;
- enable UFW with deny-by-default ingress and only 22, 80 and 443 for IPv4/IPv6;
- install and enable fail2ban for SSH;
- cap persistent journald disk usage and retain nginx logrotate;
- install monitoring primitives needed for later disk, timer, certificate and
  service-health checks;
- verify a second SSH session before closing the first session after any SSH or
  firewall change.

Every changed configuration file is copied to a timestamped root-only rollback
directory before replacement. A failed SSH validation restores the previous
file through the still-open session.

### Phase B — Versioned production operations assets

This phase is a focused repository PR. It must add or modify only operations
assets and their tests:

- production-safe systemd units which read `/etc/kivou/production.env`;
- separate production acquisition environment paths;
- versioned SIMAP and BOAMP service/timer files matching the audited source
  isolation and shared ingestion lock;
- a production nginx template derived from the audited same-origin staging
  configuration without hard-coded staging names;
- an API readiness check suitable for local blue/green validation;
- encrypted off-host backup wiring using restic with OpenStack Swift;
- tests that reject staging paths in production assets and reject production
  paths in staging assets;
- documentation for install, validation and rollback commands.

The PR must start from the then-current `main`, pass backend and frontend CI,
be reviewed for its exact head SHA, merge according to repository convention,
and pass CI again on the resulting `main` SHA before deployment.

### Phase C — Runtime and data foundation

Install only versions supported by the repository and current Ubuntu release:

- Python 3.12 and `uv`;
- Node 24 and npm for deterministic frontend builds;
- PostgreSQL 16 client/server;
- nginx 1.24, Certbot, Git, curl, jq, restic and operational utilities.

Create `/srv/kivou/{releases,rollbacks,backups,run,validation}` with explicit
ownership and permissions. Generate a production-only GitHub deploy key on the
host, add only its public half as a read-only repository deploy key, and pin
GitHub's host key from a reviewed source. No staging deploy key is copied.

Create a fresh production PostgreSQL database and application role. Generate
the database password on the host, never in shell arguments or conversational
output, and store the resulting URL only in `/etc/kivou/production.env` with
mode `0600` and group `kivou`. PostgreSQL remains bound to loopback and `pg_hba`
admits only the minimum local role/database path.

No staging SaaS account, Stripe TEST object, QA recipient, acquisition record or
provider secret is copied. Public procurement data will either be rebuilt by
the production Signal Engine or promoted later through a separately reviewed,
table-allowlisted procedure. The default for this design is a fresh database.

### Phase D — Release staging without public activation

Build backend and frontend from a clean checkout of the exact approved `main`
SHA using `uv sync --locked` and `npm ci`. Run backend tests and Ruff, then
frontend tests, build, typecheck and lint. Create immutable backend and frontend
release directories and verify their ownership, permissions and artifact
contents before creating atomic symlinks.

Apply Alembic migrations once against the fresh production database. Start the
API on loopback and validate local health, readiness, authentication boundaries
and migration head. Install nginx support files and an HTTP-only pre-DNS site,
but do not obtain a certificate or expose the application under `kivou.eu`
before the DNS go/no-go.

Signal, alert, acquisition and backup timers are installed in a disabled state.
Each service must first pass one controlled manual execution with its mutation
scope understood before its timer can be enabled.

### Phase E — Signal Engine activation

Enable sources one by one in this order: SIMAP, BOAMP, DECP, TED. For each
source, verify:

- the service exits successfully within its bound;
- the durable checkpoint advances;
- no orphaned `running` execution remains;
- source facts and materialized signals increase coherently;
- logs contain counters and bounded categories, not provider payloads;
- the next scheduled systemd invocation also succeeds.

The four schedules remain staggered and use a shared host lock where the active
staging design requires it. A source failure disables only that source timer;
it does not roll back valid facts from another source.

### Phase F — Production Acquisition Runtime

This is a separate code specification, implementation plan and PR. It must not
be simulated by renaming `STAGING` to `PRODUCTION` or bypassing its loader.

The production runtime must provide:

- an explicit `PRODUCTION` configuration contract;
- production-only provider identities, workspace, mailboxes and budgets;
- a durable Policy control revision and operator approval provenance;
- a startup state of `read_only=true` and `kill_switch=true`;
- fresh health/readiness checks for all declared dependencies;
- structural joins through Signal Seed, Supplier Discovery, company research,
  contact discovery, personalization, compliance and campaign preparation;
- zero mutation proof while closed;
- bounded activation that cannot broaden country, mailbox, campaign, volume or
  cost limits;
- incident, breaker, reconciliation and dead-letter behavior already required
  by SPEC-031;
- monotonic rollback to a lower authority without deleting database truth.

Provider credentials are entered only through a protected VPS channel. They
are never requested or displayed in chat, committed to Git, written in command
arguments or copied from staging. A service being active does not imply that it
is authorized to send. Provider mutations require a later explicit go/no-go.

## 5. Secret and configuration boundaries

Production uses distinct protected files:

- `/etc/kivou/production.env` for SaaS, database, Stripe, SMTP and webhook
  configuration;
- `/etc/kivou/acquisition-production.env` for provider and Hermes connectivity;
- `/etc/kivou/acquisition-production.json` for non-secret runtime policy;
- `/etc/kivou/swiss-backup.env` for restic/Swift credentials.

Files are regular, non-symbolic, root-owned, group-readable only where the
service requires it and never world-readable. Empty optional feature bundles
remain fully empty; partial cryptographic bundles must make startup fail.
`systemd-run` tests use `EnvironmentFile=` rather than `sudo env` so secrets do
not enter process arguments or journald metadata.

Stripe LIVE, SMTP, provider and webhook secrets are not prerequisites for the
host baseline. Their absence keeps dependent paths disabled or fail-closed.

## 6. Backup and recovery

The existing PostgreSQL backup script remains the authority for producing a
local custom-format dump. It must retain flock, `umask 077`, minimum-size check,
`pg_restore --list`, atomic publication and post-success retention.

After local verification, restic encrypts and uploads eligible dumps to the
dedicated Swiss Backup Swift repository. A separate repository password and
Swift credentials live only in `/etc/kivou/swiss-backup.env`. Local retention
is 14 days; off-host retention is 30 daily, 12 monthly and 3 yearly snapshots,
subject to the purchased 1 TB quota.

Before launch, restore the latest off-host snapshot to a temporary isolated
database, verify the migration head and expected schema, then remove only that
temporary database. A snapshot or successful upload alone is not a recovery
proof.

## 7. Observability and maintenance

- nginx owns the sole public access log and uses the existing redacted path
  format for reset, attribution and webhook routes;
- Uvicorn access logging remains disabled behind nginx;
- journald persists bounded service logs with a 512 MiB host cap;
- each systemd timer and service exposes a distinct unit state;
- health checks cover nginx, API, PostgreSQL, timer freshness, backup freshness,
  certificate expiry, disk, memory and failed units;
- provider logs contain only opaque identifiers, counters and sanitized error
  categories;
- automatic security updates remain enabled, while reboots are scheduled and
  verified manually;
- a monthly restore drill and quarterly credential/SSH access review are part
  of normal maintenance.

## 8. Activation gates

The server is only **prepared** when host hardening, package/runtime install,
database initialization, local backup, off-host restore proof and exact-SHA
release validation pass.

The SaaS and Signal Engine are only **ready for public production** when DNS,
TLS, origin/cookie settings, SMTP, legal URLs, authenticated FR/EN flows,
responsive checks, JavaScript/network checks and real production data paths
pass without staging dependencies.

The Acquisition Engine is only **ready for mutations** when its production PR
and exact-main CI pass, production identities and budgets are configured,
closed-mode zero-mutation evidence passes, one bounded authorized cycle passes,
and the operator records a separate go/no-go.

Stripe LIVE is only **ready** after its distinct key, webhook, products, prices,
portal, return URLs and fiscal decision are verified. A first controlled LIVE
payment is outside server preparation and requires separate explicit approval.

## 9. Rollback

- SSH or firewall failure: restore the timestamped configuration through the
  retained session and reload only after syntax validation.
- Package/runtime failure: leave services disabled; do not alter staging.
- Application failure: atomically restore previous backend/frontend symlinks
  and verify local/public health.
- Signal source failure: disable only its timer and retain checkpoints/data.
- Acquisition failure: set kill switch, lower authority, stop its timer/service
  and preserve policy, incident and provider-operation history.
- Migration failure: restore the pre-migration database dump; never improvise a
  downgrade against live customer state.
- Backup failure: do not purge local dumps and do not declare the host ready.

No rollback deletes releases, valid public facts, incident history or backup
evidence.

## 10. Acceptance evidence

Every completed phase records:

- exact Git and deployed SHAs;
- commands run and exit status;
- affected files, ownership and modes;
- unit/timer enabled and active states;
- firewall and listening sockets;
- migration head;
- local backup and isolated off-host restore result;
- functional checks and explicit untested paths;
- previous and current rollback targets;
- confirmation that staging, DNS, Stripe LIVE and provider mutations were not
  changed unless that exact phase was separately authorized.

Completion cannot be inferred from package installation, a green build, a
symlink switch, an active unit or the presence of API keys.
