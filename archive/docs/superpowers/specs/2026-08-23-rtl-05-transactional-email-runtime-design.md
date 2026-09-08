# RTL-05 — Transactional email runtime design

**Date:** 2026-08-23
**Status:** approved design; implementation locally validated
**Scope:** password-reset messages and account signal alerts requested by SaaS users

## 1. Outcome

Kivou must be able to deliver password-reset messages and signal alerts through a
reproducible runtime that is safe to replay, observable without exposing private
data, and installable on the staging VPS from files committed to `main`.

This work does not create acquisition email, prospecting, leads, campaigns,
Instantly or Apollo calls. It does not change signal generation, pricing,
billing authority, Stripe, or the feed ordering and access policies.

## 2. Audited baseline

The implementation starts from
`2481c6e88cd20ca5a78c7d3a8894bcdfdd0b48e4`. The isolated baseline suite passes
with 4,115 tests and 2 skips.

The existing application already provides:

- account-scoped notification preferences;
- entitlement-derived alert cadence;
- current feed and unlock checks before alert selection;
- password-reset tokens persisted only as SHA-256 hashes, with expiry and
  one-time use;
- neutral `202` reset responses for known and unknown addresses;
- FR/EN plain-text templates;
- an SMTP gateway boundary and deterministic alert `Message-ID` values;
- `signal_alert_delivery`, keyed by `(account_id, signal_key)`.

The audit found these operational gaps:

- `KIVOU_PUBLIC_APP_URL` currently includes `/app`, which gives two competing
  URL-building conventions;
- SMTP has a boolean STARTTLS switch and a hard-coded 30-second timeout, but no
  explicit implicit-TLS mode, timeout setting or optional `Reply-To`;
- partial SMTP configuration does not fail consistently;
- the alerts command takes the database URL on its command line and returns zero
  even when deliveries fail;
- the host `flock` does not prevent a second process on another host or an
  invocation that bypasses the unit;
- queued rows are not durably claimed before the network call;
- retryable and permanent failures are not separated in the persisted schedule;
- failed and ambiguous deliveries are selected again without a bounded backoff;
- a crash after SMTP acceptance but before the `sent` update can resend the
  alert without a durable attempt lease.

The read-only staging audit found the actual deployment convention:

- application user/group: `kivou`;
- checkout and working directory: `/srv/kivou/app`;
- environment file: `/etc/kivou/staging.env`;
- virtualenv Python: `/srv/kivou/app/.venv/bin/python`;
- runtime lock directory: `/srv/kivou/run`;
- SMTP provider: Infomaniak at `mail.infomaniak.com:587` with STARTTLS;
- public origin: `https://staging.kivou.eu`;
- from-domain: `kivou.eu`.

No credential, recipient address, reset token or private message content is part
of this document. A controlled staging recipient has been supplied out of band.

The existing staging history contains 55 alert delivery rows: 13 `sent` and 42
`failed`. The 42 permanent recipient refusals accumulated 652 attempts, proving
that terminality and backoff are required. No send was triggered during the
audit.

## 3. Architectural choice

Three boundaries were considered:

1. Retain the existing rows and rely on systemd `flock`.
2. Add a durable job lease and additive delivery-attempt metadata for alerts,
   while retaining the current one-shot reset-token model.
3. Build a generic transactional outbox for alerts and password resets.

Option 2 is selected. It closes the alert concurrency and recovery gaps without
placing a usable password-reset secret in a retry queue. A failed reset delivery
is recovered by a new public reset request, which creates a new token and
invalidates no secret through an outbox.

## 4. Configuration and URL authority

### 4.1 Public application origin

`KIVOU_PUBLIC_APP_URL` is an origin, not a router prefix. Deployed values are:

- staging: `https://staging.kivou.eu`;
- production: `https://kivou.eu`.

The loader will:

- require an absolute HTTPS URL;
- reject credentials, query strings and fragments;
- reject a path other than empty or `/`;
- normalize a trailing slash away;
- require the normalized origin to equal the configured allowed origin;
- never use `Host`, forwarded request data, a query parameter or frontend state.

Links are then constructed by one shared helper:

- reset: `{origin}/reset-password?token=…`;
- signal detail: `{origin}/app/signals/{opaque_signal_key}`;
- preferences: `{origin}/app/notifications`.

Only the reset email contains a raw reset token, and it is never logged or
persisted outside its existing hash.

### 4.2 SMTP settings

The supported environment contract is:

- `SMTP_HOST`;
- `SMTP_PORT`;
- `SMTP_USERNAME` and `SMTP_PASSWORD`, required as a pair;
- `SMTP_FROM_EMAIL`;
- `SMTP_FROM_NAME`;
- `SMTP_TLS_MODE=starttls|implicit_tls`;
- `SMTP_TIMEOUT_SECONDS`, positive and bounded;
- optional `SMTP_REPLY_TO_EMAIL`;
- `KIVOU_PUBLIC_APP_URL` for any message containing a link.

