# SPEC-026 — Instantly Adapter + Campaign Factory implementation

Date: 2026-08-22
Authoritative base: `dffb0717ebcb14ef664d4795367293f95f33c684`
Authoritative design: `docs/reports/2026-08-21-spec026-instantly-campaign-factory-design.md`
Implementation branch: `feat/spec026-instantly-campaign-factory`
Draft PR: #41
Executable SHA: `b98d90b05cf68652e23fbfc6dceef20e9a4793ff`
Executable CI: `32554495453` — SUCCESS
Final head: the documentation-only closeout commit containing this report; the PR head is the authoritative Git object because a commit cannot embed its own SHA.

## Outcome and architecture

SPEC-026 implements a deterministic, fail-closed Campaign Factory and narrow Instantly API V2 execution boundary. Kivou remains authoritative for targeting, opportunity decisions, exact personalization, compliance, suppression, Policy, pacing, send windows, mailbox eligibility, workflow state, and remote-operation reconciliation. Instantly receives only bounded execution instructions.

The focused package is `src/signals/campaigns/`:

- `contracts.py`: immutable versioned contracts, closed state vocabularies, deployment capabilities, and typed failures;
- `factory.py`: pure campaign grouping, batch generation, naming, and two-window planning;
- `envelope.py`: exact-copy core plus configured transport/footer validation;
- `pacing.py`: frozen product-owned limits;
- `store.py`: serialized batch/member reservations and durable provider-operation state;
- `service.py`: actionable scheduling, replay, Policy construction, queue/seal, TOCTOU, and live safety checks;
- `worker.py`: explicitly invoked provider saga, mutation ordering, reconciliation, expiry, and Step-2 release;
- `webhooks.py`: authenticated PII-minimized event normalization, dedupe, suppression, and transport truth;
- `instantly.py`: narrow typed Instantly API V2 adapter and strict provider configuration contracts.

Importing the package or constructing the default API application performs no provider I/O. No provider worker is started by ASGI startup. Runtime mutation requires explicit future wiring.

## Frozen contract versions

- `campaign-factory-v1`
- `campaign-envelope-v1`
- `campaign-sequence-policy-v1`
- `batch-seal-policy-v1`
- `send-window-policy-v1`
- `sequence-window-policy-v1`
- `tracking-policy-v1`
- `pacing-policy-v1`
- `provider-stop-policy-v1`
- `provider-operation-v1`
- `provider-event-fingerprint-v1`

Every material plan, envelope, provider configuration, operation, provider binding, sequence authorization, and realized sequence timing has a deterministic domain-separated fingerprint. Raw contact/provider PII and secrets are excluded from generic fingerprints and audit payloads.

## Migration and persistence

Alembic head is `0015_campaign_factory`, directly after `0014_compliance`. It introduces exactly four tables:

1. `acquisition_campaign`
2. `acquisition_campaign_member`
3. `acquisition_provider_operation`
4. `acquisition_provider_event`

There is no `0016` and no fifth SPEC-026 table. Tests cover fresh upgrade, `0014 -> 0015`, downgrade, re-upgrade, PostgreSQL offline SQL, schema parity, constraints, indexes, foreign keys, unique identities, and the single-head invariant.

Campaign rows hold semantic grouping, deterministic generation/name, bounded provider identity/configuration, two execution dates/deadlines, and monotonic batch lifecycle data. Member rows bind the exact opportunity, artifact, compliance assessment, safe Policy provenance, provider lead, sequence authorization, and write-once realized Step-2 timing. Provider operations store only bounded request/result fingerprints and reconciliation metadata. Provider events store only PII-minimized normalized transport facts and keyed event fingerprints; no raw webhook JSON or message/reply content is retained.

## Campaign factory and sealed batching

`CampaignFactory` is pure: it has no database, network, clock, provider client, or randomness. Its semantic group key binds wedge, jurisdiction/country, language, need, personalization catalog/template/language policy, envelope/footer, sender/mailbox pool, send-window, sequence, tracking, compliance generation, and batch-seal versions. `campaign_ref` adds the serialized batch generation; provider names contain no contact PII.

`batch-seal-policy-v1` enforces:

- maximum 10 reserved members;
- immutable `first_member_reserved_at + 15 minutes` close deadline;
- immediate close on the tenth reservation;
- valid partial batches;
- no capacity reopening after failure/stop;
- no new member or `ADD_LEAD` after closure;
- no append to sealed/activation-attempted/active campaigns.

The v1 PostgreSQL path uses a bounded transaction-scoped advisory serialization boundary for empty-group generation and the low-volume global/country/wedge/mailbox/company reservations; SQLite uses an immediate transaction. Close/reservation races deterministically place a member in one generation only. A membership-closed BUILDING campaign reconciles existing reservations only, seals only when retained members are ready, and becomes FAILED when none remain.

