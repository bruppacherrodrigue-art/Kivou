# SPEC-023 — Deterministic Acquisition Decision Engine

Date: 2026-08-20
Status: implementation complete; PR #19 remains DRAFT and unmerged

## Closeout identity

- Design audit base: `55906b7da2ea965749cf97fcde5639608760e7a7`
- Authoritative implementation base (`origin/main`): `25bc0ab22bd70819cbd71003c6222bd9ddedec87`
- The intervening main change was the supervisor-audited frontend/public-demo and P0-01 evaluation change; no acquisition, policy, or persistence contract changed.
- Executable SHA: `0c5a33548b615b20b9066d601262973cd839d6ba`
- Executable CI: `32413853200` — SUCCESS
- Branch: `feat/spec023-decision-engine`
- PR: #19, DRAFT
- Alembic head: `0012_decision_engine`

## Frozen commercial contract

`decision-policy-v1` is an immutable, callable-free rule configuration. It emits only:

- `SEND`: commercially eligible to proceed to campaign preparation; this is not email, legal, compliance, mailbox, send-window, or deliverability authorization.
- `REVIEW`: valid business evidence contains a bounded ambiguity requiring human review.
- `NO_SEND`: valid public timing evidence falls outside the acquisition window.

`HOLD` and `ENRICH` remain domain enum values but are disabled and cannot be emitted by v1. No score, probability, weighted model, confidence percentage, LLM, or benchmark tuning exists. Event confidence is `NULL`.

The supervisor-frozen recency threshold is 60 calendar days, inclusive:

- `age_days <= 60`: eligible for `SEND` after all higher-priority rules pass.
- `age_days > 60`: `NO_SEND`.

The separate public-date integrity ceiling is `max_plausible_public_age_days = 3650`. It reuses Kivou's existing `IMPLAUSIBLE_AWARD_AGE_DAYS` data-quality guard for known SIMAP and BOAMP/eForms filler anomalies. This parameter is versioned in `decision-policy-v1` and participates in both the policy-configuration and decision-input fingerprints; it does not alter the frozen 60-day commercial threshold.

The exact state/action mapping is:

| Decision | State | Next action |
|---|---|---|
| `SEND` | `SEND` | `prepare_campaign` |
| `REVIEW` | `REVIEW` | `request_human_review` |
| `NO_SEND` | `NO_SEND` | `NULL` |

No stale `evaluate_opportunity` action survives a recorded v1 decision.

## Authoritative clock and recency

`DecisionEngineService` owns an injected timezone-aware Kivou clock. For a new evaluation it captures `decision_evaluated_at` exactly once after idempotency/crash preflight, derives `as_of_date` from that instant in UTC, and passes the same instant to Policy Gateway. Hermes and callers cannot provide either `evaluated_at` or `as_of_date`. The pure evaluator contains no clock.

`acquisition-recency-v1` applies the frozen precedence:

1. `AWARD_DATE` when an authoritative award date is present.
2. `CONTRACT_NOTIFICATION_DATE` only when award date is absent.
3. `PUBLICATION_DATE` only when both higher-order dates are absent.
4. `UNRESOLVED` when all three are absent.

`discovered_at` never establishes freshness and is excluded from the public-context freshness fingerprint. A present but inconsistent higher-precedence date does not fall back to a lower-order date. Future selected dates, selected dates older than 3650 days, and award/publication contradictions beyond the one-day tolerance produce `REVIEW / PUBLIC_TIMING_INCONSISTENT`. Thus placeholder dates such as `1970-01-01` and `2000-01-01`, and the known `2002-08-17` anomaly when evaluated in 2026, cannot become an ordinary stale `NO_SEND` and cannot fall back to a recent publication date. A legitimate 61-day-old public clock remains `NO_SEND`.

Publication values preserve their actual source precision. A `date` remains that exact date, and a timezone-aware `datetime` is converted to its UTC calendar date. A naive publication `datetime` is not silently localized: it raises `DecisionPublicContextNotResolvable` before the initial Policy Gateway evaluation. If encountered during final post-policy revalidation, it becomes `DecisionInputChanged`, preventing a stale decision commit.

Notification and publication fallback remain explicit bases and add `RECENCY_NOTIFICATION_FALLBACK` or `RECENCY_PUBLICATION_FALLBACK` to successful `SEND` proposals.

## Shared public resolver extraction

The public-only core is now exposed as:

- `resolve_public_acquisition_context(...)`
- `resolve_public_acquisition_context_in_transaction(connection, ...)`

