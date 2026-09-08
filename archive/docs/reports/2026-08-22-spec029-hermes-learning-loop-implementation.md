# SPEC-029 — Hermes Learning Loop — implementation report

Date: 2026-08-22  
Status: implementation complete on a draft, unmerged pull request

## Reviewed artifact boundary

- implementation base / current main at executable freeze:
  `2865a5b2ef6d9b06aad8051658431b6e5245ee7d`;
- prerequisite SPEC-028 squash merge:
  `7943d135d9089bbf0478b1cec16c80065a9cd2c4`;
- frozen local design commit after the compatible frontend-only main rebase:
  `4f92194`;
- original reviewed executable runtime/test SHA:
  `5cbfec883f896be50b8d93db2f52b7efd21c8a30`;
- R1 executable runtime/test SHA:
  `35cc89864f089b50a8e72dec82d1bb89e704e4c1`;
- R1 executable CI: GitHub Actions run `32607695001`, SUCCESS;
- the final head is a later docs-only closeout commit. The executable-to-final
  delta is restricted to this report.

The intervening main change was PR #48, limited to the frontend public
experience and pricing. It did not touch acquisition, Policy, persistence,
migrations, conversion truth, or the learning-loop contract.

## Migration and persistence

Alembic is linear with one head:

```text
0019_conversion_tracking
-> 0020_hermes_learning_loop
```

SPEC-029 adds exactly two tables:

1. `acquisition_learning_snapshot` — immutable 60-day source/economic snapshot;
2. `acquisition_allocation_proposal` — append-auditable bounded candidate,
   selection, Policy decision, and application state.

Cell facts and allocation vectors use strictly validated bounded JSON to avoid
a third table. Snapshot/proposal identities are deterministic. A partial unique
successor constraint and serialized application make one applied proposal the
only successor of a given allocation authority. Current allocation is resolved
by walking the explicit `INITIAL -> proposal_ref` lineage, never by an ambiguous
latest-row convention. R1 adds the partial unique index
`uq_learning_snapshot_selected_proposal` on `snapshot_ref WHERE
selection_source IS NOT NULL` for both PostgreSQL and SQLite. It is mirrored in
SQLAlchemy Core and makes one durable selected proposal the database invariant
for each snapshot, independently of the existing single-APPLIED-successor
constraint.

## Metric contracts

The learning cell is exactly `country x wedge`; sector, need, campaign,
contact, and company remain reporting dimensions for SPEC-030 rather than
optimizer cells. The observation window is an explicit timezone-aware rolling
60 days with no hidden clock read.

Authoritative metrics are built from merged Kivou facts:

- `contacted_count`: distinct members with authoritative Step-1 `email_sent`;
- Step 2 is never a second contacted prospect;
- `bounce_count`: distinct contacted members with authoritative Step-1 bounce;
- `delivery_proxy_count = contacted_count - bounce_count` and the corresponding
  Decimal proxy rate; this is never called provider-confirmed delivery;
- finalized, terminal SPEC-027 response evaluations for POSITIVE, COMPLAINT,
  and UNSUBSCRIBE; provider interest labels are ignored;
- SPEC-028 CLICK, signup journey, ACTIVATED, PAID, MRR_CHANGED, RETAINED_M1,
  RETAINED_M2, and CHURNED truth;
- forwarded attribution may legitimately produce signup/activation/payment
  counts greater than contacted count;
- MRR comes only from SPEC-028 integer minor-unit facts. Unknown or mixed MRR
  remains incomplete, and a churned journey cannot retain economic value;
- safely attributed campaign Policy estimated cost and finalized response
  classifier actual cost are retained as known partial cost. Missing provider
  and mailbox costs keep repository-default `cost_complete=false`.

All ratios and economic calculations use integers and `Decimal`, never binary
floating point.

## Economic formula and gates

Frozen versions include:

- `hermes-learning-loop-v1`;
- `learning-risk-policy-v1`;
- `learning-cost-policy-v1`;
- `wedge-economic-value-v1`;
- `learning-candidate-generation-v1`;
- `learning-allocation-envelope-v1`.

`wedge-economic-value-v1` is:

```text
retained MRR per contacted prospect
- known variable cost per contacted prospect
- bounded risk penalty per contacted prospect
```

The risk numerator uses the frozen minor-unit constants from the design:
complaint `2500`, unsubscribe `500`, bounce `250`, churn `1000`, capped at
`5000` per contacted prospect. Delivery, positive response, click, activation,
payment, retention, and churn remain explanatory diagnostics rather than a
false-precision product of rates.

The closed score status is READY, INSUFFICIENT_EVIDENCE, COST_INCOMPLETE,
MRR_INCOMPLETE, or RISK_BLOCKED. A receiver must have at least 50 contacted
members, 2 paid journeys, 2 M1-eligible journeys, 1 retained M1 journey,
complete same-currency MRR and costs, no complaint, no ambiguous response
identity, and a Step-1 bounce rate no greater than 5%. M2 is stronger evidence
but not required for the first bounded move. High replies without retained MRR
cannot outrank retained economic value.

No FX conversion exists. Different or internally mismatched currencies cannot
participate in an economic shift.

## Allocation envelope and candidates

