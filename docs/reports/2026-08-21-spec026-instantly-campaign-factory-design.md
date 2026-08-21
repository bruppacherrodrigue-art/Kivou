# SPEC-026 — Instantly Adapter + Campaign Factory — design

**Status:** design only; no runtime, schema, migration, provider, campaign, or
deployment change is authorized by this report.

**Audited base:** `ea4c91c061ce3260a6ccf5d0ee9ade24e5759892`

**Audited on:** 2026-08-21

**Alembic head:** `0014_compliance`

**Observed local baseline:** backend `3523 passed`, skipped `0`; frontend
`150 passed`. These are read-only baseline runs on the audited base, not
SPEC-026 implementation validation.

### Design R1 freeze

R1 removes the unsafe possibility of enrolling a lead into an active provider
campaign. Micro-campaigns are immutable batches: all members are enrolled and
become `QUEUED` while the provider campaign is non-sending, membership is
sealed, every member is revalidated, and only then may activation be attempted.
R1 also freezes initial caps/windows/follow-up/tracking/stop settings and gates
`reply_received` subscription until SPEC-027 can durably retain sensitive reply
content. The external deployment inputs that remain unresolved are the real
mailbox catalog, exact privacy/footer catalog, Hyper Growth entitlement, and a
separately authorized paused-provider transport-contract proof.

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
The batch is then sealed, every queued member is revalidated, and only then may
provider activation be attempted. `QUEUED` means authorized for subsequent
external activation; it does not require provider ACTIVE status and does not
mean sent. Only a deduplicated authoritative `email_sent` provider event may
advance `QUEUED -> SENT`.

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
| Compliance | `acquisition_compliance_assessment` stores immutable `RECORDED`/`POLICY_BLOCKED` assessments, exact personalization and ruleset bindings, state, `valid_until`, workflow event, and fingerprints. A suppression store already performs Kivou-owned versioned HMAC matching. | A scheduler must find the exact `RECORDED/ALLOWED` assessment that caused the current `schedule_campaign` handoff, require `valid_until > now`, then perform a fresh suppression lookup immediately before provider mutation and before queue commit. |
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
10. tracking policy version; and
11. compliance ruleset generation when it changes outbound transport duties.

The deterministic `campaign_group_key` is a domain-separated fingerprint of
these semantic dimensions, not of a person or email. It deliberately excludes
batch position. Assignment occurs under database serialization:

```text
campaign_group_key = fingerprint(semantic grouping dimensions)
campaign_ref = fingerprint(campaign_group_key, batch_generation)
```

Select the lowest-generation `BUILDING` batch with an unreserved slot below the
frozen maximum of **10 members**. If none exists, atomically allocate the next
generation. A unique `(campaign_group_key, batch_generation)` constraint plus a
locked capacity reservation prevents two schedulers from allocating duplicate
batches or the same last slot. Once a batch becomes `SEALED`, it never reopens;
a later compatible opportunity joins another `BUILDING` generation or creates
the next one. Ten is intentionally conservative relative to the frozen first
ASSISTED trial cap of five new leads/day; the provider bulk maximum does not
raise it.

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
     \-----------> FAILED (typed terminal/reconciliation outcome)
