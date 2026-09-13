# Winner Enrichment Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct economic arbitration, serialize replays, and enrich winners from new active-account signals within one hour without consuming the held backfill.

**Architecture:** Keep `CompanyEnrichmentService` as the sole judge/policy boundary. Add a small winner worker that selects only active, 30-day, post-watermark jobs, reuses official winner projection, hydrates `supplier_directory`, and calls the existing budgeted service. Protect replay and worker processes with non-blocking host locks.

**Tech Stack:** Python 3.12, SQLAlchemy Core, FastAPI data model, OpenRouter gateway, Playwright renderer, pytest, systemd.

---

### Task 1: Encode the corrected arbitration contract

**Files:**
- Modify: `src/signals/company_research/enrichment.py`
- Modify: `src/signals/company_research/providers.py`
- Test: `tests/test_company_enrichment_routing.py`
- Test: `tests/test_company_enrichment.py`

- [ ] Add parameterized failing tests for present values at 0.19, 0.20, 0.79 and 0.80; null values at 0.10 and 0.90; and invalid JSON.
- [ ] Run `uv run pytest tests/test_company_enrichment_routing.py -q` and confirm failures come from the old blanket `< 0.8` rule.
- [ ] Add one pure predicate that requests arbitration only for a non-null site, email or family with `0.2 <= confidence < 0.8`; retain the invalid-JSON path.
- [ ] Make the prompt define high-confidence absence and insufficient evidence explicitly.
- [ ] Run `uv run pytest tests/test_company_enrichment_routing.py tests/test_company_enrichment.py -q` and commit the green change.

### Task 2: Refuse concurrent replay instances

**Files:**
- Create: `src/signals/company_research/instance_lock.py`
- Modify: `src/signals/company_research/replay.py`
- Test: `tests/test_company_enrichment_replay.py`

- [ ] Add a failing test holding a real temporary lock and invoking a second acquisition attempt.
- [ ] Run the focused test and confirm the second call is currently accepted.
- [ ] Implement a non-blocking `fcntl.flock` context with a stable conflict exception and acquire it before provider construction.
- [ ] Map conflict to exit code 75 and JSON status `INSTANCE_ALREADY_RUNNING` without a provider call.
- [ ] Run `uv run pytest tests/test_company_enrichment_replay.py -q` and commit.

### Task 3: Select only new, recent, active winner jobs

**Files:**
- Create: `src/signals/company_research/winner_worker.py`
- Test: `tests/test_winner_company_enrichment_worker.py`

- [ ] Add failing selection tests for active versus draft ICP, current versus stale revision, invalidated signal, event older than 30 days, and jobs before/after the activation watermark.
- [ ] Confirm the tests fail because the selector does not exist.
- [ ] Implement one bounded SQL selector using award date, notification date, then publication date, plus active-account and watermark predicates.
- [ ] Add a distinct-holder projection and deterministic queue ordering.
- [ ] Run the focused tests and commit.

### Task 4: Hydrate the directory and call the budgeted judge

**Files:**
- Modify: `src/signals/company_research/winner_worker.py`
- Modify: `src/signals/company_research/enrichment.py`
- Test: `tests/test_winner_company_enrichment_worker.py`

- [ ] Add failing tests proving official SIREN identity becomes a directory record, the judge is invoked once, duplicate holder jobs use cache, provider/budget failures are durable, and no email is sent.
- [ ] Confirm failures describe the missing worker execution.
- [ ] Compose existing official projection, exact Annuaire identity input, `SupplierDirectoryStore`, `CompanyWebCollector`, routed providers, MX verifier and director source.
- [ ] Preserve the existing append-only model call journal and 90-day cache; return bounded processed/completed/failed/budget-stop counters.
- [ ] Run focused worker, enrichment, budget and winner tests and commit.

### Task 5: Install an hourly, serialized production worker

**Files:**
- Create: `ops/systemd/kivou-winner-enrichment.service`
- Create: `ops/systemd/kivou-winner-enrichment.timer`
- Modify: `ops/README.md`
- Test: `tests/test_operations_assets.py`

- [ ] Add failing structural tests requiring a production environment file, mandatory activation watermark, hourly timer, bounded timeout, and `flock --nonblock --conflict-exit-code 75`.
- [ ] Confirm the structural test fails for missing units.
- [ ] Add hardened systemd units that run only the dedicated worker and write only its lock path.
- [ ] Document start, stop, dry-run, watermark and budget behavior.
- [ ] Run operation-asset tests and `systemd-analyze verify` in a temporary unit directory, then commit.

### Task 6: Deploy and prove staging materialization-to-enrichment

**Files:**
- Create: `docs/reports/2026-09-13-winner-enrichment-staging.md`

- [ ] Merge the verified branch through the repository GitHub workflow and deploy the resulting `main` SHA to staging.
- [ ] Set the staging activation watermark to the current UTC instant and start the hourly worker timer.
- [ ] Materialize one isolated active-account signal and record its signal key/SIREN without secrets.
- [ ] Trigger or await the worker, then query the job, `supplier_directory`, and append-only model-call rows.
- [ ] Record elapsed time, cost, model, tokens, and a staging screenshot; assert elapsed time is under one hour and no send audit was created.

### Task 7: Measure 65 remaining suppliers and project the held backfill

**Files:**
- Create: `docs/reports/2026-09-13-enrichment-arbitration-and-backfill.md`

- [ ] Deploy the same green `main` SHA to production without enabling the winner backfill.
- [ ] Run the exact remaining-65 cohort under the serialized replay and existing 3/4 USD temporary caps.
- [ ] Query distinct judge decisions, arbitration reasons, actual arbitration rate and actual model costs; require arbitration below 30 % or stop and report the cases.
- [ ] Recompute low/central/high OpenRouter cost for the frozen 590 known-SIREN recent holders, including the observed reservation/actual ratio.
- [ ] Publish the report and wait for Rodrigue's go; do not invoke the explicit backfill path.

### Task 8: Final verification

**Files:**
- Modify: `docs/reports/2026-09-13-enrichment-arbitration-and-backfill.md`

- [ ] Run all focused backend tests, Ruff, migration-head verification, systemd asset verification and `git diff --check`.
- [ ] Confirm production and staging SHA, timer states, caps, worker watermark and zero held-backfill consumption.
- [ ] Capture the production Système budget panel and staging enriched-holder evidence with Playwright.
- [ ] Commit reports and publish the exact 590-holder cost, leaving backfill stopped.
