# SPEC-028 — Conversion Tracking implementation report

Date: 2026-08-22  
Status: implementation candidate; draft PR only; not deployed

## Reviewed artifacts

- Authoritative implementation base: `dd38a92950ba9dd9efba5e397578c6a5be24e25d`.
- Frozen design path:
  `docs/reports/2026-08-22-spec028-conversion-tracking-design.md`.
- Local design-freeze commit: `31b6c8c`.
- Executable runtime/test SHA:
  `ca3c86ed8e87cfaee8eae65c8780935338026433`.
- Executable CI: `32594487306` — SUCCESS.
- Implementation branch: `feat/spec028-conversion-tracking`.
- Draft implementation PR: `#47`.

The executable-to-closeout delta is restricted to this implementation report.
No runtime, test, migration, or configuration file changes after executable CI.

## Persistence and migration

Alembic remains linear:

`0018_response_intelligence -> 0019_conversion_tracking`

The single new migration has revision `0019_conversion_tracking`, down revision
`0018_response_intelligence`, and creates exactly two SPEC-028 tables:

1. `acquisition_conversion_journey` freezes one account's immutable source
   attribution and safe analytical dimensions.
2. `acquisition_conversion_event` stores append-only, deterministically
   deduplicated conversion milestones.

Migration tests cover fresh upgrade, `0018 -> 0019`, downgrade, re-upgrade,
single-head topology, PostgreSQL offline SQL, SQLAlchemy parity, constraints,
uniques/FKs, the exact two-table boundary, and absence of raw PII columns.

## First-party click and attribution

`conversion-attribution-token-v1` is a canonical, versioned, keyed-HMAC token.
It binds campaign, member, opportunity, country, wedge/version, bounded
sector/version ref, need/version, issuance, expiry, and key version. It carries
no prospect, account, provider, billing, or copy PII and grants no access.

The campaign envelope keeps approved CTA prose unchanged and adds one explicit
Kivou-owned HTTPS `/a/kat1...` URL line. Provider link tracking remains off.
Missing attribution origin/key/materialized sector or existing transport proof
keeps provider exposure fail-closed.

`GET /a/{token}`:

- authenticates and revalidates the exact durable campaign/member binding;
- inserts or replays `CLICK`;
- accepts no caller redirect;
- returns a fixed `303 /signup` with `Cache-Control: no-store` and
  `Referrer-Policy: no-referrer`;
- sets an `HttpOnly`, repository-`Secure`, `SameSite=Lax` first-party cookie
  scoped to `/auth/signup`;
- never authenticates the browser or unlocks product access.

At signup, the last valid cookie-selected Kivou click is bound in the account
creation transaction. Eligibility is the earlier of token expiry and 30 days
after the accepted click. `account_id` and source click are unique. Once bound,
later clicks and direct traffic cannot rewrite campaign/member/opportunity or
country/sector/need/wedge attribution. No signup-email-to-lead-email match is
performed, including for forwarded links.

## Closed milestone contract

The exact implemented vocabulary is:

- `CLICK`
- `SIGNUP`
- `ACTIVATED`
- `PAID`
- `MRR_CHANGED`
- `RETAINED_M1`
- `RETAINED_M2`
- `CHURNED`

Every event has deterministic identity and an immutable source journey.
Duplicate click, signup, activation, Stripe webhook, retention observation, or
churn observation converges. MRR is a chained change fact: repeating the same
value replays, while a real reversion such as `99 -> 49 -> 99` remains an
auditable third change.

## Activation and acquisition outcomes

`ACTIVATED` is recorded only when the durable account has
`onboarding_status == ready_for_signals` and a rechecked count of at least one
account-owned TargetICP in exact `active` state. Page visits and form starts are
not activation.

The implementation preserves `acquisition-state-v1` and adds no EventType.
Existing `OUTCOME_RECORDED` is used replay-safely for:

- `ACTIVATED -> AcquisitionState.ACTIVATED`;
- `PAID -> AcquisitionState.PAID`;
- `RETAINED_M1 -> AcquisitionState.RETAINED`;
- `CHURNED -> AcquisitionState.CHURNED`.

`CLICK`, `SIGNUP`, `MRR_CHANGED`, and `RETAINED_M2` remain conversion facts, not
new acquisition states. Existing reducer monotonicity prevents an out-of-order
lower milestone from regressing acquisition truth.

## Payment and MRR

There is no new Stripe route and no Stripe read during conversion processing.
The existing verified Stripe webhook transaction first reconciles Kivou's
durable `billing_subscription`; SPEC-028 then consumes that stored truth in the
same local transaction. Checkout creation, success URL, frontend state, and
client callback cannot produce `PAID`.

