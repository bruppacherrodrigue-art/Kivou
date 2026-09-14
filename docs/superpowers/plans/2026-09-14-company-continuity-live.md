# Company Continuity and Live Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved company-data continuity, real enrichment and clean growing catalogue on staging, then promote the connected V11 product to production while preserving customer data and existing production capabilities.

**Architecture:** Reconcile deployed Git/Alembic histories first. Extend the existing company projections and enrichment engine with bounded durable user requests; publish an allowlisted company catalogue to isolated staging. Reuse the approved V11 surfaces, entitlements, notes and commercial workflows.

**Tech Stack:** Python 3.12, SQLAlchemy Core, PostgreSQL/Alembic, FastAPI, React/TypeScript, Vitest, Playwright, systemd, existing atomic VPS deployer.

---

## Approved specification

`docs/superpowers/specs/2026-09-14-company-continuity-live-design.md` and the frozen
V11 HTML plan remain authoritative. No campaign or billing-policy expansion.
Record exact commands/results and differences from this plan in the release report.

### Task 1: Reconcile production and V11 histories

**Files:** existing conflicted integration files only; new Alembic merge revision
`src/signals/persistence/migrations/versions/0061_company_live_merge.py`; migration
tests currently asserting a single historical head.

- [x] Verify isolated worktree and clean tracked baseline. Run `.venv/bin/pytest
  -n 2 tests/test_company_directory_api.py tests/test_client_directory.py
  tests/test_winner_enrichment_api.py -q`; require no failures.
- [x] Run `git merge --no-commit --no-ff origin/main`. Preserve both sets of
  behavior when resolving conflicts; do not choose one branch wholesale.
- [x] List Alembic heads with `.venv/bin/alembic heads`. Preserve deployed
  `0058_model_call_budget` and `0060_boamp_notice_facts` revision identities.
- [x] Add a merge-only revision: `revision = "0061_company_live_merge"`,
  `down_revision = ("0058_model_call_budget", "0060_boamp_notice_facts")`,
  with no-op `upgrade()`/`downgrade()`. Test upgrade from each deployed head.
- [x] Run migration and touched integration suites, inspect staged diff and
  commit the integration only after successful verification.

### Task 2: Shared source-attributed company contacts

**Files:** `src/signals/companies/contracts.py`, a focused contacts projection
under `src/signals/client_value/`, `src/signals/api/routes_companies.py`,
`src/signals/client_value/directory.py`, shared frontend contact component,
`frontend/src/prospecting/components/{HolderSummary,SignalDetail,CompanyDossier}.tsx`,
client response types, focused backend and frontend tests.

- [x] Write failing regressions for the observed BOAMP→company loss and supported
  model/site evidence withheld by publication; verify RED against actual projections.
- [x] Publish a typed common list of public company contacts on both dossier
  contracts, matching exact winner identity and preserving source/agency attribution.
- [x] Reuse that list in the existing signal summary and company dossier, without
  adding a new panel. Deduplicate facts and keep buyer contacts excluded.
- [x] Test locked projections without raw values, suppression, multiple holders,
  mismatched identity, aliases and private-contact separation; run focused suites.
- [x] Review specification compliance, then code quality, correct findings and commit.

### Task 3: Durable, bounded real company enrichment

**Files:** focused request-queue module under `src/signals/company_research/`,
existing `winner_worker.py` provider factory, company routes/contracts,
new request migration/schema, enrichment store preservation logic,
`frontend/src/prospecting/useCompanyEnrichment.ts`, dossier/summary status copy,
queue/API/worker and React regression tests.

- [x] First specify/test durable request states and stable company identity. Tests
  must fail when an existing incomplete directory returns false `ready`.
- [x] Queue explicit paid-account requests by company identity independently of
  automatic winner recency/watermark filters. Deduplicate active jobs, enforce
  refresh intervals, limits and existing model budgets; never debit lookup quota.
- [x] Consume requests through the existing full provider pipeline. Record real
  outcomes/changed fields; do not clear known public facts on incomplete results.
- [x] Expose authoritative request state on dossier reads; resume status after
  reopening and keep polling separate from requesting. Handle no-change/failure.
- [x] Test retry/lease/concurrency, historical and directory-only companies,
  budgets, close/reopen, no provider on GET, no lost contacts and no fake completion.
- [x] Review specification compliance then quality; commit verified changes.

### Task 4: Controlled catalogue publication and fixture isolation