It preserves the existing representative-award ordering exactly: completeness descending, publication descending, award key ascending. `resolve_acquisition_seed()` delegates to the shared core and then performs the existing `ContractUnderstanding` and frozen Need Graph work.

Regression fixtures compare the complete pre/post extraction seed output: signal reference, opportunity key, representative award key, event, award, public evidence, understanding, and needs. The connection-aware path returns the same deterministic public result and is used for final in-transaction decision revalidation.

## Decision input and rule matrix

`AcquisitionDecisionInput` is immutable, PII-free, versioned as `acquisition-decision-input-v1`, and validates recency consistency at its boundary. It includes the exact opportunity/supplier/contact bindings; current and profile supplier identity; safe contact verification and role versions/tiers; company prebuild identity; bounded public dates and evidence; research quality; size context; policy configuration identity; and its own fingerprint.

The ordered rule matrix is:

1. Profile/current supplier identity mismatch → `REVIEW / SUPPLIER_IDENTITY_CHANGED_SINCE_RESEARCH`.
2. Current `DOMAIN_CONFLICT` → `REVIEW / SUPPLIER_DOMAIN_CONFLICT`.
3. Unresolved recency → `REVIEW / RECENCY_UNRESOLVED`.
4. Future or contradictory public timing → `REVIEW / PUBLIC_TIMING_INCONSISTENT`.
5. Age greater than 60 days → `NO_SEND / SIGNAL_OUTSIDE_ACQUISITION_WINDOW`.
6. Otherwise → `SEND / SIGNAL_WITHIN_ACQUISITION_WINDOW`, followed deterministically by `SUPPLIER_IDENTITY_ACCEPTABLE`, `VERIFIED_COMMERCIAL_CONTACT`, and `ACQUISITION_PREBUILD_AVAILABLE`, plus an explicit fallback reason when applicable.

Reasons are stable codes, unique, ordered, and bounded to eight. Evidence is deterministic and bounded to 16 refs, using only award, source event, company profile, supplier, and contact references. No free-form reasoning or contact PII is persisted.

`LIMITED` research, size band, missing optional company facts, and contact role tier 4 are context only and do not independently block `SEND`.

## Four distinct fingerprints

The implementation keeps four semantic identities separate:

1. `decision_policy_config_fingerprint`: frozen callable-free rule configuration.
2. `decision_input_fingerprint`: every safe fact and derivation that can affect the result, including public context, `as_of_date`, current bindings, and company prebuild fingerprint.
3. `proposal_fingerprint`: input identity plus decision, reasons, evidence, next action, and next-review semantics.
4. `PolicyRequest.action_fingerprint`: command, opportunity, supplier, contact, and exact proposal fingerprint.

The public context has its own bounded fingerprint over opportunity key, representative award, source event, public dates, and public evidence refs. Timestamps unrelated to business meaning, raw documents, Need Graph output, customer data, and `discovered_at` freshness are excluded.

## Policy Gateway integration and replay integrity

`evaluate_opportunity` is now:

- risk class `PREPARATORY`
- target scope `OPPORTUNITY`
- evidence: `PUBLIC_OPPORTUNITY`, `PUBLIC_EVIDENCE`, `ACQUISITION_PROSPECT_PREBUILD`, `VERIFIED_CONTACT`, `DECISION_INPUT`
- no budget, volume, provider-quota, control-plane, send-control, or compliance gate

The proposal is computed before Policy Gateway. Policy decides only whether that exact deterministic proposal may mutate acquisition state; it does not choose `SEND`, `REVIEW`, or `NO_SEND`.

Existing decision-audit replay reconstructs and verifies the complete immutable Policy Gateway semantic fingerprint, including actor, scope, evidence/readiness, policy snapshot, and budget usage. It uses the original immutable control snapshot rather than a potentially newer effective snapshot. Historical budget usage is reconstructed from the durable snapshot caps and stored decision remainders (`cap - remaining`), never from the replay caller's current global usage. Therefore unrelated later budget activity cannot break an exact completed-decision replay, while changed actor, scope, evidence, operational, request, or action semantics still produce `DecisionEvaluationIdempotencyConflict`.

Policy Decimal fingerprinting is now numeric rather than scale-sensitive for new evaluations. Replay remains compatible with pre-R1 durable hashes through a bounded legacy Decimal encoding check over the six persisted monetary decimal places; this avoids invalidating already-recorded policy evaluations while preserving full semantic authorization checks.

If a policy evaluation exists without a decision audit, the service returns `DecisionEvaluationRequiresFreshAttempt`; an old approved decision is never reused. A new attempt requires a new evaluation ID, fresh clock capture, fresh input/proposal, and fresh policy evaluation.

