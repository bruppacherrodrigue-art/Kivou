# PR6 Alerts, Account and Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer l’alerte hebdomadaire client, les droits compte et les dernières incohérences visibles avant recette.

**Architecture:** Les décisions de sélection et de normalisation restent dans les services backend existants. Le frontend consomme des contrats complets sans recomposer les droits, les profils ou les lieux; les tâches différées restent idempotentes et pilotées par les runtimes existants.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, PostgreSQL/SQLite batch, React/TypeScript, Vitest, Playwright, systemd.

---

### Task 1: Weekly alert contract and rendering

**Files:** `src/signals/alerts/content.py`, `src/signals/alerts/job.py`, `src/signals/alerts/gateway.py`, `tests/test_alerts_cycle.py`

- [ ] Add failing tests for zero-send, three-card HTML/text parity, deep links, unsubscribe, `model_fit=none`, and Discovery one-open-plus-count behavior.
- [ ] Run only those tests with `timeout 180s uv run pytest ...` and confirm behavioral failures.
- [ ] Extend the persisted alert message contract and renderer from feed cards; do not generate client copy during rendering.
- [ ] Add a deterministic HTML preview command using the same renderer.
- [ ] Re-run the targeted alert tests and commit the green lot.

### Task 2: Account export and delayed deletion

**Files:** `src/signals/accounts/service.py`, `src/signals/api/routes_accounts.py`, `src/signals/persistence/schema.py`, `src/signals/persistence/migrations/versions/0042_account_deletion.py`, `tests/test_account_data_rights.py`

- [ ] Add failing API tests proving ownership-complete JSON export, explicit confirmation, audit fields, idempotency, and deletion within 24 hours.
- [ ] Run the new tests and confirm missing routes/schema failures.
- [ ] Add the batch-mode migration, deterministic export service, deletion request endpoint and bounded purge job.
- [ ] Re-run migration/API/job tests and commit the green lot.

### Task 3: Settings controls

**Files:** `frontend/src/api/endpoints.ts`, `frontend/src/api/types.ts`, `frontend/src/pages/Settings.tsx`, `frontend/src/pages/Settings.test.tsx`, `frontend/src/i18n/fr.ts`, `frontend/src/i18n/en.ts`

- [ ] Add failing Vitest cases for JSON download, confirmation dialog, accepted deletion request, and API errors.
- [ ] Run the single test file and observe the expected failures.
- [ ] Add typed endpoints and accessible controls without duplicating backend state.
- [ ] Re-run test, typecheck and lint; commit the green lot.

### Task 4: Complete company history

**Files:** `src/signals/api/routes_companies.py`, `src/signals/engagement/company.py`, `tests/test_companies_detail.py`, `frontend/src/companies/CompanyDrawer.tsx`, `frontend/src/companies/CompaniesPage.test.tsx`

- [ ] Add failing backend tests for dated contact, reply, note, saved and contacted events ordered newest first.
- [ ] Implement the account-scoped history projection from persisted engagement records.
- [ ] Add failing frontend assertions for every event type and empty history.
- [ ] Render the typed timeline, run targeted backend/frontend tests, and commit.

### Task 5: Dashboard consistency and factual fields

**Files:** `src/signals/dashboard/service.py`, `src/signals/feed/factual_display.py`, `tests/test_dashboard.py`, `tests/test_signal_fields.py`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/dashboard.test.tsx`

- [ ] Add failing tests for pre-update `last_seen_at`, consistent counters, mandatory active-profile labels, unnamed/titleless exclusions and normalized city/department fallback.
- [ ] Run the focused tests and confirm each missing behavior.
- [ ] Compute from one read snapshot, centralize place normalization, and filter invalid cards server-side.
- [ ] Re-run backend and dashboard tests; commit.

### Task 6: Discovery signal teaser and filter tooltips

**Files:** `src/signals/api/routes_signals.py`, `tests/test_feed_access.py`, `frontend/src/pages/SignalsFeed.tsx`, `frontend/src/pages/SignalsFeed.module.css`, `frontend/src/pages/SignalsFeed.test.tsx`

- [ ] Add failing tests for five locked rows maximum, aggregate remaining row, masked holder, rounded amount, retained date/department and tooltip ownership.
- [ ] Run the focused tests and confirm failures.
- [ ] Extend the response metadata and render the bounded teaser plus accessible tooltips.
- [ ] Re-run focused tests, typecheck and lint; commit.

### Task 7: Vocabulary and skipped-test closure

**Files:** `frontend/src/**/*.test.tsx`, `tests/**/*.py`, relevant i18n and rendering modules found by `rg`.

- [ ] Add a rendered-shell vocabulary test for all forbidden engine strings.
- [ ] Remove remaining `test.skip`/`pytest.skip` quarantine markers after replacing their assertions with current behavior.
- [ ] Run the vocabulary and formerly skipped tests, then repository lint checks; commit.

### Task 8: Final verification, PR and staging

**Files:** Playwright goldens and `docs/reports/2026-09-05-pr6-alerts-account-polish.md`.

- [ ] Run backend affected suites, frontend full Vitest once, Playwright once, typecheck and lint with explicit timeouts.
- [ ] Capture Aujourd’hui, Signaux Découverte, Entreprises and the rendered alert at desktop/mobile sizes.
- [ ] Push the branch, open the PR, wait for one final CI run, and fix only non-baseline failures.
- [ ] Deploy the exact PR SHA through `ops/bin/kivou-deploy.sh`, run readiness, and record the evidence in a 15-line report.
