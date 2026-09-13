# For You Prospection Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make unknown model fit eligible, prioritize valuable For You work, and replace the daily call cap with the existing cost budget.

**Architecture:** Keep acquisition selection deterministic, add a focused For You queue-maintenance/priority boundary, and pass the active acquisition scope into the worker from deployed configuration. Preserve completed history and bound each invocation without a daily attempt counter.

**Tech Stack:** Python 3.12, SQLAlchemy, PostgreSQL/SQLite, pytest, systemd, React Founder Console, Playwright.

---

### Task 1: Acquisition fit semantics

**Files:**
- Modify: `src/signals/acquisition_runtime/selection.py`
- Test: `tests/test_acquisition_runtime_selection.py`

- [ ] Add tests proving `model_fit=NULL` and a missing For You row are eligible while `none` is excluded.
- [ ] Run the tests and confirm the new cases fail for the fit gate.
- [ ] Change the join/filter so only explicit `none` excludes.
- [ ] Run the focused selection tests and commit.

### Task 2: Queue retention and priority

**Files:**
- Create: `src/signals/personalization/for_you_queue.py`
- Modify: `src/signals/personalization/for_you_worker.py`
- Test: `tests/test_for_you_worker.py`

- [ ] Add tests for prospecting-scope priority, active recent priority, stable fallback ordering, and dry/apply purge reports.
- [ ] Run the focused cases and confirm they fail before implementation.
- [ ] Implement decision-date retention, active-profile checks, deterministic priority and pending/expired-running cleanup.
- [ ] Run the focused worker tests and commit.

### Task 3: Cost-only daily gate

**Files:**
- Modify: `src/signals/personalization/for_you_worker.py`
- Modify: `src/signals/personalization/for_you_backfill.py`
- Modify: `ops/systemd/production/kivou-for-you.service`
- Test: `tests/test_for_you_worker.py`
- Test: `tests/test_for_you_backfill.py`
- Test: `tests/test_ops_production_runtime.py`

- [ ] Replace daily-attempt tests with per-run batch tests and preserved budget-exhaustion behavior.
- [ ] Confirm the new tests fail against the daily counter.
- [ ] Remove `attempt_day` from claim capacity, add the per-run batch limit, and load the acquisition runtime configuration in the service.
- [ ] Run worker, backfill and unit tests and commit.

### Task 4: Integration and production proof

**Files:**
- Modify: `docs/superpowers/plans/2026-09-13-for-you-prospection-priority.md`

- [ ] Run Ruff and the complete relevant backend suites.
- [ ] Push a PR, wait for every CI job, squash to `main`, and deploy the exact merge SHA.
- [ ] Run queue maintenance dry, record counts, apply it, and record counts after.
- [ ] Verify five acquisition opportunities are eligible and that the For You timer is healthy under its cost budget.
- [ ] Click “Préparer la file du jour”, verify no automatic send, and capture the five prepared targets.
