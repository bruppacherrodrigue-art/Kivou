# SPEC-016A Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Materialize existing persisted opportunities for a newly active TargetICP through the approved engines, within the accepted 500-opportunity synchronous bound.

**Architecture:** A database-only backfill service selects at most 500 recent stable opportunities, chooses one deterministic customer-nameable representation per opportunity, and delegates all eligibility to the existing `MatchingEngine`. API create/update commits the TargetICP first, then invokes the service. Existing persistence identity and feed boundaries remain authoritative.

**Tech Stack:** Python 3.12, SQLAlchemy Core, FastAPI, pytest, Alembic, existing Kivou domain engines.

---

### Task 1: Persisted canonical record reader

**Files:**
- Create: `src/signals/ingestion/persisted.py`
- Modify: `src/signals/ingestion/france.py`
- Test: `tests/test_ingestion_backfill.py`

- [ ] Write a failing test that persists a frozen real award and requests its canonical event/award through the new persisted reader.
- [ ] Run `uv run pytest -q tests/test_ingestion_backfill.py` and verify the missing reader causes the expected failure.
- [ ] Move the existing `_canonical_event()` and `_canonical_award()` reconstruction logic from `france.py` into public `canonical_event(row)` and `canonical_award(row, event)` functions. Keep every stored clock and normalized field unchanged.
- [ ] Update `FranceLinker` to use the shared reader and run the focused tests green.

### Task 2: Bounded backfill service

**Files:**
- Create: `src/signals/ingestion/backfill.py`
- Modify: `src/signals/feed/query.py`
- Test: `tests/test_ingestion_backfill.py`

- [ ] Write failing tests for facts-first/customer-second materialization, draft exclusion, repeat idempotence, 501-candidate truncation, and deterministic linked-representation selection.
- [ ] Run the focused tests and verify each failure is caused by the absent service.
- [ ] Expose the existing feed name-validity predicate without changing its rules.
- [ ] Implement `BackfillResult(candidates_available, candidates_evaluated, signals_materialized, truncated)` and `materialize_existing_opportunities_for_target()`.
- [ ] Load exactly one active TargetICP; drafts return zero work. Derive the SQL publication floor from that profile's existing `maximum_signal_age_days`; do not introduce another eligibility rule.
- [ ] Select 501 stable opportunity keys ordered by newest publication then key, retain 500, and query their representations. Choose a named representation first and then `award_key`, deterministically.
- [ ] Run existing Understanding, Need Graph, Matching and recency code. Persist only existing `match.decision == "show"` results with `materialize_signal()` in bounded per-signal transactions.
- [ ] Log an operator-visible warning when `truncated` is true and rerun focused tests green.

### Task 3: Post-commit API activation hook

**Files:**
- Modify: `src/signals/api/routes_icp.py`
- Test: `tests/test_ingestion_backfill.py`

- [ ] Write failing API tests proving active creation and draft-to-active update invoke backfill only after their profile transaction commits, while draft creation does not.
- [ ] Run the focused tests red.
- [ ] Invoke the backfill service after each successful API transaction only when the resulting status is `active`; pass the request's explicit time as both `as_of` and materialization time.
- [ ] Run the focused tests green and verify the feed returns the actual materialized signal.

### Task 4: Safe terminal skip versus processing failure

**Files:**
- Modify: `src/signals/connectors/boamp/errors.py`
- Modify: `src/signals/connectors/boamp/__init__.py`
- Modify: `src/signals/ingestion/sources.py`
- Test: `tests/test_ingestion_sources.py`
- Test: `tests/test_ingestion_runner.py`

- [ ] Write failing tests proving a recognized non-eForms BOAMP payload increments `rejected` and allows checkpoint advancement.
- [ ] Write a failing test proving empty, unparseable, or structurally broken eForms data is a typed `malformed` processing failure and retains the previous checkpoint.
- [ ] Add the minimal typed malformed BOAMP error and classify payloads before normalization. Do not change `parse_award_notice()` semantics.
- [ ] Run focused source/runner tests green.

### Task 5: Performance measurement and report contract

**Files:**
- Modify: `docs/reports/2026-08-19-spec016a-production-ingestion-runtime.md`

- [ ] Seed a deterministic isolated SQLite database with data near the 500-candidate bound and time one real backfill using `/usr/bin/time` or `time.perf_counter()`.
- [ ] Record candidate, evaluated, materialized and elapsed wall-clock values. If unsuitable for synchronous HTTP onboarding, stop with `SYNCHRONOUS BACKFILL LATENCY BLOCKER`.
- [ ] Replace planned closeout wording with implemented behavior and test evidence.
- [ ] Add exact bounded bootstrap commands using existing `--since`, checkpoint behavior, possible rerun guidance, and `HISTORY COVERAGE LAUNCH LIMITATION`.
- [ ] Replace the all-source timer contract with source-specific commands, cadences, timeouts, distinct lock files, clean lock-collision semantics and exit behavior. Do not create `ops/` files.

### Task 6: Full verification, Git and CI

**Files:**
- Modify: `docs/reports/2026-08-19-spec016a-production-ingestion-runtime.md`

- [ ] Run `uv run pytest -q`, confirm at least 2740 passed and zero skipped.
- [ ] Run `uv run ruff check .` and `git diff --check`.
- [ ] Run `npm test -- --run`, `npm run build`, `npx tsc -b`, and `npm run lint` from `frontend`; confirm 84 frontend tests.
- [ ] Scan the explicit closeout diff for secrets and confirm no `ops/` or unrelated file changed.
- [ ] Update the report with final counts, changed files and a provisional non-READY verdict until CI completes.
- [ ] Stage only explicit SPEC-016A closeout files, commit, and push normally to PR #7 without force.
- [ ] Wait for GitHub Actions backend and frontend completion, record run ID and head SHA, update the report, commit/push the final CI evidence, and wait for the resulting report-only CI run.
- [ ] End the final report with exactly one permitted production-ingestion verdict. Do not merge or deploy.
