# SPEC-026 — Instantly Adapter + Campaign Factory — design

**Status:** design only; no runtime, schema, migration, provider, campaign, or
deployment change is authorized by this report.

**Audited base:** `ea4c91c061ce3260a6ccf5d0ee9ade24e5759892`

**R3 clarification base:** `305a96d80c4b9c3903f4f1ef3337161417fc7e0f`

**Audited on:** 2026-08-21

**Alembic head:** `0014_compliance`

**Observed local baseline:** backend `3523 passed`, skipped `0`; frontend
`150 passed`. These are read-only baseline runs on the audited base, not
SPEC-026 implementation validation.

**R3 current-main baseline:** backend `3552 passed`, skipped `1` (only
`tests/test_billing_stripe_test_smoke.py`, the opt-in Stripe TEST smoke);
frontend `150 passed`. R3 changes design prose only.

### Design R1 freeze

R1 removes the unsafe possibility of enrolling a lead into an active provider
campaign. Micro-campaigns are immutable batches: retained members are enrolled
and become `QUEUED` while the provider campaign is non-sending, membership is
sealed, every retained member is revalidated, and only then may activation be
attempted.
R1 also freezes initial caps/windows/follow-up/tracking/stop settings and gates
`reply_received` subscription until SPEC-027 can durably retain sensitive reply
content. The external deployment inputs that remain unresolved are the real
mailbox catalog, exact privacy/footer catalog, Hyper Growth entitlement, and a
separately authorized paused-provider transport-contract proof.

### Design R2 freeze

R2 freezes `batch-seal-policy-v1`: the first reserved member establishes an
immutable `membership_close_at = first_member_reserved_at + 15 minutes`, and
membership closes at the earlier of that deadline or the tenth reserved slot.
A `BUILDING` campaign can therefore be membership-open or membership-closed
while already-reserved provider operations finish or reconcile. It becomes
`SEALED` only after every retained member is ready for activation; a partial
one- or three-member batch is valid, while a batch with no retained member
becomes non-active `FAILED`.

R2 also separates the acquisition `QUEUED` milestone from current transport
truth. After `SEND -> QUEUED`, the closed `acquisition_campaign_member`
execution state is authoritative for activation eligibility. Before
activation, a later hard suppression, objection, compliance expiry, or binding
invalidation moves the member to `STOPPED`, clears the generic workflow action
with the existing
reasoned `NEXT_ACTION_SET(null)` semantics, and never fabricates a reverse
AcquisitionState transition. Temporary provider or mailbox failures remain
operational reconciliation states rather than hard stops.

### Design R3 clarification

R3 separates two validity concepts that must not be collapsed. The SPEC-025
assessment `valid_until` is **pre-activation freshness authority**: every
retained member must still hold its exact, unexpired `RECORDED/ALLOWED`
assessment immediately before activation. Successful activation then
authorizes only that member's exact immutable two-step
`campaign-sequence-policy-v1`; passage beyond the assessment's normal 24-hour
freshness TTL after activation does not alone revoke Step 2.

This does not create permanent authorization. At activation, the exact
ruleset and sender-configuration validity boundaries must cover the authorized
Step-2 execution window, and suppression, unsubscribe, objection, reply,
auto-reply, pause, kill-switch, and provider/account safety stops remain live
throughout execution. SPEC-026 does not fabricate a second compliance
assessment or silently invoke the workflow-bound ComplianceService for a
`QUEUED`/`SENT` member. It does not extend SPEC-025's 24-hour TTL, add a Policy
command, add a table, or broaden the opportunity workflow.

### Design R3.2 freeze

R3.2 resolves the timing materialization boundary. Before activation,
`sequence-window-policy-v1` authorizes exactly two bounded local execution
dates and their exclusive 17:00 deadlines. It does **not** pretend the exact
Step-2 due time exists. Only a deduplicated authoritative Step-1 `email_sent`
event materializes `step_1_sent_at`, exact `step_2_due_at`, and the immutable
`sequence_timing_fingerprint`.

The provider campaign is configured before activation with both immutable
message steps, exact start/end dates, `[09:00,17:00)` hours, and only the two
required active weekdays. An unsent Step 1 expires at its first-window
deadline and must be made non-sendable before the second window; Step 2 expires
at its own deadline. Any authoritative out-of-window send remains real
transport truth and records a bounded safety incident rather than being
discarded or relabeled as authorized.

## Executive recommendation

SPEC-026 should add a deterministic, opportunity-scoped scheduling saga around
a narrow Instantly API V2 adapter. Kivou remains authoritative for the
opportunity, copy, compliance, suppression, mailbox choice, send window,
budgets, quotas, workflow, and provider reconciliation. Instantly receives only
an already-authorized execution plan and reports transport execution facts.

The design begins at:

```text
state = SEND
decision = SEND
next_action = schedule_campaign
+ exact READY personalization
+ exact current, unexpired RECORDED/ALLOWED compliance assessment
```

It reaches `SEND -> QUEUED` only after Kivou has durable proof that the exact
lead is enrolled in the exact configured **non-sending** Instantly campaign,
all provider identities are recorded, and all current execution gates pass.
Membership then closes under `batch-seal-policy-v1`; already-reserved members
finish or reconcile, the retained set is sealed, and every retained member is
revalidated before provider activation may be attempted. `QUEUED` records that
an opportunity reached durable external-enrollment authorization; it does not
require provider ACTIVE status and does not mean sent. Current activation/send
eligibility is the member execution state, and only member state `QUEUED` is
eligible. Only a deduplicated authoritative `email_sent` provider event may
advance the member and acquisition opportunity to `SENT`, and that acquisition
transition is specifically the first-step event; Step 2 advances only the
member's separate sequence state.

The minimum safe migration recommendation is `0015_campaign_factory` with four
tables: campaign, campaign member, provider operation, and provider event. Each
has a distinct normalization/idempotency purpose; none stores provider raw
responses or duplicate rendered email copy.

R1 freezes autonomous live volume at zero, the first live trial as ASSISTED,
the initial caps, weekday windows, one follow-up, and tracking/stop settings.
No live volume becomes authorized merely by implementing this design. Real
mailboxes, exact footer/privacy configuration, webhook entitlement, and the
paused Instantly transport proof remain deployment gates listed at the end.

## Repository baseline and code audit

The implementation boundary below is grounded in the actual audited main, not
the roadmap alone.

| Area | Current main contract | SPEC-026 consequence |
| --- | --- | --- |
| Acquisition contracts/state | `acquisition-state-v1` includes `SEND`, `QUEUED`, and `SENT`. The only transition out of `SEND` is `QUEUED`; `QUEUED` can move to `SENT`. `campaign_ref` already exists on `AcquisitionOpportunity`. | No state-machine v2 is needed. `campaign_ref` needs an audited event-store binding; it must not be patched directly into a projection. |
| Acquisition events | Existing types are `OPPORTUNITY_CREATED`, `STATE_TRANSITIONED`, `DECISION_RECORDED`, `NEXT_ACTION_SET`, `RETRY_SCHEDULED`, `SUPERVISOR_PLAN_OBSERVED`, `POLICY_EVALUATED`, `CONTACT_SELECTED`, and `OUTCOME_RECORDED`. `STATE_TRANSITIONED` currently changes state but does not bind a campaign. | Prefer a backward-compatible optional `campaign_ref` binding on the `SEND -> QUEUED` `STATE_TRANSITIONED` event. Historical payloads remain valid. Introduce a new event type only if implementation proves this atomic extension unsafe. |
| Personalization | `acquisition_personalization_artifact` has immutable `READY`/`POLICY_BLOCKED` dispositions and exact input/proposal/artifact/action fingerprints. Only `READY` holds the bounded subject, greeting, body, and CTA. | Scheduling binds the exact current `READY` row and fingerprint. Generic campaign/policy/event JSON must not duplicate the copy. |
| Compliance | `acquisition_compliance_assessment` stores immutable `RECORDED`/`POLICY_BLOCKED` assessments, exact personalization and ruleset bindings, state, `valid_until`, workflow event, and fingerprints. A suppression store already performs Kivou-owned versioned HMAC matching. | A scheduler must find the exact `RECORDED/ALLOWED` assessment that caused the current `schedule_campaign` handoff, require `valid_until > captured_at` through the final pre-activation check, and perform fresh suppression checks before provider exposure, queue commit, and activation. After valid activation, the assessment's aggregate freshness TTL is not itself a Step-2 revocation timer; live hard stops and the separately bound underlying ruleset/sender validity still govern. |
| Policy registry/evaluator | `schedule_campaign` is already an OPPORTUNITY-scoped `COMMERCIAL_MUTATION`, uses budget/volume/provider quota/send controls, and requires compliance. Its required evidence remains the legacy `VERIFIED_CONTACT`, `FIT_DECISION`, `RECENT_SIGNAL`; `requires_control_plane` is not enabled. ASSISTED commercial mutation requires existing ACTION approval; SHADOW is non-executable. | SPEC-026 must replace legacy evidence with Kivou-built acquisition/personalization/compliance/campaign/readiness evidence and enable the control-plane gate. It must not change TargetScope to CAMPAIGN. |
| Supervisor | `schedule_campaign`, `pause_campaign`, and later commands already exist in `ALLOWED_COMMANDS`; `ALLOWED_NEXT_ACTIONS` derives from commands. | No new command is needed to schedule one opportunity. Hermes supplies intent/authorization context, never raw provider payloads, mailbox email, or API keys. |
| Contact/company research | Durable supplier/contact/provider-verification/profile bindings exist. The business email is stored in the contact domain and is needed transiently by the provider. | Resolve email only inside the bounded adapter call and webhook resolver. Never place it in generic campaign/event/Policy payloads or provider campaign names. |
| API | The FastAPI application currently has only the established Stripe webhook route; there is no Instantly route/config. | A new provider-specific webhook endpoint must follow the same bounded-ingress/atomic-dedup discipline, but use Instantly's verified custom-header capability rather than pretending Instantly supplies Stripe-style signatures. |
| Persistence/migrations | Migrations `0007` through `0014_compliance` are linear. There is no campaign/provider table or runtime. | The next recommendation is one linear `0015_campaign_factory`; no existing table can safely serve all shared-campaign membership, outbound-operation, and inbound-event roles. |

Inspected code includes `signals/acquisition`, `personalization`, `compliance`,
`policy`, `supervisor`, `contact_discovery`, `company_research`, `persistence`,
`api`, migrations `0007`–`0014`, and their state/replay, policy, compliance,
personalization, migration, webhook, concurrency, PII, and architecture tests.
The repository contains no Instantly client, Campaign Factory, campaign worker,
or Instantly-originated acquisition event today. The Hermes v2.6 doctrine used
here is the task-provided source: “Apollo discovers. Instantly sends. Stripe
collects. Hermes pilots. Kivou keeps control.”

## Official Instantly API V2 verification

