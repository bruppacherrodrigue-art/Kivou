# Kivou production go-live design

**Date:** 2026-08-30

**Repository:** `bruppacherrodrigue-art/Kivou`

**Production host:** `kivou-production` (`179.237.105.52`)

**Canonical public URL:** `https://kivou.eu`

**Reference main SHA at design time:**
`be221b3dd46c4d45649f7412ee1091c6a97e26f4`

**Foundation PR:** `#109`, head
`0a42c184cea20977c969145959593b7f0b7194af`

## 1. Objective

Put the real Kivou SaaS, Signal Engine and Acquisition Engine into production on
the prepared Infomaniak VPS without copying mutable staging state or combining
all external side effects into one irreversible launch.

The launch uses three separately observable and reversible releases:

1. production runtime foundations;
2. public SaaS and Signal Engine;
3. Acquisition Engine, first closed and then promoted under a tightly bounded
   authority.

The exact deployable SHA is selected only after the relevant PRs are merged and
CI succeeds on the resulting current `main`. The reference SHAs in this document
are audit facts, not permission to deploy them later without revalidation.

## 2. Existing authority and current gaps

The host baseline and its security policy are already implemented by PR `#109`.
Its exact head CI is green and GitHub currently reports the PR clean and
mergeable. Its base predates the current `main`, however, so it must be rebased
or otherwise updated onto current `main`, reviewed again, and pass CI for the new
head before merge. The resulting squash SHA must then pass `main` CI.

The detailed host model remains defined by
`2026-08-28-production-vps-readiness-design.md`. This go-live design does not
weaken its SSH, firewall, PostgreSQL, service-user, backup, secret or rollback
requirements.

The audit also established the following launch blockers:

- checked-in systemd units still reference `/etc/kivou/staging.env`;
- the active staging SIMAP and BOAMP units are not versioned in the repository;
- the last inspected staging TED execution failed without an actionable error;
- the existing Acquisition Runtime accepts only `STAGING`, `SHADOW` and QA-only
  operation, so it is not a production mutation authority;
- `kivou.eu` and `www.kivou.eu` have no active DNS records;
- Swiss Backup credentials and a production restic repository are not
  configured on the host;
- production application, SMTP, Stripe LIVE and provider configuration files do
  not yet exist.

A direct staging clone and a big-bang activation are therefore rejected.

## 3. Delivery decomposition

### Release 1 — Production runtime foundations

Release 1 changes repository operations assets but does not publish the SaaS or
authorize external mutations. It must:

- integrate PR `#109` through the repository's squash-merge convention after
  exact-head revalidation;
- provide production-safe systemd services and timers which read protected
  production paths, without changing staging behavior;
- version the audited SIMAP and BOAMP one-shot services and staggered timers;
- retain the shared ingestion non-overlap lock where required;
- provide a production nginx template derived from the working same-origin
  staging model;
- provide production backup and restore wiring for encrypted off-host restic
  snapshots;
- improve TED diagnostics enough to identify a typed failure and prove a
  successful bounded cycle, or leave TED disabled;
- add static and runtime tests that reject cross-environment paths and unsafe
  defaults;
- document exact installation, activation, validation and rollback commands.

Release 1 is complete only after its merged `main` SHA and `main` CI are green.

### Release 2 — SaaS and Signal Engine

Release 2 deploys an exact green `main` SHA into immutable backend and frontend
release directories. It creates a fresh production database, applies the exact
repository migration head, configures production-only runtime values and
publishes the application only after local validation.

The Signal Engine is activated source by source: SIMAP, BOAMP, DECP, then TED.
Each timer remains disabled until a bounded manual cycle succeeds and produces
coherent counters, checkpoints and materialized results. One failed source does
not roll back durable valid facts from another source.

This release also configures DNS, TLS, SMTP, Stripe LIVE connectivity, alerts and
verified backups. Configuration of Stripe LIVE does not authorize a charge. No
payment is performed during routine launch validation.

### Release 3 — Acquisition Engine

Release 3 is a separate code specification, implementation plan and PR. The
current QA runtime must not be made production-capable by merely renaming an
environment or bypassing its loader.

The first production state is active but closed:

- environment identity is explicitly `PRODUCTION`;
- provider identities, workspaces, campaigns and mailboxes are production-only;
- `read_only=true` and the kill switch is closed;
- health and readiness are evaluated without provider mutations;
- every observed cycle proves a zero-mutation delta;
- no prospect is contacted and no provider object is created or activated.

Promotion to real activity is a later authority change. The initial cap is one
eligible prospect per day unless a stricter implemented policy applies. The cap,
country, provider account, mailbox, campaign, spend and recipient class are all
allowlisted. Any ambiguity, reconciliation failure, budget failure or provider
drift closes the kill switch. A service being active never implies authority to
send.

## 4. Runtime and release architecture

nginx is the only public application listener. It terminates TLS on ports 80 and
443 and proxies allowed API routes to a loopback-only Uvicorn service. PostgreSQL
remains bound to loopback. Workers run as the locked, non-interactive `kivou`
user with only the filesystem and network access they require.

