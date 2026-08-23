# SPEC-030 — Weekly Commercial Cockpit — frozen design

Date: 2026-08-23  
Implementation base: `8a4d0f53e2e8008a89be8d200323803fc0c72a49`  
SPEC-029 merge: `8a4d0f53e2e8008a89be8d200323803fc0c72a49`

## Scope and authority

SPEC-030 is a small, read-only Kivou business cockpit. It creates no analytics truth and
does not persist reports. Its only authorities are the durable facts already owned by
SPEC-026 through SPEC-029:

- `acquisition_campaign`, `acquisition_campaign_member`, and
  `acquisition_provider_event` for the contacted cohort and transport truth;
- `acquisition_response_evaluation` for Kivou response classification;
- `acquisition_conversion_journey` and `acquisition_conversion_event` for click,
  account, activation, payment, MRR, retention, and churn truth;
- `acquisition_learning_snapshot` and `acquisition_allocation_proposal` for an optional,
  bounded read-only learning summary.

The cockpit never queries Instantly, Stripe, Apollo, an LLM, or any other network. It
does not mutate campaigns, acquisition events, conversion facts, learning allocations,
billing, Policy, or customer data. No report table and no Alembic revision are added;
the head remains `0020_hermes_learning_loop`.

## Versioned report and week

The immutable report contract is `weekly-commercial-cockpit-v1`. Its deterministic
`report_ref` binds the version, selected week, and a canonical fingerprint of every
bounded source fact used by the report. Stable sorting is part of the contract. It uses
no randomness, insertion order, database current time, or mutable display label.

`cockpit-week-v1` uses `Europe/Zurich`. A week is Monday 00:00 local inclusive through
the next Monday 00:00 local exclusive, using IANA/`zoneinfo` semantics across DST. The
latest completed week is resolved from an injected clock by taking the start of the
current local week and selecting the immediately preceding interval. Human navigation
uses only `week_offset=0..51`, where zero is that latest completed week. Hermes supplies
no interval.

`captured_at` is the report cutoff (`week_end`), not the request time. This makes a
historical report reproducible: the same source facts observable strictly before the
cutoff produce the same report and reference whenever it is generated.

## Weekly cohort and funnel

The cohort is the unique set of campaign members with an authoritative provider
`email_sent`, `step=1`, whose `occurred_at` is inside the selected week. Duplicate
provider events converge by member identity. Step 2 never creates another contacted
prospect.

All downstream stages are attributed back to those member refs and use facts with an
authoritative business timestamp strictly before `week_end`:

- `delivered_proxy_count`: cohort members minus cohort members with an authoritative
  `email_bounced`, `step=1`, before the cutoff. The contract explicitly exposes
  `delivery_semantics = PROXY_SENT_MINUS_BOUNCE_V1`; the UI says “Emails délivrés
  (proxy)”. This is not provider-confirmed delivery.
- `positive_reply_count`: distinct cohort members whose terminal, non-superseded
  SPEC-027 response evaluation as-of the cutoff is `POSITIVE`. Reclassification chains
  are resolved only from rows finalized before the cutoff. Broken or multi-leaf
  lineages fail closed and do not count. Provider interest labels, opens, clicks,
  `AUTO_REPLY`, `OUT_OF_OFFICE`, and `AMBIGUOUS` never count.
- `click_count`: deduplicated first-party SPEC-028 `CLICK` events for cohort members.
  Instantly link events never count. A forwarded token remains one click identity.
- `activated_account_count`: distinct attributed journeys for cohort members with a
  SPEC-028 `ACTIVATED` event before the cutoff. Its underlying definition remains
  `ready_for_signals` plus at least one active account-owned TargetICP.
- `paid_account_count`: distinct attributed journeys for cohort members with a
  SPEC-028 `PAID` event before the cutoff. Checkout creation, redirects, and frontend
  success state never count.
- `mrr_by_currency`: the latest trusted SPEC-028 `MRR_CHANGED` fact per cohort journey
  as-of the cutoff. Only `mrr_known=true` contributes integer minor units. A journey
  whose latest MRR is unknown is counted in data quality and is not silently valued at
  zero. CHF and EUR are separate; there is no FX or global mixed-currency total.
- `churn_count`: distinct cohort journeys with SPEC-028 `CHURNED` before the cutoff.
  Past-due and scheduled-cancellation billing states are not queried and cannot become
  churn through this report.

Forwarded-link truth is preserved: activated or paid journey counts may exceed the
original delivered proxy. No count or rate is clamped. Rates use `Decimal`; a zero
denominator yields `null`, never NaN or infinity.

Later responses, payments, MRR changes, or churn do not restate an earlier completed
week because all source reads are as-of that week's exclusive end. Historical cohorts
can instead be inspected at the completed-week cutoffs at which their downstream facts
were knowable; no report row is rewritten.

## Analytical rows and dimensions

One row represents the exact immutable combination:

`country × sector_ref × need_ref × campaign_ref`.

- Country is `acquisition_campaign.country`; it is never inferred from language,
  domain, contact, or company.
- Need is the frozen campaign `selected_need_category` identity. Its selected version
  remains source provenance; Need Graph is never rerun.
- Campaign authority is `campaign_ref`; provider campaign name is not an analytical
  identity.
