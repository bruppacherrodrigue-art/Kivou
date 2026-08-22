# SPEC-027 Response Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement deterministic inbound-response safety, exact Email V2 resolution, bounded semantic classification, and append-auditable response outcomes without storing raw reply content or sending any customer response.

**Architecture:** The authenticated SPEC-026 webhook remains the durable transport boundary and reserves one deterministic response evaluation when `SPEC027_V1` is enabled. A pure safety layer runs before a separately injected, read-only Email V2 resolver and provider-neutral classifier; one final transaction applies suppression/STOP truth, `REPLIED`, next action, and immutable evaluation finalization. Repository defaults keep response ingress `NONE`, Email access unconfigured, the classifier unconfigured, and workers unstarted.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy Core, Alembic, FastAPI integration through the existing webhook route, httpx with injected transports, pytest, Ruff, SQLite concurrency tests, and PostgreSQL offline SQL compilation.

---

### Task 1: Freeze response contracts and content normalization

**Files:**
- Create: `src/signals/responses/__init__.py`
- Create: `src/signals/responses/contracts.py`
- Create: `src/signals/responses/normalization.py`
- Test: `tests/test_response_contracts.py`
- Test: `tests/test_response_normalization.py`

- [ ] **Step 1: Write failing contract tests**

Define tests that import the exact taxonomy, processing states, non-null safety classifier identity, strict classifier input/output models, `response_ref`, evaluation identity, and keyed content fingerprint. Prove extra classifier fields and inconsistent hot-lead output are rejected.

- [ ] **Step 2: Run the contract tests and verify RED**

Run: `uv run pytest -q tests/test_response_contracts.py`

Expected: collection fails because `signals.responses` does not exist.

- [ ] **Step 3: Implement minimal immutable contracts**

Freeze:

```python
RESPONSE_INTELLIGENCE_VERSION = "response-intelligence-v1"
RESPONSE_TAXONOMY_VERSION = "response-taxonomy-v1"
RESPONSE_SAFETY_VERSION = "response-safety-rules-v1"
RESPONSE_CLASSIFIER_VERSION = "response-classifier-v1"
CONTENT_FINGERPRINT_VERSION = "response-content-fingerprint-v1"

class ResponseClassification(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    UNSUBSCRIBE = "UNSUBSCRIBE"
    WRONG_PERSON = "WRONG_PERSON"
    REFERRAL = "REFERRAL"
    OUT_OF_OFFICE = "OUT_OF_OFFICE"
    AUTO_REPLY = "AUTO_REPLY"
    COMPLAINT = "COMPLAINT"
    SENSITIVE = "SENSITIVE"
    AMBIGUOUS = "AMBIGUOUS"
```

Use frozen `extra="forbid"` Pydantic contracts and domain-separated SHA-256/HMAC identities. Raw content exists only on `repr=False` transient input models.

- [ ] **Step 4: Write failing normalizer tests**

Cover text preference, non-network HTML fallback, Unicode/line/whitespace normalization, `>` and delimited quoted-block removal, 16 KiB rejection, missing content, and quoted Kivou outbound text that must not survive as current-response intent.

- [ ] **Step 5: Run normalizer tests and verify RED**

Run: `uv run pytest -q tests/test_response_normalization.py`

Expected: imports or behavior fail before `normalization.py` exists.

- [ ] **Step 6: Implement the non-networking normalizer**

Use only stdlib `html.parser`/`html.unescape`; never fetch links or attachments. Return a bounded canonical subject/current-response object or a typed missing/unsafe result.

- [ ] **Step 7: Run both focused suites and commit green behavior**

Run: `uv run pytest -q tests/test_response_contracts.py tests/test_response_normalization.py`

Expected: all pass.

### Task 2: Implement deterministic safety precedence

**Files:**
- Create: `src/signals/responses/safety.py`
- Test: `tests/test_response_safety.py`

- [ ] **Step 1: Write failing FR/EN safety tests**

Cover exact unsubscribe/stop requests, spam/privacy complaints, auto replies, out-of-office, unsupported language, missing content, and simultaneous positive language. Assert mandatory precedence:

```text
UNSUBSCRIBE > COMPLAINT > AUTO_REPLY / OUT_OF_OFFICE > semantic classification
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_response_safety.py`

- [ ] **Step 3: Implement pure `response-safety-rules-v1`**

Use reviewed exact/word-boundary FR/EN phrase catalogs. Return closed classifications and reason codes only—no prose, model call, or side effect.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest -q tests/test_response_safety.py`

### Task 3: Add the one-table persistence topology

**Files:**
- Create: `src/signals/persistence/migrations/versions/0018_response_intelligence.py`
- Modify: `src/signals/persistence/schema.py`
- Modify: `tests/test_campaign_factory_migration.py`
- Create: `tests/test_response_intelligence_migration.py`
- Create: `src/signals/responses/store.py`
- Test: `tests/test_response_store.py`

- [ ] **Step 1: Write failing migration/schema tests**

Assert the linear `0016_campaign_factory -> 0017_target_icp_revision -> 0018_response_intelligence` graph, one Alembic head, exactly one added table, upgrade/downgrade/re-upgrade, SQLAlchemy parity, PostgreSQL offline SQL, no raw-content columns, non-null classifier identity, hot/human/action checks, and preservation of SPEC-026 and target-ICP revision state on downgrade.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_response_intelligence_migration.py tests/test_campaign_factory_migration.py`

