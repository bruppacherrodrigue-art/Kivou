# SPEC-019 — Kivou Policy Gateway

Date: 2026-08-20
Branch: `feat/spec019-policy-gateway`
Base: `ea116a25d58bd5de9a80a607c22ad0c82bbd1b81`

## Architecture implemented

The new `signals.policy` package is the deterministic Kivou authorization boundary between validated advisory intents and future permissioned services:

```text
SupervisorPlan / ProposedAction (advisory)
        -> Kivou mapper
        -> immutable PolicyRequest + authoritative PolicySnapshot
        -> pure acquisition-policy-v1 evaluator
        -> immutable PolicyDecision
        -> atomic durable audit
```

There is no executor, provider client, command callable, queue, worker, scheduler, model call, network call, customer mutation or deployment path. `APPROVED` remains an evaluated result only and `requires_revalidation` is always true.

## Migration 0008

The single Alembic graph is:

```text
0007_acquisition_event_store
        -> 0008_policy_gateway
```

`0008_policy_gateway` is 19 characters, below the repository-wide 32-character limit. It creates exactly `acquisition_policy_snapshot` (append-only Kivou control history) and `policy_evaluation` (append-only universal authorization journal). No permissive control row is seeded. Tests cover fresh database to head, 0007 to 0008, Core/schema parity, SQLite execution, PostgreSQL offline DDL and unchanged prior tables.

## Effective snapshot selection and restart safety

At evaluation timestamp `T`, the store selects rows where `effective_at <= T` and `expires_at` is null or later than `T`, ordered by descending unique `control_revision`, limit one. Expired higher revisions and future revisions are ignored. No eligible row raises typed `PolicyControlUnavailable`; no default or expired fallback exists.

The append API requires a revision strictly greater than the current maximum and exposes no update/delete method. READ ONLY and kill switch live in the durable snapshot, so constructing a new store/process selects the same authoritative controls. Tests prove a later eligible emergency kill-switch revision immediately dominates.

## Contracts and command policy

`PolicyRequest`, `PolicySnapshot`, `PolicyControlSnapshot`, `ApprovalGrant` and `PolicyDecision` are frozen, extra-forbidden, bounded contracts. Symbolic commands accept only lowercase identifiers; malformed, empty, oversized, control-character and shell-like values fail validation. A syntactically valid unregistered command receives durable `DENIED / unknown_command`.

All eleven SPEC-017 command names have callable-free Kivou metadata and one of five risk classes: READ_ONLY, PREPARATORY, COMMERCIAL_MUTATION, RISK_REDUCTION or HUMAN_REVIEW. `classify_response` remains classification-only; it cannot unsubscribe, pause or mutate.

## Autonomy, READ ONLY and kill switch

- SHADOW requires exactly ASSISTED, AUTONOMOUS_CAPPED or ADAPTIVE_SCALE as target; recursive SHADOW and a target outside SHADOW are invalid.
- SHADOW never returns executable authorization. Counterfactual APPROVED becomes effective `DENIED / shadow_mode_execution_blocked`.
- ASSISTED commercial mutation requires an exact ACTION approval.
- AUTONOMOUS_CAPPED stays inside explicit commands/scopes/caps and cannot reallocate volume.
- ADAPTIVE_SCALE may reallocate only inside supplied wedge and caps.
- READ ONLY blocks positive mutation; kill switch dominates positive mutation regardless of autonomy, budget or approval.
- `pause_campaign`, `request_human_review` and `generate_weekly_report` retain exact safe exceptions. Pause ignores send quotas but requires the provider control plane.

## Multiple approval grants and compliance review

`approval_grants` is an immutable tuple limited to four. Each grant binds purpose, command, target, opportunity, action fingerprint, scope fingerprint, policy version, snapshot, control revision, issue/expiry, one-shot state and approver.

`COMPLIANCE_REVIEW` satisfies only `REVIEW_REQUIRED`; `ACTION` satisfies only the later commercial gate. An ASSISTED commercial mutation under compliance review needs both exact grants. Tests prove either grant alone is insufficient, both may pass remaining gates, and BLOCKED/UNKNOWN compliance cannot be overridden.

Every grant that actually satisfies a gate is now durably represented by an `ApprovalRef` containing only:

```text
approval_id
purpose
binding_fingerprint
```

`binding_fingerprint` is a Kivou-computed SHA-256 over the canonical safe fields used to bind the approval: purpose, command, target, opportunity, action fingerprint, scope fingerprint, policy version, snapshot, control revision, issue/expiry and one-shot/consumption state. It excludes arguments, prompts, reasoning and secrets. References are bounded to four and deterministically ordered. The universal `policy_evaluation.approval_refs` JSON and the opportunity-scoped `POLICY_EVALUATED` payload carry the same representation.

The deterministic dual-grant test proves an ASSISTED `schedule_campaign` with `REVIEW_REQUIRED` compliance records both `ACTION` and `COMPLIANCE_REVIEW` references with distinct purposes. Single-purpose tests prove neither purpose can masquerade as the other. Evaluations requiring no approval persist an empty list.

## Gate behavior and precedence

The evaluator is pure: no database, network, Hermes, clock, UUID or randomness. Precedence is fixed:

1. global safety;
2. version/command/scope/autonomy permission;
3. compliance, including exact review grant;
4. evidence;
5. cost/volume budget;
6. provider/mailbox/window/control-plane readiness;
7. separate ACTION approval;
8. SHADOW execution block.

