# SPEC-028 — Conversion Tracking — design v1

**Status:** frozen local design for the single SPEC-028 design-and-implementation
pass. This document does not authorize deployment, production configuration,
provider calls, Stripe calls, email, or merge.

**Audited base:** `dd38a92950ba9dd9efba5e397578c6a5be24e25d`

**Audited on:** 2026-08-22

**Current Alembic head:** `0018_response_intelligence`

**Current acquisition state machine:** `acquisition-state-v1`

## Executive decision

SPEC-028 adds a narrow first-party attribution ledger:

```text
SPEC-026 campaign member
        |
        +-- opaque Kivou CTA token
        +-- GET /a/{token}
              +-- validate, record/replay CLICK
              +-- HttpOnly first-party attribution cookie
              +-- 303 to fixed clean /signup URL
        |
        +-- successful account creation
              +-- freeze last eligible click as SIGNUP attribution
        |
        +-- real account/product/billing facts
              +-- ACTIVATED
              +-- PAID + reproducible MRR
              +-- RETAINED_M1 / RETAINED_M2
              +-- CHURNED
```

The persistence recommendation is the maximum permitted **two tables**:

1. `acquisition_conversion_journey` freezes one account's acquisition source;
2. `acquisition_conversion_event` append-only records deduplicated conversion
   milestones, including anonymous clicks before an account exists.

No browser event stream, session replay, inbox, marketing warehouse, or Stripe
shadow ledger is introduced. Instantly tracking remains disabled. Stripe's
existing authenticated webhook and Kivou's durable billing state remain the
only payment authority.

The closed milestone vocabulary is `CLICK`, `SIGNUP`, `ACTIVATED`, `PAID`,
`MRR_CHANGED`, `RETAINED_M1`, `RETAINED_M2`, and `CHURNED`. Existing
`OUTCOME_RECORDED` maps the four applicable commercial outcomes to
`ACTIVATED`, `PAID`, `RETAINED`, and `CHURNED`. `CLICK` and `SIGNUP` remain
conversion facts. No `AcquisitionState`, state-machine version, or `EventType`
is added.

## Current-main audit and reused truth

| Area | Current contract | SPEC-028 decision |
| --- | --- | --- |
| Acquisition | `acquisition-state-v1` already contains `SENT`, `REPLIED`, `ACTIVATED`, `PAID`, `RETAINED`, `CHURNED`. `OUTCOME_RECORDED` applies a monotonic outcome rank and preserves late lower-ranked audit events without regression. | Reuse it for `ACTIVATED`, `PAID`, `RETAINED_M1`, and `CHURNED`. Never create click/signup states or a conversion event type. |
| Campaign | `acquisition_campaign` freezes country, wedge, selected need, provider campaign identity, tracking policy, and exact sequence windows. `acquisition_campaign_member` binds one opportunity. Open/link tracking is false. | The Kivou token binds these immutable safe refs. Provider tracking stays off. |
| Envelope | Personalization CTA is approved prose and the exact transport envelope has no first-party CTA URL slot. | Add one explicit Kivou-owned attribution URL transport value without changing approved CTA prose. It is rendered as its own line and included in the envelope fingerprint. |
| Accounts | Signup atomically creates `account`, auth user, and session. The account owns its TargetICPs. | Bind attribution in the same signup transaction from a validated HttpOnly cookie; never match account/signup email to the outbound lead. |
| Activation | `accounts.service.onboarding_status()` returns `ready_for_signals` exactly when at least one account-owned TargetICP is `active`; otherwise it returns `icp_incomplete` or `account_created`. | `ACTIVATED` means `ready_for_signals` and a rechecked count of at least one valid active TargetICP. Page visits and form starts are irrelevant. |
| Billing | `billing_subscription` is the durable current subscription. Only status `active` plus a known purchasable Kivou plan grants paid access. `past_due`, `unpaid`, `paused`, `trialing`, scheduled cancellation, and checkout facts do not. | `PAID` consumes this local truth after the existing webhook synchronization. No new endpoint and no Stripe read is added. |
| Prices | The versioned catalogue maps monthly Essential/Pro/Scale amounts in CHF/EUR as integer minor units. The founding offer has a known current effective amount. There is no annual Kivou catalogue contract. | MRR is catalogue-owned. Monthly plans map directly; a current founding offer uses its versioned effective amount. Annual/unknown cadence or unknown plan/currency is `UNKNOWN`, never guessed. |
| Churn | `canceled` and `incomplete_expired` are terminal subscription states. Scheduled cancellation remains active until the paid entitlement actually ends; `past_due` is open but non-paying. | A journey churns only after it previously recorded `PAID` and the durable current subscription becomes `canceled`. `incomplete_expired` without prior payment is not churn. Other non-paying/open states are not churn. |
| Stripe ingress | `POST /webhooks/stripe` verifies the raw payload, deduplicates by Stripe event ID, fetches current provider state through its existing gateway, synchronizes local billing, and records the event in one transaction. | Add a local conversion reconciliation call after successful local synchronization, in the same transaction. Do not add a second webhook, raw payload copy, or provider call. |
| Migrations | Current linear head is `0018_response_intelligence`. | Add `0019_conversion_tracking -> 0018_response_intelligence`, or the next linear number if main legitimately moves. No merge revision. |