- [ ] **Step 3: Add `acquisition_response_evaluation`**

Create exactly the frozen bounded columns, one self-reference for append-only reclassification, and constraints for the processing/taxonomy/hot/machine/next-action/content-fingerprint invariants. Do not add any raw message, prompt, model-output, inbox, or operation table.

- [ ] **Step 4: Write failing store tests**

Cover deterministic reservation, `(provider_event_ref, classifier_version)` uniqueness, safety classifier non-null identity, single claimant, expired-lease unknown/reclaim semantics, retry wait, write-once finalization, conflicting finalization, and explicit superseding classifier version.

- [ ] **Step 5: Verify store RED**

Run: `uv run pytest -q tests/test_response_store.py`

- [ ] **Step 6: Implement PostgreSQL-safe SQLAlchemy Core store**

Use `INSERT .. ON CONFLICT DO NOTHING`, row locking/compare-and-set, bounded leases, and exact replay validation for SQLite/PostgreSQL only.

- [ ] **Step 7: Verify persistence GREEN**

Run: `uv run pytest -q tests/test_response_intelligence_migration.py tests/test_response_store.py tests/test_campaign_factory_migration.py`

### Task 4: Add the narrow read-only Instantly Email V2 boundary

**Files:**
- Create: `src/signals/responses/instantly_email.py`
- Create: `tests/fixtures/instantly_v2_email_response_2026-08-22.json`
- Test: `tests/test_response_instantly_email.py`

- [ ] **Step 1: Write official-fixture contract tests**

Assert only `GET /api/v2/emails` and `GET /api/v2/emails/{uuid}` exist; query allowlist is campaign/lead/eaccount/received/time/order/limit/cursor; limit is at most 100; API key is absent from repr/errors; response enrichment/AI/attachment fields are ignored; 401/402/403/404/429/5xx/timeout are typed; `Retry-After` is bounded.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_response_instantly_email.py`

- [ ] **Step 3: Implement the strict reader and models**

Use an injected `httpx.Client`/transport, base `https://api.instantly.ai/api/v2`, bearer header, no generic method/path API, no send/reply/update/delete, and a workspace rate budget capped at ten list/get requests/minute.

- [ ] **Step 4: Verify GREEN and no-network guard**

Run: `uv run pytest -q tests/test_response_instantly_email.py`

### Task 5: Implement exact candidate resolution

**Files:**
- Create: `src/signals/responses/service.py`
- Test: `tests/test_response_resolution.py`

- [ ] **Step 1: Write failing zero/one/multiple tests**

Cover the event `[-5m,+15m]` interval, at most three attempts over 15 minutes, exact campaign/lead-or-email/eaccount/time/received/auto checks, GET revalidation, zero retry/exhaustion, multiple ambiguity, webhook `email_id` not used as inbound ID, timestamp not selected alone, and no Unibox/attachment fetch.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_response_resolution.py`

- [ ] **Step 3: Implement the bounded resolver**

Return typed resolved/retryable/unavailable/ambiguous results. Select only one candidate satisfying every available binding; never use subject/body/provider AI/campaign name/Unibox URL/nearest-time heuristics.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest -q tests/test_response_resolution.py`

### Task 6: Update Policy and classifier boundaries

**Files:**
- Modify: `src/signals/policy/registry.py`
- Modify: `src/signals/policy/mapper.py`
- Create: `src/signals/responses/classifier.py`
- Test: `tests/test_response_policy_classifier.py`

- [ ] **Step 1: Write failing Policy/classifier tests**

Assert `classify_response` stays `PREPARATORY/OPPORTUNITY/RESPONSE`, changes budget/provider-quota/control-plane flags to true, retains no volume/send/compliance gate, builds exact Kivou-owned RESPONSE evidence without raw text, and blocks classifier execution on cost/control/quota denial.

Assert Hermes mapping accepts only an opaque response ref with empty arguments. Assert no configured classifier, timeout, malformed/extra fields, unknown taxonomy, invalid confidence/reason/hot invariants, and unsupported language become `AMBIGUOUS / REVIEW`.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_response_policy_classifier.py`

- [ ] **Step 3: Implement provider-neutral classifier contracts and Policy builder**

The default classifier raises a bounded unconfigured error and performs zero I/O. Kivou derives hot/review/next action from the taxonomy; classifier output cannot generate copy or choose a send action.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest -q tests/test_response_policy_classifier.py`

### Task 7: Integrate the existing webhook and response worker

**Files:**
- Modify: `src/signals/campaigns/webhooks.py`
- Create: `src/signals/responses/worker.py`
- Test: `tests/test_response_webhook_integration.py`
- Test: `tests/test_response_worker.py`

- [ ] **Step 1: Write failing ingress tests**