Lifecycle is closed to `BUILDING`, `SEALED`, `ACTIVE`, `PAUSED`, `COMPLETED`, and `FAILED`. Member execution is closed to `RESERVED`, `ENROLLED`, `QUEUED`, `STOPPED`, `SENT`, and `FAILED`. Member sequence state is separately closed to `PENDING_STEP1`, `WAITING_STEP2`, `COMPLETED`, `STOPPED`, and `FAILED`.

## Exact envelope and sequence

The Step-1 provider variables are exactly `{{kivou_subject}}` and `{{kivou_envelope}}`. Kivou reconstructs and verifies the READY artifact core as greeting, body, and CTA, then appends only the approved language-specific transport/footer catalog. The validator rejects changed or empty values, unknown/unresolved placeholders, duplicate footers, unapproved URLs/reply-to, CC/BCC, HTML in text-only mode, Liquid, spintax, provider AI, variants, and additional provider prose.

Production footer configuration is empty by default. No production privacy URL or FR/EN footer was invented. Synthetic tests use explicit fake values.

The immutable sequence has exactly two messages. Step 2 retains the frozen FR/EN copy, safe greeting, same footer, four-calendar-day delay, and empty provider subject for previous-subject/thread behavior. There is no Step 3.

## Sequence windows and transport truth

`sequence-window-policy-v1` uses DST-aware `Europe/Zurich` for CH and `Europe/Paris` for FR. Step 1 is authorized on one frozen weekday in local `[09:00, 17:00)`. The Step-2 date is Step-1 date plus four calendar days, moving a weekend result to Monday. The provider configuration contains only those required weekdays between exact start/end dates.

Before activation, each member binds both execution dates and exclusive 17:00 deadlines. Exact `step_2_due_at` does not exist until deduplicated authoritative Step-1 `email_sent` evidence supplies `step_1_sent_at`; it is then calculated in local time, checked against the pre-authorized date/deadline, and persisted with an immutable timing fingerprint.

At Step-1 expiry an unsent member becomes FAILED with `STEP1_WINDOW_EXPIRED`, its acquisition opportunity remains the truthful QUEUED milestone, its generic next action is null, and lead/campaign risk-reduction work is planned. At Step-2 expiry the sequence becomes FAILED with `STEP2_WINDOW_EXPIRED`. No extra day, campaign, or step is authorized.

Unexpected authoritative sends are never discarded. They preserve actual SENT/COMPLETED truth and add bounded early/late/unexpected transport incidents without retroactively authorizing the send.

## Policy integration and acquisition workflow

`schedule_campaign` remains opportunity-scoped with `COMMERCIAL_MUTATION` risk and exact evidence:

- `ACQUISITION_DECISION`
- `PUBLIC_EVIDENCE`
- `VERIFIED_CONTACT`
- `ACQUISITION_PROSPECT_PREBUILD`
- `PERSONALIZATION_ARTIFACT`
- `COMPLIANCE_ASSESSMENT`
- `CAMPAIGN_PLAN`
- `MAILBOX_READINESS`
- `SEND_WINDOW`

It uses budget, volume, provider quota, send controls, control plane, and compliance. Legacy `FIT_DECISION` and `RECENT_SIGNAL` were removed from this command. Target scope remains `OPPORTUNITY`; caller evidence does not choose the authorization vocabulary.

The Policy action fingerprint binds the exact opportunity/supplier/contact, artifact, assessment, campaign/member, envelope, mailbox/readiness, pacing, windows, and immutable sequence. Member persistence records only safe Policy provenance: evaluation/action/policy/snapshot/control identities, decision validity, effective autonomy, and bounded approval references/fingerprints.

Immediately before activation the exact Policy decision must remain APPROVED, executable, identity/fingerprint exact, and unexpired. The one-shot ASSISTED ACTION approval authorizes activation of this exact two-step member sequence. Once activation is accepted or reconciled, later expiry of the historical Policy decision, approval, budget period, evidence, operational readiness, or aggregate compliance freshness does not alone revoke Step 2. Step 2 creates no second Policy evaluation, approval, or volume charge.

The state machine remains `acquisition-state-v1`; no EventType was added. Backward-compatible `STATE_TRANSITIONED SEND -> QUEUED` may bind the previously null `campaign_ref`; other transitions cannot replace it and historical payloads replay unchanged. The queue transaction atomically binds campaign/member, appends SEND -> QUEUED, clears `next_action` with the existing guarded `NEXT_ACTION_SET(null)`, records event references, and leaves the provider non-sending. Authoritative Step-1 `email_sent` atomically advances QUEUED -> SENT and materializes sequence timing. Step 2 adds no acquisition state transition.

