# SPEC-030 — Weekly Commercial Cockpit — implementation report

Date: 2026-08-23
Status: implementation complete on a draft, unmerged pull request

## Artifact boundary

- authoritative implementation base and SPEC-029 squash merge:
  `8a4d0f53e2e8008a89be8d200323803fc0c72a49`;
- frozen design commit: `6ae824c1bb9ffc9bf8b916bd1e8c8d263213f653`;
- executable runtime/test SHA:
  `21cc1ea1dfb114403df1e20141ab92b27976e082`;
- executable GitHub Actions CI: `32622033939`, SUCCESS;
- implementation pull request: #51, DRAFT and unmerged;
- the final head is a later docs-only closeout commit. The executable-to-final
  delta is restricted to this report.

The implementation started only after PR #49 was merged and current `main`
contained the SPEC-027 response, SPEC-028 conversion, and SPEC-029 learning
authorities.

## Persistence and package

SPEC-030 adds no analytics truth, table, or migration. Alembic remains linear
with the single head:

```text
0019_conversion_tracking
-> 0020_hermes_learning_loop
```

The read-only backend package is `src/signals/cockpit/`:

- `contracts.py` freezes the immutable report, week, money, row, KPI, and data
  quality contracts;
- `metrics.py` performs bounded as-of aggregation over existing durable Kivou
  sources;
- `service.py` constructs the deterministic report identity;
- `api.py` exposes the authenticated internal read endpoint.

The shared SPEC-028 sector source resolver is made public and reused; no second
sector inference algorithm exists. Report generation opens read connections
only and is tested not to change campaign, response, conversion, or other
business row counts.

## Report and week contract

The report version is `weekly-commercial-cockpit-v1`. Its `report_ref` is a
deterministic semantic fingerprint of the report version, completed week, and
the stable bounded source-derived report projection. There is no randomness,
database-current-time authority, mutable provider label, or insertion-order
dependency.

`cockpit-week-v1` uses `Europe/Zurich` and the DST-aware interval Monday 00:00
local inclusive through the next Monday 00:00 local exclusive. The API accepts
only `week_offset=0..51`; offset zero is the latest completed week resolved from
the injected Kivou clock. `captured_at` equals the exclusive `week_end`, so a
historical report is evaluated against the facts knowable at that cutoff.

## Cohort and funnel

The cohort is the distinct campaign members with authoritative Step-1
`email_sent` during the selected week. Duplicate provider events converge by
member and Step 2 never adds a prospect.

The funnel is:

- delivered proxy: distinct Step-1 cohort members minus members with a Step-1
  bounce before the report cutoff;
- positive replies: distinct cohort members with a finalized terminal SPEC-027
  POSITIVE classification as-of the cutoff, after explicit reclassification
  lineage resolution;
- clicks: deduplicated first-party SPEC-028 CLICK events only;
- activated accounts: distinct attributed journeys with SPEC-028 ACTIVATED by
  the cutoff;
- paid accounts: distinct attributed journeys with SPEC-028 PAID by the cutoff;
- MRR: the latest trusted SPEC-028 MRR_CHANGED fact per paid journey, in integer
  minor units and separated into CHF and EUR;
- churn: distinct cohort journeys with authoritative SPEC-028 CHURNED by the
  cutoff.

The delivery field explicitly carries
`PROXY_SENT_MINUS_BOUNCE_V1`, and the UI says “Emails délivrés (proxy)”. It is
not presented as provider-confirmed delivery. Provider AI interest, Instantly
clicks, opens, checkout creation, redirect success, frontend state, scheduled
cancellation, and `past_due` do not become funnel truth.

Forwarded-link attribution remains truthful: one contacted member can lead to
multiple account journeys, so downstream counts and rates may exceed the
contact denominator. Counts are never clamped.

## MRR, dimensions, and M2 KPI

Known MRR is read only from SPEC-028. Unknown MRR remains unknown and increments
bounded data quality; it is never coerced to zero. A churned journey contributes
no current MRR. CHF and EUR remain separate and no FX conversion exists.

The analytical table uses the exact stable key:

```text
country x sector_ref x need_ref x campaign_ref
```

Country and need come from the frozen Kivou campaign. Campaign authority is
`campaign_ref`, never the provider display name. Sector uses the frozen journey
source when present and otherwise the shared Kivou conversion source resolver;
an unavailable or conflicting source enters the explicit `UNRESOLVED` bucket.
The row counts reconcile with the top-level funnel and stable sorting is
contract-validated.

