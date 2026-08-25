# Acquisition `run-once` runtime — implementation plan

**Status:** approved mission; implementation pending

**Issue:** #83

**Goal:** expose one bounded, restartable acquisition cycle which composes the
existing Kivou-owned stages, keeps provider mutations behind live Policy and a
QA-only transport binding, and becomes the single durable source used by
acquisition health/readiness.

## Safety invariants

- The only entrypoint is `python -m signals.acquisition_runtime run-once`.
- Normal staging timer execution remains `SHADOW`, read-only and kill-switched.
- No provider mutation can occur unless the current Policy snapshot, a fresh
  one-shot human approval and the runtime QA allowlist all agree.
- The transport recipient used by a staging provider operation is an exact
  controlled QA binding. A discovered address is never used by staging.
- Each cycle has strict cost, candidate, contact, provider-operation and wall
  clock limits. Logs contain machine codes and opaque Kivou references only.
- The Apollo cost envelope is conservative: it reserves the ordinary bounded
  call and at most one native recovery call before dispatch. A lost response
  can make provider acceptance ambiguous; Kivou is therefore at-least-once in
  that narrow crash window, never exactly-once, and permits no third call.
- Hermes may propose only closed Kivou action names. It never receives a shell,
  filesystem, network or arbitrary Python tool. Kivou revalidates Policy before
  dispatching any proposed action.
- `READY` means the pinned Hermes runtime, the durable supervisor heartbeat,
  database, Policy and the current cycle are all coherent. Missing provider,
  approval, mailbox, webhook, response or conversion evidence remains an
  explicit non-ready/waiting state.

## Durable workflow

The runtime follows the order required by the contracts already implemented in
the repository:

1. public signal seed;
2. supplier discovery / Apollo organisation search;
3. contact discovery / Apollo People;
4. exact-ID company research;
5. acquisition decision;
6. personalization;
7. compliance;
8. campaign planning;
9. bounded Instantly provider operations;
10. signed provider-event and response processing;
11. first-party attribution and conversion observation.

The contact stage precedes company research because `CompanyResearchService`
requires a provider-verified `contact_ref`; the runtime must not bypass that
existing binding.

## Task 1 — Freeze configuration and contracts with failing tests

Add `signals.acquisition_runtime.contracts` and `config` tests first. Define:

- cycle/stage statuses (`PENDING`, `RUNNING`, `WAITING`, `SUCCEEDED`, `BLOCKED`,
  `FAILED`, `SUPPRESSED`, `CANCELLED`);
- a versioned QA/SHADOW deployment document;
- exact opaque signal allowlist and controlled-recipient HMAC binding;
- positive limits for one cycle and a maximum wall-clock duration;
- fail-closed production/unknown environment behavior;
- repr/log guards for provider credentials and recipient material.

Run the new contract/config tests RED, implement only enough to make them GREEN,
then run Ruff on the touched package.

## Task 2 — Add the durable cycle, stage and singleton lease schema

Add the next linear Alembic revision after the actual head at merge time and the
matching SQLAlchemy tables:

- `acquisition_runtime_lease`: one singleton row, owner, acquisition/expiry and
  heartbeat;
- `acquisition_runtime_cycle`: deterministic cycle identity, deployment/config
  fingerprints, selected signal/opportunity, status, cost/volume counters,
  timestamps and last machine code;
- `acquisition_runtime_stage`: one row per cycle/stage with explicit status,
  attempt, bounded opaque result refs, start/completion and retry timestamps.

Tests must prove SQLite upgrade/downgrade, PostgreSQL offline SQL, uniqueness,
atomic lease contention, expired-lease reclaim, deterministic replay and that
no address, content or provider payload can enter these tables.

## Task 3 — Implement the Kivou action registry and runner TDD

Add an injected `AcquisitionActionRegistry` and `AcquisitionRuntimeRunner`.
Start with fakes and prove:

- two concurrent `run-once` calls produce one owner and one clean
  `already_running` result;
- a replay resumes the first non-terminal stage;
- every successful stage is checkpointed before the next action;
- SIGTERM/current-process interruption terminalizes or releases the lease and
  never invents success;
- expired leases resume from durable stage state;
- a Policy/approval/eligibility change becomes `BLOCKED` or `SUPPRESSED`, not a
  provider failure;
- budgets are charged before dispatch and cannot be exceeded;
- stale historical failures do not poison an otherwise healthy current cycle.

Registry actions are the existing Policy command names only. Each action is
bound to one typed handler; unknown names and argument drift fail closed.

## Task 4 — Compose the existing services, without duplicate engines

Implement handlers that call the existing services with deterministic IDs and
their native idempotency contracts. Reuse the Apollo and Instantly clients from
the current connectivity composition. Do not introduce alternate supplier,
contact, company, decision, personalization, compliance or campaign stores.

At each boundary, translate only a bounded typed disposition into the runtime
stage row. Provider/network exception text and raw payloads never cross the
runtime boundary. Add fake-provider integration tests proving a full replayable
cycle and one failure at every boundary.

For staging provider work, inject a QA transport-recipient adapter into
`CampaignWorker`. It must require the explicit STAGING QA deployment contract,
bind the override by HMAC/fingerprint, use it consistently for create/readback
and reconciliation, and be impossible to configure in production. Tests must
prove the discovered address is never sent to the provider.

## Task 5 — Give Hermes closed, executable Kivou actions

Extend the supervisor adapter with the exact action registry identity and expose
that registry in health/connectivity evidence. Keep the Hermes subprocess tool
surface itself closed: no terminal or generic MCP/tool schema is passed across
the bridge.

The runner asks Hermes for the next bounded proposal, validates the pinned
version, skill, action index, budget and command, records the plan audit, then
dispatches through the Kivou registry. Zero/unknown/mismatched actions are
`BLOCKED`, never `READY`. Tests must prove that an allowed proposal executes and
that arbitrary commands, excessive cost and missing Hermes are rejected.

## Task 6 — Make runtime state authoritative for operations

Have `OperationsReadService` obtain pinned runtime identity and supervisor
heartbeat from the latest durable runtime cycle rather than caller-only
injection. Preserve honest autonomy readiness: a healthy QA/SHADOW loop may make
operational health `READY`, but it must not imply autonomous production
readiness or verified human review when those facts are absent.

Add tests for fresh/stale/no heartbeat, failed current cycle, missing dependency,
kill switch, open breaker and truthful SHADOW readiness.

## Task 7 — Version one service, one timer and one runbook

Add `kivou-acquisition.service` and `.timer` using the deployed checkout,
existing environment files, database lease plus host `flock`, a bounded timeout,
`Persistent=true`, randomized delay, non-overlapping execution and compatible
systemd hardening. Normal timer configuration must be safe QA/SHADOW.

Document installation, manual controlled cycle, health/readiness, log queries,
kill switch, rollback, migration downgrade and the exact external approvals
needed for the one staging E2E proof. Validate units with
`systemd-analyze verify`.

## Task 8 — Final local and PR evidence

Run targeted tests during development. On the final rebased-by-merge HEAD run
once:

```bash
uv run ruff check .
uv run pytest
systemd-analyze verify ops/systemd/kivou-acquisition.service \
  ops/systemd/kivou-acquisition.timer
git diff --check
```

Open one PR referencing #83 with cause, minimal correction, risks/rollback,
proofs and closure criteria. Do not run a provider, send a message, deploy or
change staging Policy as part of local implementation.