Money is finite non-negative `Decimal`; exact cap boundaries pass, negative/NaN/infinity and currency mismatch fail closed. Evidence and compliance are typed authoritative readiness, never recomputed. Rate limiting copies `retry_after` only when supplied.

`valid_until` is informational and equals the earliest known authoritative boundary (snapshot, budget period, evidence/compliance/runtime or used approval); it is null when none exists. It is never an authorization TTL.

## Retry-safe audit and TOCTOU

Kivou supplies `evaluation_id` before transaction entry. Its maximum of 64 characters keeps `policy_evaluation:<evaluation_id>` within the SPEC-018 idempotency bound.

- same ID + the same complete semantic fingerprint returns the existing decision/event with no stream increment;
- same ID + different semantics raises `PolicyEvaluationIdempotencyConflict` with no mutation;
- a fresh ID reselects current controls and creates a new audit.

Snapshot selection now occurs before retry comparison. Consequently the same `evaluation_id` cannot return a stale durable result after the selected snapshot, control revision or kill switch changes; it fails with `PolicyEvaluationIdempotencyConflict`. A genuinely new `evaluation_id` reselects and evaluates the current controls. A future executor must still re-evaluate immediately; decisions are not bearer capabilities.

The canonical semantic fingerprint contains all authoritative evaluation inputs and excludes generated database timestamps, raw canonical arguments, transcripts and secrets. Its covered fields are:

```text
evaluation_id and request_id
command, target_ref, acquisition_opportunity_id, expected opportunity version
actor and supervisor provenance
action_fingerprint and typed scope
proposed cost, currency and volume
reason/evidence references
full evidence readiness, version, observation/freshness boundaries
full compliance state, version and observation/freshness boundaries
full operational quota/window/control-plane state, runtime revision and retry boundaries
expected policy version
normalized approval_id/purpose/binding-fingerprint set
selected policy snapshot ID, control revision and policy version
autonomy/shadow mode, READ ONLY, kill switch
allowlists/scopes and complete cost/volume budget envelope
current budget usage
evaluation timestamp
```

The retry conflict matrix proves that reusing an evaluation ID conflicts after: a control/snapshot revision change; kill switch activation; compliance `ALLOWED -> BLOCKED`; provider quota `READY -> EXHAUSTED`; budget-usage change; or approval-set/purpose change. Exactly identical complete inputs return one durable row and one opportunity event; reversing grant input order is semantically identical and does not increment the stream. A fresh ID produces a fresh audit against current controls.

Global actions use `policy_evaluation.acquisition_opportunity_id = NULL`. Opportunity actions atomically insert `policy_evaluation`, append `POLICY_EVALUATED`, and advance only acquisition audit/version metadata. Injected failures in either write direction commit neither half. An optimistic-concurrency conflict writes neither audit surface.

## SPEC-018 compatibility

`POLICY_EVALUATED` is additive under `acquisition-state-v1` and is state-, decision-, retry- and reference-neutral. Existing event streams replay unchanged. Appending it changes only `stream_version`, `last_event_id` and `updated_at`; no new state-machine version was required.

## Security and isolation

Arguments are bounded canonical JSON. Secret-looking and hidden-reasoning keys are rejected recursively while ordinary external text remains data. Audits persist no raw arguments, prompt, transcript, provider response, credential or chain of thought. Source review confirms no Apollo, Instantly, Stripe, SMTP, shell, tool or action-executor path.

Hermes is not imported by the evaluator/store/gateway. Its absence does not affect evaluation or persistence.

## Performance measurement

```text
evaluations:       1,000
elapsed wall time: 0.010402 seconds
mean:              0.010402 ms/evaluation
```

This is diagnostic, not an SLA.

## Tests and quality gates

```text
Backend:            2962 passed
Backend skipped:    0
Ruff:               PASS
git diff --check:   PASS

Frontend:           84 passed
Build:              PASS
Typecheck:          PASS
Lint:               PASS

GitHub CI:          PASS
CI run ID:          32328181815
Validated code SHA: b915fd295a022f76d67fdcb2772e36555fe0cdb9
Backend job:        PASS
Frontend job:       PASS
```

The backend count increased from the R1 entry baseline of 2955 and did not reduce the merged baseline. The 51 focused policy tests and all 2962 backend tests pass locally with zero skips. Frontend remains 84 tests with build, typecheck and lint green.

## Files changed

```text
src/signals/policy/
src/signals/acquisition/contracts.py
src/signals/acquisition/state.py
src/signals/acquisition/store.py
src/signals/persistence/schema.py
src/signals/persistence/migrations/versions/0008_policy_gateway_policy_gateway.py
tests/test_policy_*.py
tests/test_accounts_migration_and_ownership.py
tests/test_acquisition_migration.py
tests/test_billing_entitlements.py
tests/test_contract_award_text_capacity_migration.py
docs/reports/2026-08-20-spec019-policy-gateway-design.md
docs/reports/2026-08-20-spec019-policy-gateway-plan.md
docs/reports/2026-08-20-spec019-policy-gateway.md
```

Final PR diff at the validated executable head:

```text
24 files changed, 3488 insertions(+), 8 deletions(-)
git status --porcelain: clean after the executable commit
```

POLICY GATEWAY READY

PR #12 remains draft. No deployment or merge is authorized.