`SMTP_USE_TLS` is replaced by the explicit mode. The staging installation
procedure must update the environment atomically before starting the versioned
unit.

An entirely absent SMTP configuration may remain disabled for offline developer
and test processes. If any SMTP variable is present, all required values must be
valid or configuration construction fails with a short, secret-free error. The
alerts command also fails non-zero when delivery is disabled.

The gateway will use:

- `smtplib.SMTP` followed by STARTTLS for `starttls`;
- `smtplib.SMTP_SSL` for `implicit_tls`;
- authenticated submission when credentials are configured;
- a bounded timeout for connect, TLS, authentication and delivery;
- no unencrypted deployed mode.

Infomaniak recommends authenticated port 587 with STARTTLS; port 465 with
implicit TLS remains supported by the application but is not the staging
default.

## 5. Password-reset delivery

The existing security properties remain authoritative:

- cryptographically random token;
- only its digest is stored;
- fixed expiry;
- one-time consumption;
- session revocation after successful password change;
- identical public response for known and unknown addresses;
- delivery occurs after the request transaction;
- logs contain only a stable error code.

Each reset request has one SMTP attempt. If it fails, the user requests another
reset and receives a newly generated token. Kivou does not persist the raw token
or an encrypted email payload merely to retry it later.

Known and unknown accounts remain indistinguishable in status and body. A
missing or invalid delivery configuration must be observable operationally
without changing this enumeration-resistant response contract.

## 6. Durable alert delivery

### 6.1 Migration

An additive `0023` migration will preserve all existing delivery history and add
the smallest durable coordination model:

- a singleton job-lease table keyed by the logical job name;
- additive delivery columns for logical batch key, deterministic message ID,
  retryability, attempt start, lease expiry, next attempt and terminal detail;
- indexes needed to select due deliveries and expired leases;
- constraints covering the closed status vocabulary.

Upgrade and downgrade must follow repository conventions and render valid
offline PostgreSQL SQL. SQLite execution and PostgreSQL-compatible SQL are both
tested. Downgrade removes only the new coordination fields/table and does not
delete the pre-existing alert history.

Historical `sent` rows remain terminal. Every historical `failed` or
`unknown_delivery_state` row migrates as terminal by default, with no next
attempt. The migration does not infer retryability by parsing historical error
text or codes. Operator-controlled requeue, if needed, must be an explicit
operation documented in the runbook.

### 6.2 State machine

The delivery lifecycle is:

```text
queued -> sending -> sent
                  -> failed (retry scheduled)
                  -> failed (terminal)
                  -> unknown_delivery_state (retry scheduled or exhausted)
queued/failed/unknown_delivery_state -> suppressed (terminal)
```

Before network I/O, the job commits:

- the logical batch key;
- its deterministic `Message-ID`;
- `sending` state;
- attempt number and start time;
- a bounded delivery lease.

Only one process can hold the global `signals.alerts` lease. Acquisition uses an
atomic compare-and-set that works on SQLite and PostgreSQL. A second concurrent
job is normal contention: it exits without sending, reports `already_running`
and returns code 0. A technical failure while reading or acquiring the lease is
an execution incident and returns non-zero.

An expired global or delivery lease is reclaimable. A reclaimed batch keeps the
same logical key and `Message-ID`.

The versioned service has a 20-minute hard timeout. Configuration rejects a
global/delivery lease shorter than 30 minutes, so the lease remains owned while
systemd terminates an overlong execution; the extra margin prevents another
host from reclaiming it during shutdown.

### 6.3 Retry policy

Errors are classified without persisting exception strings:

- authentication, TLS configuration and permanent recipient refusal: terminal;
- connection refusal and failures known to occur before message acceptance:
  retryable;
- SMTP 4xx: retryable;
- SMTP 5xx: terminal unless a documented code is explicitly classified
  otherwise;
- disconnect, timeout or process interruption around `DATA`: acceptance may be
  ambiguous.

Retryable and ambiguous failures use bounded exponential backoff, a maximum
attempt count and the same `Message-ID`. When an attempt made by the current
execution fails or exhausts its retry budget, the state remains visible and the
current command exits non-zero. It is never silently treated as sent.

Entitlements, preference, current signal access, unlock status and cadence are
rechecked immediately before every actual retry. If the recipient is no longer
eligible because notifications were disabled, entitlements were lost, the
cadence no longer permits email, or no signal in the logical batch remains
accessible and unlocked, the affected delivery rows become terminal
`suppressed`. If only part of a batch remains accessible, inaccessible rows are
suppressed and the remaining rows form the authorized message. Suppression has
an allowlisted reason code and timestamp; it is not an SMTP failure and does not
increment an SMTP attempt count.

### 6.4 Exact guarantee

Kivou guarantees:

