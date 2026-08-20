# SPEC-022 Company Research + Acquisition Prospect Prebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded, policy-authorized Apollo exact-ID company research and persist an opportunity-scoped deterministic `AcquisitionProspectPrebuild` before moving the acquisition workflow to `READY_FOR_DECISION`.

**Architecture:** A new `signals.company_research` package separates immutable provider-request configuration, the narrow Apollo client, accepted provider observations, deterministic prebuild derivation, SQLAlchemy Core persistence, and orchestration. Migration `0011_company_research` adds exactly `acquisition_company_profile` and `company_research_run`; existing acquisition events atomically express workflow progression without a new EventType.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy Core, Alembic, httpx, pytest, Ruff, SQLite/PostgreSQL-compatible SQL.

---

### Task 1: Contracts, provider profile, fingerprints, and prebuild

**Files:**
- Create: `src/signals/company_research/__init__.py`
- Create: `src/signals/company_research/contracts.py`
- Create: `src/signals/company_research/profile.py`
- Create: `src/signals/company_research/prebuild.py`
- Test: `tests/test_company_research_profile.py`
- Test: `tests/test_company_research_prebuild.py`

- [ ] **Step 1: Write failing contract/fingerprint tests**

Tests instantiate a profile with only provider semantics, prove the same Apollo
organization yields the same provider request fingerprint across opportunities,
and prove policy action fingerprints differ once opportunity bindings are added.
They also cover size boundaries, `COMPLETE/LIMITED`, deterministic research gaps,
and assert that no final fit/lead/SEND field exists.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/test_company_research_profile.py tests/test_company_research_prebuild.py
```

Expected: collection fails because `signals.company_research` does not exist.

- [ ] **Step 3: Implement minimal immutable contracts**

Define `CompanyResearchProfile`, `ApolloOrganizationObservation`,
`AcquisitionProspectPrebuild`, enums `CompanySizeBand`,
`ResearchCompleteness`, `ProviderResearchStatus`, bounded `ResearchGap`, and
typed errors. Implement canonical SHA-256 helpers with these separations:

```python
profile_fingerprint = sha256(canonical(profile_configuration))
provider_request_fingerprint = sha256(canonical(provider_request_semantics))
prebuild_fingerprint = sha256(canonical(all_spec023_inputs))
```

- [ ] **Step 4: Run GREEN and refactor**

```bash
uv run pytest -q tests/test_company_research_profile.py tests/test_company_research_prebuild.py
```

### Task 2: Narrow Apollo exact-ID client and optional-field degradation

**Files:**
- Create: `src/signals/company_research/provider.py`
- Create: `src/signals/company_research/apollo.py`
- Test: `tests/test_company_research_apollo.py`

- [ ] **Step 1: Write failing provider tests**

Cover exact GET path/host, response streaming and 1 MiB cap, 401/403/404/422/
429/other 4xx/5xx/timeout/network categories, authoritative Retry-After,
identity-critical root/id/name failures, exact ID mismatch, and optional field
degradation into stable gaps without losing safe fields.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/test_company_research_apollo.py
```

- [ ] **Step 3: Implement minimal client**

Expose only:

```python
class CompanyResearchProvider(Protocol):
    def fetch_organization(
        self, profile: CompanyResearchProfile, *, observed_at: datetime
    ) -> ApolloOrganizationObservation: ...
```

`ApolloCompanyResearchClient` accepts an injected `httpx.Client`, fixes the
host/path, streams bytes, parses only the allowlist, and never logs secrets or
raw payloads. Optional invalid fields are dropped and represented by sorted
bounded `research_gaps`; provider observation time is supplied only after the
HTTP response is received.

- [ ] **Step 4: Run GREEN**

```bash
uv run pytest -q tests/test_company_research_apollo.py
```

### Task 3: Policy metadata

**Files:**
- Modify: `src/signals/policy/registry.py`
- Test: `tests/test_company_research_policy.py`

- [ ] **Step 1: Write failing registry tests**