Prove `NONE` preserves current SPEC-026 behavior; `SPEC027_V1` reserves one response in the same transaction; duplicate webhook converges; acknowledgement never waits for Email/Policy/classifier; auto reply is safety-only; conclusive unsubscribe/complaint suppression runs before Policy; and raw webhook content is absent from the evaluation.

- [ ] **Step 2: Verify webhook RED**

Run: `uv run pytest -q tests/test_response_webhook_integration.py`

- [ ] **Step 3: Implement injected response ingress coordinator**

Add an optional transaction-scoped collaborator to `InstantlyWebhookService`. Do not add a route, worker startup, default capability change, provider discovery, or import-time I/O.

- [ ] **Step 4: Write failing worker/final-transaction tests**

Cover FR/EN positive, negative, wrong person, referral, complaint, unsubscribe, auto/OOO, sensitive, ambiguous/missing/unsupported, positive threshold, provider label ignored, `REPLIED` truth, next action, suppression precedence, and no automatic response.

Cover crashes before/after list, GET, HMAC, Policy, classifier, and final commit; duplicate/concurrent workers; same-version replay; append-only new-version reclassification; and late response without state downgrade.

- [ ] **Step 5: Verify worker RED**

Run: `uv run pytest -q tests/test_response_worker.py`

- [ ] **Step 6: Implement the explicit worker saga**

Claim one evaluation, resolve/normalize/HMAC content in memory, apply deterministic safety, run exact Policy only for semantic classification, call only the injected classifier, and atomically finalize suppression/STOP/REPLIED/NEXT_ACTION/evaluation. Raw content must leave scope without persistence even after faults.

- [ ] **Step 7: Verify integrated GREEN**

Run: `uv run pytest -q tests/test_response_webhook_integration.py tests/test_response_worker.py tests/test_campaign_webhooks.py`

### Task 8: Architecture, PII, replay, and offline evaluation guards

**Files:**
- Create: `tests/fixtures/response_intelligence_eval_v1.json`
- Create: `tests/test_response_architecture.py`
- Create: `tests/test_response_pii.py`

- [ ] **Step 1: Write failing architecture/PII tests**

Seed unique synthetic email/name/phone/subject/body/HTML/message-ID/preview/Unibox/attachment/prompt/model-output/API-secret markers and inspect response/provider/operation/acquisition/Policy/log/error persistence. Assert no SMTP, arbitrary HTTP API, response generator, SPEC-028/029 dependency, import/startup I/O, worker autostart, Email/model network, or skipped SPEC-027 test.

- [ ] **Step 2: Verify RED where guards expose gaps**

Run: `uv run pytest -q tests/test_response_architecture.py tests/test_response_pii.py`

- [ ] **Step 3: Add minimal exports/guards and synthetic corpus**

Keep the default response capability `NONE`, Email reader unconfigured, classifier unconfigured, and no background wiring. The corpus must cover every taxonomy category, conflicts, prompt injection, quoted outbound copy, unsupported language, malformed classifier output, and positive near misses.

- [ ] **Step 4: Verify focused SPEC-027 suite**

Run: `uv run pytest -q tests/test_response_*.py tests/test_campaign_webhooks.py tests/test_policy_relevant_gates.py`

### Task 9: Executable verification and commit

**Files:**
- All runtime, migration, plan, fixtures, and tests above

- [ ] **Step 1: Run complete backend and Ruff**

Run: `uv run pytest -q`

Expected: more than 3746 passed, exactly the two existing Stripe smoke skips.

Run: `uv run ruff check .`

Expected: exit 0.

- [ ] **Step 2: Run frontend gates**

Run from `frontend/`:

```bash
npm test -- --run
npm run build
npm run typecheck
npm run lint
```

Expected: at least 253 tests and all commands exit 0.

- [ ] **Step 3: Verify migration and repository hygiene**

Run: `git diff --check && git status --short && uv run alembic heads` using the repository's programmatic Alembic configuration/test where no `.ini` exists.

- [ ] **Step 4: Commit and push the executable artifact**

Commit all non-closeout changes, record `SPEC027_EXECUTABLE_SHA`, push the branch, and wait for executable GitHub CI success before editing the implementation report.

### Task 10: Docs-only closeout and draft PR

**Files:**
- Create: `docs/reports/2026-08-22-spec027-response-intelligence-implementation.md`

- [ ] **Step 1: Write the implementation report after executable CI**

Record design squash/base/executable SHA/CI, migration/head/one table, taxonomy, Email reader, safety, Policy, default capabilities/classifier, PII and no-network proofs, counts, limitations, and no external side effects.

- [ ] **Step 2: Verify executable-to-final delta**

Commit only the report. Assert `SPEC027_EXECUTABLE_SHA..HEAD` contains exactly that report.

- [ ] **Step 3: Push, run final-head CI, and open the draft PR**

Use title `feat(acquisition): implement response intelligence`. Keep the PR draft/unmerged and include both CI identities and all fail-closed/no-side-effect declarations.

- [ ] **Step 4: Re-fetch closeout facts**

Verify current main, PR state/mergeability, final head, one Alembic head, clean status, CI logs/counts, and no post-executable runtime changes before supervisor handoff.
