# DECP Bounded Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every DECP systemd invocation converge durably in small units, finish inside its runtime budget, and leave no stale `running` ingestion rows.

**Architecture:** Keep the existing ingestion tables and idempotent publication pipeline. Add a DECP-specific daily-window planner whose versioned cursor lives in `ingestion_checkpoint.cursor`; version 2 also stores a stable daily total and intra-day offset after every bounded batch. The daily quota keeps its historical meaning, while the application deadline can stop safely between batches. Reconcile stale runs before each source start, and convert SIGTERM into a persisted terminal result.

**Tech Stack:** Python 3.12, SQLAlchemy, pytest, systemd service/timer, existing DECP connector and ingestion pipeline.

---

### Task 1: Specify daily cursor planning and stale-run reconciliation

**Files:**
- Create: `src/signals/ingestion/convergence.py`
- Modify: `src/signals/ingestion/state.py`
- Modify: `tests/test_ingestion_state.py`
- Create: `tests/test_ingestion_convergence.py`

- [x] Write failing tests for a versioned DECP cursor containing a fixed cycle end and next daily window, resumption from that next day, non-regression of the high-water `window_end`, cycle completion, and a new overlap cycle.
- [x] Write failing SQLite tests that terminalize stale `running` rows with `finished_at`, `status=failed`, and the machine category `stale_run_reconciled`, while retaining completed runs and all business rows.
- [x] Implement immutable planner/cursor helpers and one set-based reconciliation function; no migration and no new table.
- [x] Run the two focused test files RED then GREEN.

### Task 2: Persist progress after each complete DECP unit

**Files:**
- Modify: `src/signals/connectors/decp/client.py`
- Modify: `src/signals/ingestion/runner.py`
- Modify: `src/signals/ingestion/sources.py`
- Modify: `tests/test_decp_client.py`
- Modify: `tests/test_ingestion_runner.py`
- Modify: `tests/test_ingestion_sources.py`

- [x] Write failing tests proving two daily units persist independently, checkpoint advances after each unit, a failure on the next unit retains earlier progress, replay remains idempotent, and a max-window quota returns exit code 0 with work still pending.
- [x] Write a failing fake-clock test for a bounded application deadline and a termination exception categorized `terminated`; assert the run row never remains `running`.
- [x] Implement a DECP runner path which processes one calendar day at a time in batches of at most one provider page, accumulates counters, saves the versioned cursor after every persisted batch, and stops successfully between batches at the configured deadline.
- [x] Keep `KIVOU_DECP_MAX_WINDOWS_PER_RUN` as a quota of completed calendar days; several batches from the same day consume one daily window only.
- [x] Preserve `--max-records` as a strict per-pass limit and shrink the final batch to the remaining capacity.
- [x] Reset a changed daily total to offset zero for an idempotent replay; fail closed if the offset is malformed or the day mutates during a batch.
- [x] Finish a safely acquired bounded batch before observing a deadline or SIGTERM, then persist the resulting offset before terminalizing.
- [x] Reconcile stale rows in the same transaction immediately before `start_run`.

### Task 3: Configure the bounded runtime and SIGTERM handling

**Files:**
- Modify: `src/signals/ingestion/cli.py`
- Modify: `.env.example`
- Create: `ops/systemd/kivou-ingest-decp.service`
- Create: `ops/systemd/kivou-ingest-decp.timer`
- Create: `tests/test_ops_ingestion_runtime.py`
- Modify: `tests/test_ingestion_cli.py`
- Modify: `ops/README.md`

- [x] Write failing tests for positive `KIVOU_DECP_MAX_WINDOWS_PER_RUN`, bounded `KIVOU_DECP_BATCH_SIZE`, `KIVOU_DECP_TIME_BUDGET_SECONDS`, `KIVOU_DECP_OVERLAP_DAYS`, and `KIVOU_INGESTION_STALE_RUN_SECONDS`, plus CLI overrides.
- [x] Write a failing CLI test that invokes the registered SIGTERM handler and proves the runner receives a terminal cancellation without a traceback or orphan row.
- [x] Implement defaults shorter than the unit timeout, install the signal handler only for the run command, and restore the previous handler on exit.
- [x] Version one oneshot service using `/srv/kivou/app`, `/etc/kivou/staging.env`, the `kivou` user, host `flock`, `RuntimeDirectory`, and a timer with `Persistent=true`; make lock contention a clean exit.
- [x] Test unit command, timeout ordering, lock path, timer persistence, and environment loading; document installation, manual run, cursor proof, and rollback.

### Task 4: Verify and deliver #77

**Files:**
- All files above only.

- [x] Re-run the full targeted DECP/ingestion matrix after intra-day hardening: 173 tests passed; Ruff, `systemd-analyze verify` on both units, and `git diff --check` passed.
- [ ] Commit, review twice, push, open a PR with `Closes #77` and `Refs #80`, then run standard CI once on final HEAD.
- [ ] Squash-merge, verify exact main CI, deploy the merged SHA without production changes, install/enable the versioned units, and let the application reconcile the ten stale rows.
- [ ] Prove two consecutive automatic passes finish inside the budget, cursor advances each time, new materializations are idempotent, no new orphan remains, and the timer is enabled/persistent.
