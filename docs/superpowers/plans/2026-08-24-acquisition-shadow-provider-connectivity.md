# Acquisition SHADOW provider connectivity implementation plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, preserving strict RED-GREEN-REFACTOR evidence.

**Goal:** Deliver a manually invoked, fail-closed staging smoke test that proves read-only Apollo and Instantly connectivity plus one advisory pinned-Hermes/OpenRouter plan without creating any Kivou or provider-side commercial mutation.

**Architecture:** Add one isolated `signals.acquisition_connectivity` composition package. It will parse only the missing deployment document, compose all three existing Apollo clients and the existing Instantly provider/readiness source, read the existing durable Policy Control and stores, add only the missing identity GET probes, invoke the existing Hermes adapter/contracts, and compare existing acquisition-table counters after provider I/O. A disabled systemd oneshot and operator runbook remain the only deployment entry point. `CampaignWorker` remains the sole execution worker but is never started or invoked by this smoke.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLAlchemy Core, HTTPX, pytest, Ruff, systemd.

---

### Task 1: Closed deployment configuration and bounded smoke results

**Files:**
- Create: `src/signals/acquisition_connectivity/__init__.py`
- Create: `src/signals/acquisition_connectivity/contracts.py`
- Create: `src/signals/acquisition_connectivity/config.py`
- Test: `tests/test_acquisition_connectivity_config.py`

- [ ] Write tests for the exact seven required variables, missing/empty values, absolute paths, malformed JSON, unknown properties, exact schema version, exact mailbox cardinality, bounded strings, unique mailbox refs, and unique provider bindings.
- [ ] Run the focused test file and capture the expected import/contract failures.
- [ ] Implement only the absent deployment/smoke contracts as frozen, extra-forbidden Pydantic models plus a secret-safe configuration exception; reuse all existing business/provider/Hermes/Policy contracts.
- [ ] Run the focused test file and Ruff until green.

### Task 2: Apollo composition and missing identity probe

**Files:**
- Create: `src/signals/acquisition_connectivity/apollo.py`
- Test: `tests/test_acquisition_connectivity_apollo.py`

- [ ] Write tests proving only the two fixed HTTPS GET endpoints, `x-api-key`-only authentication, finite timeouts, response-size enforcement, error mapping, opaque acting-user hashing, and redaction.
- [ ] Run the tests red before implementation.
- [ ] Implement the injected identity probe with no arbitrary method/path/body escape hatch and compose the three existing Apollo clients from the same protected key without invoking their paid methods.
- [ ] Run focused tests and Ruff green.

### Task 3: Instantly provider extensions and read-only orchestration

**Files:**
- Modify: `src/signals/campaigns/instantly.py`
- Create: `src/signals/acquisition_connectivity/instantly.py`
- Test: `tests/test_acquisition_connectivity_instantly.py`

- [ ] Record the current official contracts for `GET /api/v2/workspaces/current` and `GET /api/v2/accounts/{email}` in tests and the runbook.
- [ ] Write tests for Bearer authentication, exact GET routes, URL-encoded account identifiers, workspace binding, all four existing readiness states, exactly three distinct READY mailboxes, response bounds, transport failures, and redaction.
- [ ] Run the tests red before implementation.
- [ ] Add the missing read-only workspace method and safe mailbox path encoding to `HttpInstantlyProvider`; implement only a narrow coordinator over that provider and `InstantlyMailboxReadinessSource`.
- [ ] Run focused tests and Ruff green.

### Task 4: Durable safety preflight and non-mutation proof

**Files:**
- Create: `src/signals/acquisition_connectivity/service.py`
- Test: `tests/test_acquisition_connectivity_service.py`

