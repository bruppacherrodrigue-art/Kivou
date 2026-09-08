# SPEC-018 — Kivou Event Store + Acquisition Opportunity State Machine

Date: 2026-08-19
Branch: `feat/spec018-acquisition-event-store`
Base: `main` at `c4d153c0e721836484f992da5c505e637af33290`
Status: READY — DRAFT PR #11 / CI GREEN

## Result

SPEC-018 now provides Kivou-owned durable acquisition memory without executing any acquisition action. One append-only event stream and one current-state projection support atomic writes, scoped idempotency, optimistic concurrency, restart, deterministic replay, verification, and explicit recovery.

It adds no Event Bus, Policy Gateway, Apollo, Instantly, outbound, worker, DLQ, customer API, frontend feature, or Hermes deployment.

## Terminology audit

The existing procurement opportunity remains unchanged:

```text
opportunity_key + opportunity_representation
→ linked public-procurement identity used by signals
```

SPEC-018 introduces a separate object:

```text
acquisition_opportunity_id + acquisition_event stream
→ future Acquisition Engine workflow identity and durable state
```

No procurement opportunity, signal, or historical SaaS row is renamed, reused, or backfilled into acquisition state.

## Implemented architecture

```text
validated Kivou intent
        ↓
AcquisitionStore transaction
        ↓
acquisition_event (append-only journal)
        +
acquisition_opportunity (current projection)
        ↓
restart / replay / verify / explicit rebuild
```

The new `signals.acquisition` domain contains:

- `contracts.py`: bounded values, vocabularies, payload guards, typed errors;
- `state.py`: Kivou-owned transition registry, reducer selection, pure replay;
- `store.py`: SQLAlchemy Core transactions, idempotency, concurrency, recovery;
- `supervisor_audit.py`: opportunity-scoped, non-executing `SupervisorPlan` audit.

## Acquisition Opportunity projection

`acquisition_opportunity` persists:

```text
immutable acquisition_opportunity_id and identity_key
state, stream_version, state_machine_version
signal_ref; nullable supplier/contact/campaign refs
decision, reasons, confidence, evidence
next_action, next_review_at
retry_count, retry_at, last_error_category
policy/skill/supervisor versions
estimated_cost, last_event_id, created_at, updated_at
```

Identity references are opaque. No Supplier, Contact, or Campaign table was invented. Monetary/cost data uses `Numeric(18,6)`, not floating point. Confidence is bounded to `[0,1]`; estimated cost is non-negative in both application contracts and portable DB checks.

Indexes are limited to unique `identity_key`, `state`, `next_review_at`, and `retry_at`.

## Event schema and append-only boundary

`acquisition_event` persists:

```text
event_id, acquisition_opportunity_id, stream_sequence
event_type, schema_version, state_machine_version
occurred_at, recorded_at, bounded actor identity
scoped idempotency key and semantic fingerprint
correlation/causation IDs
reasons, evidence, confidence, version provenance, cost
bounded structured payload
```

Database uniqueness protects:

```text
(acquisition_opportunity_id, stream_sequence)
(acquisition_opportunity_id, idempotency_key)
```

The application exposes append/read operations only. There is no event update/delete API. PostgreSQL role or trigger hardening remains an operational option; it was not added because SPEC-018 must stay portable across PostgreSQL and SQLite without fragile dialect-specific behavior.

## State-machine version strategy

Every event and projection persists:

```text
state_machine_version = acquisition-state-v1
```

This is deliberately separate from event `schema_version`, policy, skill, and supervisor versions. Replay dispatches through a reducer registry using the persisted version. An unknown historical version raises `UnsupportedStateMachineVersion`; it is never reinterpreted with today’s reducer. Future semantic changes must add a version while preserving the v1 reducer.

## State and transition behavior

Implemented pre-send transitions:

```text
DISCOVERED         → ENRICHING
ENRICHING          → READY_FOR_DECISION
READY_FOR_DECISION → ENRICHING | HOLD | NO_SEND | REVIEW | SEND
HOLD               → ENRICHING | READY_FOR_DECISION | REVIEW | NO_SEND
REVIEW             → ENRICHING | HOLD | READY_FOR_DECISION | NO_SEND | SEND
SEND               → QUEUED
QUEUED             → SENT
```

Direct `DISCOVERED → READY_FOR_DECISION` is not enabled because no acquisition service yet proves sufficient enrichment. Kivou, not Hermes, owns these transitions.

