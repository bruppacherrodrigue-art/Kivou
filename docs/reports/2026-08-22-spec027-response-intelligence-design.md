# SPEC-027 — Response Intelligence — design R1

**Status:** design only. This report authorizes no runtime, test, schema,
migration, provider, webhook, model, email, or deployment change.

**Audited base:** `ee44aeae91ca997277a143b013098f94f5880fab`

**Audited on:** 2026-08-22

**Current Alembic head:** `0016_campaign_factory`

**Current acquisition state machine:** `acquisition-state-v1`

**Current provider-event identity:** `provider-event-fingerprint-v2`

## Executive recommendation

SPEC-027 should add one narrow response-triage pipeline after SPEC-026's
authenticated, deduplicated transport ingress:

```text
authenticated reply transport event
        |
        +-- existing immediate sequence stop
        |
        +-- deterministic safety precedence
        |     unsubscribe / complaint / auto-reply / out-of-office
        |
        +-- exact transient content resolution when still needed
        |     typed Instantly Email V2 only; never unibox_url
        |
        +-- classify_response Policy gate
        |
        +-- strict provider-neutral structured classifier
        |
        +-- one immutable evaluation result
              +-- genuine human response -> OUTCOME_RECORDED(REPLIED)
              +-- positive -> hot_lead + request_human_review
              +-- review category -> request_human_review
              +-- negative/safe close -> next_action null
              +-- no generated or sent reply
```

The recommended data decision is **no raw response-content persistence**.
Authenticated webhook content is used transiently for immediate deterministic
safety and event identity. When semantic classification cannot safely finish
inside that bounded safety path, an asynchronous worker resolves the exact
received email through the typed Instantly Email V2 API, processes it in
memory, and persists only a keyed content fingerprint and bounded outcome
facts. This design therefore needs one new table,
`acquisition_response_evaluation`, rather than an inbox, conversation store, or
message archive.

The closed v1 taxonomy is `POSITIVE`, `NEGATIVE`, `UNSUBSCRIBE`,
`WRONG_PERSON`, `REFERRAL`, `OUT_OF_OFFICE`, `AUTO_REPLY`, `COMPLAINT`,
`SENSITIVE`, and `AMBIGUOUS`. Deterministic safety precedes semantic
classification. Only a confirmed human reply records `REPLIED`; machine
responses never do. `POSITIVE` is the only hot-lead category, always requires
human review, and never authorizes an automatic customer reply.

No new `AcquisitionState` or `EventType` is recommended. Existing
`OUTCOME_RECORDED`, `NEXT_ACTION_SET`, SPEC-025 suppression, and SPEC-026 member
stop semantics express every required business effect without changing
historical replay.

## Scope and explicit non-goals

SPEC-027 owns only:

- exact inbound-response identity and content resolution;
- deterministic unsubscribe, complaint, auto-reply, and out-of-office safety;
- bounded human-response classification;
- truthful `REPLIED` outcome recording;
- hot-lead and human-review handoff;
- safe close/no-action;
- classification audit, idempotency, and cost facts.

SPEC-027 does **not** own:

- outbound reply drafting or sending;
- a conversational or autonomous sales agent;
- arbitrary inbox browsing;
- arbitrary URL fetching;
- attachment retrieval or analysis;
- provider AI interest/custom-label authority;
- contact replacement after referral/wrong-person classification;
- CRM, meeting qualification, or sales-stage management;
- click/payment/MRR/retention/churn attribution;
- campaign allocation or adaptive volume.

No LLM is needed to implement deterministic safety. A future model-backed
classifier is an injected implementation of a closed interface, not an agent
and not a source of business authority.

## Current-main repository audit

The design below is grounded in the current merged repository rather than the
roadmap alone.

| Area | Current main contract | SPEC-027 consequence |
| --- | --- | --- |
| Acquisition state | `AcquisitionState.REPLIED` already exists. `OUTCOME_RECORDED` applies monotonic outcome rank from `SEND` through `CHURNED`; a late lower-ranked outcome is still audited without downgrading a later state. | A confirmed human reply can use `OUTCOME_RECORDED(REPLIED)`. No state-machine v2 or positive/negative state is needed. |
| Acquisition events | Nine existing event types include `OUTCOME_RECORDED`, `NEXT_ACTION_SET`, and `POLICY_EVALUATED`. Event payload validation already blocks secrets and hidden reasoning. | Record only opaque evaluation/provider evidence refs and bounded reasons. Do not put classification prose or response content in an acquisition event. |
| Next actions | `request_human_review` and `classify_response` are already in `ALLOWED_COMMANDS` and therefore `ALLOWED_NEXT_ACTIONS`. A reasoned `NEXT_ACTION_SET(null)` is supported. | Hot/review categories set `request_human_review`; safe close clears the action with a bounded reason. No new command is needed. |
| Policy | `classify_response` exists as `PREPARATORY`, `OPPORTUNITY`, required evidence `RESPONSE`. It currently has no budget, provider-quota, or control-plane flags. Policy requests and decisions already carry action fingerprints, costs, evidence refs, control revisions, and exact replay data. | Keep its class/scope/evidence name, but make the evidence exact and Kivou-built. A future implementation should enable LLM cost/quota/control-plane gates for semantic classification while keeping safety effects independent. |
| SPEC-026 webhook | `POST /webhooks/instantly` authenticates a custom secret in constant time, bounds raw bodies to 64 KiB, requires JSON, verifies workspace/campaign/member binding, and deduplicates before effects. | Do not create another webhook. SPEC-027 extends the post-authenticated handoff only after `SPEC027_V1` is enabled. |
| Webhook normalization | Current official fields, including optional reply subject/snippet/text/HTML, are bounded and transient. Unknown fields are discarded; unknown event types are quarantined. | Reuse this trust boundary. Raw provider enrichment never reaches the classifier contract or durable response rows. |
| Provider events | `acquisition_provider_event` stores a PII-minimized durable trigger with provider/campaign/member/opportunity/contact refs, event type/time, optional safe provider IDs, processing state, and final keyed fingerprint. | This existing table is the durable inbound queue identity. A second ingress/message table is unnecessary. |
| Event dedupe | `provider-event-fingerprint-v2` is a keyed HMAC. Identical reply deliveries converge; distinct documented reply content can produce distinct events without storing that content or a standalone digest. | `response_ref` derives from the durable provider-event ref. Do not redefine provider-event identity in SPEC-027. |
| Campaign/member safety | `reply_received` and `auto_reply_received` already stop remaining sequence execution. `lead_unsubscribed` writes SPEC-025 suppression. Member execution and sequence state preserve pre/post-Step-1 truth. | Classification is never allowed to resume a member. A second distinct response after STOP remains valid evidence but produces no duplicate stop authorization. |
| Suppression | SPEC-025 owns HMAC recipient identity, retained-key coverage, append-only suppressions, `UNSUBSCRIBE` and `RECIPIENT_OBJECTION` sources, and closed reason codes. | Reuse it for explicit unsubscribe and complaint. No response-local suppression table and no human override that silently re-enables acquisition. |
| Instantly adapter | Campaign/lead/account/webhook operations are narrow. There is no Email API method or `emails:read` scope. Provider I/O never starts at import/server startup. | Add only typed `list_emails`/`get_email` reads in the later implementation. Never add arbitrary request/path/URL access. |
| Persistence | The head is the linear `0016_campaign_factory`. SPEC-026 has exactly campaign, member, provider operation, and provider event tables. | Recommend linear `0017_response_intelligence` with exactly one SPEC-027 table. |

