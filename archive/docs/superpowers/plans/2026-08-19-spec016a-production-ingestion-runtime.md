# SPEC-016A Production Ingestion Runtime — Implementation Plan

> Implement test-first on `feat/spec016a-ingestion-runtime`, based on `origin/main`.
> Keep `ops/`, the VPS, alerts, billing policy, frontend behavior, and engine policy untouched.

## Task 1: Add the narrow ingestion schema

**Files:**
- Modify: `src/signals/persistence/schema.py`
- Modify: `src/signals/persistence/migrations/env.py`
- Create: `src/signals/persistence/migrations/versions/0005_ingestion_runtime_ingestion_runtime.py`
- Create: `tests/test_ingestion_migration.py`

Write failing tests for migration lineage, additive upgrade from `0004`, schema parity,
constraints, and PostgreSQL DDL compilation. Add `ingestion_checkpoint` and `ingestion_run`
only, then make the focused tests pass.

## Task 2: Add durable state and audit repositories

**Files:**
- Create: `src/signals/ingestion/state.py`
- Create: `src/signals/ingestion/model.py`
- Create: `tests/test_ingestion_state.py`

Test checkpoint creation, run start/finalization, safe success advancement, failure retention,
counter persistence, and restart reads. Implement SQLAlchemy Core services with explicit caller
transactions and sanitized error fields.

## Task 3: Separate fact persistence from customer matching

**Files:**
- Modify: `src/signals/persistence/materialization.py`
- Modify: `src/signals/persistence/__init__.py`
- Create: `tests/test_ingestion_fact_persistence.py`

Test that event, award, evidence-independent opportunity representation, and stable opportunity
identity persist without any TargetICP. Extract a public `persist_award_facts()` from the current
materialization steps and make `materialize_signal()` reuse it without semantic changes.

## Task 4: Add operational source failures and DECP client

**Files:**
- Create: `src/signals/connectors/boamp/errors.py`
- Modify: `src/signals/connectors/boamp/client.py`
- Modify: `src/signals/connectors/boamp/__init__.py`
- Create: `src/signals/connectors/decp/client.py`
- Create: `src/signals/connectors/decp/errors.py`
- Modify: `src/signals/connectors/decp/__init__.py`
- Create: `tests/test_boamp_client.py`
- Create: `tests/test_decp_client.py`

Write offline `httpx.MockTransport` tests for pagination, date windows, timeouts, rate limits,
server/client/network/malformed failures, and maximum-record bounds. Preserve parser inputs and
outputs exactly.

## Task 5: Implement source acquisition adapters

**Files:**
- Create: `src/signals/ingestion/sources.py`
- Create: `tests/test_ingestion_sources.py`

Define one small acquisition protocol and four adapters that call existing clients and existing
normalizers. Test dispatch, source-specific window/overlap behavior, bounded completeness,
finite request behavior, typed failure propagation, and every source path entirely offline.

## Task 6: Compose the approved engine for active ICPs

**Files:**
- Create: `src/signals/ingestion/pipeline.py`
- Create: `tests/test_ingestion_pipeline.py`

Test active ICP loading/conversion, draft exclusion, fact persistence with zero matches, and
materialization only when `MatchingEngine.match(...).decision == "show"`. Invoke the existing
understanding, Need Graph, matching, recency, and `materialize_signal()` APIs directly; do not
copy their policies.

## Task 7: Reuse France strong linkage across runs

**Files:**
- Create: `src/signals/ingestion/france.py`
- Extend: `tests/test_ingestion_pipeline.py`

Write late-arrival and already-separated conflict tests first. Reconstruct only the canonical
BOAMP/DECP facts required to call unchanged `resolve_candidates()` and `unique_strong()`. Pass
strong siblings to existing opportunity persistence. Record conflicts and retain separate
opportunities when `OpportunityConflict` is raised.

## Task 8: Add source-isolated orchestration and CLI

**Files:**
- Create: `src/signals/ingestion/runner.py`
- Create: `src/signals/ingestion/cli.py`
- Create: `src/signals/ingestion/__init__.py`
- Create: `src/signals/ingestion/__main__.py`
- Create: `tests/test_ingestion_runner.py`
- Create: `tests/test_ingestion_cli.py`

Test all-source continuation after TED rate limiting, no false TED checkpoint advancement,
restart/resume, non-zero partial-failure exit, dry-run no writes, structured concise summaries,
and no alert import/call. Implement `python -m signals.ingestion run` with `--source`, `--since`,
`--until`, `--max-records`, and `--dry-run`.

## Task 9: Prove the customer-facing E2E path

**Files:**
- Create: `tests/test_ingestion_e2e.py`

Using an existing frozen public-award fixture, test source-like input through normalization,
fact persistence, linkage, approved engines, active TargetICP, materialized signal, and existing
feed query. Repeat the same ingestion twice and assert stable event, award, opportunity, signal,
and feed counts. Assert draft ICP exclusion and customer-name safety.

## Task 10: Document operations and run bounded live smoke

**Files:**
- Create: `docs/reports/2026-08-19-spec016a-production-ingestion-runtime.md`

Document architecture, exact CLI contract, required `KIVOU_DATABASE_URL`, per-source overlap,
retry/rate-limit handling, recommended cadence, systemd/flock contract, migration revision,
transaction boundaries, tests, and Git state. Run each live source with a small window and low
limit in dry-run or an isolated migrated local database; record truthful outcomes without making
network a CI dependency.

## Task 11: Full verification and draft PR

Run:

```bash
uv run pytest -q
uv run ruff check .
git diff --check
cd frontend
npm test -- --run
npm run build
npx tsc -b
npm run lint
```

Confirm at least 2700 backend tests are collected and at least 84 frontend tests pass. Scan only
newly tracked changes for credentials and private keys. Explicitly stage SPEC-016A files, commit
as `feat(data): add production ingestion runtime`, push normally, open a draft PR to `main`, and
wait for backend and frontend CI. Do not merge or deploy.