The sole secondary KPI is retained M2 MRR per 1,000 delivered-proxy emails by
wedge and currency. A member is M2-eligible only once when at least one bound
journey has an authoritative PAID fact at least 60 days before the cutoff and
the member was not bounced. Retained accounts require RETAINED_M2 and no CHURNED
fact by the cutoff. Multiple forwarded journeys may contribute multiple retained
accounts and MRR while the contacted denominator stays unique. Missing maturity
or MRR yields `INSUFFICIENT_M2_EVIDENCE`, not zero performance.

## Internal access and API

The single endpoint is:

```text
GET /internal/commercial-cockpit?week_offset=0..51
```

It requires the existing authenticated Kivou session plus membership in the
bounded `KIVOU_COCKPIT_OPERATOR_ACCOUNT_IDS` allowlist. The repository and
environment-example default is empty, denying all accounts. Anonymous access is
401, ordinary authenticated accounts receive 403, and configured internal
operators receive the aggregate report. `GET /me` exposes only the derived
`capabilities.commercial_cockpit` boolean; the allowlist itself is never exposed.

The frontend route is `/app/internal/cockpit`. Its navigation item appears only
for the backend-derived capability, while backend authorization remains final.
The page contains one bounded historical-week selector, seven compact funnel
stages, the M2 KPI, the analytical table, and truthful proxy/freshness notes.
It uses existing React/CSS primitives and adds no charting dependency, mutation
button, allocation control, decorative AI summary, or second application.

## Hermes and Policy

The existing command is reused:

- command: `generate_weekly_report`;
- target: `global:commercial-cockpit-v1`;
- arguments: `{}` exactly;
- Policy: `READ_ONLY`, `GLOBAL`, no budget, volume, provider quota, send control,
  or compliance requirement.

The mapper rejects a Hermes-supplied date, filter, dimension, SQL fragment, or
aggregation rule. Kivou resolves the latest completed week and calculates the
authoritative aggregate. Hermes only receives the same bounded PII-free report
and cannot create conversion facts or mutate allocation.

## Privacy and data quality

Contracts and queries contain only bounded Kivou refs/codes, milestone and
classification vocabulary, timestamps, counts, Decimal rates, and integer
money. Tests seed synthetic prospect/signup emails, account/company markers,
provider labels, and billing-like identities and prove that sensitive markers
do not enter report JSON. Raw response content, IP, user agent, provider payload,
Stripe identity, campaign copy, and account identity are absent from the
cockpit contracts, API response, frontend fixture, and cockpit logs.

The bounded data-quality section reports only whether delivery is a proxy,
unresolved cohort sectors, paid journeys with unknown MRR, insufficient M2
wedges, and the cutoff. It is not an engineering observability console.

## Validation

Executable CI `32622033939` on
`21cc1ea1dfb114403df1e20141ab92b27976e082` recorded:

- backend: `3978 passed`, `2 skipped`;
- skipped tests: exactly the two existing opt-in Stripe TEST smokes in
  `tests/test_billing_stripe_test_smoke.py`:
  `test_stripe_accepte_une_session_pour_un_customer_existant` and
  `test_stripe_expose_une_resiliation_programmee_que_kivou_sait_lire`;
- no SPEC-030 test skipped;
- Ruff: PASS;
- frontend: `298 passed`;
- frontend build: PASS;
- frontend typecheck: PASS;
- frontend lint: PASS;
- `git diff --check`: PASS;
- Alembic heads: exactly `0020_hermes_learning_loop`.

The SPEC-030 tests cover Zurich DST weeks, bounded history, empty reports,
deterministic replay, cohort/Step-2/provider-event dedupe, bounce proxy,
response reclassification, provider-label exclusion, first-party clicks,
forwarded journeys, activation/payment/MRR/churn cutoffs, unknown and
multi-currency MRR, dimensions and reconciliation, unresolved sectors, M2
maturity/churn/no-FX, no business mutation, privacy, internal authorization,
Hermes/Policy boundaries, frontend loading/empty/error/unauthorized states,
keyboard operation, and responsive overflow containment.

## Boundaries and external effects

SPEC-030 does not implement SPEC-031 circuit breakers, DLQs, general retry
infrastructure, production health drills, runbooks, or autonomous-operations
monitoring. It does not create analytics persistence, rewrite historical
conversion facts, calculate FX, change a learning proposal, or expose the
cockpit to ordinary customers. Delivery remains a declared proxy and incomplete
MRR/sector/M2 evidence remains visible.

No LLM, Apollo, Instantly, Stripe, or other provider network was called. No
email was sent, no campaign was activated, no allocation changed, no production
autonomy changed, and no deployment was performed.
