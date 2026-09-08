# PR5 Token, Onboarding and Banner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a cold-mail click-to-value path that opens the promised signal, confirms a provisional profile in one page, and populates Today.

**Architecture:** Extend the account-owned landing projection with provisional signal grants and journey timestamps. Reuse persisted opportunity facts to create account-owned provisional materializations, then activate and rematerialize through the existing ICP pipeline. Make `/dashboard` the server-owned source for profile and plan presentation.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, React/TypeScript, Vitest, Playwright.

---

### Task 1: Runtime token binding

**Files:** `src/signals/conversion/source.py`, `src/signals/campaigns/service.py`, `tests/test_conversion_source.py`, acquisition runtime integration tests.

- [ ] Add a failing test proving every generated mail payload carries the decision engine opportunity key.
- [ ] Run the targeted test and confirm the missing-key failure.
- [ ] Bind issuance to the selected `signal_ref`, retaining legacy verification of keyless tokens.
- [ ] Run the targeted conversion and campaign tests green; commit.

### Task 2: Landing projection and provisional feed

**Files:** `src/signals/accounts/schema.py`, `src/signals/accounts/service.py`, `src/signals/api/routes_attribution.py`, `src/signals/billing/access.py`, `src/signals/persistence/migrations/versions/0038_landing_journey.py`, `tests/test_attribution_landing.py`.

- [ ] Add failing tests for account-owned bait materialization, five related grants, replay idempotence, no quota debit, and keyless feed fallback.
- [ ] Run those tests and confirm failures describe absent materialization/grants.
- [ ] Add the migration, closed journey timestamps, provisional grant rows, and deterministic account-owned materialization from persisted opportunity facts.
- [ ] Run landing, ownership, feed-access and migration tests green; commit.

### Task 3: One-page profile confirmation

**Files:** `src/signals/api/routes_icp.py`, `src/signals/accounts/service.py`, `frontend/src/presentation/dashboard/OnboardingFlow.tsx`, API endpoint/types, backend ICP tests, `frontend/src/pages/onboarding.test.tsx`.

- [ ] Add failing backend and frontend tests for prefilled zones/CPV/offer and updating the existing draft.
- [ ] Run targeted tests and confirm the wizard/current create behavior fails.
- [ ] Add a landing-profile context/confirmation contract and replace the wizard with the three-field form.
- [ ] Materialize the confirmed feed, record timestamps, navigate to `/app` with first-signals state, and run targeted tests green; commit.

### Task 4: Provisional signals banner

**Files:** `frontend/src/pages/SignalsFeed.tsx`, its CSS and tests.

- [ ] Add failing tests for exact provisional copy, onboarding CTA, and disappearance after confirmation.
- [ ] Run them red, implement the banner from authenticated onboarding state, then run them green; commit.

### Task 5: Server-owned dashboard identity and plan

**Files:** `src/signals/api/routes_dashboard.py`, dashboard/billing helpers, `tests/test_dashboard.py`, `frontend/src/api/types.ts`, `frontend/src/layouts/AppShell.tsx`, `frontend/src/pages/Dashboard.tsx`, their tests.

- [ ] Add failing API tests for `profile` and `plan`, including period end and absent-field dashes.
- [ ] Add failing frontend tests proving Dashboard/AppShell use only `/dashboard` for these labels.
- [ ] Implement backend fields, share the dashboard resource through the shell, and remove client composition from ICP/billing calls.
- [ ] Run targeted backend/frontend tests green; commit.

### Task 6: End-to-end journey and release

**Files:** end-to-end backend/frontend tests and PR report.

- [ ] Add the offline end-to-end test covering mail → token → landing → six signals → confirmation → nonempty dashboard/top3.
- [ ] Run it red, close remaining integration gaps, and run it green.
- [ ] Run formatting, lint, typecheck, migrations and the full backend/frontend/Playwright decision suite once.
- [ ] Commit, push, open the PR, wait for one CI run, address only real regressions, and merge/deploy only after green.
- [ ] Deploy the explicit SHA with `ops/bin/kivou-deploy.sh`, time the staging path, and publish the requested 12-line report.