## Scope and explicit boundaries

SPEC-028 owns immutable source attribution and factual conversion milestones.
It does not own:

- provider open/link tracking;
- user identity/authentication through an attribution token;
- arbitrary redirect, browser fingerprinting, localStorage attribution, or
  cross-site tracking;
- a general analytics/event SDK or page-view firehose;
- Stripe checkout or webhook ownership;
- payment-method, invoice, tax, or raw Stripe history;
- dashboard/weekly cockpit aggregation (SPEC-030);
- learning, scoring, or wedge reallocation (SPEC-029);
- win-back attribution after churn;
- campaign copy changes beyond an explicit transport URL slot.

Hermes may read bounded journey/event facts. It cannot create, rewrite, or
delete conversion truth, choose attribution, set MRR, mark retention/churn, or
invoke an override.

## `conversion-attribution-token-v1`

The email URL contains a versioned authenticated opaque token, not clear query
parameters. Its external representation is:

```text
kat1.<key_version>.<member_ref>.<base64url(HMAC-SHA256)>
```

`member_ref` is the sole clear lookup reference. It is already an opaque,
PII-free Kivou fingerprint. No JSON, campaign, opportunity, country, wedge,
sector, need, or timestamp payload is encoded in the public URL.

The hidden canonical HMAC input binds exactly:

- token and key versions;
- `campaign_ref`;
- `member_ref`;
- `acquisition_opportunity_id`;
- immutable `country`, `wedge` and wedge version;
- safe `sector_ref`, selected `need_ref`, and need version;
- `issued_at` and `expires_at`.

The token contains no email, contact/supplier/company name, account, Stripe ID,
provider lead ID, copy, or arbitrary URL. The signature uses an injected
retained-key keyring. Equality and verification use constant-time comparison.
Only the keyed token fingerprint and safe payload facts may persist; the raw
token does not. Verification parses only the token/key/member lookup, loads the
exact durable member/campaign/opportunity, reconstructs the complete hidden
payload through the same Kivou source resolver used at issuance, and then
constant-time verifies the HMAC and validity interval. Binding drift is an
invalid token, never a partially accepted click.

Token issuance is deterministic for the immutable campaign/member envelope.
`issued_at` is the Step-1 authorized-window start and `expires_at` is 30 days
after the Step-2 authorization deadline. This covers a click from either frozen
message without creating a permanent link. Token expiry and the 30-day
click-to-signup window are independent: signup requires both to be valid.

A valid token is attribution evidence only. It never authenticates, creates a
session, selects an account, unlocks a signal, grants access, or supplies an
authorization decision. Forwarding may attribute a resulting signup to the
campaign, but the journey explicitly makes no claim that the new account is the
original outbound contact.

## Click endpoint and browser context

The only public entry point is equivalent to `GET /a/{token}`. It accepts no
redirect argument. On a valid unexpired token it:

1. resolves the clear opaque `member_ref`, reconstructs the full hidden source
   payload, then verifies its HMAC and immutable bindings;