Relevant current-main code and tests inspected include acquisition contracts,
reducer/store/replay, campaign contracts/store/service/worker/webhooks, API
webhook routing/configuration, compliance suppression contracts/store, Policy
registry/evaluator/gateway/store, supervisor registry/contracts, the `0016`
migration and Core schema, plus acquisition, Policy, campaign, webhook,
suppression, PII, migration, replay, and concurrency tests.

## Official Instantly V2 response contracts

Only current official Instantly documentation was used. Documentation was read
on 2026-08-22; no Instantly API or Email API endpoint was called.

| Source | Current contract relevant to SPEC-027 | Design consequence |
| --- | --- | --- |
| [Webhook events](https://developer.instantly.ai/guides/webhook-events) | Base fields are `timestamp`, `event_type`, `workspace`, `campaign_id`, and `campaign_name`. Optional fields include `lead_email`, `email_account`, `unibox_url`, step/variant, `email_id`, sent-email content, and reply subject/snippet/text/HTML. Additional merged lead fields may appear. | Keep current authenticated normalization. Treat reply content and lead enrichment as sensitive transient input only. Never follow `unibox_url`. |
| [Webhook events](https://developer.instantly.ai/guides/webhook-events) | Official events include `reply_received`, `auto_reply_received`, `lead_unsubscribed`, and `account_error`, plus provider lead labels such as interested/not-interested/neutral and other lead statuses. | Response/auto-response events trigger safety. Instantly labels are observations only and never Kivou taxonomy truth. |
| [List email](https://developer.instantly.ai/api-reference/email/list-email) | `GET /api/v2/emails` requires `emails:read` or a broader equivalent; it is limited to 20 requests/minute. Filters include cursor/limit, `campaign_id`, lead, sending account, `email_type`, created-time bounds, thread search, ordering, and latest-in-thread. | Use a least-privilege `emails:read` capability with a Kivou limit below the provider ceiling. Query only a narrow exact candidate set and paginate within a hard bound. |
| [Get email](https://developer.instantly.ai/api-reference/email/get-email) | `GET /api/v2/emails/{id}` reads one UUID email under `emails:read`. | After list resolution yields one exact candidate, read that exact ID and revalidate every binding before exposing content to safety/classification. |
| [Email object](https://developer.instantly.ai/api-reference/email/get-email) | The response includes `id`, `timestamp_email`, `message_id`, subject, body text/HTML, campaign/list/subsequence bindings, lead/lead ID, sending account, step, `is_auto_reply`, thread ID, content preview, and provider-owned AI fields. The docs warn that `timestamp_email` may be manipulated by the sender/server. | Use provider IDs and Kivou bindings, not content similarity or provider AI. Treat `timestamp_email` as corroborating rather than sole identity authority. Ignore attachments and provider AI fields. |

The webhook guide describes `email_id` as `reply_to_uuid`, usable with the
provider reply endpoint. It does **not** establish that this value is the UUID
of the inbound reply returned by `GET /emails/{id}`. SPEC-027 must therefore
not blindly GET the webhook `email_id` as if it were the response. A future
provider contract may enable the direct path only after official documentation
proves the inbound identity and the returned record still passes all Kivou
binding checks.

The smallest required new provider scope is `emails:read`. Do not grant
`emails:update`, `emails:create`, reply/send, delete, or broad `all:*` scopes.
The response key should be separate from the campaign mutation capability where
practical. This report does not create a key or add a scope.

## Chosen ingestion architecture

### Options considered

1. **Persist raw webhook/email content.** This simplifies asynchronous
   classification but creates a sensitive message archive, retention/deletion
   duties, attachment/thread pressure, and an unnecessary breach surface.
   Rejected for v1.
2. **Call the semantic classifier inside the webhook request.** This retains no
   raw data, but couples provider acknowledgement to model latency, budget,
   outage, and malformed output. A timeout could cause provider redelivery and
   duplicate cost. Rejected.
3. **Durable trigger, immediate deterministic safety, typed asynchronous content
   resolution.** SPEC-026 durably records the provider event and stops sending;
   SPEC-027 records a bounded work identity, uses any webhook content only
   transiently for safety, and resolves exact content through typed Email V2
   reads only when semantic classification remains necessary. Recommended.

The chosen architecture is the only option that simultaneously preserves fast
durable webhook acknowledgement, no raw-content persistence, crash-safe work
identity, and exact semantic input.

### Ingress phases

1. The unchanged API boundary authenticates and bounds the raw webhook before
   semantic handling.
2. SPEC-026 normalizes, binds, fingerprints, durably deduplicates, and stops the
   member/remaining sequence for `reply_received` or `auto_reply_received`.
3. With `response_ingress_capability=SPEC027_V1`, the same database transaction
   reserves one deterministic response-evaluation identity containing only
   safe refs and versions. It does not copy reply content.
4. `response-safety-rules-v1` runs before any commercial classification. It may
   use bounded webhook reply fields transiently. A conclusive safety category
   is finalized without an LLM or Email read where the input is sufficient.
5. Otherwise, an explicitly wired worker claims the evaluation and performs
   the exact typed Email resolution below. Worker execution is not started by
   importing the package or constructing the ASGI app.
6. The worker normalizes content in memory, computes a keyed content
   fingerprint, constructs Kivou-owned Policy evidence, and evaluates the exact
   `classify_response` action.
7. Only an approved executable decision may invoke a configured semantic
   classifier. Policy/model failure becomes `AMBIGUOUS / REVIEW`, never
   `POSITIVE`.
8. One final transaction writes the immutable result and all idempotent Kivou
   effects. Raw content is discarded before returning from the worker.

Webhook acknowledgement never waits for an LLM. Email resolution/classifier
failure cannot undo the already-established sequence stop.

## Versioned contracts

A later implementation should freeze immutable contracts at least equivalent
to:

- `response-intelligence-v1` — orchestration and result contract;
- `response-taxonomy-v1` — category and derived-effect map;
- `response-safety-rules-v1` — deterministic safety precedence and curated
  supported-language phrase/rule catalog;
- `response-email-resolution-v1` — typed query, candidate, retry, and ambiguity
  bounds;
- `response-content-normalizer-v1` — bounded text extraction and canonical form;
- `response-classifier-v1` — provider-neutral structured classifier interface;
- `response-classifier-output-v1` — strict result schema;
- `response-evidence-v1` — exact Policy evidence construction;
- `response-content-fingerprint-v1` — domain-separated keyed HMAC;
- `response-evaluation-store-v1` — idempotency, claim, and write-once semantics.

Every material contract carries a deterministic canonical fingerprint. Raw
subject/body/HTML, email address, model secret, and hidden reasoning are absent
from Policy arguments, event payloads, logs, and generic persistence.

## Closed response taxonomy v1

Classification expresses operational meaning rather than general sentiment.

| Classification | Deterministic definition | Human reply | Hot | Review | Durable safety/business effect |
| --- | --- | ---: | ---: | ---: | --- |
| `POSITIVE` | Explicit commercial engagement: requests a demo/call/examples/pricing/more information, proposes a concrete next step, or unambiguously asks to continue the Kivou discussion. Mere delivery, open, click, politeness, or “thanks” is insufficient. | yes | yes | yes | `REPLIED`; sequence remains stopped; `request_human_review`. |
| `NEGATIVE` | Clear human decline or statement of no relevance without an explicit stop/unsubscribe demand or complaint. | yes | no | no | `REPLIED`; sequence remains stopped; reasoned next-action clear. |
| `UNSUBSCRIBE` | Explicit request to stop, remove, unsubscribe, not contact again, or equivalent approved phrase. | yes when attached to a confirmed human response | no | no | Ensure SPEC-025 `UNSUBSCRIBE/UNSUBSCRIBED`; `REPLIED` when human; no next action. Never automatically reversible. |
| `WRONG_PERSON` | Human states they are not the appropriate recipient and supplies no unambiguous referral. | yes | no | yes | `REPLIED`; no automatic contact replacement; `request_human_review`. |
| `REFERRAL` | Human explicitly directs Kivou to another person/team or provides a referral. | yes | no | yes | `REPLIED`; no automatic outreach/contact mutation; `request_human_review`. |
| `OUT_OF_OFFICE` | Deterministic machine/temporary-absence response, distinct from a substantive human reply. | no | no | no | Remaining sequence stopped; no acquisition outcome transition; no future send from this authorization. |
| `AUTO_REPLY` | Provider or exact Email record identifies an automated response not otherwise resolved as out of office. | no | no | no | Remaining sequence stopped; no acquisition outcome transition. |
| `COMPLAINT` | Explicit spam accusation, legal/privacy objection, abuse allegation, or complaint about being contacted. | yes when attached to a confirmed human response | no | yes | Ensure SPEC-025 `RECIPIENT_OBJECTION/RECIPIENT_OBJECTED`; `REPLIED` when human; `request_human_review`. |
| `SENSITIVE` | Response contains a legal, security, safety, health/personal-data, threat, or other context that should not be handled automatically but is not already an unsubscribe/complaint. | yes when confirmed | no | yes | `REPLIED` when human; sequence stopped; `request_human_review`. |
| `AMBIGUOUS` | Meaning, language, identity, content resolution, or classifier output is insufficient for any category above. | only if independent evidence confirms a human response | no | yes | Never hot; `request_human_review`; no automatic marketing continuation. |

Taxonomy precedence is mandatory:

```text
UNSUBSCRIBE
  > COMPLAINT
  > AUTO_REPLY / OUT_OF_OFFICE
  > human semantic category
```

If multiple categories appear, the highest safety category wins. `POSITIVE`
can never override an unsubscribe, complaint, machine response, or ambiguous
identity. Provider `lead_interested`, `lead_not_interested`, `lead_neutral`,
custom labels, AI interest scores, and opens/clicks cannot populate this
taxonomy.

### Human-response confirmation

`reply_received` is a trigger, not by itself sufficient to assert every
semantic fact. `human_response_confirmed` requires exact member/content
resolution plus evidence that the response is not automated. A typed Email
record with `is_auto_reply=0`, exact campaign/lead/sending-account binding, and
non-ambiguous candidate identity is the normal proof. A conclusive
authenticated webhook response may serve only when the later implementation
can prove the same exact identity contract without persisting raw content.

If identity/content resolution is missing or ambiguous,
`human_response_confirmed=false`, classification is `AMBIGUOUS`, review is
required, and `OUTCOME_RECORDED(REPLIED)` is not fabricated. This preserves the
separate rule that clear auto/out-of-office responses are never `REPLIED`.

## Deterministic safety layer

`response-safety-rules-v1` is pure, versioned, and runs without an LLM. It
receives only the normalized event kind, provider auto-reply flag if known,
campaign language, and bounded transient subject/current-response text. It
returns one closed safety disposition and bounded reason codes—never prose or
hidden reasoning.

For v1, supported semantic languages are the already-bound campaign languages
`fr` and `en`. A curated, reviewed exact phrase/rule catalog is required before
deployment. The rules may normalize Unicode/case/spacing but must not use
substring fragments broad enough to turn ordinary prose into suppression.
Unsupported language or uncertain phrase meaning is `AMBIGUOUS / REVIEW`, not
an inferred opt-in or positive lead.

Safety effects do not wait for `classify_response` Policy:

- explicit unsubscribe atomically appends/replays the SPEC-025 suppression and
  leaves the member sequence stopped;
- explicit complaint atomically appends/replays recipient-objection
  suppression, leaves the sequence stopped, and requests review;
- auto-reply/out-of-office leaves the sequence stopped and records no REPLIED
  outcome;
- a safety-processing exception preserves the stop and raises bounded review;
- no classifier, human, or Hermes argument can remove a suppression.

This separation preserves the existing Policy doctrine that
`classify_response` is classification-only. Suppression and provider risk
reduction are independent safety primitives; model or Policy failure never
blocks them.

## Exact Email API resolution

Typed Email V2 resolution is required only when the authenticated webhook and
deterministic safety layer cannot produce the final bounded evaluation without
durable raw content. It is never an arbitrary inbox browser.

### Candidate query

The resolver loads the provider event, campaign, member, contact, and mailbox
binding from Kivou. It transiently resolves the normalized business email and
sending account. The v1 query allowlist is:

```text
GET /api/v2/emails
  campaign_id = exact bound provider campaign ID
  lead = exact normalized member business email
  eaccount = exact bound provider sending account, when available
  email_type = received
  min_timestamp_created / max_timestamp_created = bounded event-resolution interval
  sort_order = asc
  limit <= 100
```

The implementation should freeze a conservative bounded interval and retry
policy in `response-email-resolution-v1`; the recommended MVP is five minutes
before through fifteen minutes after the provider event timestamp, at most
three resolution attempts over fifteen minutes, and at most ten Email list/get
requests per workspace per minute. The Kivou request cap deliberately stays
below the official 20/minute limit. A 429 respects provider retry guidance and
never creates an uncontrolled loop.

Each returned candidate must then satisfy all available exact checks:

- UUID-format provider Email ID;
- received-email type/lifecycle;
- exact provider campaign ID;
- exact provider lead ID when Kivou has it, otherwise exact transient normalized
  lead address;
- exact sending account/mailbox binding when available;
- created timestamp inside the bounded resolution interval;
- event kind consistent with `is_auto_reply`;
- no conflicting member, campaign, or workspace identity.

`timestamp_email` is corroborating only because the official docs state it can
be manipulated. Subject/body similarity, provider AI interest, campaign name,
and `unibox_url` are never selection criteria.

### Zero, one, or multiple candidates

- **Zero:** return a typed retryable resolution result while inside the bounded
  retry window. After exhaustion, finalize `AMBIGUOUS / REVIEW` with
  `RESPONSE_CONTENT_UNAVAILABLE`; do not call the classifier.
- **One:** `GET /api/v2/emails/{candidate.id}`, then re-run every binding check on
  the full object. Only that exact body may reach normalization/classification.
- **Multiple:** fail closed immediately as `AMBIGUOUS / REVIEW` with
  `RESPONSE_IDENTITY_AMBIGUOUS`. Do not choose the nearest timestamp or most
  favorable content.

If an official future contract provides a stable inbound Email ID directly,
the resolver may use GET first only after the value's semantics are proven and
all binding checks remain mandatory.

### Content normalization

`response-content-normalizer-v1` should:

- prefer bounded `body.text`;
- if absent, transform `body.html` to text with a non-networking allowlist
  sanitizer;
- normalize Unicode, line endings, and non-semantic whitespace;
- remove clearly delimited quoted prior-message blocks and `>`-quoted lines so
  Kivou's outbound copy cannot be mistaken for prospect intent;
- preserve the current response wording; never summarize or translate before
  safety classification;
- cap the classifier input at 16 KiB after rejecting an oversized/unresolvable
  current-response segment;
- ignore attachments and never fetch attachment URLs;
- return missing/unsafe extraction as `AMBIGUOUS / REVIEW`.

The canonical subject plus current-response text enters a domain-separated
keyed HMAC. Persist only the final `content_fingerprint`, its version, and key
version. No raw response or standalone unkeyed digest is retained. Key rotation
must match retained versions without exposing content.

## Structured classifier

The interface is provider/model-neutral:

```text
classify(ResponseClassifierInput) -> ResponseClassifierOutput
```

The input is Kivou-resolved and cannot be supplied by Hermes. It contains the
campaign language, bounded transient normalized content, taxonomy/safety
versions, and safe context refs needed to distinguish commercial intent. It
contains no arbitrary tool definitions, URLs, provider labels as truth, or
permission to send.

The strict frozen output contains at least:

```text
classification
confidence                 # finite 0..1
reason_codes               # closed, bounded vocabulary
hot_lead
review_required
classifier_version
```

It may also carry `language`, `human_response_confirmed`, and an opaque bounded
usage/cost result. It must never carry free-form rationale, chain of thought,
generated reply copy, arbitrary next action, or tool calls.

Kivou—not the model—derives and validates effects from
`response-taxonomy-v1`. In particular:

- `hot_lead=true` is valid only for `POSITIVE` with confidence at least `0.85`,
  approved positive reason codes, and confirmed human identity;
- every hot lead also has `review_required=true` and
  `next_action=request_human_review`;
- any non-positive category with `hot_lead=true`, inconsistent reason code, or
  malformed/extra field invalidates the output;
- an invalid output becomes `AMBIGUOUS / REVIEW` and never hot.

The minimum reason-code vocabulary should cover explicit interest/next-step,
decline/not-relevant, stop request, spam/privacy objection, wrong recipient,
referral, temporary absence, automated response, sensitive context,
insufficient content, unsupported language, uncertain identity, provider
resolution failure, classifier unavailable, and malformed output. It should
remain bounded rather than grow into a sentiment ontology.

No production model is selected by this design. Deployment requires an
explicit model/config version, structured-output proof, data-processing/privacy
approval, cost ceiling, timeout, and offline synthetic evaluation. A cheap
non-client-facing model is acceptable only inside those gates.

## Fail-closed classification behavior

The following never produce `POSITIVE`:

- missing/empty content;
- unsupported language;
- zero or multiple Email API candidates;
- uncertain campaign/member/contact identity;
- provider/model timeout or unavailability;
- malformed, extra-field, out-of-vocabulary, or inconsistent model output;
- content-normalization failure or truncation that removes the current reply;
- absence of effective Policy/budget/control-plane authority;
- a provider AI label without independent Kivou classification.

They finalize as `AMBIGUOUS`, `hot_lead=false`, `review_required=true`, with a
bounded reason and no automatic response. Immediate stop/suppression truth is
preserved independently.

## Idempotency, claims, crashes, and reclassification

### Stable identities

```text
response_ref = H(
  "response-ref-v1",
  provider_event_ref,
  campaign_ref,
  member_ref
)

response_evaluation_id = H(
  "response-evaluation-v1",
  response_ref,
  classifier_version
)
```

One provider event plus one classifier version therefore converges to one
evaluation identity. The unique `(provider_event_ref, classifier_version)`
constraint is the database authority; webhook and worker retries cannot create
duplicate semantic results.

### Claim and finalization

The single evaluation table may hold bounded operational claim fields
(`PLANNED`, `IN_FLIGHT`, lease/attempt/retry data), but semantic result fields
are null until one final compare-and-set transaction and become write-once.
Lease expiry means work outcome is unknown, not that a model was never called.

A crash after a model response but before commit may cause a repeated model
call because no universal model-call idempotency is assumed. It cannot produce
two business outcomes: the deterministic evaluation ID, final compare-and-set,
Policy/event idempotency keys, suppression ID, and acquisition stream lock make
the first durable finalization authoritative. A conflicting later result is
discarded from business effects and raises a bounded evaluation conflict; raw
content/output is never logged.

The final transaction locks and re-reads evaluation, provider event, member,
opportunity, and current suppression. It then, in safety order:

1. appends/replays required suppression;
2. keeps the campaign sequence stopped;
3. appends/replays `OUTCOME_RECORDED(REPLIED)` only when human response is
   confirmed;
4. appends/replays `NEXT_ACTION_SET(request_human_review|null)`;
5. finalizes the response evaluation with exact event refs.

Any transaction failure rolls back all five local effects. Retry reconstructs
the same identities.

### Reclassification

The same response and same classifier version is exact replay. Reclassification
requires an explicit new classifier version and a new append-only evaluation
row with `supersedes_response_evaluation_id` and a bounded reclassification
reason. The earlier row is never updated or deleted.

A new evaluation may add a hot/review handoff but cannot reverse suppression,
resume a stopped sequence, erase `REPLIED`, or trigger an automatic response.
No silent “latest model wins” projection is allowed.

## Acquisition state and event semantics

No new state or event type is recommended.

### Genuine human response

Use existing `OUTCOME_RECORDED`:

```json
{"outcome_state":"REPLIED"}
```

The event contains bounded reason codes and opaque evidence refs such as the
response-evaluation and provider-event refs. It contains no classification
text, raw content, email address, provider payload, or hidden reasoning.

From `SENT`, the current reducer advances to `REPLIED`. If a late response is
recorded after a higher-ranked outcome such as `ACTIVATED`, the event remains
truthful audit while the projection does not move backward. A human negative,
wrong-person, referral, complaint, unsubscribe, sensitive, or resolvably
ambiguous reply is still a response and may record `REPLIED`; the taxonomy is
not encoded as state.

### Machine response

`AUTO_REPLY` and `OUT_OF_OFFICE` do not append `OUTCOME_RECORDED(REPLIED)`.
They remain provider/response evaluation facts, and the campaign member's
sequence stays `STOPPED`.

### Next action

- `POSITIVE`, `WRONG_PERSON`, `REFERRAL`, `COMPLAINT`, `SENSITIVE`, and
  `AMBIGUOUS` set `request_human_review`;
- `NEGATIVE`, `UNSUBSCRIBE`, `AUTO_REPLY`, and `OUT_OF_OFFICE` clear the generic
  next action with an exact reason;
- no category sets a send/reply action.

## Hot-lead handoff

A v1 hot lead is a response evaluation, not a new acquisition state:

```text
classification = POSITIVE
confidence >= 0.85
human_response_confirmed = true
hot_lead = true
review_required = true
next_action = request_human_review
```

Human review receives only bounded classification/confidence/reason codes,
opportunity/member/campaign/contact/signal refs, provider response ref, and
timestamps. It receives no hidden reasoning and no raw response through generic
Hermes context. A separately authorized human UI may retrieve the source from
the provider under a later purpose-limited access design; that is not part of
this spec.

SPEC-027 never creates reply copy, invokes a send command, or lets the model
contact the prospect.

## `classify_response` Policy recommendation

Preserve:

```text
command = classify_response
risk_class = PREPARATORY
target_scope = OPPORTUNITY
required_evidence = RESPONSE
uses_volume = false
uses_send_controls = false
requires_compliance = false
```

Change in the future implementation:

```text
uses_budget = true
uses_provider_quota = true
requires_control_plane = true
```

Rationale: semantic classification may incur an external model cost and must
fail closed when its configured provider/control plane or quota is unavailable.
It remains preparatory because it creates local classification truth only; it
does not send, unsubscribe, or mutate a provider campaign. Deterministic
suppression/stop remains an independent risk-reduction path and runs before the
Policy gate.

The `RESPONSE` evidence name already matches repository conventions and should
not be replaced merely for novelty. Its v1 readiness, however, must be exact and
Kivou-built. It binds:

- `response_ref` and exact provider-event fingerprint/ref;
- workspace/campaign/member/opportunity/contact bindings;
- exact provider Email/source identity when resolved;
- keyed content fingerprint/version/key version;
- content-normalizer, taxonomy, safety, resolver, and classifier versions;
- supported language and human/auto-response evidence;
- observed/validity timestamps.

Hermes cannot provide the claim vocabulary or evidence. The Policy action
fingerprint binds `classify_response`, response ref, opportunity, source and
content fingerprints, all versions, proposed maximum model cost, and no raw
content. Proposed volume is zero. The evaluation stores estimated cost through
the existing Policy audit; the response row stores bounded actual usage/cost.

If the Policy decision is denied, expired, unavailable, or non-executable, no
model call occurs. The response becomes `AMBIGUOUS / REVIEW` with safe audit;
the pre-existing stop and any deterministic suppression remain effective.

## Hermes boundary

Hermes may invoke only the semantic intent:

```text
classify_response(response_id)
```

`response_id` is the opaque Kivou `response_ref`. Kivou resolves it to the
durable provider event and opportunity, constructs the target/action/evidence,
and selects the configured classifier. Hermes cannot supply or alter:

- raw subject/body/HTML or arbitrary text;
- provider email/thread/campaign IDs;
- classification, confidence, reason codes, or hot flag;
- safety-rule/model/prompt versions;
- provider URL, query, API key, or retry instructions;
- suppression override or marketing reactivation;
- generated customer reply or send instruction;
- an instruction to bypass review.

The supervisor sees bounded result facts after Kivou finalization. It never
receives the LLM's hidden reasoning.

Hermes Response Triage therefore gets the required outcomes through Kivou-owned
result mapping, not caller-selected flags:

| Required triage outcome | Authoritative Kivou path |
| --- | --- |
| suppression / stop | Deterministic safety runs before Policy/classification, writes SPEC-025 suppression when required, and preserves the SPEC-026 member stop. |
| hot-lead escalation | Only a validated `POSITIVE` result derives `hot_lead=true` and `request_human_review`. |
| human review | The closed taxonomy maps positive/referral/wrong-person/complaint/sensitive/ambiguous results to the existing next action. |
| safe close / no action | Negative, unsubscribe, and machine-response results use a reasoned `NEXT_ACTION_SET(null)` while preserving response/suppression truth. |

Hermes can trigger processing of the opaque response; it cannot choose which
of these outcomes occurs.

## Persistence recommendation — `0017_response_intelligence`

Recommend one linear migration:

```text
revision = 0017_response_intelligence
down_revision = 0016_campaign_factory
```

It creates exactly one table:

```text
acquisition_response_evaluation
```

### Why one table is sufficient

- `acquisition_provider_event` already provides durable ingress identity and
  dedupe;
- `acquisition_campaign_member` already provides sequence stop/current
  execution truth;
- `acquisition_contact_suppression` already provides durable legal/safety stop;
- `acquisition_event` already records `REPLIED` and next action;
- `policy_evaluation` already records classifier authorization/cost envelope;
- the new table needs only response semantic work/result audit.

A conversation, inbox, raw message, attachment, CRM, generic LLM trace, or
second operation table would duplicate authority or broaden scope.

### Minimum table shape

`acquisition_response_evaluation` should durably hold equivalents of:

- `response_evaluation_id` primary key;
- stable `response_ref`;
- `provider_event_ref` foreign key;
- campaign/member/opportunity/contact refs;
- nullable opaque provider Email ID and thread ID only if they pass a strict
  safe-identifier contract;
- input source (`WEBHOOK_V2` or `INSTANTLY_EMAIL_V2`) and source fingerprint;
- content fingerprint/version/key version, nullable only for final missing-
  content failure;
- resolver/normalizer/safety/taxonomy/classifier versions;
- nullable prompt/model version for model-backed results;
- `human_response_confirmed`;
- closed classification, confidence, reason-code tuple, hot/review flags, and
  next action;
- classifier Policy evaluation ID/action fingerprint/status where applicable;
- estimated/actual bounded cost and usage counters;
- processing state, bounded attempt/lease/retry/failure code;
- disposition, outcome event ref, next-action event ref, suppression ref;
- nullable `supersedes_response_evaluation_id` and reclassification reason;
- received/evaluated/finalized timestamps.

Provider `message_id` can embed mail-server addressing and is therefore not a
safe generic identifier. Persist it only as part of a keyed source fingerprint,
not as raw text. Raw sending account, lead email, subject, content preview,
body, HTML, attachment metadata, provider AI fields, raw model output, prompt,
or chain of thought are forbidden columns/JSON values.

### Constraints and write semantics

- unique `(provider_event_ref, classifier_version)`;
- a superseding row must reference the same `response_ref` and a different
  classifier version;
- only `POSITIVE` may be hot, and every hot result requires review and confirmed
  human response;
- `AUTO_REPLY`/`OUT_OF_OFFICE` require `human_response_confirmed=false` and no
  outcome event;
- `next_action` is null or `request_human_review` only;
- final semantic fields are write-once;
- processing transitions are monotonic and claimed with PostgreSQL-safe row
  locking/compare-and-set; SQLite tests must not conceal incompatible SQL;
- no delete/update API for finalized semantic facts;
- downgrade removes only this table and preserves all SPEC-026 data.

## PII and retention decision

Raw reply subject/body/HTML is **not required** for this design and must not be
persisted. It exists only in a bounded local variable between authenticated
normalization or typed Email GET and result finalization.

The following are transient only:

- lead/sending-account email;
- names, company, website, and phone enrichment;
- campaign name and Unibox URL;
- response subject/snippet/text/HTML/content preview;
- raw `message_id` when it may contain addressing;
- attachments and attachment URLs;
- raw provider response;
- raw prompt/model response.

They must be absent from evaluation/provider-operation/provider-event rows,
generic acquisition events, Policy canonical arguments, Hermes context, logs,
exception strings, telemetry tags, and reports. Only final keyed fingerprints,
safe opaque IDs, bounded categories/reasons/costs, and Kivou refs persist.

The later implementation needs explicit tests that seed unique synthetic
sensitive markers into every transient field and prove none survives database,
event, Policy, log, or error inspection.

## Response-ingress deployment gate

Repository default remains:

```text
response_ingress_capability = NONE
```

`SPEC027_V1` may be configured only after all of the following are true:

1. `0017_response_intelligence` is applied and one-table schema/replay checks
   pass;
2. existing authenticated webhook secret/workspace binding and required
   Instantly webhook-plan entitlement are verified;
3. the intentional production subscription vocabulary is reviewed and includes
   `reply_received` only after the response worker is operational;
4. a separate least-privilege `emails:read` capability exists without Email
   create/update/reply/delete scopes;
5. typed list/get contract fixtures and exact zero/one/multiple-candidate
   resolution are proven offline and in an explicitly authorized non-sending
   environment;
6. response content HMAC key/key-version retention is configured;
7. deterministic FR/EN safety rules are reviewed for unsubscribe/complaint and
   content normalizer bounds are frozen;
8. a classifier implementation, structured schema, prompt/model version,
   privacy/data-processing approval, timeout, cost cap, and offline evaluation
   pass exist—or all non-deterministic cases route to review without model use;
9. Policy control, budget/quota readiness, and human-review handoff are
   available;
10. PII/log/telemetry and no-reply-send architecture tests pass;
11. worker startup is explicit deployment wiring, never an import/ASGI side
   effect;
12. rollback to `NONE` and removal of intentional reply subscription are tested
   while SPEC-026 immediate safety remains effective.

Capability `SPEC027_V1` means Kivou can durably turn a response trigger into a
safe final evaluation or bounded review. It does not mean Kivou stores a mailbox
or may answer the prospect.

## TDD and offline evaluation matrix

The later implementation must write failing focused tests before each behavior.
Normal CI remains fully offline with a fake classifier, fake Email reader, and
official-contract fixtures.

### Taxonomy and safety

1. Clear FR and EN commercial interest -> `POSITIVE`, confirmed human, hot,
   `REPLIED`, human review.
2. Polite thanks/open/click/provider interested label without explicit intent ->
   not positive.
3. Clear decline -> `NEGATIVE`, `REPLIED`, no hot, next action null.
4. Explicit unsubscribe -> suppression first, sequence stopped, human
   `REPLIED`, no hot, no reactivation.
5. Explicit complaint/spam/privacy objection -> recipient-objection suppression,
   `REPLIED`, review, never hot.
6. Wrong person -> `REPLIED`, review, no automatic contact replacement.
7. Referral -> `REPLIED`, review, no automatic outreach.
8. Provider auto reply -> `AUTO_REPLY`, sequence stopped, not `REPLIED`, no
   classifier call.
9. Clear out-of-office -> `OUT_OF_OFFICE`, sequence stopped, not `REPLIED`.
10. Sensitive context -> `SENSITIVE`, `REPLIED` when human, review, no hot.
11. Ambiguous response -> `AMBIGUOUS`, review, no hot.
12. Safety precedence beats simultaneous positive language.
13. Unsupported language/missing content -> `AMBIGUOUS / REVIEW`.
14. Provider AI label disagreeing with Kivou -> Kivou result wins.

### Email V2 resolution

15. Official list/get fixtures validate exact bounded response schemas and
    `emails:read`-only interface.
16. Zero candidate retries within bound, then review.
17. One exact candidate GET/readback succeeds.
18. Multiple plausible candidates fail closed; nearest timestamp is not chosen.
19. Campaign, lead, sending-account, auto-reply, or workspace mismatch fails.
20. Webhook `email_id=reply_to_uuid` is not assumed to be inbound Email ID.
21. `timestamp_email` alone cannot select a response.
22. 429 honors bounded retry; resolver never exceeds Kivou/provider rate cap.
23. `unibox_url` and attachment URL are never fetched.
24. HTML fallback performs no network and quoted outbound copy cannot create a
    false positive.

### Policy, classifier, and Hermes

25. Exact Kivou-built RESPONSE evidence/action fingerprint contains refs and
    keyed fingerprints, never raw text.
26. Policy proposed cost exceeds budget -> no model, ambiguous review; safety
    remains applied.
27. control plane/quota unavailable -> no model, ambiguous review.
28. structured output with extra/missing/unknown field -> malformed -> ambiguous
    review.
29. classifier timeout/unavailable -> ambiguous review, no hot.
30. non-positive hot flag or positive below threshold -> invalid output ->
    ambiguous review.
31. Hermes may pass only opaque response ID; arbitrary text/classification/hot/
    retry/provider fields are rejected.
32. no classifier path can create reply copy or invoke Email send/reply.

### Idempotency, transaction, and replay

33. Duplicate webhook -> one response/evaluation identity and one classifier
    finalization.
34. Concurrent workers -> one claim/final result.
35. Crash before Email list -> retry same evaluation.
36. Crash after Email GET -> no raw content persists; retry resolves again.
37. Crash after model response before commit -> no partial outcome; retry cannot
    create conflicting business effects.
38. Crash during final transaction -> evaluation/suppression/outcome/action all
    roll back.
39. Same response + same classifier version -> exact replay.
40. Same response + new classifier version -> explicit superseding row; old row
    unchanged.
41. Reclassification cannot unsuppress, resume, or erase REPLIED.
42. Second distinct reply after member STOP -> distinct evaluation, idempotent
    safety.
43. Human negative can still advance `SENT -> REPLIED`.
44. Late human reply after higher outcome records event without state downgrade.
45. Auto reply records no OUTCOME_RECORDED.

### Persistence, PII, and architecture

46. Fresh DB/0016 upgrade/downgrade/re-upgrade -> one head
    `0017_response_intelligence` and exactly one new table.
47. PostgreSQL offline SQL and SQLAlchemy Core schema remain equivalent.
48. Table constraints enforce hot/human/next-action/finalization invariants.
49. Synthetic email/name/phone/subject/body/HTML/message ID/Unibox URL/attachment/
    prompt/model-output/secrets are absent from all forbidden durable/log paths.
50. Only the final keyed content fingerprint persists; no standalone digest or
    raw message table exists.
51. Importing response/campaign/API packages performs zero LLM or provider I/O.
52. ASGI creation starts no response worker.
53. Dependency guards exclude SMTP, arbitrary HTTP tools, response generation,
    SPEC-028 attribution, and SPEC-029 allocation.

Offline classifier evaluation should use a versioned synthetic FR/EN corpus
covering every taxonomy category, safety conflicts, quoted prior messages,
prompt-injection text, unsupported language, malformed output, and near-miss
positive examples. It must contain no real prospect data and must never call a
production model in CI.

## Known limitations and explicit later decisions

The architecture is frozen by this report; deployment still requires explicit
selection/review of:

- the exact FR/EN deterministic safety phrase catalog;
- the provider/model and prompt implementation, or a decision to route every
  non-deterministic reply directly to review;
- the model data-processing/privacy terms and maximum per-response cost;
- the production content-fingerprint key and rotation set;
- the least-privilege `emails:read` key and rate budget;
- the human-review destination, ownership, and operational SLA;
- the explicit production transition from `NONE` to `SPEC027_V1` and webhook
  subscription change.

None of these is silently configured here. No model choice can weaken safety,
create a customer reply, or treat provider labels as authority.

## SPEC-028 and later boundaries

SPEC-027 ends at response truth, classification, suppression/stop, hot-lead
flag, and human-review/no-action handoff.

SPEC-028 owns attribution from campaign/click to Kivou activation, payment,
MRR, retention, and churn. A positive reply is not conversion or revenue.

SPEC-029 continues to own adaptive allocation. Response classifications may
later become reviewed learning inputs, but SPEC-027 does not alter volume,
wedge allocation, pacing, or economics.

No sales-response generation, meeting qualification, autonomous conversation,
or CRM is authorized by this design.

## Design-only closeout

This report recommends:

- one closed operational taxonomy;
- deterministic safety before commercial classification;
- webhook trigger/immediate stop plus typed Email V2 exact-resolution fallback;
- no raw response-content persistence;
- one `0017_response_intelligence` table;
- existing `REPLIED`, `OUTCOME_RECORDED`, and next-action events;
- `POSITIVE` as the only hot-lead category with mandatory human review;
- budgeted/control-plane-gated provider-neutral classification;
- `ResponseIngressCapability.SPEC027_V1` only after explicit deployment gates;
- no customer reply and no SPEC-028 attribution.

No implementation, migration, model/provider call, Email API call, webhook
change, email, or deployment was performed while producing this design.