## Compliance and live safety lifetime

Before any provider exposure, queue, and activation, the service rebuilds exact durable opportunity, supplier/contact/company, READY artifact, RECORDED ALLOWED assessment, compliance ruleset, sender/envelope, suppression, mailbox, plan, Policy, pacing, and window facts. Material drift fails with typed campaign input/binding conflicts.

The SPEC-025 assessment TTL is pre-activation freshness only: it must exceed activation time. Independently, ruleset and sender configuration validity must cover the exclusive Step-2 authorization deadline. The service never extends SPEC-025 TTL, creates a second assessment, or invokes ComplianceService for SENT/WAITING_STEP2.

Suppression is freshly checked before scheduling, provider exposure, queue, activation, and Step-2 safety. Retained HMAC-key coverage remains fail-closed. Unsubscribe creates durable SPEC-025 suppression before effect completion. Suppression, objection, unsubscribe, reply/auto-reply/provider unsubscribe, explicit pause, kill switch, read-only, and unsafe provider/mailbox conditions remain live hard stops.

Before Step-2 release a bounded current control check must load a valid effective Policy control. Missing, malformed, ambiguous, kill-switched, or read-only state fails closed. This is not a second schedule Policy evaluation. Excluded members must have a confirmed per-lead non-sendable readback before their campaign can activate/release. Temporary provider unavailability waits only inside the authorized window; UNKNOWN/UNHEALTHY fails closed.

## Mailbox, pacing, tracking, and deployment defaults

The versioned mailbox catalog exposes stable `mailbox_ref` values and bounded provider-account bindings; Hermes never selects an arbitrary provider email. The production/default catalog has zero usable entries. Readiness normalizes to READY, TEMPORARILY_UNAVAILABLE, UNHEALTHY, or UNKNOWN; provider capacity can only lower Kivou limits.

`pacing-policy-v1` freezes autonomous live outbound at zero, ASSISTED first-live mode, global 5/day, country 5/day, wedge 3/day, mailbox 3/day, maximum batch 10, and one active company contact per rolling 30 days. Limits are Kivou-owned and never adaptively increased.

`tracking-policy-v1` disables open/link tracking, provider AI, automatic variants, Liquid, and spintax; enables text-only, first-email text-only, bounce protection, and desired List-Unsubscribe; disallows risky contacts. Provider stops are `stop_on_reply=true`, `stop_on_auto_reply=true`, and `stop_for_company=false`. The strict nested provider configuration/readback proves the exact two-step shape and rejects hidden/unknown configuration drift.

Deployment defaults are intentionally non-executable:

- mailbox catalog: empty;
- transport contract proof: `UNVERIFIED`;
- webhook/plan entitlement: unverified;
- response ingress capability: `NONE`;
- Instantly API secret: absent;
- Instantly webhook secret/workspace: absent;
- autonomous live outbound cap: zero.

Activation therefore cannot occur from repository defaults.

## Provider adapter, operation ledger, and reconciliation

The adapter is fixed to `https://api.instantly.ai/api/v2` and exposes only the reviewed campaign, lead, account-readiness, pause, webhook-list, and event-list methods. There is no public arbitrary method/path/body API. HTTP failures map to bounded AUTH, PERMISSION, PLAN_REQUIRED, RATE_LIMITED, TIMEOUT, NETWORK, SERVER_ERROR, CLIENT_CONTRACT_ERROR, MALFORMED_RESPONSE, and REMOTE_STATE_CONFLICT failures. Retry-After is honored; retries are capped at three attempts.

External operations use deterministic unique keys and states `PLANNED`, `IN_FLIGHT`, `CONFIRMED`, `RECONCILE_REQUIRED`, `RETRYABLE_FAILED`, and `TERMINAL_FAILED`. Lease expiry means unknown remote outcome and forces reconciliation. Timeout/network/ambiguous mutation responses are never blind-retried.

Reconciliation behavior:

- CREATE: exact deterministic name, workspace binding, full configuration, and non-sending status; zero matches permits bounded retry only after absence proof; multiple/mismatched matches conflict;
- CONFIGURE: GET and exact allowlisted configuration fingerprint;
- ADD_LEAD: exact campaign, transient email, provider lead ID, and all Kivou custom variables; partial bulk outcomes split per member;
- ACTIVATE: active plus exact configuration/members confirms; draft/paused permits retry only after proven non-activation and complete fresh checks;
- PAUSE_CAMPAIGN/PAUSE_LEAD: remote result plus exact readback must prove non-sending state; ambiguous outcomes reconcile and cannot unlock activation.