2. records or replays one `CLICK` milestone;
3. sets a signed first-party attribution cookie containing the opaque token;
4. responds `303` to the fixed relative `/signup` destination;
5. sets `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.

The cookie is `HttpOnly`, follows the repository's `Secure` policy, is
`SameSite=Lax`, has path `/auth/signup`, and expires with the token. The clean
destination URL contains no token. Nothing uses localStorage. Invalid, expired,
or mismatched tokens produce a fixed safe not-found response, set no cookie,
record no business fact, and unlock nothing.

A duplicate click for the same token converges to the same event and does not
extend its attribution clock. A click for a different valid token overwrites
the browser cookie; this makes the browser carry exactly the last valid Kivou
outbound click without storing an identifying click stack.

## Attribution rule and signup freeze

`click-to-signup-attribution-v1` is:

- eligibility: successful signup at or after `CLICK.occurred_at` and strictly
  no later than 30 days after it, while the token itself is unexpired;
- selection: deterministic last eligible Kivou outbound click before signup;
- tie-break for equal timestamps: lexicographically greatest event ID;
- freeze: one immutable journey per `account_id`, created in the successful
  account transaction;
- no rewrite: later clicks, login, direct traffic, payment, or reprocessing
  cannot change the journey;
- no identity matching: signup email is never compared to the outbound email.

The HttpOnly cookie normally identifies the last click. The store still checks
the durable click and deterministic ordering so a stale, replayed, or forged
cookie cannot select an ineligible source. Signup without an eligible context
remains a normal unattributed account; no empty journey is fabricated.

One deduplicated `CLICK` may source multiple distinct account journeys when a
legitimate attribution-only link is forwarded or shared. Each account still
freezes at most one journey; reuse never claims that either account is the
original outbound contact and never blocks either account creation.

`SIGNUP` means only that a real account was committed with an eligible frozen
journey. It is not a browser form submission.

## Analytics dimensions

The journey freezes the following safe source dimensions from the exact
campaign/source facts at token issuance:

- `country`;
- `sector_ref` — a versioned safe ref derived from the exact public signal's
  bounded sector code and inference version, never a mutable display label;
- selected `need_ref` and need-engine version;
- `campaign_ref`;
- `wedge` and wedge version.

The original opportunity/member refs remain the audit bridge. Unknown sector
must be the explicit versioned `sector-unknown-v1`, never an invented label.
SPEC-030 may aggregate these codes later; SPEC-028 does not expose a dashboard.

## Closed conversion milestones

| Milestone | Exact authority and definition | Acquisition mapping |
| --- | --- | --- |
| `CLICK` | Valid token, exact immutable source binding, first-party endpoint accepted. One event per token fingerprint. | none |
| `SIGNUP` | Account creation committed with the last eligible pre-signup click. | none |
| `ACTIVATED` | Account has `onboarding_status == ready_for_signals` and at least one account-owned TargetICP in exact `active` state. | replay-safe `OUTCOME_RECORDED(ACTIVATED)` |
| `PAID` | Current durable `billing_subscription` has status `active`, a recognized purchasable plan, and known currency under Kivou billing rules. Checkout creation/completion alone is insufficient. | replay-safe `OUTCOME_RECORDED(PAID)` |
| `MRR_CHANGED` | Reproducible MRR facts changed from the last known event, including the initial known amount. Unknown configuration records a bounded unknown result rather than a number. | none |
| `RETAINED_M1` | At `first_paid_at + 30 days` or later, the account is both currently `PAID` and currently `ACTIVATED`. | replay-safe `OUTCOME_RECORDED(RETAINED)` |
| `RETAINED_M2` | Same current conditions at `first_paid_at + 60 days` or later. | none; event only |
| `CHURNED` | Journey previously recorded `PAID`; durable current subscription is terminal `canceled`, meaning paid lifecycle ended. | replay-safe `OUTCOME_RECORDED(CHURNED)` |

Every observation time is injected. Page view, open/click provider event,
checkout page/success redirect, `checkout.session.completed`, trial, scheduled
cancellation, `past_due`, `unpaid`, temporary payment failure, and login
frequency are not substitutes for these definitions.

## MRR contract

`conversion-mrr-v1` produces either a known Money value or `UNKNOWN`:

- normal monthly plan: `catalogue.amount_for(plan_code, currency)`;
- current recognized founding offer: the catalogue's versioned effective
  monthly minor-unit amount;
- a future annual plan: annual recurring minor units divided by 12 only after
  an explicit catalogue cadence and exact divisibility/rounding contract exist;
- unknown plan, currency, cadence, or amount: `UNKNOWN` with bounded reason.

The present repository publishes monthly plans only, so annual MRR is not
supported or guessed in v1. Known MRR stores integer minor units and lowercase
ISO currency. No floating point, exchange conversion, frontend display price,
Stripe network read, or raw Stripe amount is used.

`MRR_CHANGED` identity includes the journey, subscription safe ref, catalogue
version, status, plan/offer, currency, known/unknown marker, and integer amount.
Repeated Stripe delivery converges; a real plan/offer/amount change appends a
new event.

## Retention and churn execution

An explicitly invoked `ConversionRetentionWorker` scans only attributed
journeys with `PAID` and missing due milestones. It re-reads account activation
and the local current subscription in one transaction. It never starts from
ASGI/application import or server startup and never calls Stripe.

M1/M2 are one-time cohort facts relative to the first `PAID.occurred_at`.
Failing the condition exactly at day 30/60 does not permanently close the
milestone: a later explicit run may record it if the account is then paying and
activated. After `CHURNED`, v1 records no later retention or win-back event.

`cancel_at_period_end` and `scheduled_cancellation_at` are forward-looking
facts, not churn. `past_due`, `unpaid`, `paused`, and temporary payment problems
are likewise not churn. The only v1 terminal churn observation is current
status `canceled` after a prior `PAID`; `incomplete_expired` never becomes churn
unless a prior `PAID` proves that exceptional lifecycle, in which case the
service fails closed for review rather than inferring it.

## Persistence: exactly two tables

### `acquisition_conversion_journey`

One immutable attributed account source:

- `journey_ref` primary key and `account_id` unique FK;
- source click event ref indexed and intentionally non-unique;
- campaign/member/opportunity refs and token fingerprint/version/key version;
- country, sector ref/version, need ref/version, wedge/version;
- attribution-policy version and source fingerprint;
- click/sign-up times, 30-day deadline, created time.

Source columns are write-once. There is no lead/signup email, person/company
name, IP, user agent, account display name, Stripe ID, or mutable label.

### `acquisition_conversion_event`

Append-only milestone ledger:

- deterministic `conversion_event_ref` primary key;
- nullable `journey_ref` for pre-signup `CLICK`, non-null thereafter;
- exact milestone and event-fingerprint/version;
- source token fingerprint for click lookup, safe triggering ref/type;
- occurred/observed/recorded timestamps;
- optional safe account/campaign/member/opportunity refs constrained by phase;
- activation fingerprint;
- safe billing subscription ref fingerprint and catalogue version;
- MRR known flag, integer minor units, currency, bounded reason;
- acquisition outcome event ref where applicable.

Constraints enforce the closed milestone vocabulary, click/signup journey
shape, Money completeness, M1/M2 ordering inputs, and no duplicate deterministic
identity. There are no JSON audit blobs or raw provider/Stripe payload columns.

## Idempotency, ordering, and transactions

Each event identity is a domain-separated fingerprint of the milestone and its
immutable authority:

- click: token fingerprint;
- signup: journey/account/source click;
- activation: journey + account activation fingerprint;
- paid: journey + first recognized paying subscription lifecycle;
- MRR: journey + normalized MRR/billing fingerprint;
- retention: journey + first-paid event + M1/M2 policy version;
- churn: journey + prior paid + terminal subscription observation.

Database uniqueness is the final concurrency authority. Insert-or-replay never
changes frozen attribution. Duplicate account/ICP/Stripe/worker calls return the
existing fact. Stripe synchronization, conversion reconciliation, conversion
event insertion, and acquisition outcome append share the caller's transaction,
so a crash commits all or none. Retrying after a crash re-reads local truth and
derives the same identity.

Out-of-order billing events retain current billing safeguards. SPEC-028 never
reconstructs truth from event delivery order and never regresses acquisition
state. An activation observed after payment may append its true milestone; its
lower-ranked acquisition outcome cannot downgrade `PAID`.

## Campaign/envelope boundary

The exact personalization `artifact.cta` remains unchanged prose. The smallest
transport extension is an explicit `attribution_url` value rendered on a new
line between CTA prose and the approved footer. It is:

- generated only by Kivou from the member/token contract;
- an HTTPS Kivou public-site URL with the fixed `/a/` path;
- prohibited from arbitrary caller/Hermes input;
- included in envelope/action/lead payload fingerprints;
- the only URL allowed by this new slot;
- incompatible with provider link tracking, which remains false.

If the public site URL, attribution HMAC key, safe sector binding, or exact
rendered-envelope proof is unavailable, provider exposure/activation remains
blocked. Existing empty mailbox and unverified transport defaults continue to
make live outbound impossible.

## Privacy and security boundary

Conversion rows and generic events never contain:

- outbound or signup email;
- contact/account/person/company name;
- raw attribution token;
- IP address or user agent;
- campaign subject/body/footer;
- Stripe/customer/subscription IDs in raw provider form;
- Stripe payload, invoice, payment-method, or checkout URL data.

IP-based abuse controls, if later required, remain API-security telemetry under
the repository's retention rules and never become an attribution dimension.
The token is bearer attribution evidence but not bearer authorization. Safe
provider billing identity is a domain-separated Kivou fingerprint only.

## API and integration points

- New route: fixed `GET /a/{token}` only.
- Signup: optionally consumes/clears the attribution cookie in the existing
  account transaction after account creation succeeds.
- TargetICP create/update: calls local activation reconciliation after current
  status and ownership are durable.
- Stripe webhook: calls local payment/MRR/churn reconciliation after current
  billing synchronization, in the same transaction.
- Retention: explicitly invoked local worker/service, no autostart.
- Campaign: generates the first-party URL through an injected Kivou token/link
  service; imports and default app creation perform no I/O.

No new Stripe/Instantly webhook, provider operation, tracking SDK, frontend
analytics API, or background loop is introduced.

## Migration recommendation

Create one linear migration:

```text
0018_response_intelligence
  -> 0019_conversion_tracking
