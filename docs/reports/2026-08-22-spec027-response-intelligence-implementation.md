# SPEC-027 — Response Intelligence implementation

Date: 2026-08-22
Merged design SHA: `92ac09215762fdbd2435ac9b5ddb77217bc913ee`
Final rebased implementation base: `6a391673570f6967b407a9481b8fc7dc0115155c`
Implementation branch: `feat/spec027-response-intelligence`
Draft implementation PR: #46
Executable SHA: `19f3b402c49783b9f0fc9a850a4f99e8af11066a`
Executable CI: `32587533177` — SUCCESS
Final head: the documentation-only closeout commit containing this report; the PR head is the authoritative Git object because a commit cannot embed its own SHA.

## Scope and package

The frozen SPEC-027 design is implemented in the focused `src/signals/responses/` package:

- `contracts.py`: immutable taxonomy, processing, Email-resolution, classifier, fingerprint, and evaluation contracts;
- `normalization.py`: local response-content extraction and normalization;
- `safety.py`: deterministic safety precedence;
- `instantly_email.py`: narrow read-only Instantly Email V2 adapter and resolver;
- `classifier.py`: provider-neutral classifier interface and fail-closed unconfigured default;
- `policy.py`: safe `classify_response` evidence and Policy request construction;
- `store.py`: durable work reservation, leases, replay, and append-only reclassification;
- `service.py`: webhook reservation and atomic final business effects;
- `worker.py`: explicit, non-autostarted response-processing orchestration.

The existing authenticated SPEC-026 webhook path is extended rather than duplicated. It may reserve response work in the same transaction when `ResponseIngressCapability.SPEC027_V1` is explicitly injected. Webhook acknowledgement never waits for Email API resolution, Policy, or classification.

No customer-response generation, conversation agent, inbox, CRM, attachment processing, conversion attribution, or autonomous sales reply was introduced.

## Frozen contracts

Implemented semantic versions are:

- `response-intelligence-v1`
- `response-taxonomy-v1`
- `response-safety-rules-v1`
- `response-email-resolution-v1`
- `response-content-normalizer-v1`
- `response-classifier-v1`
- `response-classifier-output-v1`
- `response-evidence-v1`
- `response-evaluation-store-v1`
- `response-content-fingerprint-v1`

The taxonomy is closed to `POSITIVE`, `NEGATIVE`, `UNSUBSCRIBE`, `WRONG_PERSON`, `REFERRAL`, `OUT_OF_OFFICE`, `AUTO_REPLY`, `COMPLAINT`, `SENSITIVE`, and `AMBIGUOUS`.

Operational processing states are `PLANNED`, `IN_FLIGHT`, `RETRY_WAIT`, and `FINALIZED`. The semantic classifier version is always non-null in deterministic evaluation identity. Safety-only finalization uses `response-safety-rules-v1`; an unavailable runtime classifier has the explicit identity `response-classifier-unconfigured-v1`.

## State and event compatibility

`acquisition-state-v1` is unchanged. No `AcquisitionState` and no `EventType` were added.

Confirmed human replies use existing `OUTCOME_RECORDED` with `outcome_state = REPLIED`. `NEXT_ACTION_SET` records `request_human_review` or a reasoned null. Machine responses do not produce REPLIED. A response cannot downgrade a later truthful acquisition outcome.

## Safety precedence and outcome semantics

Deterministic safety executes before Policy or classifier work:

1. unsubscribe / explicit stop;
2. complaint / spam or privacy objection;
3. auto reply / out of office;
4. human semantic classification.

Unsubscribe replays/appends the SPEC-025 `UNSUBSCRIBE` / `UNSUBSCRIBED` suppression, preserves the sequence stop, clears generic next action, and can never become hot. Complaint replays/appends recipient-objection suppression, preserves the stop, requests review, and can never become hot. Confirmed human unsubscribe and complaint responses truthfully record REPLIED.

Auto replies and out-of-office responses preserve STOPPED sequence execution, never become hot, never record REPLIED, and bypass the classifier when deterministic evidence is sufficient. Safety does not depend on `classify_response` Policy approval or model availability.

