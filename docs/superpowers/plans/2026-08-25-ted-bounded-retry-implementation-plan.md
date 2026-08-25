# TED Bounded Retry And Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TED ingestion converge through provider throttling while preserving every completed notice and keeping each process run bounded.

**Architecture:** Keep TED HTTP synchronous and serialize search and XML requests through one paced, retrying `TedClient` request boundary. Persist a versioned TED cursor in the existing `ingestion_checkpoint.cursor` JSON: the current date window, search page, pending opaque publication numbers, and next index. The runner checkpoints a searched page before downloading it, then checkpoints after each successfully processed notice; a crash can therefore replay at most one idempotently persisted notice and never resets the cursor to `null`.

**Tech Stack:** Python 3.12, `httpx`, SQLAlchemy, Pydantic-domain ingestion pipeline, pytest, systemd.

**Status:** Implementation and independent-review corrections locally verified. Manual TED staging validation and timer enablement remain deliberately pending.

---

### Task 1: Pace and retry every TED HTTP request

**Files:**
- Modify: `src/signals/connectors/ted/client.py`
- Modify: `src/signals/connectors/ted/errors.py`
- Test: `tests/test_ted_client.py`

- [x] **Step 1: Write failing client tests**

Add tests using `httpx.MockTransport`, injected monotonic/wall clocks, and an injected sleeper. Prove that search and XML share one minimum request interval, `Retry-After` supports delta-seconds and HTTP dates, 429/202/5xx/network failures retry sequentially, a later success is returned, and attempts stop before `max_attempts` or `max_retry_seconds` is exceeded. Assert errors contain only the operation/status/URL and never response bodies.

- [x] **Step 2: Run the client tests and verify RED**

Run: `uv run pytest tests/test_ted_client.py -q`

Expected: failures for the missing pacing/retry constructor arguments and bounded retry behavior.

- [x] **Step 3: Implement the smallest common request boundary**

Add a private lock-protected `TedClient._request()` used by both `search()` and `fetch_notice_xml()`. Before every attempt, wait for the shared minimum interval; retry only 202, 429, 5xx, and `httpx.HTTPError`; use `max(Retry-After, bounded exponential delay)` without sleeping past the total retry deadline. Raise `TedHttpError` with a machine-safe `category`, status and URL but no body.

- [x] **Step 4: Run the client tests and verify GREEN**

Run: `uv run pytest tests/test_ted_client.py -q`

Expected: all client tests pass with no network access.

### Task 2: Define and validate the durable TED cursor

**Files:**
- Create: `src/signals/ingestion/ted_convergence.py`
- Test: `tests/test_ted_convergence.py`

- [x] **Step 1: Write failing cursor contract tests**

Specify `TedCycleCursor(version=1)` with `cycle_since`, `cycle_until`, `page`, `page_size`, `pending_publication_numbers`, `next_index`, `more_pages`, and `complete`. Cover a fresh cursor, a stored partial cursor, a searched page, one-notice advancement, page advancement, terminal completion, a legacy non-versioned success cursor starting a new cycle, and rejection of unknown versions or incoherent indexes.

- [x] **Step 2: Run the cursor tests and verify RED**

Run: `uv run pytest tests/test_ted_convergence.py -q`

Expected: collection fails because `signals.ingestion.ted_convergence` does not exist.

- [x] **Step 3: Implement pure cursor transitions**

Implement immutable, JSON-round-trippable cursor helpers. Store only TED publication numbers, never XML. Keep an incomplete stored cycle fixed even if a later run has a newer `until`; treat legacy `{\"window_end\": ...}` values as completed old-format cursors and begin the requested overlap cycle; reject unknown explicit versions.

- [x] **Step 4: Run the cursor tests and verify GREEN**

Run: `uv run pytest tests/test_ted_convergence.py -q`

Expected: all cursor transition tests pass.

### Task 3: Acquire TED as checkpointable units

**Files:**
- Modify: `src/signals/ingestion/sources.py`
- Test: `tests/test_ingestion_sources.py`

- [x] **Step 1: Write failing TED unit tests**

Add a fake client proving that an empty cursor performs exactly one search request and returns a cursor containing pending publication numbers without downloading XML. Prove that a pending cursor performs exactly one XML request, maps one notice, advances one index, and never overlaps search/download calls. Prove errors retain the input cursor and carry zero uncheckpointed publications.

- [x] **Step 2: Run the source tests and verify RED**

Run: `uv run pytest tests/test_ingestion_sources.py -q`

Expected: failures because `TedSource.acquire_unit()` and its result contract are missing.

- [x] **Step 3: Implement `TedSource.acquire_unit()`**

Return one `TedAcquisitionUnit` per call: either a searched page with no publications or one normalized notice. The output includes the pure next cursor plus accurate fetched/accepted/rejected counters. Keep the existing whole-window `acquire()` only for dry-run compatibility and route all deployed persisted TED runs through units.

- [x] **Step 4: Run the source tests and verify GREEN**

Run: `uv run pytest tests/test_ingestion_sources.py -q`

Expected: all TED source unit tests pass.

### Task 4: Persist TED progress after every finalized unit

**Files:**
- Modify: `src/signals/ingestion/runner.py`
- Modify: `tests/test_ingestion_runner.py`

- [x] **Step 1: Write failing runner recovery tests**

Prove that the runner saves the initial non-null cursor before search, saves page refs before XML, advances after each successful pipeline call, retains the current publication on 429, and resumes it without duplicate source events/awards/representations. Add cases for 429 recovery, exhausted 429, maximum records, time budget, SIGTERM after a notice, and a crash-like pipeline failure after partial persistence.

- [x] **Step 2: Run the selected runner tests and verify RED**

