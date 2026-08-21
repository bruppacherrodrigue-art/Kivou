# SPEC-026 — Instantly Adapter + Campaign Factory — design

**Status:** design only; no runtime, schema, migration, provider, campaign, or
deployment change is authorized by this report.

**Audited base:** `ea4c91c061ce3260a6ccf5d0ee9ade24e5759892`

**Audited on:** 2026-08-21

**Alembic head:** `0014_compliance`

**Observed local baseline:** backend `3523 passed`, skipped `0`; frontend
`150 passed`. These are read-only baseline runs on the audited base, not
SPEC-026 implementation validation.

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

It ends at `SEND -> QUEUED` only after Kivou has durable proof that the exact
lead is enrolled in the exact configured and active Instantly campaign, all
provider identities are recorded, and a final suppression/compliance check has
passed. `QUEUED` means accepted for external execution. It does not mean sent.
Only a deduplicated authoritative `email_sent` provider event may advance
`QUEUED -> SENT`.

The minimum safe migration recommendation is `0015_campaign_factory` with four
tables: campaign, campaign member, provider operation, and provider event. Each
has a distinct normalization/idempotency purpose; none stores provider raw
responses or duplicate rendered email copy.

No autonomous live volume should be enabled merely by implementing this
design. Exact follow-up copy/cadence, sender pool, production caps, send hours,
tracking/header configuration, webhook entitlement, and first-live-send mode
remain supervisor product/deployment decisions listed at the end.

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
reconstruct the final string. Before implementation enables provider
activation, a paused/draft staging contract test must prove Instantly preserves
the entire subject/body and unsubscribe transport as expected. If that proof
fails, the safe fallback is a campaign keyed by exact envelope fingerprint with
literal subject/body; that may degenerate toward one campaign per unique
message and therefore requires explicit supervisor acceptance. It must never
silently sacrifice copy integrity to preserve grouping.

## Plan and webhook entitlement

