# SPEC-026-R2 — Instantly V2 webhook contract hotfix

Date: 2026-08-22
Authoritative base: `98503080f1cf7bb1a11741fbed7843a2b41944c6`
Implementation branch: `fix/spec026-instantly-v2-webhooks`
Draft PR: #43
Executable SHA: `78e301defdc5a7476c8b5dedb5483fde5300dce8`
Executable CI: `32567892544` — SUCCESS
Final head: the documentation-only closeout commit containing this report; the PR head is the authoritative Git object because a commit cannot embed its own SHA.

## Official contract reviewed

The provider boundary was reverified on 2026-08-22 using only the current official Instantly documentation:

- [Webhook event payloads and event vocabulary](https://developer.instantly.ai/guides/webhook-events)
- [Webhook API group](https://developer.instantly.ai/api-reference/groups/webhook)
- [Get webhook](https://developer.instantly.ai/api-reference/webhook/get-webhook)
- [Email API group](https://developer.instantly.ai/api-reference/groups/email)
- [List email](https://developer.instantly.ai/api-reference/email/list-email)
- [Get email](https://developer.instantly.ai/api-reference/email/get-email)

No Instantly API endpoint was called. Documentation pages were read only.

## Webhook normalization correction

The raw provider contract now enters one narrow `normalize_instantly_webhook_payload` boundary. It requires and maps the documented base fields `timestamp`, `event_type`, `workspace`, `campaign_id`, and `campaign_name`. Kivou's canonical workspace field is `provider_workspace_ref = raw["workspace"]`; `workspace_id` is no longer the required webhook-delivery field.

The canonical allowlist retains only bounded transport facts needed by SPEC-026: event type/time, workspace and campaign identities, transport-only campaign name, transient lead email and sending account, transient Unibox URL, optional step/variant, and optional documented email event ID. Provider-added lead enrichment and other unknown top-level fields are discarded before persistence, logging, Policy, or acquisition workflow effects. Provider campaign binding remains exact workspace plus provider campaign ID; campaign name is never binding authority. When no provider lead ID exists in the delivery, member resolution uses the exact campaign plus a transient normalized business email and fails safely on no match or ambiguity.

Unknown fields and unknown event types are deliberately different. Unknown fields are ignored. Unknown event types are stored only as a bounded `unknown` quarantine record with `UNKNOWN_PROVIDER_EVENT_TYPE`; the original value participates only in the keyed fingerprint and creates no workflow or business effect.

## Event vocabulary and safety behavior

The official `account_error` name replaces the incorrect `email_account_error` dependency. `account_error` produces only campaign risk reduction through the existing bounded pause operation. The non-official name is not accepted for subscription configuration.

`auto_reply_received` is now a closed recognized safety event. Exact member resolution stops the remaining sequence with `AUTO_REPLY_RECEIVED` while preserving any acquisition truth already reached. It performs no response classification, HOT outcome, or LLM call.

`reply_received` no longer requires subject, snippet, text, or HTML fields. With `response_ingress_capability = NONE`, an unexpected authenticated and correctly bound event still stops the remaining sequence, persists only PII-minimized transport metadata, and records `UNEXPECTED_REPLY_WITHOUT_RESPONSE_INGRESS`. It neither fetches response content nor classifies it. The normal production subscription validator continues to reject intentional `reply_received` enablement while the capability is `NONE`.

## SPEC-027 response-content handoff

SPEC-027, not this hotfix, owns durable sensitive response ingress. The reviewed future handoff uses typed Instantly Email V2 reads—`GET /api/v2/emails` and `GET /api/v2/emails/{id}`—with an `emails:read`-compatible scope. The documented Email object includes bounded identifiers and response-bearing fields such as `id`, `timestamp_email`, `subject`, `body.text`, `body.html`, `campaign_id`, `lead_id`, `thread_id`, `is_auto_reply`, and `content_preview`.

SPEC-026-R2 adds no Email API method, scope, key, request, arbitrary Unibox URL fetch, reply-content persistence, or response classification. `unibox_url` is accepted only as transient provider compatibility data and may contribute to dedupe; it is never fetched, persisted, exposed to Hermes, or treated as an authenticated object identity.

## Fingerprint and PII boundary

The canonical event fingerprint is now `provider-event-fingerprint-v2`. A domain-separated keyed HMAC binds the available normalized transport tuple: event type, `workspace`, campaign ID, optional email event ID, timestamp, optional step/variant, and transient normalized lead email, sending account, and Unibox URL where present. Key rotation still checks every retained key version. Only the final HMAC, fingerprint version, and key version are persisted.

Reply subject/body/HTML are not required and do not affect fingerprint identity. Provider enrichment is likewise excluded. Raw lead email, sending account, campaign name, Unibox URL, person/company/phone enrichment, subject/body/HTML, reply content, raw JSON, API key, and webhook secret do not enter `acquisition_provider_event`, acquisition event payloads, Policy arguments, or error strings. The provider-event row may persist the already-bound provider lead ID from Kivou's campaign member; it never persists the raw email used transiently to resolve that member.

## Persistence, architecture, and defaults

No migration was created. The linear migration head remains `0016_campaign_factory`, and the existing SPEC-026 persistence topology remains exactly four tables:

1. `acquisition_campaign`
2. `acquisition_campaign_member`
3. `acquisition_provider_operation`
4. `acquisition_provider_event`

Campaign batching, SEND -> QUEUED ordering, operation reconciliation, two-window sequence semantics, Policy/compliance lifetimes, pacing, non-executable `PAUSE_LEAD`, mailbox defaults, and disabled worker autostart are unchanged.

Fail-closed repository defaults remain unchanged: mailbox catalog empty, transport proof `UNVERIFIED`, lead risk-reduction proof `UNVERIFIED`, webhook entitlement `UNVERIFIED`, response ingress capability `NONE`, autonomous live outbound zero, and provider/webhook secrets absent.

## TDD and validation

The official synthetic fixture is `tests/fixtures/instantly_v2_webhook_events_2026-08-22.json` and covers `email_sent`, `reply_received`, `auto_reply_received`, `lead_unsubscribed`, `account_error`, and `campaign_completed` using only synthetic identifiers and reserved example domains.

Regression coverage proves official `workspace` acceptance without `workspace_id`, campaign-name and Unibox enrichment tolerance, durable PII exclusion, official account-error mapping, bodyless reply safety, response-capability behavior, auto-reply stop safety, unknown-field tolerance, unknown-event quarantine, exact/no-match/ambiguous member binding, duplicate convergence, reply-content independence, and zero Instantly/Email network I/O.

Validation at executable SHA `78e301defdc5a7476c8b5dedb5483fde5300dce8`:

- focused webhook and campaign-lifetime suite: 40 passed;
- complete Campaign Factory and Instantly adapter suite: 157 passed;
- full backend: 3,738 passed, 2 skipped;
- skipped tests: exactly the two existing opt-in Stripe TEST smokes in `tests/test_billing_stripe_test_smoke.py`; no SPEC-026 test is skipped;
- Ruff: PASS;
- frontend: 253 passed;
- frontend build: PASS;
- frontend typecheck: PASS;
- frontend lint: PASS;
- `git diff --check`: PASS;
- executable CI `32567892544`: SUCCESS with backend 3,738/2 and frontend 253, all gates green.

## Side effects

No LLM was called. No Apollo network request was made. No Instantly network request or Email API request was made. No webhook was created or modified. No campaign was created, no lead was added, no campaign was activated, no email was sent, and no deployment or production migration was performed.