- [ ] Write tests for exact STAGING identity, effective SHADOW control, `read_only=true`, `kill_switch=true`, durable volume cap zero, absence of unresolved positive provider operations, and zero provider calls on every preflight failure.
- [ ] Write parameterized tests requiring an after-snapshot on success and every reached network failure, with `LOCAL_MUTATION_DETECTED` taking precedence over a provider error.
- [ ] Run the tests red before implementation.
- [ ] Add one bounded-count method to the existing `CampaignStore`; compose it with `PolicyStore`/`OperationsStore` and never define a new store or append/update control state.
- [ ] Run focused tests and Ruff green.

### Task 5: Existing Hermes adapter, exact model configuration, and advisory plan

**Files:**
- Modify: `src/signals/acquisition_connectivity/config.py`
- Modify: `src/signals/acquisition_connectivity/service.py`
- Test: `tests/test_acquisition_connectivity_service.py`

- [ ] Write tests for the immutable Hermes pin, strict JSON-compatible `config.yaml`, exact OpenRouter model/routing, no fallback, zero tools, 30-second timeout, 2,048 output tokens, ten-action limit, CHF 1 envelope, strict SupervisorPlan validation, and no plan persistence/execution.
- [ ] Run the tests red before implementation.
- [ ] Validate the dedicated Hermes home configuration and compose the existing `HermesSupervisorAdapter`, `SupervisorSettings`, `SupervisorContext`, and `SupervisorPlan` contracts without recreating CLI, bridge, pin, engine, or plan types.
- [ ] Map all Hermes failures to the closed connectivity vocabulary without leaking prompt or response content.
- [ ] Run focused supervisor/connectivity tests and Ruff green.

### Task 6: Stable CLI and manual systemd boundary

**Files:**
- Create: `src/signals/acquisition_connectivity/cli.py`
- Create: `src/signals/acquisition_connectivity/__main__.py`
- Create: `ops/systemd/kivou-acquisition-shadow-smoke.service`
- Test: `tests/test_acquisition_connectivity_cli.py`
- Test: `tests/test_acquisition_connectivity_architecture.py`

- [ ] Write tests for the exact `check` command, bounded PASS/FAIL output, stable exit codes, secret/address redaction, no imports with network side effects, no forbidden worker/webhook/outbound imports, no forbidden HTTP methods, and no automatic retries.
- [ ] Write architecture tests proving the systemd unit is a manual `Type=oneshot` under `kivou:kivou`, has both environment files, and has no `[Install]`, timer, restart loop, or listener.
- [ ] Run tests red, implement the CLI/unit, then run focused tests and Ruff green.

### Task 7: Expurgated examples and operations runbook

**Files:**
- Modify: `.env.example`
- Create: `ops/examples/acquisition-shadow.env.example`
- Create: `ops/examples/acquisition-shadow.json.example`
- Create: `ops/examples/hermes-shadow-config.yaml`
- Create: `docs/runbooks/08-acquisition-shadow-provider-connectivity.md`
- Modify: `tests/test_acquisition_connectivity_architecture.py`

- [ ] Write failing assertions for blank secret examples, strict document cardinality, exact Hermes pin/model, protected ownership/modes, manual smoke steps, permissions verification, and rollback.
- [ ] Add only redacted examples and operator commands; never add real credentials or enablement instructions.
- [ ] Run architecture tests and Ruff green.

### Task 8: Full verification and GitHub delivery

**Files:**
- Review: all changed files

- [ ] Run all focused connectivity tests and adjacent policy/campaign/supervisor/reliability tests.
- [ ] Run Ruff, `git diff --check`, secret-pattern checks, and review the complete diff.
- [ ] Run the complete backend suite; run no frontend suite unless a shared frontend-affecting file changed.
- [ ] Use superpowers:verification-before-completion, then stage and commit the exact reviewed diff.
- [ ] Push `feat/acquisition-shadow-provider-connectivity`, open a PR to `main`, and include exact endpoint sources, validation commands/results, no-secret/no-mutation/disabled-smoke evidence, limitations, and the review SHA.
- [ ] Follow GitHub Actions for that exact SHA; do not merge and do not deploy.
