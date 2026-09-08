# Alert Delivery Observability And Terminal Refusal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every transactional delivery outcome observable through a dedicated safe JSON channel and stop creating alert deliveries for an exact recipient context after a permanent SMTP RCPT refusal, without making that controlled refusal fail the hourly job.

**Architecture:** Add an idempotently configured `signals.runtime_events` logger owned only by the ASGI and alerts CLI entry points, then emit allowlisted per-delivery JSON events from reset and alert boundaries. Persist a SHA-256 recipient-context fingerprint on each alert row; it binds the normalized address, preference version, and current eligibility/plan/cadence signature without storing or logging those inputs. A structured permanent RCPT refusal blocks new rows only for an exact account/fingerprint match; any verifiable material context change creates a different fingerprint, while retries from an older or unverifiable context are suppressed before SMTP.

**Tech Stack:** Python 3.12, FastAPI/ASGI, SQLAlchemy Core, Alembic, stdlib `logging`/`json`/`hashlib`, pytest, Ruff.

---

## File map

- `src/signals/runtime_events.py` — dedicated compact-JSON handler, idempotent configuration and allowlisted event emitter.
- `src/signals/api/asgi.py` — configure the dedicated handler for the production ASGI runtime only.
- `src/signals/alerts/cli.py` — configure the same handler for the alerts process and map closed execution categories to exit codes.
- `src/signals/accounts/reset_delivery.py` — emit reset submission/failure outcomes without changing enumeration-resistant exception swallowing.
- `src/signals/alerts/gateway.py` — distinguish a permanent single-recipient RCPT refusal from generic SMTP 5xx/auth/TLS failures.
- `src/signals/alerts/delivery.py` — recipient-context fingerprinting, durable row ownership and exact refusal lookup.
- `src/signals/alerts/job.py` — compare contexts before retry, block before queuing new rows, emit per-signal delivery outcomes, and classify current incidents.
- `src/signals/engagement/notifications.py` — preserve `updated_at` for semantic PATCH no-ops.
- `src/signals/engagement/schema.py` — declare the additive fingerprint column/index.
- `src/signals/persistence/migrations/versions/0025_alert_recipient_context.py` — add/drop only recipient-context state while preserving delivery history.
- `tests/test_runtime_events.py` — handler ownership/idempotence, ASGI/CLI wiring and PII canaries.
- `tests/test_smtp_gateway.py` — RCPT 450/550 versus generic 5xx/auth/TLS/timeout classification.
- `tests/test_alert_delivery_runtime.py` — exact blocking, re-arming, ambiguity and isolation scenarios.
- `tests/test_alerts_cycle.py` — preference no-op, locked-signal and existing alert guarantees.
- `tests/test_alerts_cli.py` — exact controlled/no-op/config/delivery/ambiguity/persistence/runtime exit statuses.
- `tests/test_alert_recipient_context_migration.py` and existing migration-head tests — SQLite/offline PostgreSQL round-trip and new single head.

### Task 1: Dedicated runtime-event channel

**Files:**
- Create: `tests/test_runtime_events.py`
- Create: `src/signals/runtime_events.py`
- Modify: `src/signals/api/asgi.py`
- Modify: `src/signals/alerts/cli.py`
- Modify: `src/signals/accounts/reset_delivery.py`

- [x] **Step 1: Write the failing handler and ASGI wiring tests**

Test that `build_application()` adds exactly one marked handler to
`logging.getLogger("signals.runtime_events")`, sets `propagate=False`, leaves
the root and `signals.billing` handler lists unchanged, and remains idempotent
across repeated ASGI/CLI configuration. Exercise the reset adapter built by
ASGI and parse its emitted line with `json.loads`.

- [x] **Step 2: Run the tests and verify RED**

Run:

```bash
uv run pytest tests/test_runtime_events.py -q
```

Expected: collection or assertion failures because the dedicated module and
entry-point wiring do not exist.

- [x] **Step 3: Implement the minimal logger and event emitter**