`LearningAllocationEnvelope` is injected Kivou configuration containing only
preapproved country/wedge cells and their current/minimum/maximum integer units.
It requires exact total conservation. SPEC-029 cannot increase global, country,
mailbox, campaign, provider, budget, or product caps.

Kivou generates at most five candidates:

- one `NO_CHANGE`;
- up to four `SHIFT_ONE_UNIT` candidates from a weaker READY cell to a stronger
  same-currency READY cell.

Every move respects allowlisted cells and min/max bounds and moves at most one
daily unit per cycle. Stale-baseline proposals are rejected. Duplicate snapshot,
candidate, selection, Policy, and apply operations converge.

When two workers select different valid candidates for the same snapshot,
`record_selection()` serializes the write and returns the durable winner. An
identical replay returns that same row; a losing proposal is left unselected.
The worker uses the returned proposal reference for every subsequent Policy and
application step, so a local Hermes choice that loses the race cannot create a
competing Policy path. Winner selection never depends on timestamp ordering.

## Hermes boundary

`HermesLearningSelector` is injected and has no network implementation in this
specification. Its input contains only the snapshot reference, formula/risk
versions, bounded safe country/wedge score summaries, and Kivou-generated
candidate summaries. Allocation vectors, customer identities, provider events,
Stripe identities, raw response content, formula weights, thresholds, and caps
are absent.

Hermes returns only:

```text
snapshot_ref
proposal_ref
bounded reason_codes
confidence
```

It cannot submit an allocation vector or numeric delta. An altered or unknown
proposal reference is rejected. The repository-default selector is
unconfigured and deterministically chooses `NO_CHANGE`.

## Policy and execution behavior

`reallocate_volume` remains the only allocation mutation command. Its final
Policy profile is:

- risk class `COMMERCIAL_MUTATION`;
- target scope `GLOBAL`;
- required evidence `LEARNING_SNAPSHOT`, `ALLOCATION_ENVELOPE`, and
  `CONVERSION_RETENTION`;
- no Policy budget, volume, provider-quota, send-control, or compliance charge;
- control plane required;
- exact target `global:acquisition-allocation-v1`;
- Hermes argument boundary: only opaque `proposal_ref`.

The action fingerprint binds the proposal/snapshot inputs, formula/risk and
envelope versions/fingerprints, current/proposed allocation fingerprints,
conserved total, one-unit delta, candidate version, observation window, and
exact current Policy snapshot/control revision. No PII enters Policy arguments.

The existing `ADAPTIVE_SCALE` evaluator hard gate remains unchanged:

- SHADOW persists the proposal and exact Policy/counterfactual result but never
  applies it;
- ASSISTED and AUTONOMOUS_CAPPED do not execute reallocation;
- only ADAPTIVE_SCALE with an executable APPROVED Policy decision may apply;
- kill switch, read-only, or unavailable controls fail closed.

Application changes only Kivou's future allocation plan. It does not modify a
sealed/active campaign, call Instantly, enroll a lead, consume a send, or alter
global volume. Every future `schedule_campaign` retains its complete existing
Policy, compliance, pacing, mailbox, provider, and window gates.

## Worker, replay, and defaults

The worker is an explicitly invoked service. It has no ASGI autostart,
background thread, import-time work, or provider/model adapter. A crash before
Policy, after a durable Policy decision, or before application resumes from the
same snapshot/proposal identity. Concurrent selection has exactly one durable
winner per snapshot and restart through `existing_cycle()` resolves that winner
without `MultipleResultsFound`. Concurrent application independently retains at
most one applied successor, and lease/timestamp ordering is not treated as
allocation authority.

Repository defaults remain a safe no-op:

- allocation envelope: EMPTY / unconfigured;
- Hermes selector: unconfigured / `NO_CHANGE`;
- autonomy: unchanged and non-ADAPTIVE by default;
- worker autostart: disabled;
- global authorized volume: unchanged.

## Validation

R1 executable CI `32607695001` on
`35cc89864f089b50a8e72dec82d1bb89e704e4c1` recorded:

- backend: `3966 passed`, `2 skipped`;
- skipped tests: exactly the two existing opt-in Stripe TEST smokes in
  `tests/test_billing_stripe_test_smoke.py`;
- no SPEC-029 test skipped;
- Ruff: PASS;
- frontend: `294 passed`;
- frontend build: PASS;
- frontend typecheck: PASS;
- frontend lint: PASS.

Focused R1 verification recorded 47 passing learning tests, including a real
two-worker/different-candidate race, database uniqueness, PostgreSQL offline
SQL, Core parity, identical-selection replay, and `existing_cycle()` restart.
Ruff and `git diff --check` passed. The GitHub executable CI is the complete
backend/frontend regression authority.

## Boundaries and limitations

SPEC-029 does not implement a dashboard (SPEC-030) or the general reliability,
DLQ, circuit-breaker, and operations platform (SPEC-031). It does not train a
model, learn weights, change Policy, alter product caps, call a provider, or
start itself. Complete provider/mailbox acquisition cost authority remains a
future reviewed input; until then real cells are cost-incomplete and cannot
receive an upshift.

No LLM, Apollo, Instantly, Stripe, or other provider network was called. No
email was sent, no campaign was activated, no production autonomy changed, no
global volume cap increased, and no deployment was performed.
