# SPEC-018 — Event Store + Acquisition Opportunity State Machine — Design

Date: 2026-08-19
Status: APPROVED WITH SUPERVISOR CORRECTIONS INCORPORATED
Branch: `feat/spec018-acquisition-event-store`
Base: `main` at `c4d153c0e721836484f992da5c505e637af33290`
Current Alembic head: `0006_award_text_capacity`

## Objective

Create Kivou-owned durable memory for the future Acquisition Engine:

```text
validated Kivou intent
        ↓
append-only acquisition_event
        +
acquisition_opportunity current projection
        ↓
restart / replay / audit / explicit recovery
```

This foundation records business state. It executes no commercial action and introduces no Policy Gateway, Event Bus, DLQ, worker, Apollo, Instantly, outbound, customer API, frontend feature, or Hermes deployment.

## Entry state and migration decision

SPEC-016A-R2 is merged. `main` and `origin/main` are identical at `c4d153c0e721836484f992da5c505e637af33290`. Alembic has one head:

```text
0005_ingestion_runtime
        ↓
0006_award_text_capacity
```

SPEC-018 was paused before code or migration creation. Its additive migration is therefore:

```text
0006_award_text_capacity
        ↓
0007_acquisition_event_store
```

No parallel head is created.

## Alternatives considered

### 1. Dedicated acquisition domain + Core store — selected

Create a small `signals.acquisition` package containing strict contracts, a pure reducer, a SQLAlchemy Core store, and the safe SupervisorPlan audit mapper. Keep the two tables in the existing persistence metadata and create one linear migration.

This satisfies deterministic replay, transactional event/projection updates, replaceability, and PostgreSQL/SQLite compatibility without leaking acquisition state into procurement `opportunity_key` semantics.

### 2. Event journal only, projection on every read — rejected

This minimizes writes but fails the required durable current-state projection and makes operational review/retry queries depend on replaying every stream.

### 3. Generic event framework — rejected

A reusable event bus/store abstraction would add speculative routing, consumers, brokers, and generic serialization. SPEC-018 needs two tables and one bounded lifecycle, not a distributed event platform.

## Terminology boundary

Two objects remain deliberately distinct:

```text
procurement opportunity
  opportunity_key + opportunity_representation
  linked public-source identity used by customer signals

acquisition opportunity
  acquisition_opportunity_id + acquisition_event stream
  future Kivou acquisition workflow state
```

SPEC-018 does not rename, reuse, backfill, or modify the existing procurement opportunity model.

## Package boundaries

```text
src/signals/acquisition/
  contracts.py        strict values, event input/output, typed errors and bounds
  state.py            Kivou transition registry, pure reducer and replay
  store.py            SQLAlchemy Core transactions, idempotency and concurrency
  supervisor_audit.py safe SupervisorPlan → advisory event mapping
  __init__.py         narrow public API
```

Persistence declarations remain in `src/signals/persistence/schema.py` and one new migration. `signals.acquisition` may import the strict SPEC-017 `SupervisorPlan` contract, but never initializes or imports the Hermes runtime adapter.

## Acquisition Opportunity projection

Table: `acquisition_opportunity`.

```text
acquisition_opportunity_id  String(64) primary key
identity_key                String(256) unique, immutable
state                       String(32)
stream_version              Integer
state_machine_version       String(64)

signal_ref                  String(256)
supplier_ref                String(256) nullable
contact_ref                 String(256) nullable
campaign_ref                String(256) nullable

decision                    String(16) nullable
reason_codes                JSON
confidence                  Numeric(5,4) nullable
evidence_refs               JSON

next_action                 String(100) nullable
next_review_at              timezone-aware DateTime nullable
retry_count                 Integer
retry_at                    timezone-aware DateTime nullable
last_error_category         String(100) nullable

policy_version              String(100) nullable
skill_version               String(100) nullable
supervisor_version          String(100) nullable
estimated_cost              Numeric(18,6) nullable

last_event_id               String(64)
created_at                  timezone-aware DateTime
updated_at                  timezone-aware DateTime
```

