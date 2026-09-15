# Hermes Chief of Staff V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a read-only, SHADOW Chief of Staff that turns existing Kivou read models into cited, validated, append-only Founder briefings.

**Architecture:** A new `signals.chief_of_staff` domain owns immutable facts, approved memory, context, report validation, orchestration and persistence. It reuses the isolated Hermes transport/pin and `signals.model_runtime`, while preserving `HermesSupervisorAdapter.plan()`. Founder GET routes and the existing Today page expose only validated reports.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy/Alembic, FastAPI, React/TypeScript, pytest, Vitest, systemd.

---

### Task 1: Strict contracts and approved memory

**Files:** create `src/signals/chief_of_staff/contracts.py`, `business_memory.py`, `business_memory.v1.json`; test `tests/chief_of_staff/test_contracts.py`, `test_business_memory.py`.

- [ ] Write RED tests for frozen/forbid-extra models, aware dates, money, unknowns, three priorities and versioned immutable memory.
- [ ] Run `uv run pytest -q tests/chief_of_staff/test_contracts.py tests/chief_of_staff/test_business_memory.py` and confirm import failures.
- [ ] Implement the minimal contracts and file loader; verify source refs against current code/specs.
- [ ] Run the tests GREEN and commit `feat(chief-of-staff): add strict facts and memory contracts`.

### Task 2: Deterministic bounded context

**Files:** create `facts.py`, `context.py`; test `test_context.py`, `test_facts.py`.

- [ ] Write RED fixture tests projecting cockpit, Founder overview/status and operations without PII, preserving CHF/EUR, proxy semantics and unknown/M2 statuses.
- [ ] Implement stable fact refs, sanitization, cardinality/byte limits and semantic fingerprint.
- [ ] Run targeted tests GREEN and commit `feat(chief-of-staff): build bounded deterministic context`.

### Task 3: Chief profile and shared structured Hermes boundary

**Files:** create profile `src/signals/supervisor/profiles/kivou-chief-of-staff/SKILL.md`, `profiles.py`, `hermes.py`; minimally modify `supervisor/hermes.py`, `hermes_bridge.py`; test Chief adapter and existing supervisor suites.

- [ ] Write RED tests for explicit profile selection, zero tools, pin/route, timeout/provider/invalid JSON and Acquisition public compatibility.
- [ ] Extract only the common structured invocation mechanics; keep `HermesSupervisorAdapter.plan()` signature and output unchanged.
- [ ] Add the report adapter with its own profile/schema/model route and no fallback/retry.
- [ ] Run `uv run pytest -q tests/test_supervisor_* tests/chief_of_staff/test_hermes.py` GREEN and commit.

### Task 4: Semantic validation and evaluation corpus

**Files:** create `validation.py`, `evaluation_cases.v1.json`; tests `test_validation.py`, `test_evaluation.py`.

- [ ] Encode the fifteen required scenarios and expected/forbidden outcomes.
- [ ] Write RED tests for unknown refs/sources, period/version/pin mismatch, unsupported critical claim, injection, PII/secret, command, executed action, scope expansion, digits and output size.
- [ ] Implement fail-closed validation and run the corpus GREEN.
- [ ] Commit `feat(chief-of-staff): validate cited shadow reports`.

### Task 5: Model configuration and budget lifecycle

**Files:** modify `model_runtime/config.py`; create `chief_of_staff/config.py`; tests `test_config.py`, `test_budget.py`.

- [ ] Write RED tests proving the Chief route is distinct, requires explicit configuration, reserves before invocation and succeeds/fails the existing journal.
- [ ] Add `chief_of_staff` usage and explicit four-variable configuration without changing Acquisition defaults.
- [ ] Run model-runtime plus Chief budget tests GREEN and commit.

### Task 6: Append-only migration and store

**Files:** modify `persistence/schema.py`; create next Alembic revision from real head; create `chief_of_staff/store.py`; tests `test_migration.py`, `test_store.py`.

- [ ] Write RED tests for migration, unique semantic identity, insert-only idempotence, latest/history and bounded history.
- [ ] Add the report table, indexes/checks and conflict-safe insert; expose no update/delete API.
- [ ] Run migration/store tests against SQLite and PostgreSQL when available; commit.

### Task 7: Application service, lock and CLI

**Files:** create `service.py`, `cli.py`, `__main__.py`; tests `test_service.py`, `test_cli.py`.

- [ ] Write RED orchestration tests for invalid context before budget, success, budget refusal, provider failure, invalid report, idempotence, dry-run default and concurrent lock refusal.
- [ ] Implement collection -> invoke -> validate -> persist with injected clock/dependencies and safe exit codes.
- [ ] Run targeted tests GREEN and commit.

### Task 8: Founder API reads

**Files:** create `founder_api/chief_of_staff.py`; modify `founder_api/app.py`, `asgi.py`; tests `tests/founder_api/test_chief_of_staff.py` and architecture tests.

- [ ] Write RED authenticated latest/history tests for empty, result, bounds and 503.
- [ ] Add GET-only routes with `FounderIdentityDependency`; do not mount them in the customer app.
- [ ] Run Founder suites GREEN and commit.

### Task 9: Founder Console briefing

**Files:** modify `frontend/founder/src/types.ts`, `api.ts`, `FounderApp.tsx`, `styles.css`, `FounderApp.test.tsx`.

- [ ] Write RED tests for report/statuses, max priorities, decisions, unknowns, stale/empty/unavailable/loading, CHF/EUR separation, headings/lists, refresh, no execution control and route preservation.
- [ ] Implement an independent `Brief d'Hermes` read state on Today with existing tokens and French copy.
- [ ] Run Founder frontend tests, typecheck/lint/build GREEN and commit.

### Task 10: Inactive scheduling and architecture proofs

**Files:** create `ops/systemd/kivou-chief-of-staff.service`, `.timer`; create `tests/chief_of_staff/test_architecture.py`, `test_systemd.py`.

- [ ] Assert oneshot, hardening, lock, timeout, no install/migration/secret and no timer activation symlink.
- [ ] Assert no SQLAlchemy/DB object in Hermes, no provider clients, no executable tools, no client route and replaceable Hermes boundary.
- [ ] Run tests GREEN and commit.

### Task 11: Reproducible demo and documentation verification

**Files:** create `tests/fixtures/chief_of_staff/demo_context.json`; complete the dated docs and runbook.

- [ ] Run the offline demo through context, simulated report, validation, persistence and Founder GET.
- [ ] Run the Founder fixture test proving UI rendering and capture the non-sensitive output path.
- [ ] Verify docs contain no activation claim or secret; commit.

### Task 12: Full verification and PR

- [ ] Run locked sync, targeted backend suites, `uv run ruff check .`, full `uv run pytest -q`, frontend install/test/typecheck/lint/build/build:founder and `git diff --check`.
- [ ] Record pre-existing/skipped failures separately with exact reproduction commands.
- [ ] Inspect full diff, migration graph, secret scan and generated files.
- [ ] Create coherent final commit(s), push `feat/hermes-chief-of-staff-v1`, and open a PR titled `feat(hermes): add read-only Chief of Staff foundation`.
- [ ] Do not merge, deploy, activate a timer or call a real provider.