`PAID` requires the existing `StoredSubscription.grants_paid_access` contract:
active status plus an exact known purchasable catalogue plan/currency. Repeated
and out-of-order Stripe delivery retains existing billing reconciliation and
cannot double payment or MRR facts.

`conversion-mrr-v1` stores integer minor units plus explicit lowercase currency:

- monthly catalogue plan: exact Kivou monthly catalogue amount;
- founding offer: exact Kivou effective monthly amount (`2900` minor units);
- annual cadence: currently unsupported by the Kivou catalogue, therefore
  unknown rather than invented;
- unknown plan/currency: `mrr_known=false`, null amount/currency, bounded
  `MRR_UNKNOWN_PLAN` reason;
- terminal churn with known currency: a reproducible zero-MRR change.

No frontend price and no floating-point value participates.

## Retention and churn

`ConversionRetentionWorker` is explicit and has no ASGI/startup wiring.

- `RETAINED_M1`: at or after 30 days from the first durable `PAID`, while the
  current local subscription still grants paid access and the account remains
  genuinely activated.
- `RETAINED_M2`: the same condition at or after 60 days.

The worker records each once. M1 produces the existing `RETAINED` acquisition
outcome; M2 remains the finer conversion milestone.

`CHURNED` requires a previously paid journey and the existing terminal
subscription status `canceled`. `past_due`, checkout expiration,
`cancel_at_period_end`, and `scheduled_cancellation_at` are not churn. A
post-churn win-back model is intentionally outside v1.

## Privacy and architecture boundaries

The conversion tables/events contain no lead or signup email, person/company
name, raw IP, user agent, raw token, campaign body, provider lead ID, Stripe
object ID, Stripe payload, payment-method data, or floating-point revenue.
Provider subscription identity is persisted only as a domain-separated safe
fingerprint. The raw token remains browser/transient input; only its keyed
fingerprint persists.

Hermes may observe durable facts but has no command or argument capable of
creating a click, binding an account, setting MRR, marking retention, or marking
churn. No generic tracking SDK, marketing warehouse, session replay, dashboard,
learning allocator, or browser fingerprinting was introduced.

SPEC-029 may later consume aggregated immutable facts for controlled learning.
SPEC-030 may later render the funnel by country × sector × need × campaign.
Neither behavior is implemented here.

## Configuration and operational defaults

- Attribution HMAC key/version: absent by default.
- Public attribution route with absent service/key: fixed fail-closed 404.
- Instantly tracking: unchanged and disabled.
- Campaign/provider live gates: unchanged and fail-closed.
- Retention worker autostart: disabled; explicit future wiring required.
- Stripe/Instantly/API credentials: none added.
- Production configuration: unchanged.

## Verification

Executable local verification:

- backend: `3914 passed, 2 skipped`;
- skipped tests: exactly the two pre-existing opt-in Stripe TEST smokes in
  `tests/test_billing_stripe_test_smoke.py`:
  `test_stripe_accepte_une_session_pour_un_customer_existant` and
  `test_stripe_expose_une_resiliation_programmee_que_kivou_sait_lire`;
- no SPEC-028 skip;
- Ruff: PASS;
- frontend: `262 passed`;
- build: PASS;
- typecheck: PASS;
- lint: PASS;
- `git diff --check`: PASS.

Executable GitHub CI `32594487306` on
`ca3c86ed8e87cfaee8eae65c8780935338026433`:

- backend: `3914 passed, 2 skipped`;
- Ruff: PASS;
- frontend tests/build/typecheck/lint: PASS;
- status: SUCCESS.

Focused coverage includes token integrity/expiry, fixed redirect and cookie,
duplicate/concurrent click, last pre-signup click, immutable account binding,
activation through the real TargetICP route, verified Stripe webhook
integration, duplicate billing delivery, MRR monthly/founding/unknown/reversion,
M1/M2, scheduled cancellation/past-due/non-churn, terminal churn, acquisition
outcomes, migration topology/parity, PII exclusion, architecture dependencies,
and absence of provider/network behavior.

## Known limitations and deployment gates

- Current Kivou billing catalogue is monthly-only; annual MRR remains unknown
  until an explicit trusted annual catalogue contract exists.
- A shared/replayed click can credit at most one account journey and never
  proves the new account is the original outbound contact.
- Retention evaluation requires separately reviewed explicit runtime scheduling.
- The updated rendered CTA envelope still depends on the existing paused/draft
  provider transport proof before any live campaign can activate.
- SPEC-029 allocation and SPEC-030 cockpit remain out of scope.

No LLM, Apollo, Instantly, Stripe, email, or webhook-management network call was
made. No provider campaign, lead, email, webhook, deployment, migration against a
live database, or production configuration change was performed.