`identity_key` is supplied by a future acquisition service and never recomputed. The store creates an internal UUID-hex ID through an injectable ID factory so tests remain deterministic. Creation requires `signal_ref`; supplier/contact/campaign references remain nullable opaque references. No future entity table is invented.

Indexes are limited to `identity_key UNIQUE`, `state`, `next_review_at`, and `retry_at`.

## Acquisition Event journal

Table: `acquisition_event`.

```text
event_id                    String(64) primary key
acquisition_opportunity_id  String(64) foreign key, RESTRICT
stream_sequence             Integer
event_type                  String(64)
schema_version              Integer
state_machine_version       String(64)

occurred_at                 timezone-aware DateTime
recorded_at                 timezone-aware DateTime
actor_type                  String(16)
actor_ref                   String(256) nullable

idempotency_key             String(128)
semantic_fingerprint        String(64)
correlation_id              String(64) nullable
causation_id                String(64) nullable

reason_codes                JSON
evidence_refs               JSON
policy_version              String(100) nullable
skill_version               String(100) nullable
supervisor_version          String(100) nullable
confidence                  Numeric(5,4) nullable
estimated_cost              Numeric(18,6) nullable
payload                     JSON
```

Database constraints include `UNIQUE(acquisition_opportunity_id, stream_sequence)` and `UNIQUE(acquisition_opportunity_id, idempotency_key)`. The same upstream token may therefore be reused for two different acquisition opportunities without conflating their business events. There is no event update/delete method. Append-only is enforced at the application boundary now; PostgreSQL role/trigger hardening remains a later operational option rather than cross-dialect SPEC-018 complexity.

## Controlled vocabularies

States:

```text
DISCOVERED ENRICHING READY_FOR_DECISION
HOLD NO_SEND REVIEW SEND
QUEUED SENT REPLIED ACTIVATED PAID RETAINED CHURNED
```

Decisions are `SEND`, `HOLD`, `ENRICH`, `NO_SEND`, `REVIEW`. Actors are `SYSTEM`, `HERMES`, `HUMAN`, `EXTERNAL`.

Foundational event types:

```text
OPPORTUNITY_CREATED
STATE_TRANSITIONED
DECISION_RECORDED
NEXT_ACTION_SET
RETRY_SCHEDULED
SUPERVISOR_PLAN_OBSERVED
OUTCOME_RECORDED
```

Strict application contracts own these values; storage uses strings instead of hard database enums so later event types do not require unsafe enum rewrites.

## State-machine version and transition registry

Kivou, never Hermes, owns the registry. Every event and the current projection persist the explicit version that determines replay semantics:

```text
state_machine_version = acquisition-state-v1
```

`schema_version`, `policy_version`, `skill_version`, and `supervisor_version` retain their separate meanings. Replay selects a registered reducer for each persisted `state_machine_version`; an unknown value raises `UnsupportedStateMachineVersion` rather than guessing current behavior. A later semantic change adds a new reducer version while keeping `acquisition-state-v1` available for historical streams.

The initial registry is:

```text
DISCOVERED         → ENRICHING
ENRICHING          → READY_FOR_DECISION

READY_FOR_DECISION → ENRICHING | HOLD | NO_SEND | REVIEW | SEND
HOLD               → ENRICHING | READY_FOR_DECISION | REVIEW | NO_SEND
REVIEW             → ENRICHING | HOLD | READY_FOR_DECISION | NO_SEND | SEND

SEND               → QUEUED
QUEUED             → SENT
```

Direct `DISCOVERED → READY_FOR_DECISION` is deliberately disabled because no acquisition service yet proves “sufficient data.” A later service may add it explicitly with its own test.

Decision mapping is fixed:

```text
ENRICH → ENRICHING
HOLD → HOLD
NO_SEND → NO_SEND
REVIEW → REVIEW
SEND → SEND
```

