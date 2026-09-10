# Pytest Fast Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the default local suite below eight minutes without changing CI coverage.

**Architecture:** Pytest runs the fast suite through xdist locally. Full benchmarks and an explicit allowlist of exhaustive migration modules carry the `slow` marker; the existing four-way CI shard helper clears local addopts and therefore still collects and runs every test. Repeated application fixtures copy a worker-local, session-scoped SQLite database already migrated to HEAD, preserving per-test isolation without replaying the full Alembic chain.

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
- [x] Mark full benchmark modules and an exact allowlist of exhaustive migration modules as slow at collection.
- [x] Clear local addopts in both CI shard pytest invocations.
- [x] Execute collection-level contract tests proving default exclusion, CI inclusion, archive exclusion, and deterministic four-way coverage.

### Task 3: Fast benchmark coverage and measurements

**Files:** `tests/test_benchmark_smoke.py`, `tests/conftest.py`, selected application test modules

- [x] Keep one bounded production-path smoke for Winner-100, Contract-100 and Document-100.
- [x] Resolve a real Luxembourg winner through `CompanyResolver` and recorded offline VIES.
- [x] Validate a real award/event and run `ContractUnderstandingEngine`.
- [x] Build `TenderDocument` objects for a real record and call `coverage_for`.
- [x] Create one migrated SQLite template per worker session and copy it per test.
- [x] Prove the template reaches HEAD, is session scoped, and copied databases do not leak writes.
- [x] Adopt the copy fixture in ten high-frequency application modules that require only a clean HEAD schema.
- [x] Leave migration-transition and PostgreSQL-specific paths unchanged.
- [ ] Run the default suite with `--durations=30` and record wall time.
- [x] Run collection including slow tests and verify CI still sees the complete suite.

### Verification evidence

- Default collection: 5,554 selected / 5,893 total; 339 slow tests deselected.
- CI-style collection (`-o addopts=`): 5,893 tests collected.
- Targeted configuration, benchmark-smoke, and template tests: 12 passed.
- Adopted-fixture regression batches: 311 passed / 1 skipped, then 150 passed.
- Timing report remains intentionally pending until the separate uncontended baseline finishes. Record both `--durations=30` outputs and wall times here; do not compare runs made under CPU contention.