```

- `BUILDING`: provider campaign is DRAFT/PAUSED and configuration/membership
  may be assembled under the ten-member cap.
- `SEALED`: membership is immutable; every provider lead binding is confirmed
  and every member is already `QUEUED`. Activation has not yet been attempted.
- `ACTIVE`: activation has been attempted and reconciled/observed as active.
  No member or `ADD_LEAD` operation can ever be added.
- `PAUSED`, `COMPLETED`, `FAILED`: non-building states; none may reopen for
  membership. A compatible later opportunity uses a new generation.

Creation of `ADD_LEAD` is allowed only while both Kivou lifecycle is `BUILDING`
and provider readback is DRAFT/PAUSED. As soon as activation is claimed, the
campaign must already be `SEALED`; membership and capacity reservations are
permanently closed. MVP never pauses a live campaign merely to append leads.

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
campaign pause, invalid compliance assessment, or unhealthy mailbox stops
further execution as soon as observed. Provider stop logic never replaces
Kivou Event Store authority or SPEC-027 response handling.

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
  Approval cannot override suppression, expired compliance, broken mailbox,
  invalid window, quota, or control-plane failure.
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
template/envelope/sequence/tracking/window/mailbox-pool versions; provider
workspace ref; deterministic provider name; nullable unique provider campaign
ID; desired/current provider configuration fingerprints; lifecycle constrained
to `BUILDING|SEALED|ACTIVE|PAUSED|COMPLETED|FAILED`; membership count/capacity
reservation; timestamps. No member email, copy, API key, or raw provider
response.

Why separate: one campaign owns many opportunities and must be created/configured
once under concurrency.

### 2. `acquisition_campaign_member`

One exact opportunity enrollment: member ref; campaign ref; opportunity,
supplier, contact, READY artifact, RECORDED/ALLOWED compliance, and Policy
evaluation refs; exact input/plan/envelope/action fingerprints; nullable unique
provider lead ID; bounded enrollment/queue/stop state; recorded queue event ref;
timestamps. Enforce one active scheduling identity per opportunity/artifact/
compliance generation and unique provider campaign/lead binding. Insertion is
valid only against a locked `BUILDING` campaign below capacity; no member is
created after seal or activation claim. No rendered copy or raw email.

Why separate: membership has independent compliance/idempotency/workflow state
while many members share one campaign.

### 3. `acquisition_provider_operation`

Durable outbox/reconciliation ledger: operation ID; deterministic unique
operation key; kind (`CREATE_CAMPAIGN`, `CONFIGURE_CAMPAIGN`, `ADD_LEAD`,
`ACTIVATE_CAMPAIGN`, `PAUSE_CAMPAIGN`, and only approved risk-reduction lead
kinds; no MVP `CREATE_WEBHOOK` operation); campaign/member refs; desired request
fingerprint; status; attempt number; provider identity/result fingerprint;
lease/start/confirm/error/retry timestamps; bounded error code; correlation. No
arbitrary request/response JSON or secrets.

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
   plan, and Policy request. For executable Policy, serialize on the semantic
   group, reserve the lowest `BUILDING` generation with capacity (or atomically
   create the next), reserve its member, and create the first `PLANNED`
   operation at the exact post-Policy stream version.
3. **Build non-sending campaign:** create/configure/reconcile the provider
   campaign as DRAFT/PAUSED. `ADD_LEAD` operations exist only for this
   `BUILDING` generation. Confirm every exact provider lead binding; an ACTIVE,
   SEALED, PAUSED-after-activation, COMPLETED, or FAILED batch rejects new
   enrollment.
4. **Queue authorized members before activation:** for each confirmed member,
   re-read its opportunity, READY artifact, RECORDED/ALLOWED unexpired
   compliance, suppression, contact/supplier/profile, mailbox, plan, window,
   caps, and Policy execution authority. In one bounded transaction bind
   `campaign_ref`, append `STATE_TRANSITIONED(SEND -> QUEUED)`, and record the
   event on the member. The provider campaign remains non-sending. A member
   that fails this check must be removed/paused through a contract-proven safe
   provider mechanism or leave the entire batch BUILDING/non-active for review;
   it cannot be silently retained.
5. **Seal:** after membership selection completes, atomically move the batch
   `BUILDING -> SEALED` only when every retained member is `QUEUED`. No later
   member or `ADD_LEAD` operation is possible.
6. **Activation revalidation:** immediately before creating/claiming
   `ACTIVATE_CAMPAIGN`, revalidate **every** queued member's opportunity,
   artifact, assessment/expiry, suppression, sender/mailbox, plan/member
   fingerprints, send-window eligibility, and Policy execution authority. The
   campaign cannot activate while any retained member remains `SEND` or is
   otherwise ineligible.
7. **Resolve unsafe membership:** because the campaign is non-sending, remove
   or pause an ineligible provider membership only through the narrowest V2
   mechanism proven safe. If exact member removal/pause semantics are not
   contract-proven, keep the entire campaign non-active in review/
   reconciliation. Never activate optimistically.
8. **Activate/reconcile:** only a fully revalidated SEALED batch with
   `transport_contract_proof=VERIFIED` may create/claim activation. A timeout or
   unknown mutation outcome becomes `RECONCILE_REQUIRED`. All members are
   already `QUEUED`, so an immediate `email_sent` can be safely bound even when
   the provider accepted activation before Kivou recorded confirmation.

There is no active-campaign enrollment path. A new suppression at any point
before lead addition prevents enrollment; after confirmed enrollment but before
queue/seal/activation it invokes the non-sending risk-reduction path. After
`QUEUED` but before activation it prevents activation for that member and, when
safe removal cannot be proven, for the entire batch.

### Crash/reconciliation matrix

| Mutation | Before request | Definite provider rejection | Timeout/network/5xx after request | Provider accepted, local response lost | Confirmed response, local workflow fails |
| --- | --- | --- | --- | --- | --- |
| Create campaign | `PLANNED`; safe claim | bounded retry/terminal classification | `RECONCILE_REQUIRED`; search exact deterministic name | list/search then exact-match workspace/name/full desired config; zero matches allows controlled retry, one exact match binds ID, ambiguity is conflict | provider campaign stays bound; replay continues configure without creating another |
| Configure campaign | existing campaign + desired fingerprint | retain prior safe config; retry only typed retryable | GET and compare exact allowed config subset | matching readback confirms; divergent readback conflicts/replans | continue from confirmed config; never repeat create |
| Add lead | only a locked `BUILDING` batch whose provider state is DRAFT/PAUSED; fresh gates | no queue; typed failure | list leads in exact campaign and reconcile by contact/provider/member identity | exact lead/custom-variable fingerprint confirms; absent permits controlled retry with skip flags; partial bulk result splits per-member outcomes | member remains provider-bound but not queued until its final local checks; no add is legal after seal/activation claim |
| Activate campaign | SEALED; every retained member already QUEUED; every member and current gate revalidated; transport proof VERIFIED | remain SEALED/non-sending | `RECONCILE_REQUIRED`; GET campaign status/config/members | active + exact config confirms; draft/paused permits controlled retry only after complete fresh all-member validation; conflicting state fails | members were already QUEUED, so local campaign-state catch-up is safe and immediate `email_sent` can bind without reactivation |
| Pause campaign/lead | risk-reduction operation reserved | alert/retry conservatively | GET status | paused/stopped readback confirms | local status/event catch-up; risk remains conservative |

No HTTP success alone advances the acquisition state. No process restart can
skip the ledger. Concurrent different opportunities for the same semantic group
serialize into the same available `BUILDING` generation until its ten slots are
reserved; only one next generation is allocated. Concurrent calls for one
opportunity converge on one member and operation chain. An uncaught unique/
integrity error is not a public semantic result.

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

It means the member is authorized for subsequent provider activation. It does
not require ACTIVE provider status. Membership is then sealed and all members
are revalidated once more before activation.

`SENT` is never emitted by campaign create/configure/add/activate success or
campaign ACTIVE status. A deduplicated `email_sent` event with exact workspace,
campaign, member, step, and provider email identity may use the existing
`OUTCOME_RECORDED`/transition convention to advance `QUEUED -> SENT` atomically
with the provider-event effect. `SENT` means authoritative external execution
evidence exists. It remains valid when it arrives after Instantly accepted an
activation whose local operation is still `RECONCILE_REQUIRED`, because all
members were durably `QUEUED` before the activation request.

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
| `email_sent` | Resolve exact member and atomically dedupe/store the PII-minimal event and advance `QUEUED -> SENT`. |
| `email_bounced` | Persist transport fact and stop/pause that member via a bounded risk-reduction operation; no response sentiment. |
| `email_opened`, link-click event | Persist bounded transport event only if tracking is enabled/authorized; no conversion attribution. |
| `reply_received` | Normally rejected at subscription verification while capability is `NONE`. If unexpectedly received, establish stop safety, persist bounded transport identity only, raise configuration alert, and do not classify; `SPEC027_V1` later owns durable sensitive content. |
| `lead_unsubscribed` | Before 2xx/effect completion, resolve contact and append Kivou's immutable SPEC-025 suppression with `UNSUBSCRIBE`; verify/pause provider lead if needed. Never wait for SPEC-027 to establish the hard block. |
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

Remote calls cannot share a SQL transaction, so each exposure point has three
layers:

1. a local transaction re-reads and locks the opportunity/member/campaign,
   exact READY artifact, exact RECORDED/ALLOWED/unexpired compliance assessment,
   supplier/contact/profile, current suppression/keyring coverage, mailbox,
   plan, window, pacing, budget/quota/control plane, then compares input/plan/
   envelope/action fingerprints and claims an operation; and
2. after the remote result/reconciliation, a final transaction repeats all
   material current checks before creating the next operation or committing
   `SEND -> QUEUED`; and
3. after all members are queued and the batch is sealed, activation performs an
   all-member revalidation in the same eligible send window. No retained member
   may remain `SEND` or fail current artifact/compliance/suppression/mailbox/
   Policy gates.

Any material change after Policy becomes a typed `CampaignInputChanged`; no
stale queue event commits. A newly inserted suppression after Policy but before
lead add/queue/activation produces zero new exposure where avoidable and a
risk-reduction reconciliation while the provider campaign is non-sending if
lead enrollment was already accepted. A suppression after `QUEUED` prevents
activation for the unsafe member; absent a contract-proven safe removal/pause,
the whole batch stays non-active.
Artifact/assessment/operation/event failures roll back their local event effects
together.

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
- `ADD_LEAD` and new member insertion are impossible on SEALED/ACTIVE or any
  non-BUILDING campaign;
- a compatible opportunity after activation receives the next batch generation;
- every member's `SEND -> QUEUED` occurs before `ACTIVATE_CAMPAIGN`; activation
  is impossible while any retained campaign member remains SEND;
- activation revalidates every queued member and exact execution gate;
- suppression after QUEUED but before activation safely removes/pauses the
  provider membership when contract-proven, otherwise leaves the whole batch
  non-active in review/reconciliation;
- activation timeout with already-QUEUED members reconciles safely, and an
  immediate provider `email_sent` can target only an already-QUEUED member;
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
- `email_sent` alone advances one exact `QUEUED -> SENT`;
- create/add/activate and ACTIVE campaign never mark SENT;
- `reply_received` stores no body and performs no semantic classification;
- `lead_unsubscribed` creates one durable suppression before safe acknowledgement
  and prevents subsequent operations;
- account error/bounce invokes bounded risk-reduction without response scoring;
- raw lead email/name/phone, mailbox email, subject/body/HTML/reply, API/webhook
  secrets, and raw provider JSON are absent from campaign/member/operation/event,
  acquisition event, and Policy JSON.

### Migration and architecture

- fresh DB to `0015`, `0014 -> 0015`, PostgreSQL offline SQL, schema parity,
  constraints/indexes/uniques/FKs, downgrade to `0014`, re-upgrade, one head;
- exactly four tables, no raw-response/copy/analytics/response/conversion table;
- campaign package has no runtime dependency on Apollo network clients, SMTP,
  LLM/OpenRouter, crawler, Stripe/billing, customer TargetICP/MatchingEngine/
  feedback, SPEC-027 response intelligence, SPEC-028 conversion, or adaptive
  SPEC-029 logic;
- all HTTP tests use strict V2 fixtures/fake server and no network.

## Offline EVAL and testing ladder

Create synthetic, non-personal fixture `tests/fixtures/campaign_factory_eval_v1.json`
covering: valid FR/CH plans; semantic group plus batch generations; concurrent
BUILDING-slot assignment; sealed/active enrollment rejection; exact envelope;
unverified transport proof; two-step FR/EN sequence; missing variable; expired
compliance; suppression before enrollment and after QUEUED; wrong artifact;
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

1. Implement the R1-frozen product contracts and fail-closed deployment
   capabilities. No activation path exists until mailbox/footer/entitlement and
   the V2 whole-message transport proof are configured.
2. Add pure contracts/factory/envelope/window/pacing tests and implementation.
3. Add `0015_campaign_factory` and the four stores with migration/parity tests.
4. Correct `schedule_campaign` Policy evidence/control-plane semantics and add
   replay/action-fingerprint tests.
5. Implement service preflight, Policy, reservation, operation ledger, and
   fake-provider saga with crash/concurrency tests.
6. Implement the narrow V2 HTTP adapter against offline official fixtures.
7. Add strict webhook ingress/event dedupe and transport-only workflow effects.
8. Run full offline regression and open a DRAFT implementation PR.
9. Only under later authorization, verify plan/key scopes/webhook/manual config
   and paused staging contract. Live send remains a separate explicit gate.

## R1-frozen product decisions and remaining deployment inputs

The supervisor has frozen the v1 product policy: ten-member sealed batches;
ASSISTED first live mode; autonomous live cap zero; daily caps `5/5/3/3` plus
one active contact/company/30 days; CH/FR weekday `[09:00,17:00)` windows; the
exact two-step/four-day FR/EN sequence; tracking disabled; reply and auto-reply
stop enabled; company stop disabled; and manual webhook ownership.

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
   whole-message variables plus List-Unsubscribe behavior. Failure stops for
   supervisor review; there is no literal-campaign fallback.

These inputs and this report authorize neither deployment nor provider traffic.

## Design-only closeout

- One report file is the only intended repository change.
- No `src/`, `tests/`, migration, schema, config, or ops file is changed.
- No Instantly API/workspace/account was accessed.
- No campaign or webhook was created.
- No email was sent.
- No deployment was performed.