Create a non-propagating logger with a single marked `StreamHandler` and a
formatter that renders only `record.runtime_event` through:

```python
json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
```

The emitter accepts only the fixed keys `event`, `channel`, `account_ref`,
`signal_ref`, `status`, `code`, `retryable`, and `attempt`. It never accepts an
exception, address, token, message body, URL, IP, provider response or arbitrary
properties mapping.

- [x] **Step 4: Wire ASGI/CLI and emit reset outcomes**

Call configuration at the start of `build_application()` and `main()`, never
at import time and never through `logging.basicConfig()` or the root logger.
After `gateway.send`, emit reset `status="submitted"` with
`code="smtp_submission_accepted"`; on a safe `AlertDeliveryError`, emit
`status="failed"` with its code/retryability. Keep `deliver()` non-raising.

- [x] **Step 5: Verify GREEN and commit**

```bash
uv run pytest tests/test_runtime_events.py tests/test_api_runtime.py -q
uv run ruff check src/signals/runtime_events.py src/signals/api/asgi.py src/signals/alerts/cli.py src/signals/accounts/reset_delivery.py tests/test_runtime_events.py
git add src/signals/runtime_events.py src/signals/api/asgi.py src/signals/alerts/cli.py src/signals/accounts/reset_delivery.py tests/test_runtime_events.py tests/test_api_runtime.py
git commit -m "feat(email): add safe runtime delivery events"
```

### Task 2: Structured permanent RCPT classification

**Files:**
- Modify: `tests/test_smtp_gateway.py`
- Modify: `src/signals/alerts/gateway.py`

- [x] **Step 1: Write failing classification tests**

Assert that `SMTPRecipientsRefused` with one RCPT status 550 produces exactly
`AlertDeliveryError("smtp_recipient_refused", retryable=False)`, while RCPT 450
remains `smtp_450`/retryable. Generic `SMTPDataError(550)`, authentication,
TLS and submission timeout retain their distinct existing codes and never gain
the permanent-recipient classification.

- [x] **Step 2: Verify RED, implement the narrow branch, and verify GREEN**

```bash
uv run pytest tests/test_smtp_gateway.py -k 'recipient_refusal or response_classification or authentication or tls or timeout' -q
```

Change only the known, single-recipient, 5xx `SMTPRecipientsRefused` path. Do
not classify from exception strings or server response text.

- [x] **Step 3: Commit**

```bash
uv run pytest tests/test_smtp_gateway.py -q
uv run ruff check src/signals/alerts/gateway.py tests/test_smtp_gateway.py
git add src/signals/alerts/gateway.py tests/test_smtp_gateway.py
git commit -m "fix(email): classify permanent RCPT refusals"
```

### Task 3: Exact durable recipient context

**Files:**
- Modify: `tests/test_alert_delivery_runtime.py`
- Modify: `tests/test_alerts_cycle.py`
- Modify: `src/signals/alerts/delivery.py`
- Modify: `src/signals/alerts/job.py`
- Modify: `src/signals/engagement/notifications.py`
- Modify: `src/signals/engagement/schema.py`

- [x] **Step 1: Write failing terminal-refusal tests**

Cover more than five eligible signals and multiple later cycles: one SMTP
attempt, exactly the original per-message maximum of delivery rows, and no new
row after the refusal. Assert the first refusal is persisted/logged but
produces no `CycleReport` incident. Assert a generic SMTP 550 still produces a
current incident and does not install the exact block.

- [x] **Step 2: Write failing context-change tests**

Prove future signals re-arm after each independently verifiable change:
normalized notification address, preference version, and paid
eligibility/plan/cadence signature. Prove a PATCH that repeats the stored values
does not change `updated_at` and does not bypass the block. Prove an account
cannot inherit another account's refusal.

- [x] **Step 3: Write failing old-batch safety tests**

Create an ambiguous batch for address A, change to address B before its due
retry, and assert it is suppressed without an SMTP attempt; a later fresh batch
may use B. Retain the existing locked/inaccessible, deterministic Message-ID,
bounded retry, inter-account and post-accept ambiguity assertions.