- Sector reuses the conversion attribution source contract. For a journey it is the
  frozen `acquisition_conversion_journey.sector_ref`; otherwise the same Kivou
  source resolver derives it from the member's opportunity signal. An unavailable
  authority maps to the explicit `UNRESOLVED` bucket and increments data quality.

Rows contain only delivered proxy, positive replies, Kivou clicks, activated accounts,
paid accounts, MRR by currency, churn, and four simple optional Decimal rates. Their
additive counts reconcile exactly to the top-level funnel. Rows are sorted by country,
sector, need, and campaign refs.

## Wedge M2 steering KPI

The sole secondary KPI is retained M2 MRR per 1,000 delivered-proxy emails, by wedge
and currency. It is not derived from replies.

M2 maturity follows SPEC-028 payment-age truth. A journey is M2-eligible only if its
first authoritative `PAID` occurred at least 60 days before the report cutoff. A member
enters `m2_eligible_delivered_proxy_count` once when it has at least one such journey
and was not bounced at Step 1 by the cutoff. This avoids double-counting one contacted
member while allowing forwarded links to produce multiple retained accounts and MRR.
`retained_m2_accounts` counts distinct mature journeys with `RETAINED_M2` before the
cutoff and no `CHURNED` before the cutoff. Their latest known, non-churned MRR supplies
`retained_m2_mrr_minor_units`.

The value is:

`Decimal(retained_m2_mrr_minor_units) * 1000 / m2_eligible_delivered_proxy_count`.

It is emitted separately for CHF and EUR. If no delivered member is mature, MRR is
unknown, or no single currency-specific value can be proved, the value is `null` and
`data_status = INSUFFICIENT_M2_EVIDENCE`. A churned journey contributes neither
retained account nor retained MRR. No FX exists.

## Data quality

The bounded quality object exposes only interpretation guards:

- `delivery_is_proxy=true`;
- `unresolved_sector_count`;
- `unknown_mrr_journey_count`;
- the sorted wedges lacking mature M2 evidence;
- `captured_at`, equal to the report cutoff.

It is not an engineering health console.

## API and internal authorization

The backend exposes one read-only endpoint:

`GET /internal/commercial-cockpit?week_offset=0..51`.

Authentication uses the existing Kivou session. Authorization additionally requires
the session `account_id` to be in the configured
`KIVOU_COCKPIT_OPERATOR_ACCOUNT_IDS` allowlist. Values are comma-separated bounded
opaque account refs and normalized into an immutable set. The repository default is
empty, so every authenticated account is denied by default. Anonymous requests return
401; ordinary customers return 403; backend authorization is final.

`GET /me` includes a bounded `capabilities.commercial_cockpit` boolean derived from the
same server allowlist. It contains no allowlist and is used only to reveal navigation.
Manual frontend navigation still calls the protected endpoint and cannot bypass the
server.

## Hermes and Policy

The existing command is reused unchanged:

- command: `generate_weekly_report`
- target: `global:commercial-cockpit-v1`
- arguments: `{}` exactly
- Policy: `READ_ONLY`, `GLOBAL`, with no budget, volume, provider quota, send control,
  or compliance requirement.

The policy mapper rejects any Hermes-supplied interval, filter, dimension, SQL, or
aggregation argument. Kivou resolves the latest completed week and computes the strict
aggregate contract. Hermes receives no raw email, name, account identity, Stripe ID,
provider payload, response content, or PII, and cannot mutate anything from the report.

## Frontend

The existing React application gains `/app/internal/cockpit`. The navigation item is
rendered only when the backend-derived capability is true. The page remains small:

1. a bounded selector for the latest 52 completed weeks;
2. seven compact funnel stages: delivered proxy, positive replies, Kivou clicks,
   activated, paid, currency-separated MRR, churn;
3. retained M2 MRR per 1,000 delivered-proxy emails by wedge;
4. the country × sector × need × campaign table;
5. a small freshness/proxy/data-quality note.

It uses accessible HTML, CSS, and existing primitives. No chart dependency, decorative
AI summary, mutation button, threshold editor, allocation action, or customer PII is
introduced. Loading, empty, error, unauthorized, keyboard, bounded history, and
responsive behavior are explicit test cases. Money formatting is frontend-only from
integer minor units; unknown MRR is “—”/“Donnée incomplète”, never zero.

## Privacy, tests, and boundaries

The read model selects only immutable refs, codes, bounded classifications, milestone
types, timestamps, and integer money. Prospect/signup emails, names, company labels,
IP, user agent, Stripe/provider IDs, response content, campaign copy, and raw payloads
are absent from contracts, API JSON, Hermes context, frontend fixtures, and cockpit
logs. Report generation is tested to leave all relevant row counts and states
unchanged.

The test matrix covers DST weeks, cohort dedupe, Step 2 exclusion, bounce proxy,
response lineage, provider-label exclusion, first-party clicks, forwarded journeys,
activation/payment/MRR/churn as-of semantics, multi-currency and unknown MRR,
dimension reconciliation and unresolved sectors, M2 maturity/churn/no-FX, privacy,
authorization, supervisor boundaries, empty weeks, deterministic references, and the
frontend states and layouts.

SPEC-030 does not implement SPEC-031 circuit breakers, DLQs, general retries, global
health, production drills, runbooks, or autonomous-operations monitoring. It only
reads existing business facts.
