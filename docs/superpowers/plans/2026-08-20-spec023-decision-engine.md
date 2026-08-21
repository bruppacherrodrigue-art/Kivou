# SPEC-023 Deterministic Acquisition Decision Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the frozen deterministic SEND/REVIEW/NO_SEND decision policy, its durable audit, and atomic acquisition-state mutation without external I/O or customer data.

**Architecture:** A pure `signals.decision_engine` package builds a PII-free decision input from authoritative local state, resolves recency with a Kivou-owned clock captured once, and evaluates an ordered rule matrix. The service binds the exact proposal to a fresh Policy Gateway evaluation, then either records a POLICY_BLOCKED audit or atomically appends `DECISION_RECORDED` with its RECORDED audit. A shared connection-aware public resolver preserves SPEC-020 selection semantics.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy Core, Alembic, pytest, Ruff, SQLite tests with PostgreSQL DDL compilation, React/Vitest frontend regression.

---

### Task 1: Pure contracts, config, recency, and fingerprints

**Files:**
- Create: `src/signals/decision_engine/__init__.py`
- Create: `src/signals/decision_engine/contracts.py`
- Create: `src/signals/decision_engine/policy.py`
- Create: `src/signals/decision_engine/input.py`
- Test: `tests/test_decision_engine_contracts.py`
- Test: `tests/test_decision_engine_input.py`

- [ ] **Step 1: Write failing contract/config tests**

```python
def test_decision_policy_v1_is_frozen():
    assert DECISION_POLICY.max_send_age_days == 60
    assert DECISION_POLICY.hold_enabled is False
    assert DECISION_POLICY.enrich_enabled is False
    assert decision_policy_config_fingerprint(DECISION_POLICY) == expected_sha256

def test_authoritative_recency_precedence_never_uses_discovered_at():
    context = public_context(award_date=None, notification_date=None, publication_date=DATE)
    got = build_decision_input(..., public_context=context, as_of_date=DATE_PLUS_60)
    assert got.recency_basis is RecencyBasis.PUBLICATION_DATE
    assert got.age_days == 60
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest -q tests/test_decision_engine_contracts.py tests/test_decision_engine_input.py`

Expected: collection failure because `signals.decision_engine` does not exist.

- [ ] **Step 3: Implement immutable contracts and canonical hashing**

```python
DECISION_POLICY_VERSION = "decision-policy-v1"
DECISION_INPUT_VERSION = "acquisition-decision-input-v1"
RECENCY_VERSION = "acquisition-recency-v1"
MAX_REASON_CODES = 8
MAX_EVIDENCE_REFS = 16

class RecencyBasis(StrEnum):
    AWARD_DATE = "AWARD_DATE"
    CONTRACT_NOTIFICATION_DATE = "CONTRACT_NOTIFICATION_DATE"
    PUBLICATION_DATE = "PUBLICATION_DATE"
    UNRESOLVED = "UNRESOLVED"
```

Implement a frozen `DecisionPolicyConfig`, PII-free `PublicAcquisitionContext`, `AcquisitionDecisionInput`, deterministic public/input/config fingerprints, and exact recency selection. Capture no clock inside these modules.

- [ ] **Step 4: Run GREEN and refactor**

Run: `uv run pytest -q tests/test_decision_engine_contracts.py tests/test_decision_engine_input.py`

Expected: PASS.

### Task 2: Pure ordered decision evaluator

**Files:**
- Create: `src/signals/decision_engine/evaluator.py`
- Modify: `src/signals/decision_engine/contracts.py`
- Test: `tests/test_decision_engine_evaluator.py`

- [ ] **Step 1: Write failing matrix tests**

```python
@pytest.mark.parametrize(("age", "expected"), [(59, Decision.SEND), (60, Decision.SEND), (61, Decision.NO_SEND)])
def test_frozen_inclusive_boundary(age, expected):
    assert evaluate_decision(decision_input(age_days=age), DECISION_POLICY).proposed_decision is expected

def test_domain_conflict_precedes_staleness():
    proposal = evaluate_decision(decision_input(identity="DOMAIN_CONFLICT", age_days=61), DECISION_POLICY)
    assert proposal.proposed_decision is Decision.REVIEW
    assert proposal.reason_codes[0] == "SUPPLIER_DOMAIN_CONFLICT"
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest -q tests/test_decision_engine_evaluator.py`

Expected: fail because `evaluate_decision` is absent.

- [ ] **Step 3: Implement the six ordered rules and exact next actions**

```python
if input.profile_supplier_identity_status != input.current_supplier_identity_status:
    return review("SUPPLIER_IDENTITY_CHANGED_SINCE_RESEARCH")
if input.current_supplier_identity_status is SupplierIdentityStatus.DOMAIN_CONFLICT:
    return review("SUPPLIER_DOMAIN_CONFLICT")
if input.recency_basis is RecencyBasis.UNRESOLVED:
    return review("RECENCY_UNRESOLVED")
if input.public_timing_inconsistent:
    return review("PUBLIC_TIMING_INCONSISTENT")
if input.age_days > config.max_send_age_days:
    return no_send("SIGNAL_OUTSIDE_ACQUISITION_WINDOW")
return send(input.recency_basis)
```