A hot lead requires `POSITIVE`, confidence at least `0.85`, independently confirmed human response, and an approved positive reason code. The resulting atomic effects are REPLIED plus `request_human_review`; no customer reply is generated. Negative human replies record REPLIED and close with no generic next action. Wrong-person, referral, sensitive, and ambiguous outcomes remain review-oriented and never automate new outreach.

Provider AI interest labels have no classification authority.

## Content normalization, fingerprinting, and PII

`response-content-normalizer-v1` prefers `body.text`, uses locally sanitized HTML only as fallback, normalizes Unicode, line endings, and non-semantic whitespace, removes clear prior-message quote blocks and `>` lines, performs no translation, fetches no attachment, and bounds classifier input to 16 KiB. Unsafe or missing extraction fails closed to AMBIGUOUS / REVIEW.

`response-content-fingerprint-v1` is a domain-separated keyed HMAC over canonical normalized subject and current-response text. Only the final HMAC, version, and key version persist. No standalone unkeyed digest exists, and retained key versions support replay/reclassification matching.

Raw subject, snippet, text, HTML, content preview, lead or account email, names, company, phone, address-bearing message ID, Unibox URL, attachments, raw provider JSON, prompt, model response, and chain of thought are never stored in `acquisition_response_evaluation`, generic acquisition/provider audit, Policy arguments, logs, or error strings.

## Instantly Email V2 read boundary

SPEC-027 adds a separate read-only adapter for official `GET /api/v2/emails` and `GET /api/v2/emails/{id}` contracts. It exposes only bounded `list_emails` and `get_email` methods. It cannot send, reply, mutate, delete, follow `unibox_url`, or issue arbitrary requests.

Resolution uses received-email candidates inside the frozen event window of five minutes before through fifteen minutes after the provider event, with at most three resolution attempts and a Kivou budget of ten Email API reads per workspace per minute. `429` respects bounded retry guidance. Every candidate must pass all available exact workspace/member, campaign, provider lead or transient normalized lead-address, sending-account, timestamp, and auto-reply checks.

Zero candidates retry only within the bounded resolver policy and then finalize AMBIGUOUS / REVIEW with `RESPONSE_CONTENT_UNAVAILABLE`. Exactly one candidate is fetched by exact Email UUID and fully revalidated before transient content use. Multiple candidates fail closed with `RESPONSE_IDENTITY_AMBIGUOUS`. The webhook `email_id` is not assumed to be an inbound Email UUID, and subject/body similarity, provider AI, campaign name, Unibox URL, or nearest timestamp alone cannot select a candidate.

The repository default Email reader is unconfigured and non-executable. No `emails:read` credential or live provider configuration was added.

Direct R1.1 review found that the earlier executable `bdba4d3232655f9674753a1849080e65b85c6437` incorrectly required `from_address_email` to equal the prospect address. The current official Email V2 contract defines `lead` as the lead address, `eaccount` as the Instantly sending account, and `from_address_email` as a sender-address field based on that account. Candidate binding now requires the exact normalized `lead`, exact `lead_id` when available, and exact bound `eaccount`; it deliberately ignores `from_address_email` for prospect selection. The official-contract fixture now uses `buyer@example.invalid` for `lead` and `sender@example.invalid` for both sender fields, and focused regressions cover both candidate filtering and exact GET readback revalidation.

## Classifier and Policy

`ResponseClassifier` is provider-neutral and accepts/returns strict bounded domain objects. Output contains category, confidence, reason codes, hot/review flags, classifier version, language, human confirmation, and bounded usage/cost only. It contains no rationale, generated reply, tool call, model-selected next action, or hidden reasoning.

The repository default classifier is unconfigured/non-executable. Tests inject deterministic fakes; no production model adapter or API credential was added. Missing configuration, timeout, unavailable model, malformed/extra output, unknown category, invalid confidence, reason mismatch, unsupported language, uncertain identity, or missing content becomes AMBIGUOUS / REVIEW and never POSITIVE.