- [x] **Step 4: Verify RED**

```bash
uv run pytest tests/test_alert_delivery_runtime.py tests/test_alerts_cycle.py -k 'recipient or context or noop or ambiguous or locked' -q
```

- [x] **Step 5: Implement the fingerprint and exact block**

Canonicalize a JSON array containing the account ID, normalized address,
preference `updated_at`, and a sorted eligibility signature containing the
effective plan, cadence, subscription state and currently feedable ICP refs;
store only its full SHA-256 digest. `queue_batch` writes the digest to every
row. `next_due_batch` returns it and state transitions include it in ownership
predicates.

Before any new call to `queue_batch`, run an exact `EXISTS` scoped by account,
fingerprint, terminal `failed`, and structured
`last_error_code="smtp_recipient_refused"`. A hit returns a controlled blocked
outcome and creates no row. A retry whose stored digest is missing or differs
from the current digest becomes terminal `suppressed` before message rendering
or SMTP.

- [x] **Step 6: Make preference PATCH no-ops stable**

Load/normalize requested values first and issue no SQL UPDATE when they equal
the stored preference. A true change updates `updated_at`; a repeated PATCH
returns the same object and timestamp.

- [x] **Step 7: Emit per-signal alert delivery events and verify GREEN**

Emit only after the durable transition when possible. Each line carries opaque
account/signal refs, status, safe code, current retryability and attempt number.
`submitted` means only that SMTP submission returned successfully; no event or
documentation claims receipt, exactly-once delivery, or inbox arrival.

```bash
uv run pytest tests/test_alert_delivery_runtime.py tests/test_alerts_cycle.py tests/test_runtime_events.py -q
uv run ruff check src/signals/alerts src/signals/engagement/notifications.py src/signals/engagement/schema.py tests/test_alert_delivery_runtime.py tests/test_alerts_cycle.py tests/test_runtime_events.py
git add src/signals/alerts src/signals/engagement/notifications.py src/signals/engagement/schema.py tests/test_alert_delivery_runtime.py tests/test_alerts_cycle.py tests/test_runtime_events.py
git commit -m "fix(email): terminalize exact recipient refusals"
```

### Task 4: CLI execution categories

**Files:**
- Modify: `tests/test_alerts_cli.py`
- Modify: `src/signals/alerts/cli.py`

- [x] **Step 1: Write failing exact-status tests**

Assert code 0 for clean/no-op/contention/configured block/controlled permanent
RCPT refusal; code 2 for invalid configuration; and separate non-zero statuses
for current retryable/generic delivery failure, ambiguity, persistence failure,
and an uncategorized runtime exception. Historical terminal rows never enter a
current report and therefore never affect a later exit.

- [x] **Step 2: Verify RED, implement minimal precedence, and verify GREEN**

Map the most severe current outcome deterministically. Do not print `detail`,
exception text, addresses or configuration values.

```bash
uv run pytest tests/test_alerts_cli.py -q
uv run ruff check src/signals/alerts/cli.py tests/test_alerts_cli.py
git add src/signals/alerts/cli.py tests/test_alerts_cli.py
git commit -m "fix(email): separate alert job exit statuses"
```

### Task 5: Additive migration 0025

**Files:**
- Create: `tests/test_alert_recipient_context_migration.py`
- Create: `src/signals/persistence/migrations/versions/0025_alert_recipient_context.py`
- Modify: migration tests that assert the repository's current head.

- [x] **Step 1: Write failing migration tests**

Starting at `0024_scheduled_plan_change`, seed queued, sent, failed and ambiguous
history. Upgrade to `0025_alert_recipient_context`, assert the nullable digest
column and scoped composite index exist, all old values remain NULL and every
row/status/error/attempt remains unchanged. Downgrade and re-upgrade on SQLite.
Render PostgreSQL offline upgrade/downgrade SQL and assert only the additive
column/index are touched; forbid any UPDATE/backfill or error-text parsing.

