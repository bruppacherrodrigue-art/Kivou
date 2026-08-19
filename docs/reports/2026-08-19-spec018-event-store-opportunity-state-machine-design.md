# SPEC-018 — Event Store + Acquisition Opportunity State Machine — Design

Date: 2026-08-19
Status: DESIGN FOR REVIEW
Branch: `feat/spec018-acquisition-event-store`
Base: `main` at `2bb72ef8e1b7598248f0a1422c0e6005f6a42362`
Current Alembic head: `0006_contract_award_text_capacity`

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

SPEC-016A-R1 is merged. `main` and `origin/main` are identical at `2bb72ef8e1b7598248f0a1422c0e6005f6a42362`. Alembic has one head:

```text
0005_ingestion_runtime
        ↓
0006_contract_award_text_capacity
```

SPEC-018 was paused before code or migration creation. Its additive migration is therefore:

```text
0006_contract_award_text_capacity
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

signal_ref                  String(128)
supplier_ref                String(128) nullable
contact_ref                 String(128) nullable
campaign_ref                String(128) nullable

decision                    String(16) nullable
reason_codes                JSON
confidence                  Numeric(5,4) nullable
evidence_refs               JSON

next_action                 String(64) nullable
next_review_at              timezone-aware DateTime nullable
retry_count                 Integer
retry_at                    timezone-aware DateTime nullable
last_error_category         String(64) nullable

policy_version              String(100) nullable
skill_version               String(100) nullable
supervisor_version          String(100) nullable
estimated_cost              Numeric(18,6) nullable

last_event_id               String(64)
created_at                  timezone-aware DateTime
updated_at                  timezone-aware DateTime
```

`identity_key` is supplied by a future acquisition service and never recomputed. The store creates an internal `acq_<uuid hex>` ID through an injectable ID factory so tests remain deterministic. Creation requires `signal_ref`; supplier/contact/campaign references remain nullable opaque references. No future entity table is invented.

Indexes are limited to `identity_key UNIQUE`, `state`, `next_review_at`, and `retry_at`.

## Acquisition Event journal

Table: `acquisition_event`.

```text
event_id                    String(64) primary key
acquisition_opportunity_id  String(64) foreign key, RESTRICT
stream_sequence             Integer
event_type                  String(64)
schema_version              Integer

occurred_at                 timezone-aware DateTime
recorded_at                 timezone-aware DateTime
actor_type                  String(16)
actor_ref                   String(256) nullable

idempotency_key             String(128) unique
semantic_fingerprint        String(64)
correlation_id              String(64) nullable
causation_id                String(64) nullable

reason_codes                JSON
evidence_refs               JSON
policy_version              String(100) nullable
skill_version               String(100) nullable
supervisor_version          String(100) nullable
estimated_cost              Numeric(18,6) nullable
payload                     JSON
```

Database constraints include `UNIQUE(acquisition_opportunity_id, stream_sequence)` and `UNIQUE(idempotency_key)`. There is no event update/delete method. Append-only is enforced at the application boundary now; PostgreSQL role/trigger hardening remains a later operational option rather than cross-dialect SPEC-018 complexity.

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

## Transition registry

Kivou, never Hermes, owns one versioned registry:

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

`record_decision()` records a supplied decision and never computes one. HOLD requires non-empty reason codes and `next_review_at`. `NO_SEND` accepts state-neutral audit events only and cannot re-enter send workflow. `CHURNED` is terminal.

## Out-of-order post-send outcomes

Post-send states have a monotonic rank:

```text
SEND < QUEUED < SENT < REPLIED < ACTIVATED < PAID < RETAINED < CHURNED
```

An `OUTCOME_RECORDED` event with a higher rank advances the projection, allowing absent intermediate milestones such as `SENT → ACTIVATED`. A lower/equal-rank outcome remains in audit history but does not regress the projection. `RETAINED → CHURNED` is allowed. Nothing advances out of `NO_SEND` or `CHURNED`.

## Pure reducer and replay

The reducer maps `AcquisitionProjection | None + AcquisitionEvent` to a new `AcquisitionProjection`. It performs no database, network, Hermes, clock, ID, or random operation. Event order must be contiguous `1..N`.