The existing `classify_response` Policy command remains `PREPARATORY`, `OPPORTUNITY`, with required evidence `RESPONSE`, no volume or send controls, and no compliance requirement. It now has `uses_budget = true`, `uses_provider_quota = true`, and `requires_control_plane = true`.

Kivou builds the exact response evidence from safe references, provider-event/content fingerprints, resolver/normalizer/safety/taxonomy/classifier versions, language and human/auto facts, timestamps, and maximum proposed model cost. Raw content never enters Policy canonical arguments. Hermes supplies only the opaque 64-hex `response_ref`; it cannot provide text, provider identifiers, classification, confidence, hot flag, query, URL, prompt/model choice, retry controls, suppression override, reply text, or send action.

## Persistence and migration

While implementation was in progress, main gained the unrelated, already-merged `0017_target_icp_revision`. Under the specification's pre-authorized linear-topology rule, SPEC-027 was rebased and renumbered without an Alembic merge revision. Migration head is therefore `0018_response_intelligence`, with the exact chain `0016_campaign_factory -> 0017_target_icp_revision -> 0018_response_intelligence`. It creates exactly one SPEC-027 table:

1. `acquisition_response_evaluation`

No inbox, conversation, raw-email, attachment, CRM, or generic LLM-trace table exists. PostgreSQL offline SQL, fresh upgrade, `0016 -> 0017`, downgrade to `0016`, re-upgrade, one-head topology, SQLAlchemy Core parity, semantic constraints, and absence of raw-content columns are covered.

The table stores bounded provider/Kivou references, keyed source/content fingerprints, version identities, semantic result, safe Policy provenance, bounded usage/cost, processing lease/retry facts, event/suppression references, and append-only reclassification lineage. Final semantic fields are write-once. Same response and classifier version converge; a new version creates a superseding row without deleting or rewriting the old evaluation.

## Transaction, crash, and replay behavior

The final local transaction replay-safely applies required suppression, preserves the SPEC-026 STOP, records REPLIED only when human-confirmed, records review/null next action, and finalizes the evaluation. Duplicate webhooks reserve one response identity. Concurrent workers claim one lease and one finalized result. Conflicting finalization fails closed without duplicate business effects.

Covered crash boundaries include before/after Email list and GET, after content HMAC, before/after Policy, after classifier before commit, during the final transaction, lease expiry, restart, and duplicate model outcome. Raw content is never durable across a crash. Reclassification cannot remove suppression, resume a sequence, erase REPLIED, generate a reply, or send email.

## Validation

The SPEC-027 response test files collect 123 focused tests. Executable CI `32587533177` checked the exact corrected executable SHA and completed successfully:

- backend: 3,880 passed, 2 skipped;
- skipped tests: exactly the two existing opt-in Stripe TEST smokes in `tests/test_billing_stripe_test_smoke.py`; no SPEC-027 test is skipped;
- Ruff: PASS;
- frontend: 262 passed;
- frontend build: PASS;
- frontend typecheck: PASS;
- frontend lint: PASS;
- `git diff --check`: PASS.

All adapter and classifier tests use strict offline fakes/fixtures. Architecture guards reject unmocked provider/model networking and forbidden dependencies. No Instantly, Email API, Apollo, LLM, SMTP, or customer-reply path ran.

## Deployment gates and limitations

Repository/default `ResponseIngressCapability` remains `NONE`; this implementation does not enable `SPEC027_V1` or change a provider subscription. Before intentional production reply ingress, deployment must separately configure and verify the existing authenticated webhook binding, `emails:read` least privilege, retained content-fingerprint keys, bounded workspace rate budget, an approved structured classifier and budget/control-plane configuration, and worker runtime wiring.

The Email reader and classifier remain unconfigured, no response worker autostarts, and no raw content archive exists. Attachments, arbitrary inbox access, reply generation, meeting automation, contact replacement/referral outreach, conversion attribution, and autonomous sales conversation remain outside SPEC-027.

## External effects

No LLM was called. No Apollo network request was made. No Instantly or Email API request was made. No webhook was created or changed. No customer reply was generated, no email was sent, and no deployment or production migration was performed.
