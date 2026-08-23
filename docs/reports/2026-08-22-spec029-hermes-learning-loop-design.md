# SPEC-029 — Hermes Learning Loop design

Date: 2026-08-22  
Status: frozen implementation design; no deployment authority

## Scope and authoritative base

This design is based on `origin/main` at
`7943d135d9089bbf0478b1cec16c80065a9cd2c4`, the merged SPEC-028 squash.
Main contains `0019_conversion_tracking`,
`acquisition_conversion_journey`, and `acquisition_conversion_event`; PR #47
is closed and merged.

SPEC-029 measures durable outcomes, computes versioned country-by-wedge
economics, generates bounded redistribution candidates, accepts at most one
opaque Hermes selection, evaluates the existing `reallocate_volume` command,
and may update only the future Kivou allocation plan. It does not send, call a
provider, increase a cap, change Policy, train a model, or implement a generic
ML system.

Three implementation shapes were considered:

1. A pure snapshot calculator plus two append-auditable tables, with validated
   bounded JSON for cells and allocation vectors. This is selected because it
   preserves source rows, avoids a third cell table, and keeps formula and
   candidate generation independently testable.
2. A normalized snapshot/cell/proposal model. This improves ad-hoc SQL but
   requires a third table and fragments a deliberately small v1 surface.
3. A generic analytics or online-learning platform. This is rejected because
   it would duplicate conversion truth and allow formula or weight drift.

## Frozen contracts and boundaries

The implementation versions are:

- `hermes-learning-loop-v1`;
- `learning-snapshot-v1`;
- `learning-cell-metrics-v1`;
- `learning-allocation-envelope-v1`;
- `learning-risk-policy-v1`;
- `learning-cost-policy-v1`;
- `wedge-economic-value-v1`;
- `learning-candidate-generation-v1`;
- `learning-selection-v1`;
- `learning-proposal-v1`.

Every contract is immutable and strictly validated. Canonical JSON sorts keys,
uses integer money and string-form Decimals, forbids non-finite values, and is
domain-separated before SHA-256 fingerprinting. No raw PII, provider payload,
response content, account identity, Stripe identity, or hidden reasoning enters
learning contracts, Policy arguments, or persistence.

The learning cell is exactly `country × wedge`. Country is `CH` or `FR`; wedge
is an existing bounded Kivou code. Sector, need, campaign, contact, company, and
account remain source/reporting dimensions and never fragment v1 allocation.

## Observation window and cohort

`learning-window-v1` is the half-open 60-day interval
`[window_start, window_end)`, with `window_start = window_end - 60 days`.
`window_end` and `captured_at` are explicit aware timestamps and
`captured_at >= window_end`. The worker passes them; no contract reads the
clock.

The cohort is one unique campaign member whose authoritative normalized
provider event is `email_sent`, `step = 1`, and whose occurrence is inside the
window. Duplicate transport events converge through SPEC-026 identity. Step 2
never adds a contacted prospect. Technical Step-2 email counts are outside the
economic denominator.

All downstream facts for a cohort member are observed at or before
`window_end`. A late fact belongs to a later snapshot, never a rewritten old
snapshot.

## Authoritative source facts

The calculator reads only merged Kivou truth:

- `acquisition_campaign` and `acquisition_campaign_member` for cell and member
  identity;
- `acquisition_provider_event` for Step-1 `email_sent` and Step-1
  `email_bounced`;
- finalized `acquisition_response_evaluation` for POSITIVE, COMPLAINT, and
  UNSUBSCRIBE;
- `acquisition_conversion_journey` and `acquisition_conversion_event` for
  CLICK, SIGNUP, ACTIVATED, PAID, MRR_CHANGED, RETAINED_M1, RETAINED_M2, and
  CHURNED;
- bounded Kivou Policy/acquisition cost records through the cost source.

Provider AI interest labels, opens, clicks reported by Instantly, campaign
names, raw replies, and frontend/Stripe/provider payloads have no authority.

Response reclassification is resolved by the explicit `supersedes` graph.
Exactly one finalized terminal evaluation is required for a response identity.
A fork, cycle, or multiple terminal evaluations marks the cell's conversion
identity ambiguous and blocks upshift. No timestamp-based “latest model wins”
rule exists. Safety categories remain sticky: any finalized COMPLAINT or
UNSUBSCRIBE for a member counts as risk even if a later semantic evaluation is
present.

## Metric definitions

For each cohort cell, v1 records:

- `contacted_count`: distinct authoritative Step-1-sent members;
- `bounce_count`: distinct contacted members with authoritative Step-1 bounce;
- `delivery_proxy_count = max(contacted_count - bounce_count, 0)`;
- `delivery_proxy_rate = delivery_proxy_count / contacted_count`;
- `positive_reply_count`: distinct contacted members whose explicit terminal
  response evaluation is POSITIVE;
- `positive_reply_rate = positive_reply_count / contacted_count`;
- distinct contacted-member `complaint_count` and `unsubscribe_count`;
- deduplicated first-party `click_count`;
- attributed journey counts for `signup_count`, `activation_count`, and
  `paid_count`;
- current `known_mrr_minor_units`, `retained_mrr_minor_units`, and one normalized
  uppercase `currency` when complete;
- `m1_eligible_count`: attributed paid journeys whose first PAID timestamp is at
  least 30 days before `window_end`;
- `retained_m1_count`: eligible journeys with RETAINED_M1 by `window_end`;
- `retention_m1_rate = retained_m1_count / m1_eligible_count`;
- the equivalent 60-day M2 eligibility/count/rate;
- `churn_count`: paid journeys with CHURNED by `window_end`;
- `churn_rate = churn_count / paid_count` when paid count is non-zero;
- `known_variable_cost_minor_units`, cost currency, `cost_complete`, and bounded
  missing-cost reason codes.

Ratios are Decimal, never binary float. A zero denominator yields null, not a
fabricated zero rate. Counts are raw truth. Because one forwarded click may
source multiple journeys, signup, activation, and paid counts may exceed
contacted count and their diagnostic ratios may exceed one.

The delivery metric is named a proxy everywhere. Kivou does not claim provider-
confirmed delivery.

## MRR, retention, churn, and currency

MRR is read only from SPEC-028 `MRR_CHANGED`. For each journey, the latest
event by explicit conversion chain and occurrence at/before `window_end`
defines current MRR. A CHURNED journey contributes no retained economic value;
the SPEC-028 zero-MRR event is expected, and a missing/inconsistent terminal
MRR fact makes MRR incomplete rather than inventing zero.

`known_mrr_minor_units` sums current known MRR. `retained_mrr_minor_units` sums
current known MRR only for M1-retained, non-churned journeys. An unknown MRR for
any materially paid/retained journey makes `mrr_complete=false`.

No FX policy exists. Currency is normalized to `CHF` or `EUR`. A cell with
mixed/unknown material currency is MRR-incomplete. Candidate generation only
compares same-currency READY cells. Cross-currency shifts are ineligible and
produce NO_CHANGE rather than a web lookup or implicit conversion.

## Cost completeness

`learning-cost-policy-v1` may record only safely attributed Kivou facts.
Current measurable components are bounded opportunity-scoped Policy cost
records and finalized response-classifier actual cost where present. They are
partial: current persistence has no complete provider delivery, mailbox, or
other acquisition-variable-cost ledger. Consequently the repository's default
`RepositoryLearningCostSource` reports the known partial amount but always
sets `cost_complete=false` with `PROVIDER_COST_UNAVAILABLE` and
`MAILBOX_COST_UNAVAILABLE`.

Unknown cost is never coerced to zero. A Kivou-owned injected cost source may
later provide complete, same-currency integer-minor-unit facts after a separate
contract review; Hermes cannot provide or override them. Tests use explicit
synthetic complete cost facts to exercise pure economics and application.

## Risk and evidence gates

`learning-risk-policy-v1` freezes:

- maximum Step-1 bounce rate for upshift: `0.05` inclusive; a value strictly
  greater than 5% is blocked;
- any complaint in the window blocks upshift;
- ambiguous response/conversion identity blocks upshift;
- incomplete cost or material MRR blocks upshift;
- insufficient M1 evidence blocks upshift.

To receive increased allocation a cell must satisfy all:

- `contacted_count >= 50`;
- `paid_count >= 2`;
- `m1_eligible_count >= 2`;
- `retained_m1_count >= 1`;
- `cost_complete == true`;
- `mrr_complete == true`;
- no risk block.

M2 is stronger diagnostic evidence but not required for the first one-unit
move. SPEC-031 retains ownership of production-wide circuit breakers.

## Economic score

The status vocabulary is closed:

- `READY`;
- `INSUFFICIENT_EVIDENCE`;
- `COST_INCOMPLETE`;
- `MRR_INCOMPLETE`;
- `RISK_BLOCKED`.

Status precedence is risk, MRR completeness, cost completeness, then evidence.
Only READY cells may be donor or receiver in an upshift candidate.