Run: `uv run pytest tests/test_ingestion_runner.py -k 'ted and (resume or retry or budget or termination or partial)' -q`

Expected: failures because persisted TED still uses one all-or-nothing acquisition.

- [x] **Step 3: Implement the bounded TED runner path**

Add `ted_max_records_per_run` and `ted_time_budget_seconds` to `RunOptions`. For non-dry-run TED, start/reconcile the persisted run, plan and save the cursor, acquire/process one unit at a time, and save its cursor only after that unit is finalized. A record/time limit returns `success` with `work_pending=True`; completed cycles atomically advance `window_end`; provider exhaustion returns the existing non-zero `rate_limited` outcome with the partial cursor retained; termination is terminalized.

- [x] **Step 4: Run runner tests and verify GREEN**

Run: `uv run pytest tests/test_ingestion_runner.py -q`

Expected: all runner tests pass, including DECP convergence tests.

### Task 5: Close the configuration and host-runtime contract

**Files:**
- Modify: `src/signals/ingestion/cli.py`
- Modify: `src/signals/ingestion/sources.py`
- Modify: `.env.example`
- Create: `ops/systemd/kivou-ingest-ted.service`
- Create: `ops/systemd/kivou-ingest-ted.timer`
- Modify: `ops/README.md`
- Modify: `tests/test_ingestion_cli.py`
- Modify: `tests/test_ops_ingestion_runtime.py`

- [x] **Step 1: Write failing configuration/runtime tests**

Cover positive parsing and fail-closed invalid values for `KIVOU_TED_REQUEST_INTERVAL_SECONDS`, `KIVOU_TED_MAX_ATTEMPTS`, `KIVOU_TED_MAX_RETRY_SECONDS`, `KIVOU_TED_MAX_RECORDS_PER_RUN`, and `KIVOU_TED_TIME_BUDGET_SECONDS`. Assert the CLI wires client and runner options. Assert a oneshot service uses the deployed checkout, protected EnvironmentFile, clean nonblocking `flock`, a 25-minute host timeout, and hardening compatible with network/database access. Assert the persistent two-hour timer is versioned but the runbook enables it only after a successful manual run.

- [x] **Step 2: Run configuration/runtime tests and verify RED**

Run: `uv run pytest tests/test_ingestion_cli.py tests/test_ops_ingestion_runtime.py -q`

Expected: failures for missing TED environment values and units.

- [x] **Step 3: Implement configuration, units and operator procedure**

Use conservative defaults: one request per second, four attempts, 120 seconds maximum retry duration, 500 notices and 1,200 seconds per run. Document install, `systemd-analyze verify`, manual proof, cursor evidence, two scheduled proofs, enablement persistence, SIMAP/BOAMP health checks, and rollback. Do not enable or touch staging in this change.

- [x] **Step 4: Run configuration/runtime tests and verify GREEN**

Run: `uv run pytest tests/test_ingestion_cli.py tests/test_ops_ingestion_runtime.py -q`

Expected: all tests pass.

### Task 6: Verify #82 without provider or staging access

**Files:**
- Modify: `docs/superpowers/plans/2026-08-25-ted-bounded-retry-implementation-plan.md` (check completed steps)

- [x] **Step 1: Run source and regression suites**

Run:

```bash
uv run pytest \
  tests/test_ted_client.py tests/test_ted_connector.py tests/test_ted_convergence.py \
  tests/test_ingestion_sources.py tests/test_ingestion_runner.py tests/test_ingestion_cli.py \
  tests/test_ingestion_state.py tests/test_ingestion_convergence.py \
  tests/test_ops_ingestion_runtime.py tests/test_simap_client.py \
  tests/test_simap_connector.py tests/test_boamp_client.py \
  tests/test_boamp_client_cursor.py tests/test_boamp_adapter.py -q
uv run ruff check \
  src/signals/connectors/ted src/signals/ingestion \
  tests/test_ted_client.py tests/test_ted_convergence.py \
  tests/test_ingestion_sources.py tests/test_ingestion_runner.py \
  tests/test_ingestion_cli.py tests/test_ops_ingestion_runtime.py
systemd-analyze verify \
  ops/systemd/kivou-ingest-ted.service ops/systemd/kivou-ingest-ted.timer
git diff --check
git status --short
```

Expected: all selected TED/ingestion/SIMAP/BOAMP tests and static/runtime checks pass; the worktree contains only #82 files.

- [x] **Step 2: Commit the verified implementation locally**

Commit only the listed files with `fix(ingestion): bound TED retries and resume progress`. Do not push, open a PR, deploy, enable the timer, or contact TED.

### Task 7: Address independent-review retry-bound findings

**Files:**
- Modify: `src/signals/connectors/ted/client.py`
- Modify: `src/signals/ingestion/runner.py`
- Modify: `tests/test_ted_client.py`
- Modify: `tests/test_ingestion_runner.py`

- [x] **Step 1: Reproduce an HTTP attempt exceeding the total retry deadline**

Use a simulated slow client and prove that the request receives the remaining retry time as its own timeout. Verify RED with the previous fixed per-request timeout.

- [x] **Step 2: Bound every HTTP attempt by the remaining retry duration**

Pass `min(configured_request_timeout, remaining_retry_duration)` on every TED HTTP call. Verify the focused client test and complete TED client suite are GREEN.

- [x] **Step 3: Reproduce and remove nested retries in TED dry-run**

Use a real `TedClient` and `TedSource` with repeated 503 responses. Verify RED at 12 HTTP attempts, then bypass the generic runner retry only for TED dry-run and verify GREEN at exactly four attempts.

- [x] **Step 4: Re-run the complete local #82 validation and commit the review corrections**

Run the targeted regression suite, Ruff, systemd unit verification and Git diff checks. Commit locally without push, PR, staging access, provider access or timer enablement.
