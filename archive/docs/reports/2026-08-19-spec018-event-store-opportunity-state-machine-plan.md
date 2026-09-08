# SPEC-018 Event Store + Acquisition Opportunity State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Kivou-owned append-only acquisition events and a durable, replayable Acquisition Opportunity projection without executing any acquisition action.

**Architecture:** A focused `signals.acquisition` package owns strict contracts, versioned pure reducers, transactional SQLAlchemy Core persistence, and an opportunity-scoped SupervisorPlan audit mapper. One additive migration creates `acquisition_opportunity` and `acquisition_event` after `0006_award_text_capacity`; no Hermes runtime, Event Bus, Policy Gateway, worker, or external service is introduced.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy Core, Alembic, PostgreSQL-compatible DDL, SQLite deterministic tests, pytest, Ruff.

---

### Task 1: Strict acquisition contracts and payload guards

**Files:**
- Create: `src/signals/acquisition/contracts.py`
- Create: `src/signals/acquisition/__init__.py`
- Create: `tests/test_acquisition_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Define wished-for tests importing `AcquisitionEvent`, `AcquisitionOpportunity`, `AcquisitionState`, `ActorType`, `Decision`, `EventType`, `STATE_MACHINE_VERSION`, and the typed errors. Assert timezone-aware dates, `confidence` in `[0, 1]`, non-negative `estimated_cost`, reason/evidence bounds, 65,536-byte JSON payload bounds, recursive secret-key rejection, recursive hidden-reasoning rejection, finite JSON, and immutable models.

```python
with pytest.raises(ValueError, match="confidence"):
    event_input(confidence=Decimal("1.01"))
with pytest.raises(ValueError, match="prohibited payload key"):
    event_input(payload={"nested": {"access_token": "value"}})
with pytest.raises(ValueError, match="hidden reasoning"):
    event_input(payload={"chain_of_thought": "private"})
```

- [ ] **Step 2: Verify RED**

Run `uv run pytest -q tests/test_acquisition_contracts.py` and confirm collection fails because `signals.acquisition` does not exist.

- [ ] **Step 3: Implement minimal strict contracts**

Use frozen Pydantic models with `extra="forbid"`, `Decimal`, aware datetime validators, and these constants:

```python
STATE_MACHINE_VERSION = "acquisition-state-v1"
MAX_EVENT_PAYLOAD_BYTES = 65_536
MAX_REASON_CODES = 50
MAX_EVIDENCE_REFS = 100
```

Define typed failures including `InvalidTransition`, `IdempotencyConflict`, `AcquisitionIdentityConflict`, `OpportunityConcurrencyConflict`, `UnsupportedStateMachineVersion`, `SupervisorAuditMappingError`, and `ProjectionNotFound`.

- [ ] **Step 4: Verify GREEN**

Run `uv run pytest -q tests/test_acquisition_contracts.py` and require all tests to pass.

### Task 2: Versioned pure reducer and replay

**Files:**
- Create: `src/signals/acquisition/state.py`
- Create: `tests/test_acquisition_state.py`

- [ ] **Step 1: Write failing state-machine tests**

Cover the approved pre-send transition matrix, decision-to-state mapping, HOLD requirements, NO_SEND/CHURNED terminal behavior, monotonic post-send outcomes, late lower-stage audit without regression, contiguous sequence enforcement, persisted `state_machine_version`, and unknown-version rejection.

```python
projection = replay((created_event(), sent_event(sequence=2), activated_event(sequence=3)))
assert projection.state == AcquisitionState.ACTIVATED
late = reduce_event(projection, replied_event(sequence=4))
assert late.state == AcquisitionState.ACTIVATED
with pytest.raises(UnsupportedStateMachineVersion):
    replay((created_event(state_machine_version="unknown"),))