Official Help Center material says [API V2 is available on paid Email Outreach
plans](https://help.instantly.ai/en/articles/10432807-api-v2), while the
[plan comparison](https://help.instantly.ai/en/articles/7920548-email-outreach-plans-comparison)
excludes trial use. The official [webhook guide](https://help.instantly.ai/en/articles/6261906-webhooks)
requires **Hyper Growth or above**. The repository contains no durable proof of
the active Instantly plan or workspace entitlement, and this task did not log
in or call the API.

Production MVP recommendation: treat Hyper Growth-or-better webhook entitlement
as a hard deployment gate. Prompt `email_sent`, reply, bounce, account-error,
and unsubscribe evidence is required for safe `SENT` semantics and stop safety.
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
these dimensions, not of a person or email. The factory returns:

- Kivou `campaign_ref`, group key, country/language/wedge/need;
- exact campaign-safe provider name;
- sequence, schedule, tracking, pacing, sender/mailbox eligibility contracts;
- required variable names/types and an envelope fingerprint;
- applicable policy/compliance/artifact fingerprints;
- maximum members and all version/config fingerprints.

Do not group materially different language, need, copy/catalog, legal
transport, sender, schedule, or sequence semantics. Do not make one giant
generic campaign. A shared micro-campaign is preferred over one campaign per
prospect only after the whole-message-variable contract is proven.

Provider-safe naming recommendation:

```text
KIVOU-{campaign_ref_short}-{country}-{language}-{wedge_slug}
```

`campaign_ref_short` comes from the full immutable grouping fingerprint, and
the full value remains in Kivou storage. The name contains no contact/person
name, email, public title, customer material, or other PII.

## Final outbound envelope

The envelope is two immutable layers:

1. **Personalization core:** exact SPEC-024 subject, greeting, two body
   paragraphs, and CTA. It cannot be rewritten or reordered.
2. **Transport/compliance layer:** configured sender/display identity,
   reply-to policy, privacy/information route, source notice, opt-out route,
   footer, MIME/text mode, and approved tracking headers. It may append only
   cataloged transport text; it cannot alter the core's claims.

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
catalog is supervisor/legal-approved. An unsubscribe header is defense in
depth, not a replacement for the required visible objection route.

## Tracking policy recommendation

Recommended conservative MVP candidate, pending supervisor freeze:

| Setting | Candidate | Reason |
| --- | --- | --- |
| Open tracking | `false` | Tracking pixel is unnecessary for scheduling truth and adds privacy/deliverability cost. Official deliverability guidance recommends no open tracking for simple first email. |
| Link tracking | `false` | The frozen CTA contains no link; tracking is unnecessary. SPEC-028 can later introduce reviewed conversion links. |
| First email text-only | `true` | Preserves controlled copy and reduces HTML/provider transformation. |
| All steps text-only | `true` for v1 | Simplifies exact-envelope proof. |
| List-Unsubscribe header | `true` once workspace behavior is contract-tested | Official campaign option exists and supports one-click unsubscribe; validate actual configuration and webhook behavior. |
| Visible opt-out/footer | required approved catalog | Legal/product capability must be visible and deterministic; exact wording is unresolved. |
| `stop_on_reply` | `true` | Provider-side defense in depth; Kivou remains authoritative. |
| `stop_for_company` | candidate `true` | Conservative defense against parallel contact after reply; requires supervisor acceptance because it can affect unrelated contacts at the same company. |
| `stop_on_auto_reply` | candidate `true` for MVP | Prevents unattended follow-ups during uncertain absence handling; supervisor must freeze. |
| Auto variants/AI/spintax | `false` | Kivou owns exact copy; no adaptive provider prose. |
| Risky contacts | disallowed | Only current verified contact bindings may enter. |
| Bounce protection | enabled | Provider may reduce sending; it never increases Kivou authority. |

Open/click transport events may still be normalized when delivered, but disabled
tracking means their absence is expected and must not affect opportunity truth.

## CampaignSequencePolicy and follow-ups

Introduce a versioned pure `CampaignSequencePolicy` whose ordered steps each
bind: step number; delay and `minutes|hours|days`; exact subject behavior; body
catalog/version; stop-on-reply and stop-on-auto-reply behavior; send-window
policy; core-fact/artifact binding; and sequence fingerprint. Follow-ups may
refer only to the already-approved event/inference/product claims or bounded
neutral follow-up text. They may not add new quantities, urgency, fit, purchase,
or sourcing claims.

Provider-side `stop_on_reply=true` is mandatory defense in depth. A current
Kivou suppression, reply/unsubscribe transport event, campaign pause, invalid
compliance assessment, or unhealthy mailbox stops further execution as soon as
observed. Provider stop logic never replaces Kivou Event Store authority or
SPEC-027 response handling.

The repository freezes no follow-up count, cadence, or FR/EN follow-up copy.
Therefore the implementation may model and test sequences, but production
activation must remain disabled until the supervisor approves
`campaign-sequence-policy-v1`. A safe no-invention interim is first-touch-only
in paused/staging testing; it does not claim the roadmap's follow-up objective
is complete.

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

## Send windows and pacing

`SendWindowPolicy` is versioned, Kivou-owned, DST-aware, and uses IANA zones.
Country and current compliance facts select the policy; language never does.
For current automatic jurisdictions the deterministic zones are
`Europe/Zurich` (CH) and `Europe/Paris` (FR). Ambiguous country/timezone fails
closed. Instantly's schedule must be explicitly populated and read back; its
defaults are never authoritative.

Candidate for supervisor review, not frozen: Monday–Friday 09:00–17:00 in the
recipient-country IANA zone, excluding a separately versioned holiday calendar
only after an authoritative calendar source is chosen. A simpler v1 may omit
holiday logic rather than guess it. The exact weekday/hour choice remains open.

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

No adaptive increase is allowed. SPEC-029 owns learning/allocation. A
conservative staged candidate for supervisor review is: autonomous cap **zero**
until explicitly enabled; first ASSISTED live trial global 5 new leads/day,
country 5/day, wedge 3/day, mailbox 3/day, micro-campaign 10 members, and one
active contact per company per 30 days. These are not law, benchmark-tuned
thresholds, or implementation defaults until approved.

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
  Approval cannot override suppression, expired compliance, broken mailbox,
  invalid window, quota, or control-plane failure.
- **AUTONOMOUS_CAPPED:** executable only inside exact approved
  country/language/wedge/mailbox/budget/volume/window/compliance boundaries.
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
lead-pause operation after contract testing. Recommended deployment-time webhook
management needs `webhooks:create`, `webhooks:read`, and `webhooks:update` on a
separate operational key. Manual creation plus read-only verification needs
only `webhooks:read` at runtime. Do not request `all:all`.

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

Shared immutable Kivou micro-campaign identity and bounded provider mapping:
`campaign_ref` primary key; group/version/fingerprint; country/language/wedge/
need; template/envelope/sequence/tracking/window/mailbox-pool versions;
provider workspace ref; deterministic provider name; nullable unique provider
campaign ID; desired/current provider configuration fingerprints; bounded
lifecycle status; timestamps. No member email, copy, API key, or raw provider
response.

Why separate: one campaign owns many opportunities and must be created/configured
once under concurrency.

### 2. `acquisition_campaign_member`

One exact opportunity enrollment: member ref; campaign ref; opportunity,
supplier, contact, READY artifact, RECORDED/ALLOWED compliance, and Policy
evaluation refs; exact input/plan/envelope/action fingerprints; nullable unique
provider lead ID; bounded enrollment/queue/stop state; recorded queue event ref;
timestamps. Enforce one active scheduling identity per opportunity/artifact/
compliance generation and unique provider campaign/lead binding. No rendered
copy or raw email.

Why separate: membership has independent compliance/idempotency/workflow state
while many members share one campaign.

### 3. `acquisition_provider_operation`

Durable outbox/reconciliation ledger: operation ID; deterministic unique
operation key; kind (`CREATE_CAMPAIGN`, `CONFIGURE_CAMPAIGN`, `ADD_LEAD`,
`ACTIVATE_CAMPAIGN`, `PAUSE_CAMPAIGN`, and only approved risk-reduction/webhook
kinds); campaign/member refs; desired request fingerprint; status; attempt
number; provider identity/result fingerprint; lease/start/confirm/error/retry
timestamps; bounded error code; correlation. No arbitrary request/response JSON
or secrets.

States are `PLANNED`, `IN_FLIGHT`, `CONFIRMED`, `RECONCILE_REQUIRED`,
`RETRYABLE_FAILED`, and `TERMINAL_FAILED`. `IN_FLIGHT` expiration means unknown,
not failed.

Why separate: remote mutations cannot be atomically committed with Kivou's DB;
an outbox/ledger is necessary to distinguish never-called from accepted-but-
unrecorded.

### 4. `acquisition_provider_event`

Deduplicated PII-minimized ingress: canonical event fingerprint; provider
event type; workspace/campaign/lead/email-event ID when provided; Kivou
campaign/member/opportunity/contact refs; step/variant; occurred/received time;
mailbox ref; bounded transport status; resolution/processing state; recorded
acquisition event ref. No raw lead email/name/phone, subject, body, HTML, reply
content, Unibox URL, or raw payload.

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
2. **Plan and authorize:** capture one UTC instant; build exact current inputs,
   suppression, envelope, mailbox readiness, window/pacing, plan, and Policy
   request. For executable Policy, atomically reserve the campaign/member and
   first `PLANNED` operation at the exact post-Policy stream version.
3. **Execute/reconcile:** a worker claims one operation, revalidates current
   compliance/suppression/capacity where the operation can expose the recipient,
   performs the typed call, and records confirmation or reconciliation state.
4. **Finalize:** after exact campaign config, lead enrollment, and activation
   are durably confirmed, capture/rebuild current compliance/suppression and
   provider readback in a bounded final transaction, bind `campaign_ref`, append
   `STATE_TRANSITIONED(SEND -> QUEUED)`, and store the event on the member.

For a previously active shared campaign, `ADD_LEAD` is the exposure boundary;
fresh gates run immediately before it. For a new campaign they also run before
activation. A new suppression at any point prevents later operations and queue
commit; a provider lead already added under an unknown outcome triggers a
risk-reduction reconciliation/pause path, never an optimistic queue.

### Crash/reconciliation matrix

| Mutation | Before request | Definite provider rejection | Timeout/network/5xx after request | Provider accepted, local response lost | Confirmed response, local workflow fails |
| --- | --- | --- | --- | --- | --- |
| Create campaign | `PLANNED`; safe claim | bounded retry/terminal classification | `RECONCILE_REQUIRED`; search exact deterministic name | list/search then exact-match workspace/name/full desired config; zero matches allows controlled retry, one exact match binds ID, ambiguity is conflict | provider campaign stays bound; replay continues configure without creating another |
| Configure campaign | existing campaign + desired fingerprint | retain prior safe config; retry only typed retryable | GET and compare exact allowed config subset | matching readback confirms; divergent readback conflicts/replans | continue from confirmed config; never repeat create |
| Add lead | member reserved; fresh compliance/suppression | no queue; typed failure | list leads in exact campaign and reconcile by contact/provider/member identity | exact lead/custom-variable fingerprint confirms; absent permits controlled retry with skip flags; partial bulk result splits per-member outcomes | member remains provider-bound but not queued until final gates/readback; never add blindly |
| Activate campaign | campaign configured, member enrolled, fresh gates | no queue | GET campaign status/config/member | active + exact config confirms; draft/paused permits controlled retry only after fresh gates; conflicting state fails | final local queue transaction retries without reactivation |
| Pause campaign/lead | risk-reduction operation reserved | alert/retry conservatively | GET status | paused/stopped readback confirms | local status/event catch-up; risk remains conservative |
| Create webhook (if API-managed later) | deployment op reserved | deployment gate fails | list exact target/name/event/header-key names, never secret values | unique exact subscription binds ID; ambiguity blocks | local configuration reconciliation only; scheduler remains separate |

No HTTP success alone advances the acquisition state. No process restart can
skip the ledger. Concurrent different opportunities for the same group converge
on one `acquisition_campaign`; concurrent calls for one opportunity converge on
one member and one operation chain. An uncaught unique/integrity error is not a
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
- exact current configured campaign and assigned mailbox pool;
- campaign active/scheduled as intended;
- current unexpired compliance and fresh suppression clearance; and
- all provider identities/operation confirmations persisted.

`SENT` is never emitted by campaign create/configure/add/activate success or
campaign ACTIVE status. A deduplicated `email_sent` event with exact workspace,
campaign, member, step, and provider email identity may use the existing
`OUTCOME_RECORDED`/transition convention to advance `QUEUED -> SENT` atomically
with the provider-event effect. `SENT` means authoritative external execution
evidence exists.

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

Instantly's documented delivery payload does not promise a stable event ID.
Use a provider ID when actually present; otherwise derive a versioned canonical
fingerprint from stable workspace, event type, campaign, resolved member (or
keyed transient recipient identity), provider `email_id` when present,
step/variant, and provider occurrence timestamp. Never use `received_at` as
identity. Duplicate delivery creates exactly one event and effect.

### Event handling

| Provider event | SPEC-026 action |
| --- | --- |
| `email_sent` | Resolve exact member and atomically dedupe/store the PII-minimal event and advance `QUEUED -> SENT`. |
| `email_bounced` | Persist transport fact and stop/pause that member via a bounded risk-reduction operation; no response sentiment. |
| `email_opened`, link-click event | Persist bounded transport event only if tracking is enabled/authorized; no conversion attribution. |
| `reply_received` | Persist bounded event identity/metadata, ensure provider/Kivou stop safety, and hand off to SPEC-027. Do not persist reply body here or classify it. |
| `lead_unsubscribed` | Before 2xx/effect completion, resolve contact and append Kivou's immutable SPEC-025 suppression with `UNSUBSCRIBE`; verify/pause provider lead if needed. Never wait for SPEC-027 to establish the hard block. |
| `campaign_completed` | Update bounded campaign transport status only; do not synthesize SENT for unsent members. |
| `account_error` | Mark mailbox unhealthy/unknown, prevent new schedule operations, and initiate bounded pause/reconciliation. |

No reply text/HTML/subject is stored in the generic provider event. SPEC-027
needs a separately reviewed sensitive-response ingestion contract. No click is
attributed to Kivou activation/payment/MRR in SPEC-026; SPEC-028 owns that loop.

### Webhook ownership

Two valid deployment models exist:

1. **Manual/deployment-owned (recommended MVP):** operator configures target,
   event types, and custom secret header; Kivou uses `webhooks:read` to verify
   exact workspace/event/status without receiving a mutation key in the
   scheduler.
2. **API-managed:** a separate deployment operation ledger uses
   `webhooks:create/read/update`, reconciles by exact target/name/event/campaign,
   and never exposes URL/secret selection to Hermes.

Manual ownership is safer initially because public URL, TLS, plan entitlement,
secret injection, rotation, and infrastructure deployment are operational
concerns. Do not create or test a live subscription from CI.

## Final local/remote TOCTOU rules

Remote calls cannot share a SQL transaction, so each exposure point has two
layers:

1. a local transaction re-reads and locks the opportunity/member/campaign,
   exact READY artifact, exact RECORDED/ALLOWED/unexpired compliance assessment,
   supplier/contact/profile, current suppression/keyring coverage, mailbox,
   plan, window, pacing, budget/quota/control plane, then compares input/plan/
   envelope/action fingerprints and claims an operation; and
2. after the remote result/reconciliation, a final transaction repeats all
   material current checks before creating the next operation or committing
   `SEND -> QUEUED`.

Any material change after Policy becomes a typed `CampaignInputChanged`; no
stale queue event commits. A newly inserted suppression after Policy but before
lead add/activation/queue produces zero new exposure where avoidable and a
risk-reduction reconciliation if the provider may already have accepted it.
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
- legacy schedule evidence is removed; exact internally built claims/action
  fingerprint are required;
- budget, volume, provider quota, send window, mailbox, and control-plane caps;
- SHADOW has zero provider mutation/queue; ASSISTED requires existing ACTION
  approval; autonomous-capped rejects every out-of-bound dimension.

### Mailbox, windows, and pacing

- each documented active/paused/maintenance/error/setup/warmup/tracking-domain
  state maps to READY/TEMPORARILY_UNAVAILABLE/UNHEALTHY/UNKNOWN;
- unknown/malformed/missing mailbox fails closed;
- provider limit only reduces Kivou cap;
- DST boundary and exact CH/FR IANA windows; wrong/ambiguous timezone rejects;
- global/country/wedge/campaign/mailbox/company minimum cap and concurrent slot
  reservation.

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
- different opportunities in same group create one provider campaign;
- new suppression at every after-Policy/before-add/before-activate/before-queue
  seam prevents stale ALLOWED scheduling;
- 401/402/403/429/5xx/network/malformed/conflict typed behavior; bounded retry;
- restart never creates a duplicate campaign, lead enrollment, activation, or
  send.

### Webhooks and workflow

- wrong/missing secret, wrong content type, oversized body, malformed schema,
  future timestamp, wrong workspace/campaign/member, unknown event fail safely;
- duplicate event produces one row/effect;
- no documented ID uses stable canonical fingerprint, not receipt time;
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
covering: valid FR/CH plans; different language/need/wedge group splits; same
group convergence; exact envelope; missing variable; expired compliance; fresh
suppression; wrong artifact; mailbox active/paused/error/setup-pending; cap/window
edges; shadow/assisted/capped; create/add/activate crash positions; partial bulk
result; 429/402/401/403/5xx; duplicate webhooks; sent/reply/unsubscribe/bounce/
account error; and PII-adversarial payloads. Evaluate invariants and identities,
not provider prose or desired conversion rates.

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

- **SPEC-027 Response Intelligence:** owns reply content retention, positive/
  negative classification, hot-lead scoring, semantic LLM use, response
  generation, and meeting qualification. SPEC-026 persists only bounded
  transport identity and ensures stop safety. Unsubscribe hard suppression is
  handled immediately because it cannot wait for semantic analysis.
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

1. Freeze the open product/deployment decisions and the V2 whole-message
   variable contract; no activation path exists before that freeze.
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

## Decisions requiring supervisor/business approval

These are deliberately not hidden or silently frozen:

1. **Initial daily volume:** approve exact global, country, wedge, mailbox,
   campaign, and per-company caps. Recommendation: autonomous zero until
   enabled; ASSISTED trial candidate 5 global/day, 5/country, 3/wedge,
   3/mailbox, 10 members/campaign, one contact/company/30 days.
2. **Micro-campaign size:** approve the initial maximum (candidate 10 members),
   independent of Instantly's 1,000-lead bulk maximum.
3. **Send window:** approve exact weekdays/hours and holiday handling.
   Candidate: Monday–Friday, 09:00–17:00 in Europe/Zurich or Europe/Paris,
   DST-aware, no guessed timezone.
4. **Follow-ups:** freeze count, delay/cadence, exact FR copy, exact EN copy,
   subject reuse, stop-on-auto-reply, and sequence version. No repository source
   currently authorizes any follow-up prose.
5. **Mailbox pool:** approve real `mailbox_ref` catalog, sender identities,
   eligible jurisdictions/languages/wedges, warmup policy, and Kivou caps.
6. **Tracking:** approve open=false, link=false, text-only=true,
   List-Unsubscribe=true, visible footer catalog, stop-on-reply=true,
   stop-for-company candidate, and stop-on-auto-reply candidate.
7. **Unsubscribe envelope:** approve exact FR/EN visible opt-out/source/privacy
   wording and validate provider List-Unsubscribe behavior.
8. **Plan entitlement:** verify/purchase Hyper Growth-or-better for production
   webhooks; no repository fact proves entitlement.
9. **Webhook ownership:** approve recommended manual/deployment-time creation
   plus read-only runtime verification, or authorize a separate API-managed
   operational key.
10. **First live send:** recommendation is ASSISTED with explicit existing
    ACTION approval and synthetic/staging proof before any real recipient;
    autonomous execution remains disabled.
11. **Whole-message transport:** approve micro-campaign custom-variable strategy
    only after paused staging proves exact subject/body/footer substitution; if
    it fails, decide whether exact-envelope/literal campaigns are commercially
    acceptable.

None of these decisions permits deployment or provider traffic from this
design task.

## Design-only closeout

- One report file is the only intended repository change.
- No `src/`, `tests/`, migration, schema, config, or ops file is changed.
- No Instantly API/workspace/account was accessed.
- No campaign or webhook was created.
- No email was sent.
- No deployment was performed.