The mutation order is create non-sending campaign, configure/read back, reserve/add/reconcile leads, close membership, queue retained members, seal, revalidate every retained/excluded member, then activate. Activation dependencies wait for all required risk-reduction operations. An immediate email event during activation reconciliation is safe because every sendable member was already QUEUED.

## Webhook ingress, authentication, dedupe, and PII

`POST /webhooks/instantly` follows existing API composition and is disabled without injected service plus configured secret/workspace. It requires JSON, enforces 64 KiB before/during streaming, compares the custom secret in constant time, never puts a secret in the URL, validates a strict bounded schema and workspace/campaign/member binding, and durably accepts/deduplicates before effects.

Stable provider event/message IDs participate when present. Otherwise a versioned keyed domain-separated fingerprint uses stable metadata plus transient event-specific differentiation; all retained fingerprint-key versions are matched. Reply-like content may differentiate the transient fingerprint, but only the final fingerprint/key version persists. Raw email/name/phone/subject/body/HTML/reply content/provider JSON/secrets never enter provider-event rows, generic events, Policy canonical arguments, or error strings.

Step-1 and Step-2 `email_sent` handling preserves provider truth and is idempotent. `lead_unsubscribed` resolves transient identity, writes durable suppression, stops the remaining sequence, and plans provider risk reduction. `reply_received` subscription is rejected while response ingress is NONE; an unexpected authenticated reply event stores only transport metadata, stops safely, and raises a bounded configuration incident without classification or reply-content persistence. Bounce/account error perform risk reduction only; open/link events are transport observations only; unknown event names have no business effect.

## TDD, EVAL, crash, concurrency, and validation

The synthetic offline corpus is `tests/fixtures/campaign_factory_eval_v1.json`. Focused implementation tests exercise pure factory/envelope/pacing/windows, migration constraints/parity, batch closure/generation/concurrency, Policy/replay/lifetimes, compliance/suppression TOCTOU, provider HTTP contracts, remote reconciliation, webhook auth/dedupe/PII, sequence timing/windows, live safety, and dependency boundaries.

Crash/restart coverage includes pre-request crash, unknown CREATE/CONFIGURE/ADD/ACTIVATE/PAUSE results, provider success before local persistence, partial lead outcomes, queue commit, immediate send during activation reconciliation, durable Step-1 event before timing completion, duplicate webhook, expired operation lease, bounded retry, and process restart. Concurrency covers same opportunity convergence, compatible members sharing one BUILDING generation, capacity/close races, and one remote-operation claimant. No restart path treats lease expiry or timeout as provider rejection.

Final executable validation at `b98d90b05cf68652e23fbfc6dceef20e9a4793ff`:

- focused campaign/Policy/state/migration suite: 218 passed;
- full backend: 3,677 passed, 1 skipped;
- only skipped test: `tests/test_billing_stripe_test_smoke.py` (explicit Stripe TEST opt-in; no key present);
- Ruff: PASS;
- frontend: 150 passed;
- frontend build: PASS;
- frontend typecheck: PASS;
- frontend lint: PASS;
- `git diff --check`: PASS;
- executable CI `32554495453`: SUCCESS with the same 3,677/1/150 counts and all gates green.

Architecture tests prove no runtime dependency on Apollo network clients, SMTP, OpenRouter/LLM, crawler, Stripe execution, customer TargetICP/MatchingEngine/feedback, SPEC-027 response classification, SPEC-028 attribution, or SPEC-029 adaptive allocation. HTTP adapter tests use strict `httpx.MockTransport`; campaign workflow tests use an injected fake provider. Normal CI is offline.

## Known limitations and deployment gates

Production execution remains intentionally blocked pending all external deployment inputs:

- explicit real mailbox catalog;
- authoritative FR/EN privacy/footer configuration and URL;
- Hyper Growth webhook entitlement verification;
- manually/deployment-time configured authenticated webhook;
- separately authorized paused/draft Instantly transport-contract proof covering exact variables/rendering, List-Unsubscribe, dates/hours/timezone/weekdays, end-date containment, actual-send-relative follow-up delay, empty follow-up subject, reply/auto-reply stops, and per-lead pause/removal;
- explicit future worker/runtime wiring;
- separate supervisor authorization for any live trial.

SPEC-027 owns sensitive response ingress/classification, SPEC-028 owns conversion attribution, SPEC-029 owns adaptive allocation, and SPEC-031 owns broader reliability/runbooks. No fallback architecture was silently selected.

## Side effects

No LLM/provider was called. No Apollo network request was made. No Instantly network request was made. No Instantly campaign was created, configured, paused, or activated. No lead was added to Instantly. No email was sent. No Instantly webhook or API key was created or changed. No Stripe mutation occurred. No staging/production deployment, VPS access, or production migration was performed.