Only official Instantly developer documentation and Help Center sources were
used. No live API, account, workspace, or provider key was accessed. The V2
documentation was verified on 2026-08-21. Instantly's official
[V1-to-V2 migration guide](https://developer.instantly.ai/guides/api-v1-migration)
states that V1 was deprecated on 2026-01-19; SPEC-026 must reject any V1 base
path.

### Endpoint and scope matrix

| Capability | Official V2 contract verified | Narrow scope | Design use/caveat |
| --- | --- | --- | --- |
| Create campaign | [`POST /api/v2/campaigns`](https://developer.instantly.ai/api-reference/campaign/create-campaign) | `campaigns:create` | Requires `name`; supports schedule, sequences, assigned accounts, pacing/tracking/stop options. No universal Kivou idempotency header is documented. |
| List campaigns | [`GET /api/v2/campaigns`](https://developer.instantly.ai/api-reference/campaign/list-campaign) | `campaigns:read` | Supports pagination and name `search`; docs do not promise exact/unique matching, so reconciliation must exact-match Kivou name plus configuration/workspace identity. |
| Get campaign | [`GET /api/v2/campaigns/{id}`](https://developer.instantly.ai/api-reference/campaign/get-campaign) | `campaigns:read` | Authoritative readback for provider ID, status, configuration, accounts, sequence, and reconciliation. |
| Configure campaign | [`PATCH /api/v2/campaigns/{id}`](https://developer.instantly.ai/api-reference/campaign/patch-campaign) | `campaigns:update` | Configuration must be a closed adapter-owned schema, never arbitrary Hermes JSON. Read back and fingerprint the desired subset after mutation. |
| Activate | [`POST /api/v2/campaigns/{id}/activate`](https://developer.instantly.ai/api-reference/campaign/activatestart-or-resume-a-campaign) | `campaigns:update` | Success means campaign activation, not email sent. A timeout is remote-unknown and requires GET reconciliation. |
| Pause | [`POST /api/v2/campaigns/{id}/pause`](https://developer.instantly.ai/api-reference/campaign/stopor-pause-a-campaign) | `campaigns:update` | Risk-reducing operation; still ledgered/reconciled. It does not itself classify a lead response. |
| Create one lead | [`POST /api/v2/leads`](https://developer.instantly.ai/api-reference/lead/create-lead) | `leads:create` | Requires email and can bind a campaign; supports `custom_variables` and duplicate/skip controls. Email is used transiently. |
| Bulk-add leads | [`POST /api/v2/leads/add`](https://developer.instantly.ai/api-reference/lead/add-leads-in-bulk-to-a-campaign-or-list) | `leads:create` | Accepts 1–1000 leads and returns created/skipped/invalid counts. The provider maximum is not Kivou's product cap. Partial result reconciliation is mandatory. |
| Lead lookup/reconciliation | [`POST /api/v2/leads/list`](https://developer.instantly.ai/api-reference/lead/list-leads), [`GET /api/v2/leads/{id}`](https://developer.instantly.ai/api-reference/lead/get-lead) | `leads:read` | Filter by campaign/contact/IDs and paginate. Provider lead status includes active, paused, completed, bounced, unsubscribed, and skipped. |
| Lead safety mutation | [`PATCH /api/v2/leads/{id}`](https://developer.instantly.ai/api-reference/lead/patch-lead) | `leads:update` | Reserve only for a reviewed stop/pause/reconciliation operation; do not expose generic lead patching to Hermes. |
| List accounts | [`GET /api/v2/accounts`](https://developer.instantly.ai/api-reference/account/list-account) | `accounts:read` | Bounded readiness catalog discovery/reconciliation only. |
| Get account | [`GET /api/v2/accounts/{email}`](https://developer.instantly.ai/api-reference/account/get-account) | `accounts:read` | Provider identifies an account by email; Kivou callers use `mailbox_ref`, and only the adapter resolves the raw provider identifier. |
| Create/list webhook | [`POST /api/v2/webhooks`](https://developer.instantly.ai/api-reference/webhook/create-webhook), [`GET /api/v2/webhooks`](https://developer.instantly.ai/api-reference/webhook/list-webhooks) | `webhooks:create`, `webhooks:read` | Creation supports target URL, optional campaign/event filter, and custom headers. Recommended as deployment-owned, not scheduler-owned. |
| Webhook event types | [`GET /api/v2/webhooks/event-types`](https://developer.instantly.ai/api-reference/webhook/list-available-event-types) | `webhooks:read` | Deployment verification should pin the accepted transport vocabulary. Unknown values fail closed. |
| Webhook test/resume | [`POST /api/v2/webhooks/{id}/test`](https://developer.instantly.ai/api-reference/webhook/test-a-webhook), [`POST /api/v2/webhooks/{id}/resume`](https://developer.instantly.ai/api-reference/webhook/resume-a-webhook) | `webhooks:update` | Deployment/operations capability, separate from normal scheduling. |
| Webhook delivery records | [`GET /api/v2/webhook-events`](https://developer.instantly.ai/api-reference/groups/webhook-event) and item/summary endpoints | `webhooks:read` | Useful for bounded reconciliation. The documented push payload itself does not promise this record ID. |

The official [Campaign schema](https://developer.instantly.ai/api-reference/schemas/campaign)
documents draft/active/paused/completed status, sequences/steps/variants,
delay and delay unit, schedules with days/times/timezone, account assignment,
email gap, random wait, text-only settings, daily limits, `stop_on_reply`,
tracking options, unsubscribe header, risky-contact/bounce controls, company
limits, and auto-variant features. Only an explicit allowlist subset belongs in
the adapter.

The official [Account schema](https://developer.instantly.ai/api-reference/schemas/account)
documents account status (active, paused, maintenance, connection error,
soft-bounce error, sending error), `warmup_status`, `setup_pending`,
`daily_limit`, `sending_gap`, and `tracking_domain_status`. Provider account
objects also contain email/name/signature data; the readiness projection must
discard those fields after resolving the Kivou mailbox.

Instantly's [rate-limit guidance](https://developer.instantly.ai/getting-started/rate-limit)
documents workspace-wide limits of 100 requests/second and 6,000/minute across
keys and returns HTTP 429 when exceeded. It recommends batching. The page does
not document a guaranteed `Retry-After` response, so the adapter should honor it
when present but otherwise use a bounded Kivou backoff, never an uncontrolled
loop.

### Variables and exact-copy caveat

The official [lead-create contract](https://developer.instantly.ai/api-reference/lead/create-lead)
accepts bounded `custom_variables`. Official Help Center guidance confirms that
custom variables use `{{variableName}}` syntax and are available in both
[campaign subject and body](https://help.instantly.ai/en/articles/6135930-how-to-add-and-use-variables-in-campaigns).
It also warns that a missing mail-merge value may render as an empty string.

The official material does **not** provide a byte-for-byte guarantee for placing
one variable across an entire subject/body, nor a V2 preview/render endpoint
that proves provider escaping and footer interaction without sending. Therefore
the preferred transport is conditional on a provider-contract proof before any
activation:

```text
campaign subject = {{kivou_subject}}
campaign body    = {{kivou_envelope}}

lead custom variables:
  kivou_subject  = exact READY artifact subject
  kivou_envelope = exact, locally validated core + approved transport/footer
  kivou_member_ref = opaque Kivou member reference
```

The adapter must reject missing/empty/extra variables, spintax, Liquid
conditionals, variants, AI personalization, AI SDR, and provider-generated
copy. It must read back the campaign template and lead variables and locally
reconstruct the final string. Deployment configuration carries a bounded
capability:

```text
transport_contract_proof = UNVERIFIED | VERIFIED
default = UNVERIFIED
```

`UNVERIFIED` permits only separately authorized staging creation/configuration
with the provider campaign kept DRAFT/PAUSED; `ACTIVATE_CAMPAIGN` is impossible.
Only a separately authorized paused/draft Instantly contract test may establish
`VERIFIED` after proving exact whole-subject/body and unsubscribe transport.
Failure does not trigger a literal or one-message-per-campaign fallback: it
stops for supervisor architecture review.

## Plan and webhook entitlement

Official Help Center material says [API V2 is available on paid Email Outreach
plans](https://help.instantly.ai/en/articles/10432807-api-v2), while the
[plan comparison](https://help.instantly.ai/en/articles/7920548-email-outreach-plans-comparison)
excludes trial use. The official [webhook guide](https://help.instantly.ai/en/articles/6261906-webhooks)
requires **Hyper Growth or above**. The repository contains no durable proof of
the active Instantly plan or workspace entitlement, and this task did not log
in or call the API.

Production MVP requires Hyper Growth-or-better webhook entitlement as a hard
deployment gate. Prompt `email_sent`, bounce, account-error, and unsubscribe
evidence is required for safe `SENT` semantics and stop safety. A
`reply_received` subscription remains prohibited until SPEC-027 provides the
response-ingress capability frozen below.
A bounded polling fallback is technically possible using campaign/lead reads
and webhook-delivery records, but it is not equivalent for timely unsubscribe
or reply handling and should be later reliability work, not a silent SPEC-026
substitute. The supervisor owns any plan upgrade/purchase decision.

## Proposed package boundary

Suggested focused package:

```text
src/signals/campaigns/
  contracts.py        # plans, envelopes, mailbox/readiness, operations/events
  factory.py          # pure CampaignFactory
  envelope.py         # pure exact transport validation
  pacing.py           # pure cap/window calculations
  store.py            # campaigns, members, operation ledger, events
  service.py          # opportunity-scoped orchestration and replay
  worker.py           # claims bounded operations and reconciles
  webhooks.py         # strict transport normalization; no reply semantics
  instantly.py        # narrow HTTP V2 adapter
```

This is not a generic HTTP tool. The adapter owns the base URL, endpoint paths,
methods, payload schemas, timeouts, response bounds, and allowed fields. Hermes
can request `schedule_campaign`; it cannot supply URLs, JSON, account emails,
API keys, campaign IDs, variables, sequence prose, or retry instructions.

## CampaignPlan and deterministic micro-campaign grouping

`CampaignFactory` is pure and has no provider dependency. It consumes a
versioned, immutable `CampaignFactoryInput` and emits a versioned immutable
`CampaignPlan`. Every material input and output receives a canonical SHA-256
fingerprint; secret and raw PII fields are excluded.

### Actionable input

A genuinely new schedule attempt captures one timezone-aware Kivou clock once
and must prove, before Policy and any provider call:

- opportunity state/decision/next action are exactly `SEND`/`SEND`/
  `schedule_campaign`, with supplier and contact bindings;
- the exact workflow-causing personalization artifact is `READY` and all
  opportunity/supplier/contact/input/proposal/artifact fingerprints remain
  current;
- the exact workflow-causing compliance assessment is `RECORDED`, `ALLOWED`,
  targets that artifact/contact/supplier, has the current legal ruleset/config
  fingerprint, and has `valid_until > captured_at`;
- current supplier/contact/company-profile bindings and provider-verified
  contact remain valid;
- fresh suppression matching, across all retained key versions, is definitely
  clear; unavailable key coverage or ambiguous identity fails closed;
- mailbox catalog, provider readiness, sender profile, send window, pacing,
  control plane, budget, volume, and provider quota inputs are present and
  versioned.

Typed pre-Policy failures create no scheduling Policy evaluation, campaign,
member, operation, provider call, or workflow event.

### Grouping identity

Recommended `campaign-factory-v1` grouping dimensions are:

1. wedge identifier/version;
2. resolved compliance jurisdiction/country;
3. output language;
4. selected NeedCategory and Need Graph version;
5. personalization catalog/template/language-policy versions;
6. transport-envelope/footer version;
7. sender profile and eligible mailbox-pool version;
8. send-window/timezone policy version;
9. follow-up sequence version;
10. tracking policy version;
11. compliance ruleset generation when it changes outbound transport duties;
    and
12. batch-seal policy version/config fingerprint.

The deterministic `campaign_group_key` is a domain-separated fingerprint of
these semantic dimensions, not of a person or email. It deliberately excludes
batch position. Assignment occurs under database serialization:

```text
campaign_group_key = fingerprint(semantic grouping dimensions)
campaign_ref = fingerprint(campaign_group_key, batch_generation)
```

`batch-seal-policy-v1` fixes both capacity and assembly time:

```text
maximum_members = 10
maximum_assembly_duration = 15 minutes
membership_close_at = first_member_reserved_at + 15 minutes
membership closes at min(tenth slot reserved, membership_close_at)
```

Select the lowest-generation `BUILDING` batch whose membership is open, whose
captured Kivou time is strictly before `membership_close_at` when that deadline
exists, and which has fewer than ten reserved slots. The first slot reservation
atomically writes immutable `first_member_reserved_at` and
`membership_close_at`. Later reservations never change either timestamp. The
tenth reservation atomically sets `membership_closed_at`; a due-close worker or
the next scheduler observation sets it when captured time reaches the deadline.
The time predicate itself prevents a late reservation even if the materialized
closure timestamp has not yet been written. Capacity closure records the tenth
reservation's captured instant; deadline closure records the immutable
`membership_close_at`, not a later worker-observation time.

Assignment and closure lock the campaign row/group serialization boundary. A
scheduler racing the close receives exactly one result: its slot was committed
before closure in this generation, or it is rejected from this generation and
assigned to the next open/new generation. A unique
`(campaign_group_key, batch_generation)` constraint and locked slot reservation
prevent duplicate generations, duplicate last-slot assignment, or capacity
above ten. A reservation consumes its generation slot even if that member later
stops or fails; capacity is not silently reopened and the deadline never moves.

If no open batch exists, atomically allocate the next generation. Once
`membership_closed_at` is set, no member insertion, slot reservation, or
new `ADD_LEAD` operation may be created and the generation never reopens. Ten is
intentionally conservative relative to the frozen first ASSISTED trial cap of
five new leads/day; the provider bulk maximum does not raise it. A batch need
not be full: one or three retained members may proceed after the 15-minute
deadline once all remaining seal and activation gates pass.

The factory returns:

- Kivou `campaign_ref`, group key, country/language/wedge/need;
- exact campaign-safe provider name;
- sequence, schedule, tracking, pacing, sender/mailbox eligibility contracts;
- required variable names/types and an envelope fingerprint;
- applicable policy/compliance/artifact fingerprints;
- maximum members and all version/config fingerprints.

Do not group materially different language, need, copy/catalog, legal
transport, sender, schedule, or sequence semantics. Do not make one giant
generic campaign. A shared micro-campaign is preferred over one campaign per
prospect only after the whole-message-variable contract is proven. R1 forbids
an automatic literal/one-message-per-campaign fallback if that proof fails;
failure returns for supervisor architecture review.

Provider-safe naming recommendation:

```text
KIVOU-{campaign_ref_short}-{country}-{language}-{wedge_slug}
```

`campaign_ref_short` comes from the immutable group-plus-generation
fingerprint, and the full value remains in Kivou storage. The name contains no
contact/person name, email, public title, customer material, or other PII.

### Sealed campaign lifecycle

Kivou's deterministic lifecycle is:

```text
BUILDING -> SEALED -> ACTIVE -> PAUSED | COMPLETED
BUILDING -> FAILED
SEALED   -> FAILED (before activation only)
```

- `BUILDING`: provider campaign is DRAFT/PAUSED. While
  `membership_closed_at IS NULL` and captured time is before the immutable
  deadline, configuration and membership may be assembled under the ten-member
  cap. After membership closes, the campaign remains `BUILDING` only to finish
  or reconcile operations for already-reserved members; no new member or
  `ADD_LEAD` operation may be created.
- `SEALED`: membership is immutable; every provider lead binding is confirmed
  and every retained member is already execution-state `QUEUED`. Activation
  has not yet been attempted. A partial retained batch is valid.
- `ACTIVE`: activation has been attempted and reconciled/observed as active.
  No member or `ADD_LEAD` operation can ever be added.
- `PAUSED`, `COMPLETED`, `FAILED`: non-building states; none may reopen for
  membership. A compatible later opportunity uses a new generation.

`FAILED` may be reached from membership-closed `BUILDING` when no member is
retained, or from pre-activation `SEALED` when all members become stopped or
cannot be reconciled safely. It is never an activation/send claim.

Membership closure and lifecycle sealing are distinct. Closure prevents new
membership immediately, but `BUILDING -> SEALED` waits until every retained
member has the exact confirmed provider enrollment and queue milestone required
for activation. `STOPPED`/terminally failed members are excluded only through
the contract-proven non-sending risk-reduction path. If no retained member
remains, the campaign becomes `FAILED` and never activates. Creation of
`ADD_LEAD` is allowed only while Kivou lifecycle is `BUILDING`, membership is
open, and provider readback is DRAFT/PAUSED. As soon as activation is claimed,
the campaign must already be `SEALED`; membership and capacity reservations are
permanently closed. MVP never pauses a live campaign merely to append leads.

### Member execution state

The campaign member is the current post-queue execution truth. Its closed v1
vocabulary is:

```text
RESERVED -> ENROLLED -> QUEUED -> SENT
    |          |          \----> STOPPED --Step-1 email_sent incident--> SENT
    \----------\----------------> FAILED --Step-1 email_sent incident--> SENT
```

- `RESERVED`: one serialized batch slot and immutable member identity exist;
  provider enrollment is not yet confirmed.
- `ENROLLED`: the exact provider lead/campaign binding is confirmed while the
  campaign remains non-sending; the acquisition queue milestone is not yet
  committed.
- `QUEUED`: the provider binding is confirmed, all queue-time gates passed,
  `SEND -> QUEUED` and the campaign binding are durable, and the member is a
  candidate for the final all-member activation check.
- `STOPPED`: the member must not send under its current authorization or
  binding. It is excluded from activation and receives contract-proven provider
  pause/removal risk reduction. It cannot return to `QUEUED` in SPEC-026.
- `SENT`: authoritative deduplicated Step-1 `email_sent` evidence proves the
  initial email left the provider. This is the only ordinary transition from
  member `QUEUED` to `SENT`; Step-2 evidence is represented by sequence state.
- `FAILED`: an irrecoverable, terminal non-send enrollment/member failure. A
  retryable provider failure, temporary mailbox unavailability, rate limit, or
  `RECONCILE_REQUIRED` operation does not use this state.

Only member execution state `QUEUED` is activation/send eligible. A later hard
condition moves `QUEUED -> STOPPED` without reversing the acquisition
opportunity, which remains `QUEUED` as historical fact. If authoritative
Step-1 `email_sent` unexpectedly arrives for a `STOPPED` or window-expired
`FAILED` member, Kivou must preserve the real transport evidence, record a
bounded transport incident, advance the member and opportunity to `SENT`, and
never discard or relabel the send.

The v1 workflow/member reason catalog is bounded and non-free-form:
`CAMPAIGN_MEMBER_QUEUED` for the queue-time action clear;
`SUPPRESSION_AFTER_QUEUE`, `OBJECTION_AFTER_QUEUE`,
`COMPLIANCE_EXPIRED_AFTER_QUEUE` (before activation),
`ARTIFACT_BINDING_CHANGED_AFTER_QUEUE`, and
`CONTACT_BINDING_CHANGED_AFTER_QUEUE` for hard stops; and
`STEP1_WINDOW_EXPIRED`, `STEP2_WINDOW_EXPIRED`,
`STEP1_SENT_OUTSIDE_AUTHORIZED_WINDOW`,
`STEP2_SENT_BEFORE_AUTHORIZED_WINDOW`,
`STEP2_SENT_OUTSIDE_AUTHORIZED_WINDOW`, and
`UNEXPECTED_EMAIL_SENT_AFTER_STOP` for bounded expiry/transport incidents.
These codes explain workflow/member effects without copying PII or legal
reasoning into generic events.

### Member sequence state

Execution state preserves the truthful acquisition milestone; a separate
closed `sequence_state` represents progress through the already-authorized
two-message sequence:

```text
PENDING_STEP1 -> WAITING_STEP2 -> COMPLETED
       |              |
       +------------> STOPPED
       \------------> FAILED
```

- `PENDING_STEP1`: activation may occur, but authoritative Step-1 send evidence
  does not yet exist.
- `WAITING_STEP2`: Step 1 was authoritatively sent, exact Step-2 timing was
  materialized, and no hard stop is known.
- `COMPLETED`: authoritative Step-2 `email_sent` evidence exists, including a
  bounded incident when the real send fell outside its authorized interval.
- `STOPPED`: a hard safety signal prohibits the next unsent step. Before Step 1,
  execution state is also `STOPPED` and AcquisitionOpportunity stays `QUEUED`;
  after Step 1, execution state and AcquisitionOpportunity remain truthfully
  `SENT`.
- `FAILED`: an authorized window expired without its expected send, or timing
  materialization failed closed. It is not provider-send evidence.

At the Step-1 exclusive deadline, a member without authoritative Step-1 send
evidence becomes execution-state `FAILED`, sequence-state `FAILED`, reason
`STEP1_WINDOW_EXPIRED`; its AcquisitionOpportunity remains `QUEUED` and its
generic next action is null. Step-1 truth arriving later still advances the
execution/opportunity to `SENT`, but sequence state becomes `STOPPED` and the
out-of-window incident is retained. At the Step-2 exclusive deadline, absence
of Step-2 evidence makes sequence state `FAILED` with
`STEP2_WINDOW_EXPIRED`; the acquisition remains `SENT`.

## Final outbound envelope

The envelope is two immutable layers:

1. **Personalization core:** exact SPEC-024 subject, greeting, two body
   paragraphs, and CTA. It cannot be rewritten or reordered.
2. **Transport/compliance layer:** configured sender/display identity,
   reply-to policy, privacy/information route, source notice, opt-out route,
   footer, MIME/text mode, and approved tracking headers. It may append only
   cataloged transport text; it cannot alter the core's claims.

The deterministic v1 assembly is explicit:

```text
provider_subject = artifact.subject
personalization_core_body =
    artifact.greeting + "\n\n" + artifact.body + "\n\n" + artifact.cta
provider_body =
    personalization_core_body + "\n\n" + approved_transport_footer
```

The transport footer is one bounded FR/EN catalog entry selected by the exact
jurisdiction/language/sender configuration; it is never free-form provider
text. Until that catalog is approved, `approved_transport_footer` is unresolved
and the executable envelope cannot be constructed.

`campaign-envelope-v1` must bind:

- exact personalization artifact and proposal fingerprints;
- language and exact core strings;
- sender profile/config fingerprint, mailbox ref, reply-to class;
- jurisdiction and compliance assessment/ruleset fingerprints;
- footer/source/privacy/opt-out catalog versions and exact strings;
- tracking, List-Unsubscribe, text/HTML, sequence, and send-window settings;
- required lead variables and value fingerprints; and
- final subject/body/envelope fingerprints.

The validator independently reconstructs the expected core from the durable
READY artifact, appends only the jurisdiction-approved transport catalog,
expands every required provider variable, and proves exact equality with the
provider-bound subject/body. It rejects missing/empty variables, unknown
variables, placeholders, Liquid, spintax, URLs not present in the approved
transport catalog, variants, HTML when text-only is required, extra recipients,
CC/BCC, unapproved reply-to, duplicate/unapproved footer, or any changed core
byte. Validation occurs before each mutation and is rebuilt inside final
transactions with the same captured time.

The exact production FR/CH source/privacy/opt-out footer wording is not frozen
in current repository sources; activation remains disabled until that bounded
catalog is configured. Every entry must provide sender identity, source notice,
privacy-information route, and a visible simple opt-out. Existing contacts are
Apollo-derived, but the design does not invent or hard-code a public privacy
URL that is not authoritative repository/deployment configuration. Synthetic
fixtures may use fake URLs. An unsubscribe header is defense in depth, not a
replacement for the required visible objection route.

## Frozen tracking and provider-stop policy

`tracking-policy-v1` is frozen:

| Setting | V1 value | Consequence |
| --- | --- | --- |
| Open tracking | `false` | No tracking pixel. |
| Link tracking | `false` | No tracked link; SPEC-028 owns later conversion design. |
| Text-only | `true` | Both steps use deterministic plain text. |
| First email text-only | `true` | No HTML first-step transformation. |
| Auto variant selection | disabled | No provider copy selection. |
| AI SDR | disabled | No provider AI. |
| Spintax / Liquid | forbidden | No provider-generated or conditional prose. |
| Risky contacts | `false` | Only current verified contacts enter. |
| Bounce protection | enabled | Provider may reduce sending, never increase Kivou authority. |
| Insert unsubscribe header | desired `true`, activation-gated | Activation remains impossible until a paused staging proof establishes compatible List-Unsubscribe behavior. |
| Visible opt-out/footer | mandatory | Required independently of the header; exact catalog remains a deployment input. |

Provider stop settings are also frozen:

```text
stop_on_reply = true
stop_on_auto_reply = true
stop_for_company = false
```

Reply and auto-reply stops are conservative per-lead defenses. Provider-wide
company stopping is deliberately disabled because it could suppress unrelated
future Kivou opportunities; Kivou's company/contact pacing remains
authoritative. Disabled open/link tracking means missing events are expected
and never change opportunity truth.

## Frozen CampaignSequencePolicy v1

`campaign-sequence-policy-v1` contains exactly **two email steps**:

1. **Step 1:** the exact approved SPEC-024/SPEC-026 initial envelope.
2. **Step 2:** one follow-up, delayed **four calendar days** after Step 1 and
   then deferred to the next eligible Kivou send-window instant when necessary.
   The provider follow-up subject is the empty string, using Instantly's
   documented previous-subject reuse behavior. It reuses the exact safe
   artifact greeting and appends the exact same approved transport/footer
   catalog as Step 1.

Exact Step 2 body, after the reused greeting and before the transport footer:

```text
fr: Je me permets de revenir sur mon précédent message. Si le sujet vous intéresse, je peux vous montrer quelques exemples des signaux que Kivou repère dans les marchés publics.

en: Just following up on my previous message. If this is relevant to you, I can show you a few examples of the signals Kivou identifies in public procurement.
```

There is no Step 3. The follow-up adds no procurement fact, buyer intent, need,
urgency, fit, quantity, or sourcing claim. Its input and sequence fingerprints
bind language, greeting mode, exact body, empty-subject behavior, four-day
delay, send-window version, footer version, and the stop/tracking policies.

Provider-side `stop_on_reply=true` and `stop_on_auto_reply=true` are mandatory
defense in depth. A current Kivou suppression, unsubscribe transport event,
campaign pause, revoked/broken compliance binding, or unsafe provider/account
condition stops further execution as soon as observed. Provider stop logic
never replaces Kivou Event Store authority or SPEC-027 response handling.

### Assessment freshness and pre-activation sequence authorization

SPEC-025 `ComplianceAssessment.valid_until` is the authority for the freshness
of a **new activation decision**. It is normally the assessment time plus 24
hours, clipped earlier by the sender configuration or compliance ruleset. It
is not a post-activation timer that cancels an immutable sequence solely
because wall-clock time passes.

Immediately before `ACTIVATE_CAMPAIGN`, every retained member must still prove:

- the exact `RECORDED` assessment is `ALLOWED`;
- exact personalization, contact, and supplier bindings;
- the exact compliance ruleset version/config fingerprint;
- `assessment.valid_until > captured_at` using the activation attempt's one
  Kivou clock;
- a fresh authoritative suppression result of `CLEAR`; and
- every other SPEC-026 execution gate.

An assessment expired at this boundary moves the member to `STOPPED` and no
activation may expose it. There is no exception, no TTL extension, and no
fabricated replacement assessment.

### Frozen SequenceWindowPolicy v1

`sequence-window-policy-v1` binds two dates before activation without claiming
an exact provider execution timestamp. Each campaign has one jurisdiction IANA
timezone: `Europe/Zurich` for CH or `Europe/Paris` for FR. The CampaignPlan
selects and freezes one eligible Monday-Friday local
`step_1_execution_date` before provider configuration. Final activation is
allowed only on that same date within `[09:00,17:00)`; a missed date does not
roll forward or mutate the plan.

The date-only Step-2 computation is:

```text
raw_step_2_date = step_1_execution_date + 4 calendar days

if raw_step_2_date is Monday-Friday:
  step_2_execution_date = raw_step_2_date
else:
  step_2_execution_date = next Monday

step_1_authorization_deadline = 17:00 local on step_1_execution_date
step_2_authorization_deadline = 17:00 local on step_2_execution_date
```

Both deadlines are timezone-aware and **exclusive execution boundaries**. V1
has no holiday calendar. Before activation, the immutable
`sequence_authorization_fingerprint` binds the two execution dates, both
deadlines, timezone, campaign/send-window/sequence/tracking/stop policies,
artifact and envelope fingerprints, compliance assessment identity, ruleset
and sender-config fingerprints, and campaign/member identities. It does not
bind `step_2_due_at`, which does not yet exist.

The complete Step-1 and Step-2 copy is configured before activation. There is
no dynamic copy generation, second campaign, or Step 3. This preserves exact
sequence identity, sending-account behavior, and the empty follow-up subject/
thread contract.

Known underlying validity must cover every instant in the final authorized
window:

```text
compliance_ruleset.valid_until is None
  or compliance_ruleset.valid_until >= step_2_authorization_deadline

sender_compliance_config.valid_until is None
  or sender_compliance_config.valid_until >= step_2_authorization_deadline
```

Equality is allowed because the deadline itself is exclusive: authority is
valid throughout every permitted send instant without an artificial
microsecond gap. Failure of either check blocks activation. The aggregate
assessment `valid_until` need only remain strictly later than activation's
captured instant; it is deliberately not extended to cover Step 2.

### Provider schedule containment

The exact provider configuration uses `step_1_execution_date` as start date,
`step_2_execution_date` as end date, local `[09:00,17:00)` hours, the exact
CH/FR timezone, and a bounded active-days map containing only the weekday of
Step 1 and the weekday of Step 2. For example, Monday/Friday enables only
Monday and Friday; Tuesday followed by next Monday enables only Tuesday and
Monday. No intervening date is authorized merely because it lies between the
campaign dates.

Paused/DRAFT transport-contract proof must verify exact round-trip of start/end
dates, hours, timezone, active weekday set, campaign end-date completion,
four-calendar-day delay from the actual preceding send, empty Step-2 subject,
reply/auto-reply stops, and the per-lead pause/removal operation required for
unsent Step-1 safety. Provider pacing and capacity may choose an actual instant
inside an authorized window; neither Instantly nor Kivou promises an exact send
timestamp before transport evidence exists.

Official provider behavior describes campaign completion at the configured end
date even when leads remain, but Kivou treats that as an external contract to
prove in paused staging rather than as local authority.

If the provider can roll an unsent step beyond its authorized date, ignores
the end date, or cannot provide contract-proven per-lead risk reduction,
`transport_contract_proof` remains `UNVERIFIED` and production activation is
blocked. The design does not silently accept rollover or choose a different
follow-up architecture.

### Post-Step-1 timing realization

An authoritative deduplicated `email_sent(step=1)` event records immutable
`step_1_sent_at`. In the frozen local timezone, Kivou adds four calendar days
while preserving the local clock. If that date is inactive, the exact
`step_2_due_at` becomes 09:00 on the next eligible date; otherwise it keeps the
derived local time. The realized value must satisfy both:

```text
local_date(step_2_due_at) == step_2_execution_date
step_2_due_at < step_2_authorization_deadline
```

Failure is typed `SequenceTimingInvariantViolation`; no optimistic continuation
is allowed. The immutable `sequence_timing_fingerprint` is written once and
binds `sequence_authorization_fingerprint`, `step_1_sent_at`, `step_2_due_at`,
and `step_2_authorization_deadline`. It cannot exist before authoritative
Step-1 evidence. Duplicate delivery converges on the same materialization;
conflicting Step-1 identity/timestamp fails closed, and a crash between event
acceptance and timing persistence reconciles to the same values.

Step 2 is authorized only for:

```text
step_2_due_at <= actual_send_time < step_2_authorization_deadline
```

There is one Step-2 window. If it closes without authoritative Step-2 evidence,
sequence state becomes `FAILED` with `STEP2_WINDOW_EXPIRED`; no next day,
weekday, campaign, or Step 3 is authorized.

### Live stops and post-activation compliance

Once valid activation is accepted, later expiry of the assessment's 24-hour
freshness TTL alone does not cancel the bounded Step-2 authorization. The
member remains bound to the exact ruleset/configuration approved at activation;
publication of a new ruleset version does not silently rewrite the campaign.

Sequence authorization never overrides newly observed hard stops: Kivou
suppression, recipient unsubscribe or objection, provider unsubscribe, reply,
auto-reply, explicit campaign pause, observed kill-switch/risk-reduction
control, or a provider/account condition requiring a safety pause moves
`sequence_state` to `STOPPED` after Step 1 and prohibits Step 2. The truthful
member/opportunity `SENT` milestone is unchanged. Kivou suppression remains
authoritative, with provider reply/auto-reply stops as defense in depth.

SPEC-026 v1 performs no post-activation ComplianceService reassessment for a
`QUEUED` or `SENT` member. The exact two-window envelope was authorized before
activation, exact timing is materialized from transport truth, and live hard
stops remain enforceable. A future step-level reauthorization flow requires
separate review; it is not silently added here.

### Window expiry and unexpected provider truth

At `step_1_authorization_deadline`, each member without authoritative Step-1
evidence becomes execution-state and sequence-state `FAILED` with
`STEP1_WINDOW_EXPIRED`; opportunity state remains historical `QUEUED` and
generic next action is null. Before the next provider-active window, Kivou must
confirm contract-proven per-lead pause/removal for every such member. If any
outcome is unknown or unsafe, the entire campaign is paused and cannot resume
until those members are proven non-sendable. Failure to guarantee this keeps
production activation blocked.

Authoritative provider truth is never discarded:

- Step 1 inside its window produces execution/opportunity `SENT` and sequence
  `WAITING_STEP2`.
- Step 1 outside its window still produces real `SENT`, records
  `STEP1_SENT_OUTSIDE_AUTHORIZED_WINDOW`, and makes sequence state `STOPPED`.
- Step 2 inside its due/deadline interval makes sequence state `COMPLETED`.
- Step 2 before `step_2_due_at` still records real execution, makes sequence
  state `COMPLETED`, and records `STEP2_SENT_BEFORE_AUTHORIZED_WINDOW`.
- Step 2 at or after its deadline still records real execution, makes sequence
  state `COMPLETED`, and records `STEP2_SENT_OUTSIDE_AUTHORIZED_WINDOW`.

Occurrence never retroactively makes an unauthorized send authorized.

## Mailbox catalog and readiness

`MailboxCatalog` is Kivou-owned, versioned injected configuration rather than a
fifth `0015` table. It maps stable `mailbox_ref` to:

- provider workspace/account identifier (resolved internally);
- sender profile and display/reply-to identity;
- eligible country, language, wedge, and timezone policies;
- domain and provider tracking-domain requirement;
- Kivou daily/campaign caps;
- catalog/config version and fingerprint.

It contains no provider API key. Hermes selects neither account email nor raw
provider ID. Secrets use the deployment's secret injection and never enter
catalog fingerprints, Policy arguments, events, or artifacts.

The production default catalog contains **zero usable mailboxes**. Defining the
contract does not authorize a provider account. Provider mutation is impossible
until explicit real `mailbox_ref` entries are deployed and each is readiness-
verified; the design invents no mailbox address.

The adapter maps current provider facts into a bounded `MailboxReadiness`:

| Result | Provider evidence | Scheduling behavior |
| --- | --- | --- |
| `READY` | active status; setup not pending; accepted warmup policy; usable daily limit/gap; required tracking-domain state; exact catalog/workspace binding | May proceed subject to every Kivou cap/gate. |
| `TEMPORARILY_UNAVAILABLE` | paused, maintenance, temporary warmup pause, or capacity currently exhausted | No mutation; bounded retry/review action, never a fake send. |
| `UNHEALTHY` | connection error, soft-bounce error, sending error, banned/suspended warmup, invalid required tracking domain | No scheduling; pause/review and expose safe reason. |
| `UNKNOWN` | malformed/unknown status, missing account, ambiguous workspace, or incomplete response | Fail closed; no provider mutation. |

The exact warmup threshold is an operational product decision. A provider
`daily_limit` or availability can only reduce capacity:

```text
effective_mailbox_capacity = min(Kivou mailbox cap,
                                 provider observed remaining usable capacity)
```

Provider state can never increase an approved Kivou volume.

## Frozen send windows and pacing

`SendWindowPolicy` is versioned, Kivou-owned, DST-aware, and uses IANA zones.
Country and current compliance facts select the policy; language never does.
For current automatic jurisdictions the deterministic zones are
`Europe/Zurich` (CH) and `Europe/Paris` (FR). Ambiguous country/timezone fails
closed. Instantly's schedule must be explicitly populated and read back; its
defaults are never authoritative.

`send-window-policy-v1` is frozen for Monday through Friday, with local start
`09:00:00` **inclusive** and local cutoff `17:00:00` **exclusive**. CH uses
`Europe/Zurich`; FR uses `Europe/Paris`. The calculation uses the IANA timezone
at the candidate instant, including DST transitions, rather than a fixed UTC
offset. V1 has no holiday calendar and does not guess holidays. Outside the
window, no lead may be exposed to a sending campaign and activation cannot be
attempted; the next eligible instant is the next weekday at local 09:00.

Pacing is an ordered minimum across:

- global acquisition daily cap;
- jurisdiction/country cap;
- wedge cap;
- micro-campaign active-member/daily-new-lead cap;
- mailbox cap;
- provider-observed remaining account daily limit;
- opportunity/company contact cap;
- Policy-authorized volume; and
- currently available budget/provider quota.

`pacing-policy-v1` is frozen:

```text
AUTONOMOUS_CAPPED live outbound = 0 until separately enabled
first live trial mode = ASSISTED with existing ACTION approval
global new leads/day = 5
country new leads/day = 5
wedge new leads/day = 3
mailbox new leads/day = 3
micro-campaign members = 10 maximum
active contacts/company = 1 per rolling 30 days
```

All counters use Kivou-owned reservations and the relevant policy timezone/day
or rolling interval. Provider capacity, Policy budget/volume, or a healthier
mailbox may only lower the effective minimum; nothing raises these values
automatically. A later explicit supervisor authorization is required before
autonomous live volume exceeds zero. SPEC-029 owns adaptive allocation.

## Corrected `schedule_campaign` Policy contract

Keep `TargetScope.OPPORTUNITY`. Each contact/opportunity is independently
authorized even when Campaign Factory groups it into a shared provider
campaign. Recommended final policy:

```text
command: schedule_campaign
risk_class: COMMERCIAL_MUTATION
target_scope: OPPORTUNITY
required_evidence:
  ACQUISITION_DECISION
  PUBLIC_EVIDENCE
  VERIFIED_CONTACT
  ACQUISITION_PROSPECT_PREBUILD
  PERSONALIZATION_ARTIFACT
  COMPLIANCE_ASSESSMENT
  CAMPAIGN_PLAN
  MAILBOX_READINESS
  SEND_WINDOW
uses_budget: true
uses_volume: true
uses_provider_quota: true
uses_send_controls: true
requires_control_plane: true
requires_compliance: true
```

The exact symbols should be introduced additively using existing bounded claim
conventions. Remove `FIT_DECISION` and caller-asserted `RECENT_SIGNAL`; neither
is authoritative schedule evidence. Kivou constructs evidence from durable
decision, public context, exact artifact/compliance, plan, envelope, mailbox,
window, and pacing records. The Policy action fingerprint binds the exact
opportunity member proposal and shared campaign-plan fingerprint without
placing email/copy/PII in canonical arguments.

The compliance object passed to Policy is the exact current SPEC-025
`ALLOWED` assessment with its validity/ruleset identity. Immediately before any
provider mutation and queue commit, Kivou revalidates its expiry and suppression.
Historical exact replay reconstructs the original immutable Policy snapshot and
stored remaining budget/volume; unrelated current usage must not invalidate a
completed scheduling audit. Changed actor, scope, evidence, plan, artifact,
compliance, mailbox, or action fingerprint conflicts.

### Autonomy semantics

- **SHADOW:** build/fingerprint plan and envelope and persist only a PII-minimal
  non-executable schedule audit/member identity if justified; zero Instantly
  mutation and no `SEND -> QUEUED`.
- **ASSISTED:** planning/readiness may run, but the existing
  `COMMERCIAL_MUTATION` ACTION-approval semantics control external mutation.
  The first live outbound mode is frozen to ASSISTED.
  Approval cannot override suppression, expired pre-activation compliance,
  broken mailbox, invalid window, quota, or control-plane failure.
- **AUTONOMOUS_CAPPED:** live outbound cap is frozen at zero until a later
  explicit supervisor authorization raises it. The bounded machinery is tested
  but cannot execute live sends in v1 deployment.
- **ADAPTIVE_SCALE:** out of scope; SPEC-029 owns adaptive allocation.

## Narrow InstantlyProvider

The provider abstraction exposes only typed capabilities:

```text
list_campaigns(search, cursor)
get_campaign(provider_campaign_id)
create_campaign(CreateCampaignRequest)
configure_campaign(provider_campaign_id, ConfigureCampaignRequest)
activate_campaign(provider_campaign_id)
pause_campaign(provider_campaign_id)
get_mailbox_readiness(provider_account_identifier)
create_lead_or_batch(AddLeadRequest[])
list_leads(ReconciliationFilter)
get_lead(provider_lead_id)
pause_lead(provider_lead_id)              # risk-reduction only, if V2 patch contract is frozen
list_webhooks(...), get_webhook_events(...) # deployment/reconciliation path
```

No generic URL, method, headers, or JSON method is exposed. The adapter enforces
HTTPS, `api.instantly.ai`, `/api/v2`, response/body bounds, strict enums,
timeouts, redaction, and typed failures:

- `AUTH` for 401;
- `PERMISSION` for 403;
- `PLAN_REQUIRED` for 402 or entitlement response;
- `RATE_LIMITED` for 429;
- `TIMEOUT`, `NETWORK`, `SERVER_ERROR`;
- `CLIENT_CONTRACT_ERROR` for validated 4xx inputs;
- `MALFORMED_RESPONSE`; and
- `REMOTE_STATE_CONFLICT`.

429 honors `Retry-After` when present, otherwise a bounded Kivou backoff. GET
failures may retry within a fixed attempt/time budget. A timeout/network/5xx
after a mutation is never treated as rejection and never blindly retried; the
operation becomes `RECONCILE_REQUIRED`.

### Least-privilege keys

Core production scheduling needs exactly:

```text
campaigns:create
campaigns:read
campaigns:update
leads:create
leads:read
accounts:read
```

Add `leads:update` only if the supervisor approves the bounded risk-reduction
lead-pause/removal operation after contract testing. MVP webhook creation is
manual/deployment-time. The runtime scheduling key receives no
`webhooks:create` or `webhooks:update`; it may receive only `webhooks:read` for
narrow verification/reconciliation. A later API-managed deployment design
would require separate `webhooks:create/read/update` authority. Do not request
`all:all`.

Where Instantly permits multiple keys, separate read/reconciliation and mutation
keys so a read worker cannot create or activate campaigns and the webhook setup
path cannot schedule leads. Hermes never sees any key.

## Persistence recommendation — `0015_campaign_factory`

Recommend one linear migration:

```text
0014_compliance
  -> 0015_campaign_factory
```

It adds exactly four tables.

### 1. `acquisition_campaign`

Shared immutable Kivou micro-campaign batch and bounded provider mapping:
`campaign_ref` primary key; `campaign_group_key`; `batch_generation`; unique
group/generation; group/version/fingerprint; country/language/wedge/need;
template/envelope/sequence/tracking/window/mailbox-pool and batch-seal policy
versions/config fingerprints; provider workspace ref; deterministic provider
name; nullable unique provider campaign ID; desired/current provider
configuration fingerprints; frozen timezone, Step-1/Step-2 execution dates and
exclusive authorization deadlines shared by the batch; lifecycle constrained
to `BUILDING|SEALED|ACTIVE|PAUSED|COMPLETED|FAILED`; membership count/capacity
reservation; nullable immutable `first_member_reserved_at` and
`membership_close_at`; nullable monotonic `membership_closed_at`; timestamps.
Portable checks bind the first/deadline pair and ten-member bound. Service/store
invariants require `membership_close_at = first_member_reserved_at + 15
minutes`, prohibit clearing/changing any closure timestamp, and serialize
closure against member insertion. No member email, copy, API key, or raw
provider response.

Why separate: one campaign owns many opportunities and must be created/configured
once under concurrency.

### 2. `acquisition_campaign_member`

One exact opportunity enrollment: member ref; campaign ref; opportunity,
supplier, contact, READY artifact, RECORDED/ALLOWED compliance, and Policy
evaluation refs; exact input/plan/envelope/action fingerprints; nullable unique
provider lead ID; exact ruleset and sender-configuration fingerprints;
immutable `step_1_execution_date`, `step_1_authorization_deadline`,
`step_2_execution_date`, and `step_2_authorization_deadline`; immutable pre-
activation `sequence_authorization_fingerprint` over those bounds plus the
assessment, artifact, envelope, sequence, tracking, stop, window, campaign, and
member identities; nullable write-once `step_1_sent_at`, `step_2_due_at`, and
`sequence_timing_fingerprint`; execution state constrained to
`RESERVED|ENROLLED|QUEUED|STOPPED|SENT|FAILED`; sequence state constrained to
`PENDING_STEP1|WAITING_STEP2|COMPLETED|STOPPED|FAILED`; bounded stop/failure/
transport-incident reason; recorded queue/action-clear/SENT and provider-event
refs as applicable; timestamps. Enforce one active scheduling identity per
opportunity/artifact/compliance generation and unique provider campaign/lead
binding. Insertion is valid only against a locked, membership-open `BUILDING`
campaign below capacity and before its deadline; no member is created after
membership closure, seal, or activation claim. No rendered copy or raw email.

Why separate: membership has independent compliance/idempotency/workflow and
sequence progress while many members share one campaign. These bounded R3.2
fields separate facts known before activation from timing realized by Step-1
transport truth, without a fifth table or a duplicate ComplianceAssessment.

### 3. `acquisition_provider_operation`

Durable outbox/reconciliation ledger: operation ID; deterministic unique
operation key; kind (`CREATE_CAMPAIGN`, `CONFIGURE_CAMPAIGN`, `ADD_LEAD`,
`ACTIVATE_CAMPAIGN`, `PAUSE_CAMPAIGN`, and only approved risk-reduction lead
kinds; no MVP `CREATE_WEBHOOK` operation); campaign/member refs; desired request
fingerprint; status; attempt number; provider identity/result fingerprint;
lease/start/confirm/error/retry timestamps; bounded error code; correlation. No
arbitrary request/response JSON or secrets.

The existing ledger represents any contract-approved per-lead pause/removal;
there is no fifth table, generic arbitrary `PATCH`, or Hermes-supplied provider
JSON.

States are `PLANNED`, `IN_FLIGHT`, `CONFIRMED`, `RECONCILE_REQUIRED`,
`RETRYABLE_FAILED`, and `TERMINAL_FAILED`. `IN_FLIGHT` expiration means unknown,
not failed.

Why separate: remote mutations cannot be atomically committed with Kivou's DB;
an outbox/ledger is necessary to distinguish never-called from accepted-but-
unrecorded.

### 4. `acquisition_provider_event`

Deduplicated PII-minimized ingress: canonical event fingerprint and fingerprint
version; provider event type; workspace/campaign/lead/email-event ID when
provided; Kivou campaign/member/opportunity/contact refs; step/variant;
occurred/received time; mailbox ref; bounded transport status; resolution/
processing state; recorded acquisition event ref. No raw lead email/name/phone,
subject, body, HTML, reply content, Unibox URL, or raw payload.

Why separate: inbound at-least-once delivery has its own identity, retention,
and atomic effects and cannot safely share an outbound operation row.

When a documented webhook lacks provider lead ID, use `campaign_id` to load the
small bounded member set and compare the transient normalized `lead_email`
against current contact emails inside the transaction. Persist only the
resolved contact/member; if unresolved, retain at most a keyed, versioned
recipient-resolution fingerprint required for retry, never raw email. Ambiguous
duplicates fail closed.

Four tables are minimal because campaign/member is a one-to-many model and
outbound operations/inbound events have different idempotency and lifecycle
semantics. A provider raw-response, copy, webhook-subscription, analytics,
response-intelligence, or conversion table is explicitly rejected. The mailbox
catalog remains injected versioned configuration.

## Remote mutation saga and idempotency

Every mutation uses a domain-separated deterministic operation key over kind,
campaign/member ref, desired fingerprint, and adapter version. A unique
constraint plus row locking/leases permits one claimant. Provider duplicate
skip flags are defense in depth, not Kivou's source of truth.

### Scheduling phases

1. **Preflight/replay:** look up a completed member by Policy evaluation before
   clock/provider access. Exact historical replay returns it with zero clock,
   Policy, provider, event, or row. A Policy decision without schedule/member
   state requires a fresh attempt ID rather than reusing stale approval.
2. **Plan, authorize, assign batch:** capture one UTC instant; build exact
   current inputs, suppression, envelope, mailbox readiness, window/pacing,
   plan, and Policy request. Select and freeze the Step-1 execution date, derive
   the date-only Step-2 execution date and both exclusive deadlines, and bind
   them to the batch/member plan before provider configuration. For executable
   Policy, serialize on the semantic
   group, close any due generation, reserve the lowest membership-open
   `BUILDING` generation with capacity (or atomically create the next), and
   reserve its member. The first member writes the immutable 15-minute close
   deadline. The member reservation atomically creates its deterministic
   `PLANNED ADD_LEAD` operation identity, even if shared campaign creation must
   execute first; after membership closure no new member-specific add operation
   may be created.
3. **Build non-sending campaign:** create/configure/reconcile the provider
   campaign as DRAFT/PAUSED. Execute or reconcile only deterministic
   `ADD_LEAD` operations planned while membership was open. Confirm every exact
   provider lead binding; an ACTIVE, SEALED, PAUSED-after-activation,
   COMPLETED, FAILED, or membership-closed batch rejects new enrollment or
   operation creation.
4. **Close membership:** under the campaign/group serialization boundary,
   atomically set `membership_closed_at` on the tenth reservation or when
   captured time reaches the immutable deadline. A reservation/closure race
   commits either the slot in this generation or closure and next-generation
   assignment, never both. One- and three-member partial batches are valid.
5. **Finish the closed BUILDING set:** execute or reconcile only already-
   reserved members and operations. Closure does not force `SEALED` while a
   reserved lead outcome is unknown. Terminally ineligible members take the
   non-sending risk-reduction path; if none is retained, set campaign `FAILED`
   and never activate.
6. **Queue authorized members before activation:** for each confirmed retained
   member,
   re-read its opportunity, READY artifact, RECORDED/ALLOWED unexpired
   compliance, suppression, contact/supplier/profile, mailbox, plan, window,
   caps, and Policy execution authority. In one bounded transaction bind
   `campaign_ref`, append `STATE_TRANSITIONED(SEND -> QUEUED)`, append a
   reasoned `NEXT_ACTION_SET(null)` so `schedule_campaign` is not left as the
   generic action, set member execution state `QUEUED`, and bind the events on
   the member. The provider campaign remains non-sending. A member that fails
   this check must be removed/paused through a contract-proven safe provider
   mechanism or leave the entire batch BUILDING/non-active for review; it
   cannot be silently retained.
7. **Seal:** once membership is closed and every retained member is `QUEUED`,
   atomically move the partial-or-full batch `BUILDING -> SEALED`. No later
   member, slot reservation, or `ADD_LEAD` operation is possible.
8. **Activation revalidation:** immediately before creating/claiming
   `ACTIVATE_CAMPAIGN`, revalidate **every** queued member's opportunity,
   exact `RECORDED/ALLOWED` assessment and personalization/contact/supplier/
   ruleset bindings, `assessment.valid_until > captured_at`, fresh suppression,
   sender/mailbox, plan/member fingerprints, send-window eligibility, and
   Policy execution authority. Revalidate the already-frozen Step-1 execution
   date/window and derived Step-2 execution date/deadline, require ruleset/
   sender validity to cover that deadline, and persist the immutable
   `sequence_authorization_fingerprint` with `sequence_state=PENDING_STEP1`.
   Exact provider configuration/readback must bind the same dates, bounded
   weekdays, hours, timezone, sequence, and envelope. The campaign cannot
   activate while any retained member is not execution-state `QUEUED` or fails
   a current gate.
9. **Stop unsafe queued membership:** a hard suppression/objection, expired
   pre-activation assessment, or artifact/contact binding invalidation
   atomically moves the member to `STOPPED` and appends a bounded reasoned
   `NEXT_ACTION_SET(null)`. The acquisition opportunity remains `QUEUED`; no
   reverse transition is fabricated. Remove or pause the provider membership
   only through the narrowest V2 mechanism proven safe. If exact member
   removal/pause semantics are not contract-proven, keep the entire campaign
   non-active in review/reconciliation. Never activate optimistically and never
   fabricate a fresh ALLOWED compliance result. Rate limiting, temporary
   mailbox unavailability, and unknown activation outcome remain operation
   reconciliation states and do not mark a member `STOPPED`.
10. **Activate/reconcile:** only a fully revalidated SEALED batch with at least
   one retained `QUEUED` member and
   `transport_contract_proof=VERIFIED` may create/claim activation. A timeout or
   unknown mutation outcome becomes `RECONCILE_REQUIRED`. All retained members
   were already `QUEUED`, so an immediate `email_sent` can be safely bound even
   when the provider accepted activation before Kivou recorded confirmation.
   Acceptance/reconciliation makes each retained member's precommitted exact
   two-date/two-window sequence authorization effective; later passage beyond
   the assessment freshness TTL alone does not revoke Step 2.

There is no active-campaign enrollment path. A new suppression at any point
before lead addition prevents enrollment; after confirmed enrollment but before
queue/seal/activation it invokes the non-sending risk-reduction path. After
`QUEUED` but before activation it moves the member to `STOPPED`, prevents
activation for that member, and, when safe removal cannot be proven, prevents
activation for the entire batch. Compliance expiry follows the same hard-stop
path only while activation is still pending. After valid activation, simple
expiry of the assessment's 24-hour freshness TTL is not itself a hard stop for
the already-authorized exact Step 2. Live suppression/reply/pause/safety stops
still terminate the remaining sequence, and SPEC-026 has no silent post-queue
or post-activation compliance reauthorization flow.

Authoritative Step-1 `email_sent` materializes the exact Step-2 due instant and
timing fingerprint exactly once. At the Step-1 deadline, unsent members fail and
must be proven paused/removed before the Step-2 provider-active date; otherwise
the whole campaign remains paused. At the Step-2 deadline, a waiting sequence
without authoritative Step-2 evidence fails and gains no additional send day.

### Crash/reconciliation matrix

| Mutation | Before request | Definite provider rejection | Timeout/network/5xx after request | Provider accepted, local response lost | Confirmed response, local workflow fails |
| --- | --- | --- | --- | --- | --- |
| Create campaign | `PLANNED`; safe claim | bounded retry/terminal classification | `RECONCILE_REQUIRED`; search exact deterministic name | list/search then exact-match workspace/name/full desired config; zero matches allows controlled retry, one exact match binds ID, ambiguity is conflict | provider campaign stays bound; replay continues configure without creating another |
| Configure campaign | existing campaign + desired fingerprint | retain prior safe config; retry only typed retryable | GET and compare exact allowed config subset | matching readback confirms; divergent readback conflicts/replans | continue from confirmed config; never repeat create |
| Add lead | operation was durably planned while the locked `BUILDING` batch was membership-open and provider state is DRAFT/PAUSED; fresh gates | no queue; typed failure | list leads in exact campaign and reconcile by contact/provider/member identity | exact lead/custom-variable fingerprint confirms; absent permits controlled retry with skip flags; partial bulk result splits per-member outcomes | member remains provider-bound but not queued until its final local checks; after membership closure an existing operation may reconcile, but no new add operation or member is legal |
| Activate campaign | SEALED; every retained member already QUEUED; exact two-date/two-window authorization and provider schedule readback persisted; every member/current gate revalidated; transport proof VERIFIED | remain SEALED/non-sending | `RECONCILE_REQUIRED`; GET campaign status/config/members | active + exact config confirms; draft/paused permits controlled retry only after complete fresh all-member validation; conflicting state fails | members were already QUEUED, so local campaign-state catch-up is safe and immediate Step-1 `email_sent` can bind without reactivation |
| Pause campaign/lead | risk-reduction operation reserved | alert/retry conservatively | GET status | paused/stopped readback confirms | local status/event catch-up; risk remains conservative |

No HTTP success alone advances the acquisition state. No process restart can
skip the ledger. Concurrent different opportunities for the same semantic group
serialize into the same membership-open `BUILDING` generation until its ten
slots are reserved or its immutable 15-minute deadline is reached; only one
next generation is allocated. The close/member race yields exactly one
committed generation per member. Concurrent calls for one opportunity converge
on one member and operation chain. An uncaught unique/integrity error is not a
public semantic result.

## `campaign_ref`, QUEUED, and SENT

`campaign_ref` is the immutable Kivou shared-campaign reference, not the
Instantly campaign UUID. The provider UUID lives only on
`acquisition_campaign`.

Preferred backward-compatible event path: extend `STATE_TRANSITIONED` so a
new `SEND -> QUEUED` event may carry a non-null `campaign_ref` plus a bounded
member/provider-confirmation fingerprint. The reducer atomically sets state and
campaign ref. Historical events without those fields replay identically, and
other transitions cannot change the binding. If implementation proves this
payload extension ambiguous, stop and request approval for a dedicated
`CAMPAIGN_BOUND` event rather than direct projection mutation. The design does
not recommend a new event or state-machine version by default.

`QUEUED` requires durable proof of:

- exact member -> exact provider lead -> exact provider campaign binding;
- exact current configuration and assigned mailbox pool while the provider
  campaign remains DRAFT/PAUSED and non-sending;
- current unexpired compliance, fresh suppression, window, cap, and Policy
  execution authority for the member;
- all provider identities/operation confirmations persisted.

The queue transaction also clears the obsolete `schedule_campaign` handoff with
the existing `NEXT_ACTION_SET(null)` contract and a bounded queue reason. It
means the opportunity reached durable external-enrollment authorization. It
does not require ACTIVE provider status, and it is an irreversible historical
milestone under `acquisition-state-v1`, not a complete representation of later
transport eligibility.

After queue, current truth is `acquisition_campaign_member.execution_state`.
Only `QUEUED` members may be retained for activation. If suppression,
unsubscribe/objection, expired assessment freshness, or artifact/contact
binding drift appears before activation, the same local transaction moves the
member to
`STOPPED`, records the bounded reason, and ensures generic `next_action` is
null. Provider pause/removal risk reduction is then reconciled before any
activation. The acquisition opportunity remains `QUEUED`; SPEC-026 neither
reverses it to `SEND` nor silently obtains a fresh compliance authorization.
Temporary rate limiting, a temporarily unavailable mailbox, or an activation
operation in `RECONCILE_REQUIRED` leaves the member's legal/authorization state
unchanged and is not a `STOPPED` condition.

After valid activation, the member's exact immutable sequence authorization is
the execution authority for the two frozen steps. It initially has sequence
state `PENDING_STEP1`; exact Step-2 due timing does not exist yet. The assessment
freshness TTL expiring after activation does not alone move the member to
`STOPPED`; newly observed hard stops still do. No reverse acquisition transition
and no second ComplianceService flow is introduced.

`SENT` is never emitted by campaign create/configure/add/activate success or
campaign ACTIVE status. A deduplicated Step-1 `email_sent` event with exact
workspace, campaign, member, step, and provider email identity may use the
existing `OUTCOME_RECORDED`/transition convention to advance opportunity
`QUEUED -> SENT` atomically with member execution state `SENT`, sequence state
`WAITING_STEP2`, provider-event effect, and write-once Step-2 timing
materialization. Acquisition `SENT` means authoritative initial external
execution evidence exists. It remains valid when it arrives after Instantly
accepted activation while the local operation is still `RECONCILE_REQUIRED`,
because every retained member was durably `QUEUED` before the activation
request.

A deduplicated Step-2 `email_sent` changes sequence state to `COMPLETED`; it does
not create a second acquisition transition. If Step-1 evidence unexpectedly
targets a `STOPPED` or `FAILED` member, the provider event is still preserved,
member/opportunity move to real `SENT`, and a bounded out-of-window/after-stop
transport incident is recorded. Step-2 evidence before due or at/after deadline
is likewise preserved as real transport truth and completes sequence state with
the corresponding incident. Evidence is never discarded merely because the
provider violated Kivou authorization.

## Webhook ingress and transport boundary

Official [webhook-event guidance](https://developer.instantly.ai/guides/webhook-events)
documents base `timestamp`, `event_type`, `workspace`, `campaign_id`, and
`campaign_name`, plus optional lead email, sending account, step/variant,
email ID/subject/text/HTML, reply snippets/content, and additional lead data.
Kivou must validate but not persist the unnecessary sensitive fields.

The official guide names `link_clicked`, while the webhook resource enum uses
`email_link_clicked`. This official inconsistency must be resolved by pinning a
workspace's `GET /webhooks/event-types` response and fixtures before deployment;
unknown/changed event names are durably quarantined without effects.

### Endpoint contract

Recommend `POST /webhooks/instantly` as a provider-specific route with:

- HTTPS only at deployment; JSON `Content-Type`; a conservative 64 KiB raw-body
  limit before decoding; exact object/schema and bounded strings/counts;
- a deployment-injected high-entropy secret in a custom header supported by
  Instantly (for example `X-Kivou-Instantly-Webhook`), compared in constant
  time; no secret in URL, logs, DB, event, or response;
- exact configured workspace and known provider campaign binding;
- timezone-aware timestamp with bounded future skew and a documented retention
  horizon; old valid provider events may reconcile but never bypass current
  suppression/transition rules;
- canonical dedupe before effect; and
- fast 2xx only after the safe event projection is durably accepted. Processing
  may be asynchronous after acceptance except an unsubscribe must first establish
  the Kivou hard suppression boundary.

Instantly's documented delivery payload does not promise a stable event ID or
a reply-specific `email_id`. Use a provider event/message ID when actually
present. Otherwise derive a versioned canonical HMAC fingerprint from stable
workspace, event type, campaign, resolved member (or keyed transient recipient
identity), step/variant, provider occurrence timestamp, and a digest of the
canonical transient event-specific content needed to distinguish deliveries.
For reply-like events this content component covers the present bounded reply
subject/snippet/text/HTML fields before they are discarded. Never use
`received_at` as identity.

Persist only the final event fingerprint and fingerprint-key version, never the
reply content or its standalone digest. A keyed, domain-separated construction
reduces offline guessing risk but remains pseudonymous event metadata, so its
access/retention follows the provider-event record. Retain matching key versions
through the webhook redelivery/reconciliation horizon. Synthetic tests must
prove identical redeliveries converge while distinct reply payloads sharing
campaign/member/step/timestamp do not collapse.

### Response-ingress deployment gate

Deployment configuration has a versioned capability:

```text
response_ingress_capability = NONE | SPEC027_V1
SPEC-026 default = NONE
```

When it is `NONE`, deployment verification rejects any Instantly subscription
containing `reply_received`. SPEC-026 must not acknowledge-and-discard the only
available reply content, and official documentation does not guarantee that it
can be fetched later. `stop_on_reply=true` remains mandatory provider defense.
SPEC-027 owns the separately reviewed sensitive reply-ingress storage and is
the only component that may set `SPEC027_V1`.

If `reply_received` nevertheless arrives under `NONE`, SPEC-026 establishes
stop safety, persists only the PII-minimized transport metadata/fingerprint,
raises an operational configuration alert, and performs no semantic
classification. This exceptional handling does not make the subscription
configuration valid.

### Event handling

| Provider event | SPEC-026 action |
| --- | --- |
| `email_sent` | Resolve exact member, step, and authorized window and atomically dedupe/store the PII-minimal event. Step 1 inside its window advances opportunity/member execution `QUEUED -> SENT`, changes sequence `PENDING_STEP1 -> WAITING_STEP2`, and materializes exact Step-2 timing once. Step 2 inside its due/deadline interval changes sequence `WAITING_STEP2 -> COMPLETED`. Before-due, late, stopped, failed, or otherwise out-of-window evidence remains real transport truth and records the bounded incident instead of being discarded. |
| `email_bounced` | Persist transport fact and stop/pause that member via a bounded risk-reduction operation; no response sentiment. |
| `email_opened`, link-click event | Persist bounded transport event only if tracking is enabled/authorized; no conversion attribution. |
| `reply_received` | Normally rejected at subscription verification while capability is `NONE`. If unexpectedly received, establish stop safety, persist bounded transport identity only, raise configuration alert, and do not classify; `SPEC027_V1` later owns durable sensitive content. |
| `lead_unsubscribed` | Before 2xx/effect completion, resolve contact and append Kivou's immutable SPEC-025 suppression with `UNSUBSCRIBE`. If queued but Step 1 is unsent, atomically make execution/sequence `STOPPED`, keep opportunity `QUEUED`, clear generic action, and verify/pause provider lead. After Step 1, keep truthful opportunity/member `SENT`, make sequence `STOPPED`, and prohibit Step 2. Never wait for SPEC-027 to establish the hard block. |
| `campaign_completed` | Update bounded campaign transport status only; do not synthesize SENT for unsent members. |
| `account_error` | Mark mailbox unhealthy/unknown, prevent new schedule operations, and initiate bounded pause/reconciliation. |

No reply text/HTML/subject is stored in the generic provider event. SPEC-027
needs a separately reviewed sensitive-response ingestion contract. No click is
attributed to Kivou activation/payment/MRR in SPEC-026; SPEC-028 owns that loop.

### Frozen webhook ownership

MVP webhook creation is manual/deployment-time. An operator configures the
target, allowed event set, and custom secret header; Kivou uses only
`webhooks:read` at runtime to verify exact workspace, event set, status,
Hyper-Growth-or-better entitlement, and response-ingress capability. The
scheduling key receives no webhook create/update permission. No polling
fallback silently substitutes for absent entitlement. API-managed webhook
creation is later work requiring separate review and authority.

## Final local/remote TOCTOU rules

Remote calls cannot share a SQL transaction, so pre-activation exposure has
four layers:

1. a local transaction re-reads and locks the opportunity/member/campaign,
   exact READY artifact, exact RECORDED/ALLOWED/unexpired compliance assessment,
   supplier/contact/profile, current suppression/keyring coverage, mailbox,
   plan, window, pacing, budget/quota/control plane, then compares input/plan/
   envelope/action fingerprints and claims an operation; and
2. after the remote result/reconciliation, a final transaction repeats all
   material current checks before creating the next operation or committing
   `SEND -> QUEUED`; and
3. membership reservation and deadline/capacity closure serialize on the
   campaign/group boundary; once closed, only already-reserved operations may
   finish or reconcile and no new member/add operation can appear; and
4. after every retained member is execution-state `QUEUED` and the membership-
   closed batch is sealed, activation performs an all-member revalidation in
   the same eligible Step-1 window. No retained member may fail current artifact,
   exact `RECORDED/ALLOWED` assessment freshness, suppression, mailbox, or
   Policy gates. The activation proposal binds both execution dates, both
   exclusive deadlines, timezone, exact provider schedule, and pre-activation
   sequence-authorization fingerprint; explicit ruleset/sender validity must
   cover the Step-2 deadline.

Any material change after Policy becomes a typed `CampaignInputChanged`; no
stale queue event commits. A newly inserted suppression after Policy but before
lead add/queue/activation produces zero new exposure where avoidable and a
risk-reduction reconciliation while the provider campaign is non-sending if
lead enrollment was already accepted. Before activation, a suppression,
objection, compliance expiry, or binding invalidation after `QUEUED` atomically
makes the member `STOPPED` and clears generic next action with a bounded reason.
Absent a
contract-proven safe removal/pause, the whole batch stays non-active. A
temporary provider/mailbox condition stays in the operation/reconciliation
layer and does not create a false hard stop.
Artifact/assessment/operation/event failures roll back their local event effects
together.

After activation is accepted/reconciled, the immutable sequence-authorization
fingerprint controls only the exact two-step/date/window plan. Step-1 provider
truth atomically or reconciliation-idempotently writes the separate immutable
timing fingerprint. Assessment freshness expiry alone is no longer a TOCTOU
failure. Each live hard-stop observation still claims the bounded pause/risk-
reduction path before remaining execution; a new ruleset version alone does not
mutate the bound plan. No post-activation ComplianceService call is part of this
design.

## TDD matrix

Implementation begins with failing tests and offline fakes. Required coverage:

### Entry, plan, envelope, and Policy

- exact FR `ALLOWED` opportunity produces deterministic plan/group/name;
- non-SEND/wrong action, wrong READY artifact, wrong current compliance binding,
  expired/not-ALLOWED compliance, profile/contact/supplier drift fail before
  provider;
- suppression inserted after compliance fails before provider;
- variable missing/empty/extra, changed subject/body/core, unapproved footer,
  Liquid/spintax/AI/variant, URL/CC/BCC, or provider readback mismatch fail;
- approved transport reconstructs byte-exact subject/body;
- `transport_contract_proof=UNVERIFIED` permits draft/paused staging setup but
  no activation, while only `VERIFIED` passes the activation gate;
- sequence has exactly two steps; Step 2 delay is four calendar days followed
  by window deferral, provider subject is empty, greeting is the exact safe
  artifact greeting, FR/EN bodies match the frozen strings, and there is no
  Step 3;
- tracking/stop readback is exact: open/link false, text-only/first-text-only
  true, variants/AI/spintax/Liquid/risky contacts disabled, bounce protection
  enabled, reply/auto-reply stop true, and company stop false;
- legacy schedule evidence is removed; exact internally built claims/action
  fingerprint are required;
- budget, volume, provider quota, send window, mailbox, and control-plane caps;
- SHADOW has zero provider mutation/queue; ASSISTED requires existing ACTION
  approval; autonomous-capped rejects every out-of-bound dimension.

### Two-window sequence authorization

Pre-activation date/authority tests:

1. a Monday Step-1 date derives Friday as Step-2 date;
2. Tuesday derives next Monday;
3. Wednesday derives next Monday;
4. Thursday derives next Monday;
5. Friday derives next Tuesday;
6. a DST transition preserves the frozen IANA local dates, `[09:00,17:00)`
   hours, and exclusive deadline semantics;
7. a compliance ruleset expiring before the Step-2 deadline blocks activation;
8. a sender configuration expiring before the Step-2 deadline blocks
   activation; and
9. an assessment expired before activation makes the member `STOPPED` and
   blocks activation.

Provider-schedule containment tests:

10. the provider is active only on the Step-1 and Step-2 weekdays within the
    exact start/end date range;
11. no intervening day is an authorized provider sending day; and
12. provider campaign `end_date` equals `step_2_execution_date`.

Step-1 realization/expiry tests:

13. Step 1 sent at local 10:00 materializes exact Step-2 due time at local 10:00
    on the pre-authorized Step-2 date;
14. Step 1 sent at local 16:59 materializes a due instant inside that date's
    authorized window;
15. absent Step-1 evidence at its exclusive 17:00 deadline produces
    `STEP1_WINDOW_EXPIRED`;
16. an unsent Step-1 member cannot remain provider-sendable until the Step-2
    date;
17. failure to prove the per-lead pause/removal result keeps the whole campaign
    paused; and
18. late/out-of-window Step-1 evidence records real `SENT` plus incident and
    permits no Step-2 continuation.

Step-2 materialization/expiry tests:

19. exact `step_2_due_at` exists only after authoritative Step-1 evidence;
20. `sequence_timing_fingerprint` cannot exist before that event;
21. the realized due instant must match the authorized Step-2 date and precede
    its deadline or raise `SequenceTimingInvariantViolation`;
22. Step-2 evidence before due is preserved as real execution with an incident,
    never treated as authorized;
23. Step 2 inside `[step_2_due_at, step_2_authorization_deadline)` produces
    `COMPLETED`;
24. no Step-2 evidence by the deadline produces `STEP2_WINDOW_EXPIRED`; and
25. Step-2 evidence at/after deadline remains real execution plus a late-send
    incident.

Sequence-state and live-stop tests:

26. ordinary Step-1 `SENT` changes sequence state to `WAITING_STEP2`;
27. suppression after Step 1 changes sequence state to `STOPPED`;
28. unsubscribe after Step 1 changes sequence state to `STOPPED` and records
    durable Kivou suppression;
29. reply/auto-reply stop safety changes sequence state to `STOPPED`;
30. ordinary Step-2 evidence changes sequence state to `COMPLETED`; and
31. acquisition state remains truthful `SENT` while sequence state may be
    `WAITING_STEP2`, `STOPPED`, `FAILED`, or `COMPLETED`.

Replay/crash tests:

32. duplicate Step-1 webhook delivery does not rematerialize timing;
33. conflicting Step-1 event identity/timestamp fails closed;
34. a crash after durable Step-1 event acceptance but before timing persistence
    reconciles to the same exact due time/fingerprint;
35. restart never opens an additional execution day; and
36. concurrent/replayed handling cannot create duplicate Step-2 authorization.

Additional lifetime tests prove that a valid-at-activation assessment may pass
its normal 24-hour freshness TTL before Step 2 without canceling the immutable
bounded sequence when ruleset/sender coverage remains valid; suppression,
unsubscribe, reply, explicit pause, and kill switch still stop it. Publishing a
new ruleset version does not rewrite a still-effective bound plan. No test may
fabricate a second ComplianceAssessment, call ComplianceService for a
`QUEUED`/`SENT` member, authorize another execution date, or add Step 3.

### Mailbox, windows, and pacing

- each documented active/paused/maintenance/error/setup/warmup/tracking-domain
  state maps to READY/TEMPORARILY_UNAVAILABLE/UNHEALTHY/UNKNOWN;
- unknown/malformed/missing mailbox fails closed;
- production catalog with zero usable mailboxes creates zero provider mutation;
- provider limit only reduces Kivou cap;
- DST boundary and exact CH/FR IANA Monday–Friday `[09:00, 17:00)` windows;
  wrong/ambiguous timezone and exact 17:00 cutoff reject; no holiday guess;
- autonomous live cap is zero; ASSISTED trial enforces global/country/wedge/
  mailbox limits `5/5/3/3`, ten-member batch capacity, and one active company
  contact per rolling 30 days;
- provider capacity can lower but never raise any frozen cap.

### Remote operations, replay, crashes, and concurrency

- exact completed replay uses zero clock/Policy/provider/event/row and
  reconstructs historical Policy budget semantics;
- changed actor/scope/evidence/plan/artifact/compliance/mailbox conflicts;
- Policy exists without member/operation requires fresh evaluation;
- crash before request remains PLANNED;
- timeout after create/add/configure/activate becomes RECONCILE_REQUIRED, not
  blind retry;
- provider acceptance before local commit reconciles to the same remote ID;
- partial bulk lead result resolves every member independently;
- two schedulers for same opportunity create one member/enrollment/queue event;
- two concurrent compatible members converge on one available `BUILDING` batch
  and never allocate two generations for the same slot;
- first member reservation establishes exactly one immutable
  `first_member_reserved_at` and `membership_close_at = +15 minutes`; a second
  or later member cannot extend the deadline;
- the tenth slot closes membership in the reservation transaction before the
  deadline, while one-member and three-member partial batches close at the
  15-minute deadline;
- `membership_closed_at` prohibits every later member insertion, slot
  reservation, and new `ADD_LEAD` operation even while lifecycle remains
  `BUILDING`;
- a genuine close/reservation race gives the member exactly one deterministic
  generation: committed before closure in the old batch or rejected into the
  next open generation, never both and never an eleventh slot;
- membership-closed `BUILDING` executes/reconciles only operations planned for
  already-reserved members; it cannot reopen or accept a replacement for a
  failed/stopped reservation;
- zero retained members produces non-active `FAILED`; a partial retained batch
  can become `SEALED` and activate when every retained member is `QUEUED` and
  every final gate passes;
- `ADD_LEAD` and new member insertion are impossible on SEALED/ACTIVE or any
  non-BUILDING campaign;
- a compatible opportunity after activation receives the next batch generation;
- every member's `SEND -> QUEUED` occurs before `ACTIVATE_CAMPAIGN`; activation
  is impossible while any retained campaign member is not execution-state
  `QUEUED`; the queue commit also clears `schedule_campaign` with reasoned
  `NEXT_ACTION_SET(null)` and exact `CAMPAIGN_MEMBER_QUEUED`;
- activation revalidates every queued member and exact execution gate;
- suppression after QUEUED but before activation safely removes/pauses the
  provider membership when contract-proven, marks the member `STOPPED`, leaves
  the acquisition opportunity `QUEUED`, and otherwise leaves the whole batch
  non-active in review/reconciliation;
- unsubscribe/objection, expired assessment freshness, and artifact/contact
  binding drift after QUEUED but before activation follow the same `STOPPED`
  path; expiry never creates a fabricated fresh ALLOWED result or sends;
- temporary rate limiting, mailbox unavailability, or activation
  `RECONCILE_REQUIRED` does not mark a member `STOPPED`;
- activation timeout with already-QUEUED members reconciles safely, and an
  expected immediate provider `email_sent` targets an already-QUEUED retained
  member;
- an unexpected authoritative `email_sent` for a `STOPPED` member is deduped,
  recorded with `UNEXPECTED_EMAIL_SENT_AFTER_STOP` as a transport incident and
  real SENT evidence, and advances the member/opportunity rather than
  discarding provider truth;
- new suppression at every after-Policy/before-add/before-activate/before-queue
  seam prevents stale ALLOWED scheduling;
- 401/402/403/429/5xx/network/malformed/conflict typed behavior; bounded retry;
- restart never creates a duplicate campaign, lead enrollment, activation, or
  send.

### Webhooks and workflow

- wrong/missing secret, wrong content type, oversized body, malformed schema,
  future timestamp, wrong workspace/campaign/member, unknown event fail safely;
- duplicate event produces one row/effect;
- no documented ID uses a keyed stable canonical fingerprint with transient
  event-content digest, not receipt time; identical replies dedupe and distinct
  reply payloads sharing member/step/timestamp remain distinct;
- deployment verification rejects a `reply_received` subscription while
  `response_ingress_capability=NONE`;
- only ordinary in-window Step-1 `email_sent` advances one exact
  `QUEUED -> SENT` and materializes one timing fingerprint; Step-2 changes
  sequence state only, while stopped/failed/before-due/late evidence requires
  the bounded incident path without discarding transport truth;
- create/add/activate and ACTIVE campaign never mark SENT;
- `reply_received` stores no body and performs no semantic classification;
- `lead_unsubscribed` creates one durable suppression before safe
  acknowledgement, moves a queued/unsent member to `STOPPED`, clears generic
  next action, and prevents subsequent send operations;
- account error/bounce invokes bounded risk-reduction without response scoring;
- raw lead email/name/phone, mailbox email, subject/body/HTML/reply, API/webhook
  secrets, and raw provider JSON are absent from campaign/member/operation/event,
  acquisition event, and Policy JSON.

### Migration and architecture

- fresh DB to `0015`, `0014 -> 0015`, PostgreSQL offline SQL, schema parity,
  constraints/indexes/uniques/FKs, downgrade to `0014`, re-upgrade, one head;
- exactly four tables, no raw-response/copy/analytics/response/conversion table;
- campaign schema/store enforce immutable first-member/deadline/closure fields,
  maximum ten reservations, membership-open insertion, and serialization of
  closure against assignment plus one immutable batch timezone/date/deadline
  schedule; member schema/store enforce the closed
  `RESERVED|ENROLLED|QUEUED|STOPPED|SENT|FAILED` execution vocabulary, closed
  `PENDING_STEP1|WAITING_STEP2|COMPLETED|STOPPED|FAILED` sequence vocabulary,
  immutable pre-activation dates/deadlines/fingerprint, and nullable write-once
  Step-1/timing fields;
- campaign package has no runtime dependency on Apollo network clients, SMTP,
  LLM/OpenRouter, crawler, Stripe/billing, customer TargetICP/MatchingEngine/
  feedback, SPEC-027 response intelligence, SPEC-028 conversion, or adaptive
  SPEC-029 logic;
- all HTTP tests use strict V2 fixtures/fake server and no network.

## Offline EVAL and testing ladder

Create synthetic, non-personal fixture `tests/fixtures/campaign_factory_eval_v1.json`
covering: valid FR/CH plans; semantic group plus batch generations; concurrent
BUILDING-slot assignment; immutable first-member 15-minute close deadline;
capacity and partial-batch closure; closure/reservation races; membership-closed
BUILDING reconciliation; sealed/active enrollment rejection; exact envelope;
unverified transport proof; two-step FR/EN sequence; missing variable; expired
compliance before queue and after QUEUED/before activation; post-activation
24-hour freshness expiry with bounded Step 2 still authorized; Monday-through-
Friday date derivations and DST; ruleset/sender coverage on both sides of the
Step-2 deadline; exact provider active-day/start/end containment; post-Step-1
due-time materialization and replay; Step-1/Step-2 window expiry; unsent-Step-1
rollover prevention; suppression/unsubscribe/reply and explicit pause after
Step 1; new-ruleset publication without implicit sequence rewrite; suppression
before enrollment and after QUEUED; STOPPED versus temporary operational
reconciliation; before-due/late/unexpected send incidents;
wrong artifact;
mailbox active/paused/error/setup-pending/empty catalog; frozen cap/window edges;
shadow/assisted/zero-autonomous; create/add/activate crash positions; partial
bulk result; 429/402/401/403/5xx; duplicate and distinct-content reply event
fingerprints; forbidden reply subscription; sent/unsubscribe/bounce/account
error; and PII-adversarial payloads. Evaluate invariants and identities, not
provider prose or desired conversion rates.

Testing ladder:

1. pure CampaignFactory/envelope/window/pacing tests;
2. fake `InstantlyProvider` service/saga tests;
3. strict offline HTTP fixtures derived from official V2 docs;
4. file-backed SQL crash/concurrency/outbox/webhook tests;
5. separately authorized staging integration with a provider campaign kept
   draft/paused and no send;
6. explicitly authorized synthetic-address test send; and
7. later explicit capped outbound authorization.

Normal CI stops at step 4 and never makes a network call or sends mail. A live
send is not a prerequisite for merging implementation code.

## Later-spec boundaries

- **SPEC-027 Response Intelligence:** first owns the sensitive response-ingress
  capability that allows `reply_received` subscription, then owns reply-content
  retention, positive/negative classification, hot-lead scoring, semantic LLM
  use, response generation, and meeting qualification. SPEC-026 persists only
  bounded transport identity and ensures stop safety. Unsubscribe hard
  suppression is handled immediately because it cannot wait for semantic
  analysis.
- **SPEC-028 Conversion Tracking:** owns campaign/click -> activation/payment/
  MRR/retention/churn attribution. SPEC-026 may persist a deduplicated click
  transport event only.
- **SPEC-029 Hermes Learning Loop:** owns adaptive volume/economic/wedge/mailbox
  allocation. SPEC-026 applies fixed minima only.
- **SPEC-031 Reliability & Autonomous Operations:** owns global DLQ, full
  circuit breakers, kill-switch runbooks, and cross-system recovery. SPEC-026
  still exposes typed provider errors, durable operations, leases, bounded
  retries, pause primitives, and reconciliation-safe states.

## Recommended implementation sequence

1. Implement the R1/R2/R3.2-frozen product contracts and fail-closed deployment
   capabilities. No activation path exists until mailbox/footer/entitlement and
   the V2 whole-message transport proof are configured.
2. Add pure contracts/factory/envelope/window/pacing/batch-seal/sequence-window
   tests and implementation.
3. Add `0015_campaign_factory` and the four stores, including serialized
   membership closure, member execution/sequence states, pre-activation window
   bounds, and write-once timing materialization, with migration/parity tests.
4. Correct `schedule_campaign` Policy evidence/control-plane semantics and add
   replay/action-fingerprint tests.
5. Implement service preflight, Policy, reservation, operation ledger, and
   fake-provider saga with crash/concurrency tests.
6. Implement the narrow V2 HTTP adapter against offline official fixtures.
7. Add strict webhook ingress/event dedupe and transport-only workflow effects.
8. Run full offline regression and open a DRAFT implementation PR.
9. Only under later authorization, verify plan/key scopes/webhook/manual config
   and paused staging contract. Live send remains a separate explicit gate.

## R1/R2/R3.2-frozen product decisions and remaining deployment inputs

The supervisor has frozen the v1 product policy: `batch-seal-policy-v1` with a
ten-member maximum and immutable first-member-plus-15-minute assembly deadline;
partial batches; acquisition `QUEUED` as an irreversible enrollment milestone;
member execution state as post-queue truth; fail-closed `STOPPED` handling;
ASSISTED first live mode; autonomous live cap zero; daily caps `5/5/3/3` plus
one active contact/company/30 days; CH/FR weekday `[09:00,17:00)` windows; the
exact two-step/four-day FR/EN sequence; tracking disabled; reply and auto-reply
stop enabled; company stop disabled; and manual webhook ownership. The
SPEC-025 assessment TTL is frozen as pre-activation freshness authority, while
valid activation binds exact Step-1/Step-2 execution dates and exclusive
deadlines under `sequence-window-policy-v1`. Underlying ruleset/sender validity
must cover the Step-2 deadline. Exact `step_2_due_at` and its timing fingerprint
materialize only from authoritative Step-1 `email_sent`; live hard stops remain
authoritative without a post-activation reassessment flow. Step-1 and Step-2
window expiry never grants a later execution date, while unexpected provider
truth is preserved with a bounded incident.

R3.2 does not change the `0015_campaign_factory` recommendation or its four-table
topology. It also changes none of the external deployment gates below.

Only these genuinely external deployment inputs remain:

1. **Mailbox catalog:** real `mailbox_ref` entries, sender identities,
   eligible jurisdiction/language/wedge, warmup/readiness policy, and provider
   account bindings. Production defaults to zero usable mailboxes.
2. **Privacy/footer configuration:** exact FR/EN sender/source/privacy/visible-
   opt-out catalog and authoritative privacy URL. No executable envelope exists
   without it.
3. **Hyper Growth entitlement:** verify the production workspace has the
   required webhook plan. No polling fallback substitutes for it.
4. **Paused Instantly transport proof:** a separately authorized DRAFT/PAUSED
   staging contract test must set `transport_contract_proof=VERIFIED` and prove
   whole-message variables, List-Unsubscribe behavior, exact two-date schedule
   round-trip/end-date containment, actual-preceding-send delay, and contract-
   proven per-lead pause/removal. Failure stops for supervisor review; there is
   no literal-campaign fallback.

These inputs and this report authorize neither deployment nor provider traffic.

## Design-only closeout

- One report file is the only intended repository change.
- No `src/`, `tests/`, migration, schema, config, or ops file is changed.
- No Instantly API/workspace/account was accessed.
- No campaign or webhook was created.
- No email was sent.
- No deployment was performed.