## SHADOW and policy-blocked behavior

A non-executable Policy decision, including SHADOW, persists the exact proposal in `acquisition_decision_evaluation` with disposition `POLICY_BLOCKED`. The bounded transaction verifies the durable policy evaluation and exact action fingerprint before inserting the audit.

It does not append `DECISION_RECORDED` and does not mutate decision, state, or next action. The audit is historical comparison data, never an execution token.

## Migration 0012

The linear graph is:

`0011_company_research -> 0012_decision_engine`

Exactly one table is added: `acquisition_decision_evaluation`.

The table is append-only and stores a deterministic evaluation ID derived from `policy_evaluation_id`, exact input/proposal/policy identities, bounded PII-free decision input JSON, recency fields, reasons/evidence, proposed action, expected post-policy stream version, disposition, and optional recorded event reference. It enforces unique policy evaluation and recorded event references, restrictive foreign keys, resolved/unresolved recency consistency, decision/action mappings, and recorded/blocked disposition consistency.

Fresh database, 0011-to-0012 upgrade, PostgreSQL offline SQL, single-head topology, schema parity, constraints, and downgrade to 0011 are covered. No score, reason, evidence, feature, run, queue, or event-bus table was added.

## Additive `DECISION_RECORDED` compatibility

No new Acquisition `EventType` was added. `acquisition-state-v1` remains current.

Historical `DECISION_RECORDED` payloads without `next_action` retain the exact previous reducer path and replay projection. The new path activates only when `next_action` is present, rejects unexpected payload keys, requires v1 decision/action mapping, requires bounded reasons/evidence, requires `confidence = NULL`, and atomically updates decision, state, and next action.

Historical streams are replay-tested before and after the extension, and unknown event types continue to fail closed.

## Transaction and concurrency boundary

After Policy Gateway appends `POLICY_EVALUATED` (`V -> V+1`), an executable decision uses one caller-owned transaction to:

1. lock/reload the opportunity and require `V+1`, `READY_FOR_DECISION`, and `evaluate_opportunity`;
2. reload supplier, safe contact binding, company profile, and public context through the same connection;
3. rebuild the decision input with the same captured `as_of_date` and frozen config;
4. rebuild the proposal and require identical input/proposal fingerprints;
5. append `DECISION_RECORDED`;
6. insert the `RECORDED` decision audit with the event ID;
7. commit at `V+2`.

Any material opportunity, supplier, contact, profile, or public-context change becomes `DecisionInputChanged`; no stale decision is recorded. Event, projection, and audit failures roll back together. No global `SERIALIZABLE` mode, ingestion lock, retry system, or last-write-wins behavior was introduced.

Review hardening additionally closes full replay-authorization validation, policy-blocked action binding, equal-recency contract ambiguity, downgrade proof, and typed post-policy binding changes.

## Privacy, customer boundary, and side effects

Architecture tests prohibit Decision Engine dependencies on TargetICP, MatchingEngine, customer accounts/preferences/feedback, billing, entitlements, and materialized customer ownership.

Decision input, proposal, audit, and event contain no email, person name, phone, personal LinkedIn URL, raw Apollo data, or customer information. The service reads only safe contact binding and verification metadata; it does not select contact PII.

SPEC-023 performs zero Apollo, Instantly, SMTP, HTTP/web, crawler, LLM, campaign-creation, email, or other external side effects. It needs no provider credential.

## Validation

Pre-implementation merged baseline:

- Backend: 3218 passed, 0 skipped
- Frontend: 116 passed

Final local validation:

- `uv run pytest -q`: **3303 passed**, 0 skipped
- `uv run ruff check .`: PASS
- `git diff --check`: PASS
- `npm test -- --run`: **116 passed**
- `npm run build`: PASS
- `npx tsc -b`: PASS
- `npm run lint`: PASS

Executable GitHub CI:

- Run `32413853200`: SUCCESS
- Backend job `96570341819`: tests and lint PASS
- Frontend job `96570342102`: tests, build, typecheck, and lint PASS

Performance diagnostic (not an SLA): 1,000 deterministic in-memory input/evaluation/proposal operations completed in approximately `0.058826s` on the local validation host.

## Diff and repository status

R1 executable commit stat:

`9 files changed, 323 insertions(+), 19 deletions(-)`

PR diff against authoritative main before this R1 documentation closeout:

`37 files changed, 4914 insertions(+), 53 deletions(-)`

After the documentation-only closeout commit, `git status --porcelain` is expected to be empty. The worktree and draft PR remain intact; nothing is merged or deployed.