Backend and frontend releases are immutable and named with their UTC creation
time and exact Git SHA:

- `/srv/kivou/releases/backend-<timestamp>-<sha>`;
- `/srv/kivou/releases/frontend-<timestamp>-<sha>`.

The active paths are atomic symlinks:

- `/srv/kivou/app`;
- `/srv/kivou/frontend`.

The previous exact targets are captured before every switch. Old releases are
not modified or deleted as part of deployment or rollback.

Backend activation uses the repository's existing local blue/green pattern: a
candidate starts on an alternate loopback port, passes health and readiness,
then nginx is switched only after syntax validation. The frontend is built from
the same approved SHA and its static artifacts are verified before its symlink
switch. A version marker or equivalent immutable asset evidence must prove the
served release matches the announced SHA.

## 5. Data and configuration isolation

Production starts with a fresh PostgreSQL database and a dedicated application
role. No staging customer, Stripe TEST object, QA recipient, prototype fixture,
demo record or provider state is copied. Public procurement facts are rebuilt by
the production Signal Engine unless a separate table-allowlisted promotion is
designed and approved later.

Protected production files are distinct:

- `/etc/kivou/production.env` for SaaS, database, SMTP, Stripe and webhook
  runtime configuration;
- `/etc/kivou/acquisition-production.env` for provider connectivity;
- `/etc/kivou/acquisition-production.json` for non-secret acquisition policy;
- `/etc/kivou/swiss-backup.env` for the encrypted off-host backup repository.

Secrets are created or entered through protected host/provider mechanisms. They
are never requested in chat, committed, placed in command arguments, written to
reports or embedded in the frontend. Files are regular, non-symbolic,
root-owned and mode `0600` by default. A file that must be read directly by the
unprivileged runtime may instead be `root:kivou` mode `0640` only after that need
is demonstrated; systemd environment files remain `0600` when the service
manager can read them before dropping privileges.

Apollo data is neither used nor displayed. Provider logs and reports contain
only opaque identifiers, counters and sanitized categories, never payloads,
tokens, personal data or contact details.

## 6. Domain, TLS and external systems

`https://kivou.eu` is canonical. `https://www.kivou.eu` redirects permanently to
the canonical origin after both names have valid DNS and certificates. DNS is
changed only after the local HTTP/TLS candidate and rollback path are ready.

The required external gates are:

- Infomaniak DNS authority for the apex and `www` records;
- a Swiss Backup repository and its protected restic/Swift configuration;
- a production SMTP identity with authenticated delivery and required DNS
  records;
- the intended Stripe account in LIVE mode, its restricted keys, webhook
  endpoint/signing secret, products, prices, customer portal and return URLs;
- production-only acquisition provider accounts and policy configuration.

If an integration cannot be accessed through an already authorized protected
channel, deployment stops at that gate. The operator receives the exact action
or permission required; no credential is pasted into conversation.

## 7. Security controls

### Backend and edge

- FastAPI debug and auto-reload are disabled in production.
- Public OpenAPI and interactive documentation are disabled or explicitly
  protected.
- accepted Host values are limited to the production domain set;
- CORS is disabled where same-origin routing makes it unnecessary, otherwise it
  uses an exact allowlist and never wildcard origins with credentials;
- forwarded headers are trusted only from the local nginx boundary;
- nginx applies bounded request bodies, connection limits and rate limits to
  expensive and authentication endpoints;
- application errors return generic responses while detailed, sanitized errors
  remain in protected logs;
- cookies are marked `Secure` only after TLS is active and retain `HttpOnly` and
  the appropriate `SameSite` policy;
- cookie-authenticated state changes retain their existing CSRF protection;
- security headers include MIME sniffing, clickjacking, referrer and appropriate
  permissions controls;
- CSP is deployed without a broad `unsafe-eval` allowance. HSTS is not enabled
  until the complete domain/TLS behavior has been separately observed and
  approved.

### Frontend and supply chain

- the frontend is a production build installed reproducibly from its lockfile;
- values exposed through Vite or browser runtime configuration are treated as
  public and contain no secrets;
- source maps are not publicly served unless a later protected error-reporting
  design explicitly requires them;
- untrusted data continues to use React's escaped rendering paths; no raw HTML
  sink, arbitrary redirect or credentialed arbitrary-origin request is added;
- third-party browser scripts are minimized, pinned and constrained by CSP;
- dependency audits are reviewed, but automatic broad dependency rewrites are
  not performed during launch.

### Host and services

- the existing key-only SSH, UFW, fail2ban, PostgreSQL loopback and unattended
  security update controls remain in force;
- systemd units use least privilege and sandboxing compatible with each tested
  runtime;
- API, ingestion, backup and acquisition units have bounded execution,
  non-overlap and explicit failure states;
- no security control is weakened merely to make a launch test pass.

## 8. Activation sequence and go/no-go gates

1. Rebase or update PR `#109` onto current `main`; re-review its exact diff and
   pass exact-head CI.
2. Squash-merge PR `#109`; verify the resulting current `main` SHA, merged tree
   and successor `main` CI.