Decision recording maps only the approved values:

```text
ENRICH → ENRICHING
HOLD → HOLD
NO_SEND → NO_SEND
REVIEW → REVIEW
SEND → SEND
```

`record_decision()` records; it does not decide or execute. HOLD requires a meaningful reason and timezone-aware `next_review_at`. NO_SEND cannot silently re-enter SEND. CHURNED is terminal for the current lifecycle.

Post-send outcomes use monotonic progression:

```text
SEND < QUEUED < SENT < REPLIED < ACTIVATED < PAID < RETAINED < CHURNED
```

Forward jumps such as `SENT → ACTIVATED` are accepted. A late `REPLIED` after `ACTIVATED` is appended to audit history and advances stream version, but the projected state remains `ACTIVATED`; `ACTIVATED → PAID` then proceeds normally.

## Atomicity and concurrency

Every change is bounded to one transaction. The store validates and reduces the event, conditionally updates the projection using `WHERE stream_version = expected_version`, then inserts the event before commit. Any event insert failure rolls the projection update back. Creation inserts the initial projection and `OPPORTUNITY_CREATED` event in one transaction.

Two workers reading version 3 cannot both win. The first produces version 4; the second gets `OpportunityConcurrencyConflict`, creates no event 5, and leaves the projection correct.

## Scoped and creation idempotency

Event replay is scoped by opportunity:

```text
same opportunity + same key + same semantic fingerprint
→ existing event/result; no version increment

same opportunity + same key + different semantics
→ IdempotencyConflict; no mutation

different opportunity + same key
→ allowed
```

The fingerprint includes event type, actor, validated payload, explicit occurrence time when supplied, reasons/evidence, provenance versions, confidence, cost, and correlation metadata. Generated event ID, recorded time, and expected version are excluded.

Creation has an explicit pre-ID rule:

```text
same identity_key + same creation key + same semantics
→ one opportunity and one creation event

same identity_key + same creation key + different semantics
→ IdempotencyConflict

same identity_key + different creation key
→ AcquisitionIdentityConflict; no second opportunity
```

Repeated retry, restart, and audit tests prove sequence and identity stability.

## Retry and next action

`set_next_action()` accepts only Kivou’s non-executable allowed command names; arbitrary shell text fails closed. `schedule_retry()` appends an idempotent event and persists:

```text
retry_count
retry_at
last_error_category
```

No raw exception trace is stored. A fresh store instance reloads these fields and continues from the exact next stream sequence. No retry worker or DLQ was introduced.

## Pure replay, verification, and explicit rebuild

The reducer has no network, database, Hermes, clock, ID, or randomness dependency. Events must be contiguous from sequence 1.

`verify_projection(id)` replays the stream and returns `MATCH` or `MISMATCH` without mutation. `rebuild_projection(id)` is an explicit internal transactional recovery operation; normal reads never repair silently.

The rebuild regression deliberately corrupts mutable projection fields (`state`, `stream_version`, `next_action`), preserves the `RESTRICT` foreign key and event history, observes `MISMATCH`, rebuilds, then obtains an exact replay match. Event rows remain unchanged.

## Hermes Shadow plan audit

`record_supervisor_plan(acquisition_opportunity_id, plan)` accepts the strict SPEC-017 plan contract but imports no Hermes runtime. Every action target must map unambiguously by exact acquisition ID or unique identity key. Unknown or ambiguous targets reject the whole audit with `SupervisorAuditMappingError` and no event.

Only actions belonging to the selected opportunity are stored. Other opportunities’ actions are omitted. If zero actions belong to the selected stream, the deterministic result is `recorded=false` and no event/version increment.

Stored fields are limited to safe plan metadata, command names, target references, reason codes, evidence refs, cost and version provenance. Action arguments, raw prompts, model transcripts, hidden reasoning, provider credentials, and Hermes memory are not stored. `SUPERVISOR_PLAN_OBSERVED` is state-neutral and has no executor path. A test forces the Hermes adapter to fail and proves the event store, state machine, and replay remain available.

## Payload safety

Payloads must be finite JSON and at most 65,536 serialized UTF-8 bytes. Recursive normalized-key validation rejects credential containers including passwords, secrets, API keys, authorization, access/refresh/session tokens and private keys. It also rejects hidden-reasoning containers such as chain of thought, reasoning trace, scratchpad, internal reasoning, and hidden reasoning.