Proposal fingerprint covers exact ordered output; `confidence` and `next_review_at` remain `None`. HOLD/ENRICH have no branch.

- [ ] **Step 4: Run GREEN plus 1,000-input diagnostic**

Run: `uv run pytest -q tests/test_decision_engine_evaluator.py`

Expected: PASS with deterministic benchmark output.

### Task 3: Shared public resolver and Policy metadata

**Files:**
- Modify: `src/signals/supplier_discovery/seed.py`
- Modify: `src/signals/policy/registry.py`
- Test: `tests/test_decision_engine_public_context.py`
- Test: `tests/test_decision_engine_policy.py`
- Test: `tests/test_supplier_discovery_seed.py`

- [ ] **Step 1: Write failing resolver preservation and policy tests**

```python
def test_connection_aware_public_core_matches_existing_seed(engine):
    before = resolve_acquisition_seed(engine, KEY)
    with engine.connect() as connection:
        core = resolve_public_acquisition_context_in_transaction(connection, KEY)
    assert core.representative_award_key == before.representative_award_key
    assert core.public_evidence_refs == before.public_evidence_refs

def test_evaluate_opportunity_has_only_local_preparatory_gates():
    profile = COMMAND_POLICIES["evaluate_opportunity"]
    assert profile.required_evidence == ("PUBLIC_OPPORTUNITY", "PUBLIC_EVIDENCE", "ACQUISITION_PROSPECT_PREBUILD", "VERIFIED_CONTACT", "DECISION_INPUT")
    assert not any((profile.uses_budget, profile.uses_provider_quota, profile.uses_send_controls, profile.requires_control_plane, profile.requires_compliance))
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest -q tests/test_decision_engine_public_context.py tests/test_decision_engine_policy.py tests/test_supplier_discovery_seed.py`

Expected: fail because the shared public resolver and new evidence metadata are absent.

- [ ] **Step 3: Extract one selection helper and preserve SPEC-020 outputs**

```python
def resolve_public_acquisition_context_in_transaction(connection, opportunity_key):
    rows = _public_rows(connection, opportunity_key)
    return _select_public_context(rows)

def resolve_acquisition_seed(engine, opportunity_key):
    with engine.connect() as connection:
        core = resolve_public_acquisition_context_in_transaction(connection, opportunity_key)
    understanding = ContractUnderstandingEngine().understand(core.award, core.event)
    needs = NeedGraphEngine().derive(understanding)
    return AcquisitionSeed(**core.fields(), understanding=understanding, needs=needs)
```

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest -q tests/test_decision_engine_public_context.py tests/test_decision_engine_policy.py tests/test_supplier_discovery_seed.py tests/test_supplier_discovery_service.py`

Expected: PASS and identical seed outputs.

### Task 4: Migration 0012 and append-only audit store

**Files:**
- Modify: `src/signals/persistence/schema.py`
- Create: `src/signals/persistence/migrations/versions/0012_decision_engine_decision_engine.py`
- Create: `src/signals/decision_engine/store.py`
- Modify: migration-head assertions in existing migration tests
- Test: `tests/test_decision_engine_migration.py`
- Test: `tests/test_decision_engine_store.py`

- [ ] **Step 1: Write failing migration/store tests**

```python
def test_0012_adds_exactly_one_decision_audit_table(migrated_engine):
    assert current_revision(migrated_engine) == "0012_decision_engine"
    assert "acquisition_decision_evaluation" in inspect(migrated_engine).get_table_names()

def test_same_policy_evaluation_conflicting_proposal_is_typed(store, row):
    store.insert_policy_blocked(row)
    with pytest.raises(DecisionEvaluationIdempotencyConflict):
        store.insert_policy_blocked(row.model_copy(update={"proposal_fingerprint": OTHER}))
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest -q tests/test_decision_engine_migration.py tests/test_decision_engine_store.py`

Expected: fail because revision/table/store do not exist.

- [ ] **Step 3: Implement one table and conflict-safe inserts**

Implement the approved columns, `CHECK` constraints for disposition/recency/next-action semantics, `UNIQUE(policy_evaluation_id)`, `UNIQUE(recorded_event_id)`, JSON bounds at contract layer, and SQLite/PostgreSQL `ON CONFLICT DO NOTHING` followed by semantic reload.

- [ ] **Step 4: Run GREEN and all migration tests**

Run: `uv run pytest -q tests/test_decision_engine_migration.py tests/test_decision_engine_store.py tests/test_*migration*.py`

Expected: PASS with exactly one Alembic head.

### Task 5: Additive state reducer semantics

**Files:**
- Modify: `src/signals/acquisition/state.py`
- Test: `tests/test_acquisition_state.py`
- Test: `tests/test_decision_engine_state.py`

- [ ] **Step 1: Write failing new-path and historical replay tests**

```python
def test_new_no_send_event_clears_evaluate_opportunity():
    result = reduce_event(ready(next_action="evaluate_opportunity"), decision_event("NO_SEND", next_action=None))
    assert result.state is AcquisitionState.NO_SEND
    assert result.next_action is None