Assert `enrich_company` is opportunity-scoped PREPARATORY, requires
`SUPPLIER`, `VERIFIED_CONTACT`, `COMPANY_RESEARCH_PROFILE`, uses budget/provider
quota/control plane, and does not use send controls or compliance.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/test_company_research_policy.py
```

- [ ] **Step 3: Modify only the callable-free registry entry and run GREEN**

```bash
uv run pytest -q tests/test_company_research_policy.py tests/test_policy_*.py
```

### Task 4: Schema and migration 0011

**Files:**
- Modify: `src/signals/persistence/schema.py`
- Create: `src/signals/persistence/migrations/versions/0011_company_research_company_research.py`
- Test: `tests/test_company_research_migration.py`

- [ ] **Step 1: Write failing migration tests**

Assert a single graph `0010_contact_discovery -> 0011_company_research`, fresh
upgrade, populated 0010 upgrade, exactly two new tables, FK/unique/check/index
contracts, revision length <=32, and PostgreSQL offline SQL.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/test_company_research_migration.py
```

- [ ] **Step 3: Add exactly two tables and the linear migration**

`acquisition_company_profile` owns the current prebuild; `company_research_run`
owns one provider execution per unique `policy_evaluation_id`. No EventType,
cache, history, queue, worker, or third table is added.

- [ ] **Step 4: Run GREEN**

```bash
uv run pytest -q tests/test_company_research_migration.py tests/test_persistence_migrations.py
```

### Task 5: Store ownership, CAS, and caller-owned terminal transaction

**Files:**
- Create: `src/signals/company_research/store.py`
- Test: `tests/test_company_research_store.py`

- [ ] **Step 1: Write failing persistence tests**

Cover STARTED-before-provider ownership, unique policy replay, typed run-ID
collision, run terminal updates, immutable bindings, newer CAS, equal exact
replay, equal semantic conflict, stale no-overwrite, and rollback when any
profile/run write fails.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/test_company_research_store.py
```

- [ ] **Step 3: Implement SQLite/PostgreSQL conflict-safe Core operations**

Provide `start_run`, `get_run_by_policy`, `upsert_profile_in_transaction`, and
`finish_run_in_transaction`. Inserts use dialect-specific
`on_conflict_do_nothing`; raw uniqueness errors never escape normal ownership.

- [ ] **Step 4: Run GREEN**

```bash
uv run pytest -q tests/test_company_research_store.py
```

### Task 6: Permissioned orchestration and atomic workflow progression

**Files:**
- Create: `src/signals/company_research/service.py`
- Test: `tests/test_company_research_service.py`

- [ ] **Step 1: Write failing service tests**

Cover pre-policy actionability, no contact email read, SHADOW/quota zero-call,
policy-evaluation/run crash window, durable run replay, separate clocks,
exactly one provider call, 404/422 failure without profile/workflow change,
COMPLETE/LIMITED success, concurrency failure, and atomic profile +
`READY_FOR_DECISION` + `evaluate_opportunity` + terminal run.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/test_company_research_service.py
```

- [ ] **Step 3: Implement the approved service flow**

The service checks run/evaluation preflight, loads actionable opportunity and
safe supplier/contact metadata, constructs fresh policy request at V, stores
STARTED at V+1, invokes the fakeable provider once, timestamps the accepted
observation after response, and finalizes all profile/workflow writes in one
transaction. A failed terminal transaction marks the pre-existing run FAILED
separately without partial readiness.

- [ ] **Step 4: Run GREEN**

```bash
uv run pytest -q tests/test_company_research_service.py
```

### Task 7: Architecture, privacy, performance, and regression

**Files:**
- Test: `tests/test_company_research_architecture.py`
- Test: `tests/test_company_research_performance.py`
- Modify: migration head expectations in existing migration tests

- [ ] **Step 1: Write architecture/performance tests**

AST checks forbid TargetICP/customer/billing/materialized-signal imports and
provider endpoint/PII leakage. A diagnostic processes 100 deterministic
fixtures without SLA.

- [ ] **Step 2: Run focused suite**

```bash
uv run pytest -q tests/test_company_research_*.py
```

- [ ] **Step 3: Update only legitimate current-head expectations to 0011**

- [ ] **Step 4: Run all quality gates**

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

### Task 8: Final report and publication

**Files:**
- Create: `docs/reports/2026-08-20-spec022-company-research-icp-prebuild.md`
- Update: this plan's checkboxes

- [ ] **Step 1: Record architecture, proofs, test counts, timing, SHA/CI placeholders only after evidence exists**
- [ ] **Step 2: Run final `git diff --check` and inspect every changed file**
- [ ] **Step 3: Stage SPEC-022 files explicitly, commit, and push without force**
- [ ] **Step 4: Keep PR #18 DRAFT and wait for the new GitHub Actions run**
