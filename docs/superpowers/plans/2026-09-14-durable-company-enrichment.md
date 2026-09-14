# Durable company enrichment implementation plan

> **For agentic workers:** Execute the approved component in this session, with focused regression tests before each implementation. Git integration belongs to the coordinating agent.

**Goal:** An explicit paid click durably enriches an exact French company, including an existing incomplete directory profile, with truthful progress and results.

**Architecture:** A shared SIREN queue persists generation, claim lease, retries and outcome independently of recent winner signals. A requests-only mode of the existing winner worker uses the same provider factory, model budgets and instance lock; its dedicated timer checks once a minute. Dossier GETs only read this queue and existing public data.

**Tech Stack:** SQLAlchemy Core, Alembic, FastAPI, React, systemd, pytest and Vitest.

**Approved implementation details:** admission uses the existing append-only
`product_event` ledger (job ID and public SIREN only), with five concurrent jobs
per initiating account and a global limit of 100. PostgreSQL admission holds a
transactional advisory mutex; SQLite starts its write transaction before counting.
No commercial quota or table column is added for this limit. The API capability
and POST remain closed unless `KIVOU_COMPANY_DIRECTORY_ENRICHMENT_ENABLED=true`;
the coordinating deployment step enables it only after verifying the worker.

## 1. Queue and migration

- [x] Add offline regression cases in `tests/test_company_enrichment_requests.py`: existing directory is available, exact request deduplicates, paid-only API, stale and missing data enqueue, completed data reused, cooldown, no contact-ledger write, lease recovery and three-attempt bound.
- [x] Run `.venv/bin/pytest tests/test_company_enrichment_requests.py -q` and record the missing-behavior failure.
- [x] Add `company_directory_enrichment_job` to `src/signals/companies/schema.py` and migration `0062_company_enrichment_requests`, based on `0061_company_live_merge`. The SIREN primary key deliberately has no directory FK, allowing enrichment before a directory exists.
- [x] Implement `request_enrichment(connection, siren, now)` and `enrichment_view(connection, siren, now)` in `src/signals/company_research/company_requests.py`. The response contains state, job ID, timestamps, retry time, missing/stale/added fields, outcome, and can_refresh. Requests use a new generation only after terminal cooldown; fresh complete data uses the stored result.

## 2. Worker and public-data preservation

- [x] Add offline cases for persisted enriched/no_change outcomes, provider failure, exhausted budget, suppression during the request, preserved known public values, and unchanged Apollo identity/cache.
- [x] Implement `run_company_enrichment_requests(engine, now, worker_ref, identity_source, enrichment_service, limit, clock)`: claim in a short transaction, resolve the exact registry identity, call the existing service outside the transaction and finish only with a persisted unsuppressed directory observation. Claim token and generation guard stale completion; expired claims retry up to three times. Production injects the actual clock for each claim/completion; the 30-minute lease covers the service's 20-minute runtime bound.
- [x] Budget exhaustion becomes `budget_wait` until the next Europe/Zurich day and stops the batch. No quota ledger is changed, no costs or models are configured here.
- [x] Modify `SupplierDirectoryStore.record_model_enrichment` to preserve already known public values when a pass finds nothing. Preserve Apollo organization binding when the confirmed domain is unchanged; retain existing invalidation when it changes. Manual registry refresh preserves missing optional identity fields and old confirmed family; invalid phone results cannot erase a usable number. Previously proven published email retains its original proof and observation time.
- [x] Add `--requests-only` to `src/signals/company_research/winner_worker.py`. It does not require the automatic winner activation watermark and never selects automatic winner jobs. Both modes keep the same factory and file lock.
- [x] Add staging/production `kivou-company-enrichment.service` and `.timer`, with a 60-second timer, bounded batch and the same hardened runtime. Cover the command and timer in `tests/test_ops_company_enrichment_runtime.py`.

## 3. API and interface

- [x] Add the closed `CompanyDirectoryEnrichmentView` contract and optional `directory_enrichment` fields to both dossier variants in `src/signals/companies/contracts.py`.
- [x] Replace only the directory-enrichment POST in `src/signals/api/routes_companies.py`; derive exact SIREN from the authorized subject and return the durable view. Add read projections to dossier GETs, without provider calls.
- [x] Update frontend API contracts and endpoint typing. Add hook regressions: an existing directory with a queued job stays pending; reopen resumes GET polling only; bounded polling preserves server queued/budget_wait state; partial/no_change never claims new data.
- [x] Update `frontend/src/prospecting/useCompanyEnrichment.ts` to read durable state, preserve existing contact data, and resume an initial active job on reopen. Add `CompanyEnrichmentStatus.tsx` with truthful queued/running/budget_wait/enriched/no_change/failed copy.
- [x] Coordinate profile and signal rendering with the public-contacts component owner; it passes initialDirectoryEnrichment and renders the status component. The current dossier consumes fetched snapshots in place; global invalidation waits until close, preserving a private contact draft during public completion.

## 4. Verification

- [x] Run queue, worker, provider/store, API and runtime focused pytest files. Run enrichment Vitest and frontend typecheck. No external provider is used in these checks.
- [x] Run Ruff on changed Python files and `git diff --check`; review migration lifecycle constraints and API permission boundaries.
- [x] Report exact evidence, deployment integration requirements and any remaining blocker to the coordinating agent. No staging/commit/deploy from this component agent.

### Review corrections and evidence (2026-09-14)

Offline regressions first reproduced stale fields falsely becoming ready, real
observations occurring after the batch-start clock, changed existing phone being
called no_change, and public completion destroying a private contact draft.
Those regressions pass after the focused corrections. Readiness now requires
fresh individual website/phone/email evidence; preserving old facts does not
refresh their clocks. `enriched` covers added or changed values, while
`added_fields` contains only newly present fields.
An additional RED→GREEN cache regression covers a partial job followed by a
fresh complete winner/mirror result: POST reuses that result, without enqueueing
another provider pass.

Focused backend command: queue requests, preservation, company enrichment,
routing, winner company worker, SaaS architecture, dossier fallback and both
manual/automatic runtime modules: **87 passed, 1 inherited xfail**. Frontend
enrichment, company-dossier and signal-detail-regression modules: **30 passed**.
Typecheck and ESLint passed. Independent spec and quality review run through
the coordinating agents; final integration and deployment remain with root.
After the cache correction, requests/preservation/manual-runtime were rerun:
**34 passed**. Independent spec re-read accepted the four review corrections.

Operational boundaries: enable the API flag only after installing/verifying the
manual service and its existing provider environment. The shared automatic lock
can delay a queued manual job; budget exhaustion waits for the next configured
budget day. Neither delay is reported as completion. The timer does not activate
automatic winner processing, change budgets, buy credits or reserve contact
lookup quota. Migration 0062 deliberately refuses downgrade to preserve requests;
rollback restores the previous application artifact without downgrading data.