- [x] **Step 2: Verify RED, implement the migration, and verify GREEN**

```bash
uv run pytest tests/test_alert_recipient_context_migration.py -q
```

Use revision `0025_alert_recipient_context` with down revision
`0024_scheduled_plan_change`. Update current-head assertions mechanically,
without changing the historical migration-specific HEAD/PREVIOUS constants.

- [x] **Step 3: Commit**

```bash
uv run pytest tests/test_alert_recipient_context_migration.py tests/test_transactional_email_migration.py tests/test_policy_persistence.py -q
uv run ruff check src/signals/persistence/migrations/versions/0025_alert_recipient_context.py tests/test_alert_recipient_context_migration.py
git add src/signals/persistence/migrations/versions/0025_alert_recipient_context.py tests
git commit -m "feat(email): persist alert recipient context"
```

### Task 6: Documentation, regression and release evidence

**Files:**
- Modify: `docs/reports/2026-08-23-rtl-05-transactional-email-runtime.md`
- Modify only if necessary: `ops/README.md`
- Do not modify: `ops/systemd/kivou-alerts.service`, `ops/systemd/kivou-alerts.timer`

- [x] **Step 1: Document the corrected operational semantics**

Record the dedicated logger, safe event fields, exact context block/re-arm
rules, SMTP-submission meaning, controlled terminal refusal exit 0, and distinct
current incident exits. Preserve the no-exactly-once warning and state that no
staging, GitHub, DNS or real SMTP action occurred. The existing unit already
routes stdout/stderr to the journal, so leave it unchanged.

- [x] **Step 2: Run targeted regression (expected at least 48 tests)**

```bash
uv run pytest \
  tests/test_runtime_events.py \
  tests/test_smtp_gateway.py \
  tests/test_alert_delivery_runtime.py \
  tests/test_alerts_cycle.py \
  tests/test_alerts_cli.py \
  tests/test_alert_recipient_context_migration.py \
  tests/test_transactional_email_migration.py \
  tests/test_api_runtime.py -q
```

- [x] **Step 3: Run static, migration and diff verification**

```bash
uv run ruff check src/signals/runtime_events.py src/signals/accounts/reset_delivery.py src/signals/alerts src/signals/api/asgi.py src/signals/engagement src/signals/persistence/migrations/versions/0025_alert_recipient_context.py tests/test_runtime_events.py tests/test_smtp_gateway.py tests/test_alert_delivery_runtime.py tests/test_alerts_cycle.py tests/test_alerts_cli.py tests/test_alert_recipient_context_migration.py
uv run python -c 'from alembic.script import ScriptDirectory; from signals.persistence.database import alembic_config, create_database_engine; scripts = ScriptDirectory.from_config(alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))); assert scripts.get_heads() == ["0025_alert_recipient_context"]; assert scripts.get_revision("0025_alert_recipient_context").down_revision == "0024_scheduled_plan_change"'
uv run pytest tests/test_alert_recipient_context_migration.py::test_postgresql_offline_sql_is_additive_and_never_classifies_history -q
git diff --check 7253c3a...HEAD
git status --short
```

- [x] **Step 4: Run PII/secret and scope canaries**

Parse every captured runtime line as JSON; scan keys and serialized values for
synthetic email, reset token, message body, URL, IP, SMTP password, raw response
and exception markers. Confirm changed paths contain no Acquisition Engine,
Stripe action, frontend or systemd unit mutation.

- [x] **Step 5: Self-review and commit docs**

Review `git diff --stat`, `git diff`, migration SQL and the plan requirement by
requirement. Fix all Critical/Important findings, rerun affected commands, then:

```bash
git add docs/reports/2026-08-23-rtl-05-transactional-email-runtime.md
git commit -m "docs(email): explain terminal refusal operations"
```

Do not push, open/update a PR, deploy, invoke real SMTP, mutate staging, or
claim exactly-once delivery.