```

- [ ] **Step 2: Verify RED**

Run `uv run pytest -q tests/test_acquisition_state.py` and confirm missing reducer functions fail collection.

- [ ] **Step 3: Implement reducer registry**

Create `REDUCERS = {"acquisition-state-v1": _reduce_v1}`. `reduce_event()` selects by the event's persisted version; `replay()` validates opportunity identity and exact `1..N` sequence. Reducer functions perform no I/O, clock, ID generation, randomness, or Hermes call.

- [ ] **Step 4: Verify GREEN**

Run `uv run pytest -q tests/test_acquisition_state.py`.

### Task 3: Core schema and linear migration 0007

**Files:**
- Modify: `src/signals/persistence/schema.py`
- Create: `src/signals/persistence/migrations/versions/0007_acquisition_event_store_acquisition_event_store.py`
- Create: `tests/test_acquisition_migration.py`
- Modify: legitimate current-head assertions in existing migration tests

- [ ] **Step 1: Re-verify migration gate**

Load `ScriptDirectory` from current `main` and require one head `0006_award_text_capacity`, no existing `0007`, and every existing revision ID length `<= 32`.

- [ ] **Step 2: Write failing migration tests**

Tests require:

```text
0006_award_text_capacity -> 0007_acquisition_event_store
```

They verify fresh DB -> head, populated `0006` -> `0007`, exactly two additive tables, existing tables preserved, projection indexes, `RESTRICT` FK, unique `(opportunity_id, sequence)`, unique `(opportunity_id, idempotency_key)`, numeric checks, and PostgreSQL DDL compilation.

- [ ] **Step 3: Verify RED**

Run `uv run pytest -q tests/test_acquisition_migration.py`; expect missing revision/table failures.

- [ ] **Step 4: Add Core declarations and migration**

Declare `acquisition_opportunity` and `acquisition_event` in existing `METADATA`, using portable strings/JSON/Numeric/DateTime types and no ORM. Migration revision metadata must be:

```python
revision = "0007_acquisition_event_store"
down_revision = "0006_award_text_capacity"
```

- [ ] **Step 5: Verify GREEN and the whole migration suite**

Run `uv run pytest -q tests/test_acquisition_migration.py tests/test_persistence_migrations.py tests/test_contract_award_text_capacity_migration.py`.

### Task 4: Transactional store, creation idempotency, sequencing and concurrency

**Files:**
- Create: `src/signals/acquisition/store.py`
- Create: `tests/test_acquisition_store.py`

- [ ] **Step 1: Write failing creation/store tests**

Specify `AcquisitionStore(engine, clock=..., opportunity_id_factory=..., event_id_factory=...)`, with `create_opportunity()`, `get_opportunity()`, and `list_events()`. Prove atomic creation, immutable identity, creation-idempotency rules, event sequence `1..N`, scoped event idempotency, cross-opportunity key reuse, same-key semantic conflict, and no event mutation/deletion API.

```python
first = store.create_opportunity(identity_key="signal:s1", signal_ref="s1", idempotency_key="create")
again = store.create_opportunity(identity_key="signal:s1", signal_ref="s1", idempotency_key="create")
assert again.event.event_id == first.event.event_id
with pytest.raises(AcquisitionIdentityConflict):
    store.create_opportunity(identity_key="signal:s1", signal_ref="s1", idempotency_key="other")
