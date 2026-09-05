# PR5b “Pour vous” Sentence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce one grounded French “Pour vous” sentence per current signal/profile pair and reuse it unchanged across the product and emails.

**Architecture:** Materialization persists an immediate fit-reason fallback and a durable pending job without calling the provider. A bounded worker generates and validates sentences asynchronously, while every consumer joins the same current cached row. Fingerprints and policy version invalidate the cache deterministically.

**Tech Stack:** Python 3.12, SQLAlchemy, Alembic batch migrations, FastAPI, Anthropic HTTP adapter, React/TypeScript, pytest, Vitest.

---

### Task 1: Persistence contract and migration

**Files:**
- Modify: `src/signals/persistence/schema.py`
- Create: `src/signals/persistence/migrations/versions/0039_for_you_sentence.py`
- Test: `tests/test_for_you_sentence_migration.py`
- Modify: `tests/test_*_migration.py`

- [ ] **Step 1: Write the failing migration test** asserting SQLite/PostgreSQL parity, the composite uniqueness of `(signal_key, target_icp_id, signal_fingerprint, profile_fingerprint, policy_version)`, closed states `pending|running|completed`, closed rejection reasons, timestamps, counters, and Alembic head `0039_for_you_sentence`.
- [ ] **Step 2: Run `uv run pytest -q tests/test_for_you_sentence_migration.py`** and verify it fails because the table and revision do not exist.
- [ ] **Step 3: Add `for_you_sentence`** with served sentence, fallback, fingerprints, provenance, state, validation verdict/reason/detail, attempt date, lease owner/expiry, provider usage metadata, and timestamps. Use Alembic batch mode for SQLite.
- [ ] **Step 4: Run `uv run pytest -q tests/test_for_you_sentence_migration.py`** and verify it passes.
- [ ] **Step 5: Update migration-head assertions mechanically**, run the migration test set once, and commit `feat(personalization): persist for-you sentence jobs`.

### Task 2: Strict generation and validation contracts

**Files:**
- Create: `src/signals/personalization/for_you.py`
- Test: `tests/test_for_you_sentence.py`

- [ ] **Step 1: Write failing tests** for a `ForYouInput`, `ForYouProvider` protocol, `validate_sentence`, 25-word limit, French sentence shape, `!`, superlatives, invented numbers/dates/names/places, and accepted CPV/department/canton labels.
- [ ] **Step 2: Run `uv run pytest -q tests/test_for_you_sentence.py`** and verify failures are missing-contract failures.
- [ ] **Step 3: Implement immutable input/output models and validator**. Normalize Unicode/case/spacing; build the allowed lexicon only from verified fields plus `cpv_label` and `subdivision_label`; return a closed `ValidationResult` instead of raising on provider text.
- [ ] **Step 4: Run the same tests** and verify all validation cases pass.
- [ ] **Step 5: Commit `feat(personalization): validate grounded for-you copy`**.

### Task 3: Reuse the sole provider adapter

**Files:**
- Modify: `src/signals/documents/providers.py`
- Modify: `src/signals/personalization/for_you.py`
- Test: `tests/test_document_providers.py`
- Test: `tests/test_for_you_sentence.py`

- [ ] **Step 1: Write failing fake-HTTP tests** proving classification behavior stays unchanged and a generic single-sentence request uses the same configured model, timeout, credentials, usage accounting, and prompt boundary.
- [ ] **Step 2: Run both focused test files** and verify only the new generic request contract fails.
- [ ] **Step 3: Extract the shared Anthropic request primitive inside `documents/providers.py`**; keep the model literal and API URL only there. Adapt it to the `ForYouProvider` protocol without importing provider brands into domain code.
- [ ] **Step 4: Run both focused files** and verify they pass without network.
- [ ] **Step 5: Commit `refactor(providers): share bounded text generation adapter`**.

### Task 4: Non-blocking enqueue at materialization

**Files:**
- Create: `src/signals/personalization/for_you_store.py`
- Modify: `src/signals/persistence/materialization.py`
- Modify: `src/signals/ingestion/backfill.py`
- Test: `tests/test_for_you_materialization.py`

- [ ] **Step 1: Write failing tests** showing materialization commits a visible fallback plus pending job, never calls a deliberately blocking provider, deduplicates identical fingerprints, and enqueues a fresh version when signal/profile input changes.
- [ ] **Step 2: Run `uv run pytest -q tests/test_for_you_materialization.py`** and verify the cache row is absent.
- [ ] **Step 3: Implement deterministic input snapshots/fingerprints and `enqueue_fallback_in_transaction`**. Call it only after a signal row is created or updated; do not instantiate or invoke a provider.
- [ ] **Step 4: Run the focused tests**, including the PR5 landing-path test, and verify materialization remains provider-free.
- [ ] **Step 5: Commit `feat(personalization): enqueue for-you copy without blocking signals`**.