3. Implement and merge Release 1 through the same exact-SHA gates.
4. Install production operations assets with all application timers disabled.
5. Create the production database and role; verify local backup creation.
6. Configure Swiss Backup and restore the latest off-host snapshot into a
   temporary isolated database; verify schema and migration head.
7. Build backend and frontend from a clean checkout of the exact approved
   `main` SHA using the repository lockfiles.
8. Run backend tests and lint plus frontend tests, typecheck, lint and build.
9. Apply migrations only after a verified pre-migration backup and compatibility
   review.
10. Start the backend candidate on loopback and pass health, readiness,
    authentication-boundary and database checks.
11. Validate frontend artifacts, nginx candidate configuration and local
    same-origin routing.
12. Configure DNS and TLS; enable secure production cookies only after HTTPS
    works end to end.
13. Switch backend and frontend atomically and prove the served SHA.
14. Run public, anonymous and authenticated functional validation in French and
    English.
15. Run each Signal source manually and enable only the successful source timer.
16. Enable alerts, backup schedules and operational monitoring.
17. Deploy Release 3 in closed `SHADOW/READ_ONLY` mode and collect zero-mutation
    evidence.
18. Consider the separately controlled capped-live acquisition promotion only
    after the closed runtime remains stable.

Every numbered step is a go/no-go boundary. A later step cannot compensate for
an earlier failed gate.

## 9. Validation and acceptance evidence

### SaaS functional validation

Test the routes declared by the current router, not a remembered route list.
The minimum coverage in both French and English includes:

- public pages and navigation;
- sign-up and sign-in boundaries;
- forgot-password and reset-page rendering without consuming a real reset;
- private-route protection;
- onboarding without dashboard sidebar or dashboard wordmark;
- dashboard and `/app` redirects;
- signal list and detail, including customer note persistence through the
  existing backend contract;
- editable targeting profile;
- company profile;
- settings, billing and notifications;
- login, logout, session persistence and paywall behavior.

An already configured non-personal production QA account may be used if one is
available through a protected mechanism. No real personal data, payment or
contact send is created for testing.

### Visual, browser and network validation

The production build is checked at widths 1440, 1024, 768, 390 and 320 pixels.
Checks cover layout centering, horizontal overflow, keyboard basics, readable
text, mobile menus, blank pages, unexpected 404s, JavaScript console errors and
failed network requests.

The signal detail preserves the approved order: published facts, Kivou analysis
and targeting match, evidence, then customer judgment/note. V2 commercial
follow-up is not exposed, Apollo data is absent, public company provenance is
truthful, and nonexistent functions are not simulated.

### Operations evidence

The launch report records:

- exact PR heads, merge SHAs, deployed SHA and CI runs;
- previous and current backend/frontend symlink targets;
- migration head and database backup/restore evidence;
- nginx syntax, certificates, listening sockets and security headers;
- service/timer enabled and active states plus latest successful invocation;
- functional and responsive results, with every untested path explicit;
- DNS, SMTP, Stripe, backup and acquisition state;
- whether rollback was exercised or remained available.

An HTTP 200, green build, symlink change, active service or present API key is
never sufficient evidence by itself.

## 10. Failure handling and rollback

- A PR, CI or SHA mismatch stops before deployment.
- A migration incompatibility or failed pre-migration backup stops before
  mutation. A migration failure restores the verified pre-migration dump before
  public traffic; no improvised downgrade is attempted on customer state.
- A backend, frontend, authentication, paywall, route, JavaScript, TLS or served
  SHA failure restores the captured backend/frontend targets and prior nginx
  state, then verifies public recovery.
- A Signal source failure disables only that source timer and preserves durable
  checkpoints and valid facts.
- A backup or restore failure prevents production readiness and never triggers
  deletion of local dumps.
- An Acquisition failure closes the kill switch, lowers authority, stops its
  timer/service and preserves policy, incident and provider-operation history.
- A DNS or certificate failure returns to the previous record or leaves the
  production host unpublished, depending on the activation point.

No rollback deletes an immutable release, valid production fact, incident
history or backup evidence.

## 11. Explicit non-goals

This design does not:

- modify or retire staging;
- copy staging secrets, accounts or database state;
- deploy a ChatGPT Sites prototype or redirect Kivou to one;
- modify application API contracts merely to simplify deployment;
- perform a Stripe payment;
- expose Apollo data;
- contact a prospect during initial production validation;
- declare the Acquisition Engine live merely because its systemd unit is active;
- enable HSTS, delete old releases or automate unattended reboots as part of the
  launch.

## 12. Completion definition

Production is complete only when the canonical HTTPS URL serves the exact green
`main` SHA, authenticated and public FR/EN flows pass, real production backend
data loads, all enabled Signal sources have fresh successful evidence, backup
restore has been proved, monitoring is active and the Acquisition Engine's
actual authority is reported accurately.

If external permissions prevent a gate, the outcome is **blocked at that gate**,
not successful. The report must name the missing access and the exact operator
action required without requesting or exposing a secret.