`wedge-economic-value-v1` uses integer minor-unit inputs and Decimal division:

```text
retained_mrr_per_contact = retained_mrr_minor_units / contacted_count
cost_per_contact = known_variable_cost_minor_units / contacted_count
risk_numerator =
    2500 * complaint_count
  + 500  * unsubscribe_count
  + 250  * bounce_count
  + 1000 * churn_count
risk_penalty_per_contact = min(5000, risk_numerator / contacted_count)
economic_score =
    retained_mrr_per_contact
  - cost_per_contact
  - risk_penalty_per_contact
```

All constants are minor units in the cell currency and are included in the
formula fingerprint. Delivery proxy, positive response, click, activation,
payment, M1/M2 retention, and churn remain explanatory diagnostics rather than
being multiplied into false precision. A high-reply/no-retained-MRR cell cannot
outrank a retained-MRR cell merely through engagement.

## Allocation envelope and current authority

`LearningAllocationEnvelope` is injected Kivou configuration with version,
valid interval, total daily units, and at most 64 preapproved country×wedge
cells containing current, minimum, and maximum integer units. Cells are unique,
`minimum <= current <= maximum`, and current units sum exactly to total units.

Repository default is absent/unconfigured. No snapshot, selector, Policy
mutation, or application occurs without a valid envelope. SPEC-029 never
changes total daily units, global/country/mailbox/campaign/provider caps, Policy
budget, or product caps.

Current allocation is the configured initial vector or the proposed vector of
the latest successfully APPLIED proposal in the same envelope lineage. It is
never inferred from sends. Every proposal binds the baseline allocation
fingerprint and a baseline authority reference (`INITIAL:<envelope fp>` or the
prior applied proposal ref).

## Candidate generation

`learning-candidate-generation-v1` deterministically produces at most five
candidates:

- one `NO_CHANGE` candidate;
- zero to four `SHIFT_ONE_UNIT` candidates.

A shift moves exactly one daily unit from one weaker READY cell to one stronger
READY cell with the same currency and strictly higher score. It preserves total
units, cell minimums/maximums, and the envelope allowlist. Candidates sort by
descending score delta, then stable cell keys. No cycle can move more than one
unit. If no safe move exists, NO_CHANGE is the only candidate.

Snapshot and proposal refs are deterministic fingerprints. The same window,
input facts, versions, envelope and current authority converge to one snapshot;
the same snapshot/candidate/move converges to one proposal.

## Hermes boundary

`HermesLearningSelector` is an injected protocol. Repository default is
unconfigured and deterministically selects the supplied NO_CHANGE proposal
without network access.

Input contains only snapshot ref, formula/risk versions, bounded safe cell
summaries, proposal refs, delta summaries, and reason codes. It contains no raw
customer/provider/account/billing records or hidden Policy inputs. Strict output
is:

```text
LearningSelection {
  snapshot_ref
  proposal_ref
  reason_codes
  confidence
}
```

The proposal ref must be one of the supplied candidates. Hermes cannot submit
an allocation vector, number, cell, cap, formula, threshold, or side effect.
An altered/unknown selection fails closed.

The generic supervisor boundary keeps only `reallocate_volume`. Its target is
exactly `global:acquisition-allocation-v1`, and its arguments are exactly
`{"proposal_ref":"<opaque ref>"}`. Kivou resolves every other fact.

## Policy and application

The existing `reallocate_volume` profile becomes:

- risk class `COMMERCIAL_MUTATION`;
- target scope `GLOBAL`;
- evidence `LEARNING_SNAPSHOT`, `ALLOCATION_ENVELOPE`,
  `CONVERSION_RETENTION`;
- `uses_budget=false`, `uses_volume=false`, `uses_provider_quota=false`,
  `uses_send_controls=false`;
- `requires_control_plane=true`, `requires_compliance=false`.

The evaluator's existing `effective_mode == ADAPTIVE_SCALE` hard gate remains.
Kill switch, read-only, unavailable/expired control plane, stale evidence, or a
disallowed command blocks application. The Policy request uses zero proposed
cost and volume because it mutates only a future internal plan.

Kivou's action fingerprint binds proposal/snapshot refs, snapshot input,
formula/risk/envelope versions and fingerprints, current/proposed allocation
fingerprints, total, delta, candidate version, observation window, and current
Policy/control provenance. Canonical Policy arguments contain only
`proposal_ref` and no PII.

Mode behavior is:

- SHADOW: proposal and DENIED decision persist, including APPROVED
  counterfactual when applicable; never apply;
