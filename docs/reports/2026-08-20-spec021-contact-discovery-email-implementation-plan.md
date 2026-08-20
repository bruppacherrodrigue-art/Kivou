# SPEC-021 Contact Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover at most one Apollo-provider-verified business contact for an actionable AcquisitionOpportunity, attach it through the event stream, and advance the bounded workflow without any outbound side effect.

**Architecture:** A new `signals.contact_discovery` package owns strict profiles, ranking, Apollo parsing, persistence, and orchestration. Policy is evaluated freshly before a durable one-to-one run; selected-contact persistence and acquisition mutations commit atomically. `CONTACT_SELECTED` is an additive `acquisition-state-v1` event, and migration 0010 adds only `acquisition_contact` and `contact_discovery_run`.

**Tech Stack:** Python 3.12, Pydantic, SQLAlchemy Core, Alembic, httpx, pytest, Ruff, PostgreSQL/SQLite compatibility.

---

### Task 1: Contact contracts, identity, profile, and ranking

**Files:**
- Create: `src/signals/contact_discovery/contracts.py`
- Create: `src/signals/contact_discovery/identity.py`
- Create: `src/signals/contact_discovery/profile.py`
- Create: `src/signals/contact_discovery/ranking.py`
- Test: `tests/test_contact_discovery_profile.py`

- [ ] Write failing tests for the immutable FR/EN profile, exclusion of `expected_opportunity_version`, identity scoping, deterministic ranking, and 1/25/3 bounds.
- [ ] Run `uv run pytest -q tests/test_contact_discovery_profile.py` and confirm failures are caused by missing contact-discovery code.
- [ ] Implement `DecisionMakerSearchProfile`, `contact_ref_for()`, Kivou-owned title metadata, and the pure ranking key. The profile fingerprint covers only provider-search semantics.
- [ ] Re-run the focused tests to green and refactor without changing behavior.

### Task 2: Apollo People Search and People Enrichment boundary

**Files:**
- Create: `src/signals/contact_discovery/provider.py`
- Create: `src/signals/contact_discovery/apollo.py`
- Test: `tests/test_contact_discovery_apollo.py`

- [ ] Write failing HTTP-mock tests for the exact two endpoints, exact request parameters, bounded response parsing, typed 401/403/429/timeout/5xx/network errors, and no phone/personal/waterfall flags.
- [ ] Prove organization-name mismatch does not reject a Search candidate while enrichment organization-ID mismatch does.
- [ ] Implement the narrow provider protocol/client, item rejection and page-level malformed-response handling, without persisting or logging raw responses.
- [ ] Re-run focused tests to green.

### Task 3: `CONTACT_SELECTED` additive reducer event

**Files:**
- Modify: `src/signals/acquisition/contracts.py`
- Modify: `src/signals/acquisition/state.py`
- Modify: `src/signals/acquisition/store.py`
- Test: `tests/test_contact_selected_event.py`
- Test: `tests/test_acquisition_replay.py`

- [ ] Write failing tests for reducer preconditions, reference-only mutation, idempotence/concurrency, and old-stream projection equality.
- [ ] Run the focused tests and verify RED.
- [ ] Add `EventType.CONTACT_SELECTED` and a connection-aware append path using the existing reducer/version. Do not change historical event semantics.
- [ ] Re-run reducer/replay/acquisition tests to green.

### Task 4: Migration 0010 and contact/run store

**Files:**
- Modify: `src/signals/persistence/schema.py`
- Create: `src/signals/persistence/migrations/versions/0010_contact_discovery_contact_discovery.py`
- Create: `src/signals/contact_discovery/store.py`
- Test: `tests/test_contact_discovery_migration.py`
- Test: `tests/test_contact_discovery_store.py`

- [ ] Write failing migration tests for fresh/head and 0009→0010, two tables only, FKs, uniqueness, indexes, constraints, and revision length/linearity.
- [ ] Write failing store tests for run ownership, typed run-ID conflicts, one policy evaluation per run, observation CAS, stale no-op, equal-time replay, and equal-time fingerprint conflict.
- [ ] Add the two tables and SQLAlchemy Core store. Use `UNIQUE(provider, provider_person_id, supplier_ref)` and `UNIQUE(policy_evaluation_id)`.
- [ ] Re-run migration/store tests to green, including PostgreSQL offline SQL generation.

### Task 5: Policy metadata and crash-window preflight

**Files:**
- Modify: `src/signals/policy/registry.py`
- Create: `src/signals/contact_discovery/service.py`
- Test: `tests/test_contact_discovery_policy.py`
- Test: `tests/test_contact_discovery_service.py`

- [ ] Write failing tests for actionable preflight, SHADOW/quota/control-plane zero-call behavior, existing-run replay, and audited-evaluation-without-run fresh-attempt requirement.
- [ ] Confirm `expected_opportunity_version` is passed only to `PolicyRequest`, never profile/fingerprint.
- [ ] Implement the deterministic preflight order: existing run; existing policy without run; actionable opportunity; fresh profile/policy; durable STARTED ownership; provider.
- [ ] Re-run focused tests to green.

### Task 6: Atomic success and no-contact workflows

**Files:**
- Modify: `src/signals/contact_discovery/service.py`
- Modify: `src/signals/contact_discovery/store.py`
- Modify: `src/signals/acquisition/store.py`
- Test: `tests/test_contact_discovery_service.py`

- [ ] Write failing tests for success transaction rollback at each boundary, version `V+1` enforcement, three enrichment attempts, first-success stop, and no workflow overwrite.
- [ ] Write failing tests for `NO_CANDIDATE`, `NO_VERIFIED_CONTACT`, and `CONTACT_SEARCH_TOO_BROAD` atomically setting `request_human_review`, plus concurrency rollback.
- [ ] Implement caller-owned transaction methods that verify the selected contact, append `CONTACT_SELECTED`, transition to `ENRICHING`, set `enrich_company`, and finish the run.
- [ ] Persist `provider_total_entries`, returned count, and deterministic truncation without claiming exhaustive coverage.
- [ ] Re-run focused and all acquisition/policy/supplier/contact tests to green.

### Task 7: Full verification, report, publication, and CI

**Files:**
- Create: `docs/reports/2026-08-20-spec021-contact-discovery-email.md`
- Modify: `docs/reports/2026-08-20-spec021-contact-discovery-email-design.md` only if a factual design correction is needed.

- [ ] Run `uv run pytest -q`, `uv run ruff check .`, and `git diff --check`; require at least 3055 backend tests and zero skipped.
- [ ] Run frontend `npm test -- --run`, `npm run build`, `npx tsc -b`, and `npm run lint`; require at least 84 tests.
- [ ] Write the completed-behavior report with migration, replay, crash-window, privacy, truncation, atomicity, counts, files, diff stat, and status.
- [ ] Stage only SPEC-021 files, commit, push normally to PR #16, and wait for a green GitHub Actions run.
- [ ] Return exactly one required CONTACT DISCOVERY verdict without merging or deploying.
