# SPEC-025 Compliance CH / FR / EU Implementation Plan

> **For Codex:** Execute this plan in order with test-driven development and verification checkpoints.

**Goal:** Add a deterministic, PII-minimized CH/FR/EU acquisition-email compliance gate that produces an immutable assessment and safe workflow handoff without sending, scheduling, or calling external providers.

**Architecture:** Introduce a pure `signals.compliance` domain (contracts, jurisdiction, suppression identity, rules), two append-only persistence stores, and an orchestration service modelled on the SPEC-023/024 Policy/replay/TOCTOU pattern. Promote `assess_campaign_compliance` to a PREPARATORY command, keep `acquisition-state-v1`, and add a backwards-compatible explicit `NEXT_ACTION_SET(null)` clear.

**Tech stack:** Python 3.12, Pydantic v2, SQLAlchemy Core, Alembic, pytest, SQLite/PostgreSQL migration SQL, existing Kivou Policy Gateway and acquisition event store.

---

## Task 1: Freeze migration and reducer contracts with failing tests

**Files:**
- Create: `tests/test_compliance_migration.py`
- Modify: `tests/test_acquisition_state.py`
- Modify: migration-head assertions under `tests/`

1. Add tests requiring `0014_compliance` over `0013_personalization`, exactly the two approved tables, schema parity, constraints/indexes, offline PostgreSQL SQL, downgrade/re-upgrade, and no PII/provider/model fields.
2. Add state tests for canonical strings, unknown strings, `next_action=None` with reasons, rejection without reasons, and historical replay equality.
3. Run the focused tests and confirm they fail for the missing migration/reducer behavior.

## Task 2: Implement migration/schema and explicit action clear

**Files:**
- Create: `src/signals/persistence/migrations/versions/0014_compliance.py`
- Modify: `src/signals/persistence/schema.py`
- Modify: `src/signals/acquisition/state.py`
- Modify: migration-head assertions under `tests/`

1. Add `acquisition_contact_suppression` and `acquisition_compliance_assessment` only, with restrictive FKs, bounded vocabularies, indexes, and disposition/state/action constraints.
2. Extend `NEXT_ACTION_SET` so `None` is accepted only with non-empty reason codes; leave historical string behavior unchanged.
3. Run focused migration/state tests to green.

## Task 3: Drive pure contracts, jurisdiction, suppression, and rules from tests

**Files:**
- Create: `tests/test_compliance_contracts.py`
- Create: `tests/test_compliance_jurisdiction.py`
- Create: `tests/test_compliance_suppression.py`
- Create: `tests/test_compliance_rules.py`
- Create: `src/signals/compliance/{__init__,contracts,jurisdiction,suppression,rules}.py`

1. Test immutable/bounded/PII-free inputs, sender configuration, fingerprints, proposal mappings, and 24-hour ALLOWED validity.
2. Test CH/FR/EU/out-of-scope/unresolved routing from canonical supplier/provider country facts without language/TLD/name inference.
3. Test normalized HMAC identity, key rotation, retained-version matching, incomplete-keyring fail-closed behavior, no raw email persistence, duplicate-email convergence, and three-year retention validation.
4. Test ordered rule precedence and all frozen CH, FR tier, EU, unresolved, out-of-scope, sender capability, and suppression outcomes.
5. Implement the minimum pure code needed to make each focused test pass.

## Task 4: Promote the Policy command with failing and passing tests

**Files:**
- Modify: `tests/test_policy_gateway.py`
- Modify: `src/signals/supervisor/registry.py`
- Modify: `src/signals/policy/registry.py`

1. Add tests for command/registry equality and exact PREPARATORY metadata/evidence.
2. Confirm failure while the name is reservation-only.
3. Promote the command in both registries, remove the reservation exception, and keep `schedule_campaign` unchanged.
4. Prove ASSISTED assessment is not ACTION-approval-gated and generic Policy compliance is neutral/pending because the command does not require compliance.

## Task 5: Drive append-only stores and suppression recording from tests

**Files:**
- Create: `tests/test_compliance_store.py`
- Create: `src/signals/compliance/store.py`

1. Test deterministic IDs, insert-if-absent replay, typed semantic conflicts, lookup by Policy evaluation, and connection-aware assessment insert.
2. Test contact-bound suppression recording loads the durable email internally, stores only HMAC identity, is idempotent, and rejects unavailable key coverage.
3. Implement dialect-safe SQLite/PostgreSQL upserts and bounded semantic comparisons.

## Task 6: Drive the orchestration service from durability tests

**Files:**
- Create: `tests/test_compliance_service.py`
- Create: `src/signals/compliance/service.py`
- Modify: `src/signals/compliance/__init__.py`

1. Build reusable fixtures for a current SEND opportunity, exact READY personalization artifact, decision, supplier/contact/profile, public evidence, Policy controls, sender config, and synthetic keyring.
2. Add failing tests for actionability/bindings, one clock, CH DB limitation, FR outcomes, EU/out-of-scope/unresolved routing, and zero pre-Policy writes on typed failures.
3. Add replay tests including historical BudgetUsage reconstruction, changed actor/scope/evidence conflicts, and Policy-without-assessment crash handling before the clock.
4. Add final-transaction drift tests for opportunity, artifact, supplier, contact, profile, jurisdiction, sender config, and suppression; all post-Policy material changes become `ComplianceInputChanged`.
5. Add SHADOW tests and atomic rollback tests.
6. Add genuine file-backed concurrency tests for same evaluation convergence, changed semantics, and suppression inserted between Policy and commit.
7. Implement internal evidence, fixed pending compliance, proposal-bound Policy action fingerprint, exact replay, and atomic event+assessment commit.

## Task 7: Add EVAL, privacy, and architecture guards

**Files:**
- Create: `tests/fixtures/compliance_eval_v1.json`
- Create: `tests/test_compliance_eval.py`
- Create: `tests/test_compliance_architecture.py`

1. Add the 20 approved synthetic EVAL cases and verify invariant outcomes without real people/data.
2. Assert no forbidden imports/external I/O dependencies.
3. Assert input snapshots, Policy JSON, events, and assessments contain no contact PII, rendered copy, raw Apollo data, or HMAC secrets.

## Task 8: Full verification and executable commit

1. Run focused compliance/migration/state/policy suites.
2. Run `uv run pytest -q`, require more than 3373 passed and zero skipped.
3. Run `uv run ruff check .` and `git diff --check`.
4. Run frontend tests, build, typecheck, and lint; require at least 150 tests.
5. Create `docs/reports/2026-08-21-spec025-compliance-ch-fr-eu.md` with only proven facts.
6. Commit the executable implementation, push `feat/spec025-compliance`, open a DRAFT PR, and wait for required GitHub CI.
7. Keep the PR unmerged and perform no deployment or external provider call.