Every event advances `stream_version` and `last_event_id`; state-neutral audit and late lower-stage events leave business state unchanged. `replay(events)` reconstructs the projection. `verify_projection(id)` returns `MATCH` or `MISMATCH` without mutation. `rebuild_projection(id)` is an explicit transactional recovery operation and never runs during normal reads.

## Atomicity and optimistic concurrency

Every mutation uses one bounded transaction. For an existing opportunity:

```text
1. resolve prior idempotency key
2. load projection
3. require expected_version
4. validate and reduce purely
5. conditional projection update WHERE stream_version = expected_version
6. insert event at expected_version + 1
7. commit
```

Zero updated rows raises `OpportunityConcurrencyConflict`. If event insertion fails, the projection update rolls back. This physical update-first ordering gives a typed race result while preserving the required atomic event+projection invariant.

Creation writes projection and `OPPORTUNITY_CREATED` within the same transaction. The initial projection is `DISCOVERED`, event sequence and stream version are both `1`, and the creation idempotency key obeys the same same-content/different-content rules as every later event.

## Idempotency

Every event operation requires an `idempotency_key`. A canonical semantic fingerprint covers opportunity, event type, actor, occurrence time, reasons, evidence, provenance versions, cost, and validated payload; it excludes expected version, generated event ID, and recorded time.

```text
same key + same fingerprint
  → existing event/result, no event, no version increment

same key + different fingerprint
  → IdempotencyConflict, no mutation
```

Idempotency is checked before expected-version rejection so a retry stays successful after later stream events.

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
```

`next_action` must belong to Kivou's existing non-executable `ALLOWED_COMMANDS`. It is symbolic metadata, never shell text or a callable.

## Retry persistence

`schedule_retry()` appends `RETRY_SCHEDULED` and persists incremented `retry_count`, `retry_at`, `last_error_category`, and validated `next_action`. It stores no raw stack trace. No retry worker, replay daemon, or DLQ is created.

## Hermes Shadow plan audit

`record_supervisor_plan()` accepts an already validated SPEC-017 `SupervisorPlan` and maps only:

```text
plan_id objective priority
proposed command names and target references
reason_codes evidence_refs estimated_cost
supervisor_version skill_version
```

It stores no action arguments, raw prompt, transcript, Hermes memory, provider data, or hidden reasoning. It appends `SUPERVISOR_PLAN_OBSERVED` with actor `HERMES`. Stream version and audit pointer advance, while acquisition state, decision, next action, retry state, and references remain unchanged. No proposed action executes.

The event store imports no Hermes runtime and functions when Hermes is unavailable.

## Migration 0007

The strictly additive migration creates only `acquisition_opportunity`, `acquisition_event`, and justified indexes/constraints. It supports `0006 → 0007` and fresh database → head on SQLite, with PostgreSQL DDL validation. Existing migrations and SaaS tables remain unchanged. No signal or procurement opportunity is backfilled.

## Test strategy

TDD groups cover:

```text
strict contracts, size/secret/reasoning guards
pure reducer and transition matrix
decision mapping and HOLD requirements
post-send jumps and late lower-stage audit
creation and immutable identity
atomic event/projection behavior
sequence and optimistic concurrency
same/different idempotency replay
retry and next-action persistence
restart through a fresh store instance
replay, verification and explicit rebuild
SupervisorPlan advisory audit with zero execution/state mutation
Hermes-unavailable isolation
migration 0006 → 0007 and fresh → head
PostgreSQL/SQLite compatibility
100-event replay/load/verify measurement
```

Normal CI is deterministic, offline, and uses no real Hermes/model call.

## Baseline and non-regression

Fresh branch baseline after R1 merge:

```text
2824 backend tests passed
0 skipped
```

Frontend remains unchanged, but its 84-test/build/typecheck/lint gates will run before publication.

## Non-goals

SPEC-018 does not implement Policy Gateway, Event Bus, outbox, Kafka, Celery, Redis, DLQ, worker, Supplier/Contact/Campaign tables, Apollo, Instantly, outbound, email, Stripe mutation, customer acquisition API, frontend, automatic repair, historical acquisition backfill, VPS, systemd, or deployment changes.

## Design verdict

The selected design is the smallest compliant implementation: two additive tables, one strict domain package, one pure reducer, and one transactional Core store. Kivou owns durable facts, transitions, idempotency, concurrency and audit; Hermes contributes only optional Shadow-plan input.