`record_decision()` records a supplied decision and never computes one. HOLD requires non-empty reason codes and `next_review_at`. `NO_SEND` cannot re-enter the send workflow; advisory audit/retry metadata may still be recorded without changing state. `CHURNED` is terminal.

## Out-of-order post-send outcomes

Post-send states have a monotonic rank:

```text
SEND < QUEUED < SENT < REPLIED < ACTIVATED < PAID < RETAINED < CHURNED
```

An `OUTCOME_RECORDED` event with a higher rank advances the projection, allowing absent intermediate milestones such as `SENT → ACTIVATED`. A lower/equal-rank outcome remains in audit history but does not regress the projection. `RETAINED → CHURNED` is allowed. Nothing advances out of `NO_SEND` or `CHURNED`.

## Pure reducer and replay

The reducer maps `AcquisitionProjection | None + AcquisitionEvent` to a new `AcquisitionProjection`. It performs no database, network, Hermes, clock, ID, or random operation. Event order must be contiguous `1..N`.

Every event advances `stream_version` and `last_event_id`; state-neutral audit and late lower-stage events leave business state unchanged. `replay(events)` dispatches each event to its persisted state-machine version and reconstructs the projection. Unknown versions fail closed. `verify_projection(id)` returns `MATCH` or `MISMATCH` without mutation. `rebuild_projection(id)` is an explicit transactional recovery operation and never runs during normal reads.

The rebuild test preserves the `RESTRICT` foreign key. It corrupts mutable projection fields (`state`, `stream_version`, and `next_action`) through controlled test SQL, proves `verify_projection()` reports `MISMATCH`, rebuilds transactionally, and confirms the immutable event rows are byte-for-byte unchanged.

## Atomicity and optimistic concurrency

Every mutation uses one bounded transaction. For an existing opportunity:

```text
1. load projection
2. resolve prior idempotency key within that opportunity
3. require expected_version
4. validate and reduce purely
5. conditional projection update WHERE stream_version = expected_version
6. insert event at expected_version + 1
7. commit
```

Zero updated rows raises `OpportunityConcurrencyConflict`. If event insertion fails, the projection update rolls back. This physical update-first ordering gives a typed race result while preserving the required atomic event+projection invariant.

Creation writes projection and `OPPORTUNITY_CREATED` within the same transaction. The initial projection is `DISCOVERED`, event sequence and stream version are both `1`, and both rows persist `acquisition-state-v1`.

## Idempotency

Every event operation requires an `idempotency_key`. Replay lookup is scoped by `(acquisition_opportunity_id, idempotency_key)`. A canonical semantic fingerprint covers event type, actor, explicitly supplied occurrence time, reasons, evidence, provenance versions, state-machine version, cost, and validated payload; opportunity scope comes from the database uniqueness key. It excludes expected version, generated event ID, and recorded time. When callers omit occurrence time, the store-generated clock value is deliberately excluded so an ordinary retry remains idempotent.

```text
same opportunity + same key + same fingerprint
  → existing event/result, no event, no version increment

same opportunity + same key + different fingerprint
  → IdempotencyConflict, no mutation

different opportunity + same key
  → allowed
```

Idempotency is checked before expected-version rejection so a retry stays successful after later stream events.

Creation is resolved through the immutable `identity_key` before an internal opportunity ID exists:

```text
same identity_key + same creation key + same fingerprint
  → existing opportunity and creation event

same identity_key + same creation key + different fingerprint
  → IdempotencyConflict

same identity_key + different creation key
  → AcquisitionIdentityConflict; never a second opportunity
```

## Payload and metadata guards

Payload is JSON-native, finite, and limited to 65,536 serialized UTF-8 bytes. Recursive normalized-key rejection covers credentials:

```text
password secret api_key authorization access_token refresh_token
session_token private_key client_secret bearer_token
```

Hidden-reasoning containers are also rejected:

```text
chain_of_thought reasoning_trace scratchpad internal_reasoning hidden_reasoning
```

Bounds are:

```text
reason_codes: max 50, each 1..100 characters
evidence_refs: max 100, each 1..100 characters
confidence: 0..1 inclusive
estimated_cost: >= 0
```

`next_action` must belong to Kivou's existing non-executable `ALLOWED_COMMANDS`. It is symbolic metadata, never shell text or a callable.

## Retry persistence

`schedule_retry()` appends `RETRY_SCHEDULED` and persists incremented `retry_count`, `retry_at`, and `last_error_category`. `set_next_action()` separately persists a validated Kivou command name. Neither stores raw stack traces. No retry worker, replay daemon, or DLQ is created.

## Hermes Shadow plan audit

`record_supervisor_plan(acquisition_opportunity_id, plan)` accepts an already validated SPEC-017 `SupervisorPlan`. Each proposed action's `target_ref` must resolve unambiguously to one acquisition opportunity by exact internal ID or unique `identity_key`; otherwise the whole audit request raises `SupervisorAuditMappingError` and writes no event. Actions mapped to other streams are omitted. Only actions mapped to the selected stream are stored, using:

```text
plan_id objective priority
proposed command names and target references
reason_codes evidence_refs estimated_cost
supervisor_version skill_version
```

It stores no action arguments, raw prompt, transcript, Hermes memory, provider data, or hidden reasoning. If no action maps to the selected opportunity, the deterministic rule is **no event written** and an explicit `recorded=False` result; metadata-only duplication is not useful in an opportunity stream. Otherwise it appends `SUPERVISOR_PLAN_OBSERVED` with actor `HERMES`. Stream version and audit pointer advance, while acquisition state, decision, next action, retry state, and references remain unchanged. No proposed action executes.

The event store imports no Hermes runtime and functions when Hermes is unavailable.

## Migration 0007

The strictly additive migration creates only `acquisition_opportunity`, `acquisition_event`, and justified indexes/constraints. It supports `0006 → 0007` and fresh database → head on SQLite, with PostgreSQL DDL validation. Existing migrations and SaaS tables remain unchanged. No signal or procurement opportunity is backfilled.

## Test strategy

TDD groups cover:

```text
strict contracts, numeric/size/secret/reasoning guards
pure reducer and transition matrix
persisted state-machine version and unknown-version rejection
decision mapping and HOLD requirements
post-send jumps and late lower-stage audit
creation and immutable identity
atomic event/projection behavior
sequence and optimistic concurrency
opportunity-scoped idempotency, conflicts, and cross-opportunity key reuse
creation idempotency and immutable identity conflicts
retry and next-action persistence
restart through a fresh store instance
replay, verification and explicit rebuild with the RESTRICT FK preserved
opportunity-scoped SupervisorPlan audit, mapping failures and zero-action no-op
Hermes-unavailable isolation
migration 0006 → 0007 and fresh → head
PostgreSQL/SQLite compatibility
100-event replay/load/verify measurement
```

Normal CI is deterministic, offline, and uses no real Hermes/model call.

## Baseline and non-regression

Fresh branch baseline after R2 merge:

```text
2826 backend tests passed
0 skipped
```

Frontend remains unchanged, but its 84-test/build/typecheck/lint gates will run before publication.

## Non-goals

SPEC-018 does not implement Policy Gateway, Event Bus, outbox, Kafka, Celery, Redis, DLQ, worker, Supplier/Contact/Campaign tables, Apollo, Instantly, outbound, email, Stripe mutation, customer acquisition API, frontend, automatic repair, historical acquisition backfill, VPS, systemd, or deployment changes.

## Design verdict

The selected design is the smallest compliant implementation: two additive tables, one strict domain package, one pure reducer, and one transactional Core store. Kivou owns durable facts, transitions, idempotency, concurrency and audit; Hermes contributes only optional Shadow-plan input.