**Files:** `src/signals/supplier_directory/catalogue_publication.py`,
`src/signals/supplier_directory/catalogue_mirror.py`, bounded publication route,
configuration, mirror ownership metadata/migration, CLI/systemd definitions,
`frontend/src/companies/CompaniesPage.tsx`, tests and deployment runbook.

- [x] RED tests define the explicit column allowlist, bounded snapshot schema,
  authentication, staging-only destination and transactionality before implementation.
- [x] Add an authenticated, read-only production export with no private/client
  tables or raw model evidence. Import idempotently by SIREN into staging only;
  preserve locally owned rows/private data and propagate source withdrawals safely.
- [x] Add a periodic isolated staging mirror service using a dedicated publication
  credential; fail closed on absent credentials or invalid/truncated snapshots.
- [x] Add visibility-aware catalogue refresh preserving filters and editing state;
  demonstrate new row/count coherence with frontend tests.
- [x] Prepare an exact-target recoverable quarantine for the 30 audited fixtures;
  independently review the manifest and backup before any live data mutation.
- [x] Review specification compliance then quality; commit verified changes.

### Task 5: Integrated release verification

**Files:** `docs/reports/prospecting-v11/company-continuity-live.md`, bounded
PostgreSQL rehearsal/QA tooling, migration and UI scenarios.

- [x] Run full backend suite, frontend tests/typecheck/lint, client and Founder
  builds, visual tests, and fresh CI on the exact executable candidate.
- [x] Rehearse upgrades from staging and production heads on isolated PostgreSQL
  copies. Verify notes, memberships, billing, grants and all private rows unchanged;
  exercise old-artifact rollback compatibility without destructive downgrade.
- [x] Review complete diff and all acceptance criteria independently. Resolve
  every material issue before approving activation.

### Task 6: Staging activation and catalogue correction

- [x] Verify target host/database/SHA, capture existing links/unit states and
  acquire existing worker locks as required; back up before migration.
- [x] Deploy exact tested SHA with existing `ops/bin/kivou-deploy.sh staging SHA`.
  No second deployment while an earlier one is still running.
- [x] Install/configure the reviewed narrow mirror, import shareable catalogue
  and quarantine only manifested fixtures with recoverable backups.
- [x] Verify real BOAMP→dossier, directory-rich paid/discovery displays, catalogue
  counts, durable enrichment and automatic refresh. Do not send commercial mail,
  buy subscriptions or expose credentials during QA.
  Evidence: live BOAMP/dossier/entitlements and mirror counts; local contracts
  for durable jobs and refresh behavior. Staging provider execution stays off.
- [x] Confirm health, scheduler outcomes, no unexpected errors, cleanup of only
  newly created QA artifacts and restoration of previous worker activity.

### Task 7: Production promotion and post-release proof

- [x] Confirm production baseline has not advanced unexpectedly; integrate any
  necessary new changes and repeat candidate verification rather than overwrite.
- [x] Retain a verified pre-migration backup and exact rollback artifact. Promote
  the exact reviewed candidate through the normal Git/main/CI workflow.
- [x] Deploy using `ops/bin/kivou-deploy.sh production SHA` with protected existing
  environment; do not broaden acquisition modes, provider budgets or mail volume.
- [x] Verify client/Founder artefacts, schema, catalogue, entitlements and three
  V11 tabs, worker processing, billing routes and shallow health. Review errors.
  Evidence: live production artefacts/health/catalogue and empty request-worker
  run; authenticated entitlements/UI on staging and private contracts on the
  exact production copy, not a live authenticated production session.
- [x] Deliver production URL and exact SHA, test evidence and any remaining
  limitations honestly. Do not call the release complete before these checks.
  Production URL: https://kivou.eu/app/today — executable SHA
  `88f189196f80bb8f93566398b0d5fddc95a379ed`; evidence and limitations below.

### Delivery evidence and explicit limits

See `docs/reports/prospecting-v11/company-continuity-live.md`. Production serves
`88f1891`; staging serves `cae05b3` with identical V11 code, the only later product
delta preserving the upstream mail footer. Exact candidate CI, production-copy
upgrade/rollback, live three-tier staging QA, public production artefacts and
runtime checks passed. Authenticated production QA was not performed with the
staging credentials; no account impersonation or reset. The production request
worker and renderer are verified operational with an empty queue, not claimed
as a completed real-provider enrichment; staging providers remain disabled.
BOAMP coverage is explicitly partial:94/136facts, six complex notices reserved
after bounded attempts, no forced identity alignment. All suspended timers are
restored; catalogue mirror and production request/retention timers are active.