- no duplicate send in deterministic sequential or concurrent execution;
- no alert for a currently inaccessible or locked signal;
- no unbounded retry;
- a stable logical identity across retries;
- a persisted, auditable final state without private payloads.

Kivou does not claim exactly-once SMTP delivery. If the SMTP server accepts a
message and the connection or database commit fails before Kivou records
`sent`, retrying the stable message can produce a duplicate. The design favors a
bounded delivery retry over silently losing the alert. The deterministic
`Message-ID` gives receiving systems a deduplication hint but is not a protocol
guarantee.

## 7. Runtime units

The repository will version:

- `ops/systemd/kivou-alerts.service`;
- `ops/systemd/kivou-alerts.timer`.

The service uses the audited deployment convention and executes:

```text
/usr/bin/flock --verbose --nonblock --conflict-exit-code 0 \
  /srv/kivou/run/alerts.lock \
  /srv/kivou/app/.venv/bin/python -m signals.alerts
```

The database URL is loaded from `/etc/kivou/staging.env`, not exposed in
`ExecStart`. The service is `Type=oneshot`, has a bounded runtime, writes only to
the lock directory, and applies systemd hardening compatible with DNS and SMTP
network access.

The timer runs hourly, uses `Persistent=true` and a bounded randomized delay.
This permits the server-supported priority cadence to run at most once per
timer cycle; it does not describe it as real-time.

Host-lock or database-lease contention is an expected no-op and returns zero,
with an `already_running`/contention indication in the operational log. A
technical lock or lease acquisition failure returns non-zero.

The Python command's non-zero result depends only on incidents encountered by
the current invocation: configuration failure, persistence failure, a delivery
attempt that fails or exhausts its retry budget, or a newly ambiguous result.
Historical terminal or ambiguous rows do not make every future timer run fail.
The command emits aggregate account/signal/status counts only.

## 8. Testing strategy

Implementation follows test-driven development.

Automated coverage will include:

- strict public-origin normalization and staging/production links;
- complete, absent and partial SMTP configuration;
- STARTTLS, implicit TLS and bounded timeout;
- secret-free errors and logs;
- reset FR/EN, unknown-account neutrality, expiry and one-time use;
- alert preferences and entitlement-derived cadence;
- current access, unlock and inter-account isolation checks on every attempt;
- terminal `suppressed` results for preferences, entitlements or signal access
  lost during revalidation, without an SMTP attempt;
- sequential replay and concurrent job acquisition;
- normal lease contention returning zero and technical acquisition failure
  returning non-zero;
- known pre-accept failure, retry and backoff;
- permanent failure terminality;
- expired job and delivery leases;
- process/persistence failure around SMTP acceptance;
- deterministic `Message-ID` reuse and the documented ambiguity boundary;
- CLI exit codes, environment-only database URL and dry-run behavior;
- current-run-only failure exit codes, with historical terminal rows ignored;
- versioned service/timer content and local runtime locking;
- migration upgrade/downgrade on SQLite and offline PostgreSQL SQL;
- a local fake SMTP integration that never reaches the public network.

The full backend suite, Ruff, systemd unit verification and diff checks are
mandatory. Frontend checks are run if frontend code changes; existing deep-link
route and preference behavior must not regress.

## 9. DNS and staging validation

The read-only DNS audit currently shows:

- one SPF record authorizing Infomaniak;
- no competing SPF record;
- a DMARC policy of `p=reject`;
- Infomaniak MX and nameservers.

DKIM cannot be proven by guessing common selectors. Its exact selector and
record must come from the Infomaniak Global Security view. No DNS write is part
of this implementation.

After code, CI and an explicitly authorized staging installation, the controlled
mailbox supplied out of band may be used for exactly the requested reset and
alert validation. The report records only redacted evidence. Final mail headers
must demonstrate SPF, DKIM and DMARC results and Return-Path alignment.

If DNS needs modification, the exact provider-supplied record and impact are
reported first; execution stops for separate authorization.

## 10. Deployment and rollback boundary

The pull request remains a draft and is not merged by this mission. Production
is never modified.

Staging preparation will document:

1. database backup;
2. deploy the reviewed SHA;
3. migrate through `0023`;
4. update the non-secret environment contract without printing secrets;
5. install and verify the versioned unit and timer;
6. run a dry-run and inspect aggregate logs;
7. perform the authorized reset and alert checks;
8. verify headers and replay behavior.

Rollback stops/disables the new timer, restores the prior units and application
SHA, downgrades `0023` only when the release procedure officially selects a
database rollback, and restores the backup if downgrade is unsafe. Existing
delivery history is preserved whenever the database is not restored wholesale.

## 11. ROAD_TO_LIVE state

RTL-05 is marked **livré en PR** only after the draft pull request exists. It is
marked **validé sur staging** only after both controlled messages succeed. It is
marked **opérationnel** only after merge, green `main` CI, installed service and
timer, recovery/idempotence validation, and SPF/DKIM/DMARC confirmation from a
received message.