```

- [ ] **Step 2: Verify RED**

Run the selected creation/idempotency tests and observe missing store failures.

- [ ] **Step 3: Implement bounded transactions**

Creation looks up immutable `identity_key`, resolves its creation event, fingerprints canonical semantics, and inserts event+projection in one `engine.begin()`. Existing mutations check `(opportunity_id, idempotency_key)` before `expected_version`, reduce purely, conditionally update `WHERE stream_version = expected_version`, insert the event in the same transaction, and raise typed conflicts.

- [ ] **Step 4: Verify GREEN**

Run `uv run pytest -q tests/test_acquisition_store.py -k 'creation or identity or idempotency or concurrency or sequence or atomic'`.

### Task 5: Workflow operations, retry state and restart

**Files:**
- Modify: `src/signals/acquisition/store.py`
- Modify: `tests/test_acquisition_store.py`

- [ ] **Step 1: Write failing operation tests**

Cover `transition_state()`, `record_decision()`, `set_next_action()`, `schedule_retry()`, and `record_outcome()`. HOLD must require reasons and `next_review_at`; `next_action` must be in Kivou's `ALLOWED_COMMANDS`; retry persists count/time/category without stack traces; SEND records a decision but executes nothing.

- [ ] **Step 2: Verify RED**

Run selected workflow tests and confirm missing method failures.

- [ ] **Step 3: Implement validated event append operations**

Each method builds one strict event, delegates to the same atomic append path, and returns a `MutationResult` containing projection, event, and `replayed` status. No operation imports Apollo, Instantly, Stripe, SMTP, shell, Celery, or Redis.

- [ ] **Step 4: Prove restart**

Create events against a file-backed SQLite engine, dispose it, construct a fresh engine/store, reload exact state/version, and append the next sequence.

- [ ] **Step 5: Verify GREEN**

Run all `tests/test_acquisition_store.py` tests.

### Task 6: Verification, explicit rebuild and Shadow plan audit

**Files:**
- Modify: `src/signals/acquisition/store.py`
- Create: `src/signals/acquisition/supervisor_audit.py`
- Create: `tests/test_acquisition_recovery.py`
- Create: `tests/test_acquisition_supervisor_audit.py`

- [ ] **Step 1: Write failing recovery tests**

Require `verify_projection()` to return `MATCH`/`MISMATCH` without mutation. Corrupt projection `state`, `stream_version`, and `next_action` directly in a controlled test transaction, preserve the `RESTRICT` FK and event snapshot, run explicit transactional `rebuild_projection()`, and assert projection equals replay while events remain unchanged.

- [ ] **Step 2: Write failing scoped audit tests**

Build validated SPEC-017 `SupervisorPlan` fixtures. Exact target matches by acquisition ID or unique identity key are stored; actions for other streams are excluded; unknown/ambiguous mappings raise `SupervisorAuditMappingError` with no event; zero selected actions returns `recorded=False` with no stream increment. Stored payload contains safe metadata/command names but no arguments, prompt, transcript, memory, or hidden reasoning. State is unchanged and no executor is invoked.

- [ ] **Step 3: Verify RED**

Run `uv run pytest -q tests/test_acquisition_recovery.py tests/test_acquisition_supervisor_audit.py`.

- [ ] **Step 4: Implement recovery and audit boundary**

Rebuild uses one explicit transaction and the immutable event stream. Supervisor audit imports only `SupervisorPlan` contracts, resolves every target deterministically through the store, and appends a state-neutral event only when selected actions exist.

- [ ] **Step 5: Verify GREEN**

Run both recovery/audit test files and assert Hermes runtime unavailability does not affect store/replay tests.

### Task 7: Replay measurement and complete deterministic regression

**Files:**
- Create: `tests/test_acquisition_replay_performance.py`
- Modify: `docs/reports/2026-08-19-spec018-event-store-opportunity-state-machine.md`

- [ ] **Step 1: Add deterministic 100-event measurement fixture**

Create one opportunity and 99 valid state-neutral/metadata events, then measure with `time.perf_counter()`:

```text
load stream
pure replay
verify projection
```

Assert correctness only, not an invented SLA. Print/record candidate count and timings for the report.

- [ ] **Step 2: Run all acquisition tests**

Run `uv run pytest -q tests/test_acquisition_*.py` and fix only evidence-backed failures through new RED→GREEN cycles.

- [ ] **Step 3: Run full backend and frontend gates**

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

Require backend count `>= 2826`, zero skipped, frontend `>= 84`, and all static/build checks green.

### Task 8: Final report and CI-tested draft PR

**Files:**
- Create: `docs/reports/2026-08-19-spec018-event-store-opportunity-state-machine.md`

- [ ] **Step 1: Finalize completed evidence**

Document terminology, schemas, explicit `state_machine_version`, scoped/creation idempotency, transition/outcome rules, retry/next action, atomicity, replay/verify/rebuild, scoped Shadow-plan audit, payload guards, migration `0007`, restart/concurrency/idempotency results, 100-event measurement, tests, diff/stat/status, and no side effects.

- [ ] **Step 2: Mirror reports to the canonical WSL path**

Ensure final design, plan, and report are present under `/home/jaybe/projects/Kivou/docs/reports/` without modifying code in Claude's worktree.

- [ ] **Step 3: Stage explicitly, commit and publish**

Stage only SPEC-018 paths; never `git add .`. Commit with:

```text
feat(acquisition): add event store and opportunity state machine
```

Push `feat/spec018-acquisition-event-store`, open a draft PR to `main`, and do not merge.

- [ ] **Step 4: Wait for GitHub Actions**

Require backend and frontend PASS on the PR head, record run ID/head SHA in the report, keep the PR draft, and stop before SPEC-019.
