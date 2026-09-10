# Pytest Fast Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the default local suite below eight minutes without changing CI coverage.

**Architecture:** Pytest runs the fast suite through xdist locally and uses a dedicated Linux tmpfs run root only when at least 4 GiB are free; the controller removes it, including read-only test artifacts, at session end. Full benchmarks, an explicit allowlist of exhaustive migration modules, and exhaustive transitions embedded in mixed modules carry the `slow` marker; the existing four-way CI shard helper clears local addopts and therefore still collects and runs every test. Repeated application fixtures copy one run-shared, session-scoped SQLite database already migrated to HEAD, preserving per-test isolation without replaying the full Alembic chain. CI and operator-selected temporary roots are not overridden.

**Tech Stack:** pytest, pytest-xdist, Bash, GitHub Actions.

---

### Task 1: Deterministic parallel collection

**Files:** `tests/test_acquisition_state.py`

- [x] Reproduce the worker collection mismatch.
- [x] Sort the set-backed transition parameters.
- [x] Verify collection across 12 workers.

### Task 2: Fast local defaults, unchanged CI

**Files:** `pyproject.toml`, `uv.lock`, `ops/bin/kivou-pytest-shard.sh`, `tests/conftest.py`, `tests/test_pytest_configuration.py`

- [x] Add failing configuration contract tests.
- [x] Add pytest-xdist and local `-n auto -m "not slow"` defaults.
- [x] Mark full benchmark modules, an exact allowlist of exhaustive migration modules, and exhaustive transitions in mixed modules as slow.
- [x] Clear local addopts in both CI shard pytest invocations.
- [x] Execute collection-level contract tests proving default exclusion, CI inclusion, archive exclusion, and deterministic four-way coverage.

### Task 3: Fast benchmark coverage and measurements

**Files:** `tests/test_benchmark_smoke.py`, `tests/conftest.py`, selected application test modules

- [x] Keep one bounded production-path smoke for Winner-100, Contract-100 and Document-100.
- [x] Resolve a real Luxembourg winner through `CompanyResolver` and recorded offline VIES.
- [x] Validate a real award/event and run `ContractUnderstandingEngine`.
- [x] Build `TenderDocument` objects for a real record and call `coverage_for`.
- [x] Create one migrated SQLite template shared by every worker in the test session and copy it per test.
- [x] Prove the template reaches HEAD, is session scoped, and copied databases do not leak writes.
- [x] Adopt the copy fixture in ten high-frequency application modules that require only a clean HEAD schema.
- [x] Leave migration-transition and PostgreSQL-specific paths unchanged.
- [x] Run the default suite with `--durations=30` and record wall time.
- [x] Run collection including slow tests and verify CI still sees the complete suite.

### Verification evidence

- Default collection: 5,550 selected / 5,900 total; 350 slow tests deselected.
- CI-style collection (`-o addopts=`): 5,900 tests collected.
- Targeted configuration, benchmark-smoke, template, and shard tests: 18 passed.
- Adopted-fixture regression batches: 311 passed / 1 skipped, then 150 passed.
- Serial baseline: stopped after 61m26 at 29% (`real 3686.75`); the observed
  rate projected a complete run around 3h32.
- First parallel run on disk: still running at the 10-minute timeout.
- Final local fast suite with guarded, self-cleaning Linux tmpfs: 5,525 passed,
  24 skipped, 1 xfailed in 4m33.65 (`real 279.85`), under the eight-minute target;
  `/dev/shm` returned to 0 bytes used by the run.