def test_historical_decision_without_next_action_replays_identically():
    assert replay(HISTORICAL_STREAM) == HISTORICAL_EXPECTED_PROJECTION
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest -q tests/test_decision_engine_state.py tests/test_acquisition_state.py`

Expected: new-path test fails because current reducer leaves `next_action` stale.

- [ ] **Step 3: Implement field-presence-gated additive behavior**

```python
if "next_action" in event.payload:
    allowed = {Decision.SEND: "prepare_campaign", Decision.REVIEW: "request_human_review", Decision.NO_SEND: None}
    if decision not in allowed or event.payload["next_action"] != allowed[decision]:
        raise InvalidTransition("decision next_action mismatch")
    updates["next_action"] = event.payload["next_action"]
```

Reject unexpected keys on the new path while leaving payloads without `next_action` on exact legacy semantics.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest -q tests/test_decision_engine_state.py tests/test_acquisition_state.py tests/test_acquisition_store.py`

Expected: PASS, including byte-equivalent historical projections.

### Task 6: Orchestration, authoritative clock, SHADOW, and atomic commit

**Files:**
- Create: `src/signals/decision_engine/service.py`
- Modify: `src/signals/decision_engine/store.py`
- Test: `tests/test_decision_engine_service.py`
- Test: `tests/test_decision_engine_architecture.py`

- [ ] **Step 1: Write failing service tests**

```python
def test_service_captures_clock_once_for_input_and_policy(context):
    result = context.service.evaluate(OPPORTUNITY_ID, authorization())
    assert context.clock.calls == 1
    assert result.audit.as_of_date == context.now.date()
    assert context.gateway.requests[0].evaluated_at == context.now

def test_shadow_persists_blocked_proposal_without_business_event(context):
    result = context.service.evaluate(OPPORTUNITY_ID, shadow_authorization())
    assert result.audit.disposition == "POLICY_BLOCKED"
    assert context.acquisition.get_opportunity(OPPORTUNITY_ID).state is AcquisitionState.READY_FOR_DECISION

def test_success_audit_event_projection_are_atomic(context, monkeypatch):
    monkeypatch.setattr(context.store, "insert_recorded_in_transaction", fail)
    with pytest.raises(RuntimeError):
        context.service.evaluate(OPPORTUNITY_ID, authorization())
    assert context.acquisition.get_opportunity(OPPORTUNITY_ID).state is AcquisitionState.READY_FOR_DECISION
    assert context.store.get_by_policy(EVALUATION_ID) is None
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest -q tests/test_decision_engine_service.py tests/test_decision_engine_architecture.py`

Expected: fail because the service is absent.

- [ ] **Step 3: Implement preflight, one clock capture, policy binding, and final revalidation**

Use no caller `evaluated_at`. Preflight existing audit, then policy-without-audit. Capture `self._now()` once. Build proposal, call Policy Gateway with that instant, persist POLICY_BLOCKED when non-executable, or use one caller-owned transaction to lock/reload, rebuild using the same `as_of_date`, compare both fingerprints, append `DECISION_RECORDED`, and insert RECORDED audit.

- [ ] **Step 4: Run GREEN and focused integration suite**

Run: `uv run pytest -q tests/test_decision_engine_*.py tests/test_acquisition_*.py tests/test_policy_*.py tests/test_supplier_discovery_*.py`

Expected: PASS with zero external I/O paths.

### Task 7: Full regression, report, publication, and CI

**Files:**
- Create: `docs/reports/2026-08-20-spec023-decision-engine.md`
- Modify: `docs/reports/2026-08-20-spec023-decision-engine-design.md` only if factual closeout correction is required

- [ ] **Step 1: Run full backend verification**

Run: `uv run pytest -q && uv run ruff check . && git diff --check`

Expected: all tests pass, zero skipped, Ruff and whitespace clean.

- [ ] **Step 2: Run full frontend verification**

Run from `frontend`: `npm test -- --run && npm run build && npx tsc -b && npm run lint`

Expected: all current P0-01 tests and build checks pass.

- [ ] **Step 3: Record performance and final report**

Document the frozen threshold, authoritative clock, resolver preservation proof, migration/event compatibility, exact counts, executable SHA, CI run, diff stat, and clean status.

- [ ] **Step 4: Stage explicitly, commit, and push normally**

Use explicit paths; never `git add .`. Push `feat/spec023-decision-engine` without force and keep PR #19 draft.

- [ ] **Step 5: Wait for GitHub Actions**

Run: `gh pr checks 19 --watch`

Expected: required GitHub Actions checks succeed before reporting READY.