- ASSISTED: denied by the ADAPTIVE_SCALE gate; no ACTION approval bypass;
- AUTONOMOUS_CAPPED: denied by the ADAPTIVE_SCALE gate;
- ADAPTIVE_SCALE: may apply only when the exact Policy decision is current,
  APPROVED, executable, and all baseline invariants still match.

Application changes only the current future allocation plan. It never mutates a
campaign/provider, member, cap, Policy control, or historical snapshot. Future
`schedule_campaign` calls retain every existing budget, volume, quota, mailbox,
window, compliance, approval, and transport gate.

## Persistence and concurrency

Migration `0020_hermes_learning_loop` descends from
`0019_conversion_tracking` and creates exactly two tables.

`acquisition_learning_snapshot` stores immutable window/version/fingerprint
facts, bounded validated cell metrics JSON, envelope identity, current
allocation fingerprint, previous applied proposal ref, and timestamps.

`acquisition_allocation_proposal` stores the snapshot FK, candidate/envelope
identity, baseline authority, immutable current/proposed bounded JSON and
fingerprints, from/to cells, delta, expected score delta, reason codes,
selection source/confidence, monotonic state, Policy provenance, and decision/
application timestamps.

Proposal states are `PROPOSED`, `SHADOW_ONLY`, `POLICY_DENIED`, `APPLIED`, and
`REJECTED`. Allocation vectors and economic facts are write-once; only bounded
decision/application columns move monotonically.

Snapshot insertion and proposal insertion use deterministic primary keys with
exact replay validation. Application locks the proposal and snapshot, rebuilds
the current authority, and compares baseline fingerprints. A partial unique
index allows at most one APPLIED successor for an envelope/baseline authority.
Concurrent/stale losers become REJECTED with a bounded reason; a duplicate of
the already-applied proposal replays without moving volume twice.

No acquisition EventType or state is added. `acquisition-state-v1` remains
unchanged; learning audit lives only in the two learning tables and Policy
journal.

## Defaults, worker, and downstream boundaries

The worker is explicit and has no ASGI/import/startup wiring. Default allocation
envelope is absent, Hermes selector is unconfigured/NO_CHANGE, cost coverage is
incomplete, and repository Policy mode remains non-ADAPTIVE. Defaults therefore
cannot apply a reallocation.

SPEC-030 owns dashboards and country×sector×need×campaign presentation.
SPEC-029 exposes only bounded read-only snapshot/proposal queries. SPEC-031 owns
global reliability, DLQ, circuit breakers, runbooks, and production kill-switch
validation.

## Test and implementation plan

Implementation proceeds TDD in these bounded stages:

1. Add failing contract/economics tests for Decimal metrics, 60-day cohorts,
   evidence/risk statuses, retained-MRR score, cross-currency rejection, and
   envelope conservation; implement `contracts.py`, `metrics.py`, and
   `economics.py`.
2. Add failing candidate/Hermes boundary tests for one-unit moves, allowlists,
   min/max, maximum five candidates, opaque proposal selection, and default
   NO_CHANGE; implement `candidates.py` and `hermes.py`.
3. Add failing source aggregation tests for Step-1 denominator, bounce proxy,
   explicit response lineage, provider-label exclusion, forwarded journeys,
   SPEC-028 MRR/retention/churn, and incomplete costs; implement the repository
   metric source.
4. Add failing migration/parity tests; create `0020_hermes_learning_loop`, the
   two Core tables, constraints, PostgreSQL offline SQL, upgrade/downgrade, and
   one-head proof.
5. Add failing replay/concurrency/store tests; implement deterministic snapshot
   and proposal persistence, baseline authority, monotonic decisions, and
   single-successor application.
6. Add failing Policy/mapper tests; update the sole `reallocate_volume` profile,
   enforce the global target/proposal-only argument, and implement exact Kivou
   evidence/action construction.
7. Add failing worker/mode/crash tests; implement capture, selector, Policy,
   SHADOW/ASSISTED/AUTONOMOUS/ADAPTIVE handling, stale rejection, duplicate
   replay, explicit no-autostart defaults, and no-network architecture guards.
8. Run focused suites, migration tests, Ruff, and `git diff --check`; create the
   executable commit and run full backend/frontend CI. Only after success write
   the implementation report as a docs-only closeout and run final-head CI.

The test matrix explicitly covers every case required by the specification,
including high replies/no MRR losing to retained MRR, unknown MRR/cost, risk
gates, forwarded conversion counts above one, all autonomy modes, duplicate and
concurrent application, no global cap increase, no new command/EventType, and
absence of provider/LLM/dashboard behavior.