```

It creates exactly `acquisition_conversion_journey` and
`acquisition_conversion_event`. If origin/main gains an unrelated migration
before finalization, renumber to the next linear revision without an Alembic
merge revision. Downgrade removes only these two tables in dependency order.

## Required implementation tests

The implementation must prove with focused unit/integration tests:

- opaque token components cannot disclose the hidden canonical payload;
- valid, deterministic, retained-key, tampered, expired, malformed, and
  wrong-binding click tokens;
- token never authenticates or unlocks a protected route;
- fixed clean redirect, cookie flags, no arbitrary redirect/referrer leak;
- last eligible pre-signup click wins; equal-time tie-break is deterministic;
- signup inside/outside 30 days; one forwarded token may source two account
  journeys while its CLICK stays deduplicated and never claims contact identity;
- account attribution is immutable against later/direct clicks;
- activation requires exact `ready_for_signals` plus active TargetICP and is
  idempotent under create/update/concurrency;
- checkout success/completion alone never records payment;
- active recognized local subscription records one `PAID` and initial MRR;
- duplicate/out-of-order Stripe deliveries cannot double events/revenue;
- monthly and founding MRR; future annual/unknown price fails closed without an
  invented number;
- M1 and M2 at/after 30/60 days only while currently paying and activated;
- scheduled cancellation, `past_due`, temporary problem, and
  `incomplete_expired` without prior paid are not churn;
- terminal `canceled` after paid records one `CHURNED`;
- acquisition outcomes remain monotonic and use existing EventType only;
- crash/replay/concurrent click, signup, activation, billing, and retention
  observations converge;
- raw PII/token/provider payload markers are absent from both tables,
  acquisition events, Policy arguments, logs, and errors;
- no Stripe, Instantly, Apollo, email, or LLM network activity;
- no SPEC-029 allocation and no SPEC-030 cockpit/dashboard behavior.

Migration tests cover fresh head, `0018 -> 0019`, downgrade/re-upgrade, one
Alembic head, PostgreSQL offline SQL, SQLAlchemy Core parity, exactly two
SPEC-028 tables, constraints/FKs/uniques, and absence of PII columns.

## Deployment defaults and remaining gates

Repository defaults remain non-live:

- no attribution HMAC key;
- no configured public attribution base URL beyond explicit deployment config;
- empty campaign mailbox catalogue;
- Instantly transport proof unverified;
- autonomous outbound zero;
- no worker autostart;
- no production migration or route deployment in this task.

Before production use, an operator must separately configure a retained
attribution HMAC key/version, exact HTTPS public site URL and cookie policy,
deploy the migration/route, prove the updated envelope rendering in the paused
transport contract, and explicitly wire retention execution. This report does
not perform any of those actions.

## SPEC-029 and SPEC-030 handoff

SPEC-028 ends at immutable, queryable conversion facts. SPEC-029 may later
consume aggregated results to propose controlled allocation changes, but cannot
rewrite them. SPEC-030 may aggregate the frozen country/sector/need/campaign/
wedge dimensions into weekly funnels, but owns all presentation, cohort
definitions beyond M1/M2, and cockpit UX. Neither learning nor dashboard logic
belongs in the SPEC-028 package.