### Task 5: Bounded asynchronous worker and counters

**Files:**
- Create: `src/signals/personalization/for_you_worker.py`
- Modify: `src/signals/api/config.py`
- Test: `tests/test_for_you_worker.py`

- [ ] **Step 1: Write failing tests** for accepted generation, rejected generation with persisted fallback, provider outage, four simultaneous calls maximum, configurable daily cap, exposed `generated_today/daily_limit/pending` counters, expired-lease recovery, and next-day resumption.
- [ ] **Step 2: Run `uv run pytest -q tests/test_for_you_worker.py`** and verify the worker is missing.
- [ ] **Step 3: Implement atomic claims with leases**, a thread pool defaulting to four workers, and a database-counted UTC daily cap. Stop cleanly at the cap without changing unclaimed jobs. Persist sanitized failure categories and provider usage.
- [ ] **Step 4: Run the worker tests** and verify maximum observed concurrency is four and calls never exceed the daily cap.
- [ ] **Step 5: Commit `feat(personalization): run bounded for-you generation`**.

### Task 6: One persisted phrase for four consumers

**Files:**
- Modify: `src/signals/feed/view.py`
- Modify: `src/signals/api/routes_dashboard.py`
- Modify: `src/signals/alerts/content.py`
- Modify: `src/signals/campaigns/service.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/signals/components/SignalDrawer.tsx`
- Test: `tests/test_for_you_consumers.py`
- Test: `frontend/src/pages/dashboard.test.tsx`
- Test: `frontend/src/signals/feed.test.tsx`

- [ ] **Step 1: Write failing backend contract test** that materializes one cached sentence and asserts byte-identical text in feed/detail, dashboard, runtime mail variables, and weekly alert line.
- [ ] **Step 2: Write failing frontend tests** asserting Today and drawer render `for_you_sentence`, not `fit.reasons[0]`.
- [ ] **Step 3: Run only those tests** and verify expected old-copy failures.
- [ ] **Step 4: Join the current cache row once in server projections**, add `for_you_sentence` to the response contract, and make all four consumers read it without local rewriting.
- [ ] **Step 5: Run backend and frontend focused tests** and commit `feat(product): share for-you sentence across every surface`.

### Task 7: Explicit bounded backfill CLI

**Files:**
- Create: `src/signals/personalization/for_you_backfill.py`
- Test: `tests/test_for_you_backfill.py`
- Modify: `ops/README.md`

- [ ] **Step 1: Write failing CLI tests** requiring positive `--limit`, ISO `--since`, selection of current uncached pairs only, exact limit enforcement, sanitized output, worker counters, and no work outside the date window.
- [ ] **Step 2: Run `uv run pytest -q tests/test_for_you_backfill.py`** and verify the module is missing.
- [ ] **Step 3: Implement the CLI** using `ApiConfig`, the shared provider adapter, enqueue selection, and the same worker. Print only aggregate counters and return nonzero on configuration/persistence failure.
- [ ] **Step 4: Document staging and pre-production invocations**, explicitly prohibiting an unbounded 39,000-signal production replay.
- [ ] **Step 5: Run CLI tests and `bash`/ruff checks**, then commit `feat(ops): add bounded for-you backfill`.

### Task 8: Verification, PR, staging, and benchmark

**Files:**
- Create: `docs/reports/2026-09-04-pr5b-for-you-benchmark.md`

- [ ] **Step 1: Run focused backend suites, frontend suites, ruff, typecheck, lint, build, and `git diff --check`**; do not repeatedly run the full suites locally.
- [ ] **Step 2: Push once, open the PR, and wait for one complete decision CI**. Fix and rerun only if a non-baseline regression appears.
- [ ] **Step 3: Deploy the green SHA to staging via `kivou-deploy.sh`** and verify active SHA, migration rehearsal, service and readiness.
- [ ] **Step 4: Run exactly one staging backfill with `--limit 50 --since 2026-08-01`**, then query persisted rows for 20 sentences and `attempted/accepted/rejected/fallback` totals. Do not run a production backfill.
- [ ] **Step 5: Re-run the isolated PR5 click-to-dashboard measurement with provider generation disabled** and compare it with `0.424 s`; record the result and benchmark table.
- [ ] **Step 6: Commit the report, push once, let docs-only CI complete, and deliver the PR URL plus rejection rate and 20 persisted phrases.**
