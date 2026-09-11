# PR6b Fiche Valeur Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich authenticated signal and company profiles with a commercial calendar, holder history, local directory context and gated generated copy without changing acquisition or Founder code.

**Architecture:** Pure SQLAlchemy Core read-models under `signals.client_value` assemble optional value blocks from existing awards, target profiles and `supplier_directory`. Existing FastAPI routes attach those blocks only after ownership and plan checks; React renders them through focused optional sections. Contact lookup remains a separate post-merge task.

**Tech Stack:** Python 3.12, SQLAlchemy Core, FastAPI/Pydantic, React 19, TypeScript, pytest, Vitest, Playwright.

---

### Task 1: Commercial calendar

**Files:** `tests/test_client_value_calendar.py`, `src/signals/client_value/calendar.py`, `src/signals/feed/view.py`, `src/signals/api/config.py`

- [ ] Write tests for notification plus default/configured CPV delay, published duration conversion, explicit start date, and complete absence.
- [ ] Run the focused test and confirm the missing read-model failure.
- [ ] Implement month-safe date addition and an optional `commercial_calendar` projection.
- [ ] Run the focused test and commit the green slice.

### Task 2: Holder history

**Files:** `tests/test_client_value_history.py`, `src/signals/client_value/history.py`, `src/signals/api/routes_signals.py`, `src/signals/api/routes_companies.py`, `src/signals/companies/contracts.py`

- [ ] Write tests for company-key resolution, normalized-name plus department fallback, twelve-month counts/totals, first date, quarterly cadence, medians, group share, recurring buyers and missing data.
- [ ] Run the tests red, implement one deduplicated award reader, and rerun green.
- [ ] Attach the compact block to unlocked signal detail and the full summary to an accessible company profile.
- [ ] Prove locked and cross-account responses reveal nothing, then commit.

### Task 3: Client directory reader

**Files:** `tests/test_client_directory.py`, `src/signals/client_value/directory.py`, `src/signals/api/routes_signals.py`, `src/signals/api/routes_companies.py`

- [ ] Write tests for SIREN-first and name/department fallback, omitted missing fields, suppressed directors, family filtering, same-city/effectif ordering and eight-row cap.
- [ ] Run red, implement read-only projections over `supplier_directory`, and rerun green.
- [ ] Add authenticated `/companies/directory/{siren}` and signal-detail circuit responses without exposing professional email.
- [ ] Test authentication and absent-result shapes, then commit.

### Task 4: Generated phrase activation and bounded active-account backfill

**Files:** `tests/test_for_you_activation.py`, `tests/test_for_you_backfill.py`, `src/signals/api/config.py`, `src/signals/feed/view.py`, `src/signals/personalization/for_you_backfill.py`

- [ ] Write red tests for the disabled flag, strong/non-none activation, deterministic fallback elsewhere and active-profile-only selection.
- [ ] Implement the environment flag, plumb it through card/detail/dashboard renderers, and constrain the existing bounded backfill.
- [ ] Run the phrase and four-channel contract tests and commit.

### Task 5: React value blocks

**Files:** `frontend/src/api/types.ts`, `frontend/src/signals/components/SignalDrawer.tsx`, `frontend/src/signals/components/signals.module.css`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/Dashboard.module.css`, `frontend/src/companies/CompanyDrawer.tsx`, `frontend/src/companies/CompaniesPage.tsx`, `frontend/src/companies/CompaniesPage.module.css`, focused Vitest files

- [ ] Add failing component tests for each present/absent block, exact order, directory navigation, source/suppression copy and Today calendar line.
- [ ] Implement typed optional sections and the directory-company route while reusing current layout tokens.
- [ ] Run Vitest, typecheck, lint and build; commit the green UI slice.

### Task 6: Verify the existing DCE block and channel boundary

**Files:** focused existing DCE and mail tests; no production logic unless a regression is identified.

- [ ] Run the PR4b production-chain tests and confirm determined requirements retain document/page provenance while empty data removes the block.
- [ ] Run a contract test proving none of calendar/history/directory data enters cold mail or alerts.
- [ ] Record any production-data gap separately rather than inventing client data.

### Task 7: Contact lookup after window A lands

**Files:** to be fixed only after rebasing onto the merged Apollo contract.

- [ ] Fetch and rebase onto current `origin/main`; verify the A merge includes organization enrich, people search and people match.
- [ ] Write offline tests with fake providers for persisted account-scoped results, 90-day freshness, monthly quotas 0/20/100 and actual provider-cost logging.
- [ ] Add the migration and client application service without changing acquisition runtime or provider modules.
- [ ] Render locked Découverte and available Essentiel/Pro states, then run migration, backend and frontend tests.

### Task 8: Delivery evidence

- [ ] Run focused backend/frontend suites, ruff, typecheck, lint, build and `git diff --check`.
- [ ] Push the branch, open the PR and wait for decisive CI.
- [ ] Announce the shared staging deployment, deploy the exact green SHA, run the bounded backfill, and verify the active SHA.
- [ ] Capture desktop/mobile drawer and company profile for `client-3mois` and QA Découverte.
- [ ] Restore staging to current `main`, attach evidence to the report/PR and deliver the requested 15-line summary.