Limits are:

```text
reason_codes: <= 50, each <= 100 characters
evidence_refs: <= 100, each <= 100 characters
confidence: 0..1
estimated_cost: >= 0
```

Oversized or prohibited events fail before persistence; projection state does not change.

## Migration 0007

The migration graph is one linear head:

```text
0006_award_text_capacity
        ↓
0007_acquisition_event_store
```

Migration `0007_acquisition_event_store` creates only `acquisition_opportunity`, `acquisition_event`, their constraints and justified indexes. Tests prove populated `0006 → 0007`, fresh database → head, exact Core/migration column alignment, `RESTRICT` FK, scoped uniqueness, and PostgreSQL offline DDL. Previous migrations and SaaS tables are unchanged.

## Deterministic results

Implemented tests prove:

```text
creation and immutable identity                         PASS
atomic event + projection                              PASS
contiguous event sequencing                            PASS
scoped idempotency / conflict / cross-stream reuse     PASS
optimistic concurrency                                 PASS
approved transitions and decision mapping              PASS
HOLD review requirement / NO_SEND safety               PASS
retry and next-action persistence                      PASS
restart with exact next sequence                       PASS
pure replay and unknown reducer rejection              PASS
projection verification and explicit rebuild           PASS
SENT → ACTIVATED; late REPLIED no regression           PASS
opportunity-scoped SupervisorPlan audit                PASS
Hermes unavailable isolation                           PASS
secret / hidden-reasoning / payload-size guards        PASS
migration 0007                                         PASS
```

No live internet or real model invocation is used.

## Replay performance measurement

One deterministic SQLite opportunity with 100 events (1 creation + 99 state-neutral advisory audit events) produced:

```text
event load:          7.141 ms
pure replay:         0.354 ms
projection verify:   7.382 ms
combined:            14.877 ms
result:              MATCH, state DISCOVERED, stream_version 100
```

This is a diagnostic local measurement, not a performance SLA. No caching infrastructure was added.

## Full regression

Backend:

```text
uv run pytest -q       2911 passed, 0 skipped
uv run ruff check .    PASS
git diff --check       PASS
```

Frontend (unchanged):

```text
npm test -- --run      84 passed
npm run build          PASS
npx tsc -b             PASS
npm run lint           PASS
```

## Side-effect boundary

Confirmed absent from this SPEC:

```text
external command executor
generic shell/tool access
Apollo / Instantly / SMTP / Stripe calls
customer mutation or customer API
Event Bus / Policy Gateway / DLQ / worker / scheduler
Hermes memory as business authority
VPS, ops, systemd, deployment, frontend feature work
```

## Files changed

```text
src/signals/acquisition/__init__.py
src/signals/acquisition/contracts.py
src/signals/acquisition/state.py
src/signals/acquisition/store.py
src/signals/acquisition/supervisor_audit.py
src/signals/persistence/schema.py
src/signals/persistence/migrations/versions/0007_acquisition_event_store_acquisition_event_store.py
tests/test_acquisition_contracts.py
tests/test_acquisition_migration.py
tests/test_acquisition_replay.py
tests/test_acquisition_state.py
tests/test_acquisition_store.py
tests/test_acquisition_supervisor_audit.py
tests/test_accounts_migration_and_ownership.py
tests/test_billing_entitlements.py
tests/test_contract_award_text_capacity_migration.py
tests/test_ingestion_migration.py
docs/reports/2026-08-19-spec018-event-store-opportunity-state-machine-design.md
docs/reports/2026-08-19-spec018-event-store-opportunity-state-machine-plan.md
docs/reports/2026-08-19-spec018-event-store-opportunity-state-machine.md
```

## Git and GitHub CI

```text
branch: feat/spec018-acquisition-event-store
draft PR: #11 https://github.com/bruppacherrodrigue-art/Kivou/pull/11
validated executable SHA: 191293c44d2a1667ad4a2d24627d9210c78e07ef
GitHub Actions run: 32305295994 — SUCCESS
backend job: PASS (tests + Ruff)
frontend job: PASS (84 tests + build + typecheck + lint)
validated diff stat: 20 files changed, 3829 insertions, 11 deletions
git status --porcelain at validated executable SHA: empty
```

The branch is not merged and nothing is deployed.

ACQUISITION EVENT STORE READY
