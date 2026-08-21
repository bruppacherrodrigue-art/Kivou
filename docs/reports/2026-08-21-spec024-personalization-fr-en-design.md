# SPEC-024 — Personalization FR / EN: D1 design closeout

**Status:** design only — implementation requires supervisor approval
**Audited main:** `d4e4818d9eb2f57526842335e5bd39898730acf3`
**Alembic head:** `0012_decision_engine`
**Design branch:** `feat/spec024-personalization-design`

## 1. Frozen v1 decision

SPEC-024 produces one short, grounded French **or** English campaign-preparation artifact for an opportunity that is currently eligible under the authoritative SPEC-023 decision rules. It does not send email, create a campaign, authorize outreach, decide compliance, schedule mail, call Apollo/Instantly/SMTP, crawl the web, or alter the Decision Engine’s historical decision.

V1 is **template-only**:

- deterministic and versioned FR/EN renderer;
- supported languages exactly `fr` and `en`;
- one selected-language artifact, never automatic bilingual output/fallback;
- zero LLM/provider calls, zero web research/crawler calls, and zero generation cost;
- no LLM abstraction, provider selection, model selection, model/provider schema column, or speculative future LLM persistence in this SPEC.

Templates are the safer v1 boundary: audited acquisition data establishes public procurement facts, a frozen calibrated Need Graph inference, supplier identity, company context, and a verified business contact. It does **not** establish the supplier’s actual offering and SPEC-022 does not crawl or understand its web site. V1 must not turn bounded data into unconstrained commercial claims.

## 2. Audited current-main contracts

### 2.1 Acquisition workflow

`acquisition-state-v1` and SPEC-023 already produce the required input state:

| Decision | State | Next action |
| --- | --- | --- |
| `SEND` | `SEND` | `prepare_campaign` |
| `REVIEW` | `REVIEW` | `request_human_review` |
| `NO_SEND` | `NO_SEND` | `NULL` |

`DECISION_RECORDED` already changes decision, state, and next action atomically. Historical decision events that lack its additive `next_action` payload replay under their historical path. SPEC-024 needs neither a new EventType nor `acquisition-state-v2`.

`acquisition_event` is bounded and PII-minimized. It is not an acceptable place for rendered text, greeting data, input snapshots, or claim provenance. Existing `NEXT_ACTION_SET` is the appropriate event for the post-artifact operational step.

### 2.2 Authoritative inputs

The public-only resolver in `supplier_discovery.seed` remains authoritative. It resolves `procurement-opportunity:<opportunity_key>`, selects a representative award deterministically (completeness descending, publication descending, award key ascending), and returns the public event, award, and stable `source-event:<key>` / `contract-award:<key>` evidence refs.

The SPEC-022 `AcquisitionProspectPrebuild` stores opportunity/signal/supplier/contact bindings; Apollo organization identity; bounded company name, domain/website, country, industry, employee count, founded year, short description, keywords, observation fingerprint, research gaps/completeness, size band, and contact role tier/version. It does **not** crawl/read a web site, prove company capability, contain annual revenue, or duplicate contact PII. `acquisition_supplier` remains the supplier identity source (`PROVIDER_IDENTIFIED` / `DOMAIN_CONFLICT`).

`acquisition_contact` is the purpose-limited source for provider-verified contact data. SPEC-024 may read an optional safe first name for greeting selection, but must not place email, surname, display name, LinkedIn, or other contact PII in generic acquisition events, Policy JSON, or decision audits.

SPEC-023 provides the durable SEND decision/audit, decision and proposal fingerprints, and its frozen recency policy. Its date precedence is award date; contract-notification date only when award date is absent; publication date only when both are absent; then unresolved. `discovered_at` never establishes freshness.

### 2.3 Need Graph availability and D1 no-need rule

The public resolver can derive `ContractUnderstanding` and `NeedGraphResult` from the selected representative award without customer data. No opportunity-scoped Need Graph snapshot is currently persisted, so SPEC-024 re-derives it from the same public context using the pinned current engine/version.

For v1 the selected need is **exactly** `NeedGraphResult.needs[0]`: the current deterministic top-ranked result. Suppressed candidates and lower-ranked needs are never used. Persist the Need Graph engine version and selected-need fingerprint in the input/artifact provenance.

If `needs == ()`, or `needs[0]` is not eligible under the existing confidence/calibration contract, return `PersonalizationGroundingInsufficient` before Policy. It causes zero `prepare_campaign` Policy evaluation, zero artifact, zero `NEXT_ACTION_SET`, and zero workflow mutation. There is no minimal award-only cold email.

The Need Graph is public-only acquisition context. SPEC-024 must not read TargetICP, customer materialized-signal ownership, customer matching scores, account data, feedback, billing, entitlements, or another customer’s behavior.

## 3. Fresh current eligibility revalidation

A durable SPEC-023 SEND can become stale after it is recorded. A decision recorded at age 60 must not permit personalization at age 61. Therefore the service must perform this **read-only, pure revalidation before rendering and before `prepare_campaign` Policy Gateway evaluation**.

1. Capture the Kivou-owned, injectable timezone-aware evaluation instant exactly once.
2. Derive `as_of_date` from that instant in UTC.
3. Re-read current opportunity, supplier/contact/company-profile bindings and current public context through the authoritative resolver.
4. Reapply the frozen `decision-policy-v1` pure semantics with:
   - `max_send_age_days = 60`, inclusive;
   - `max_plausible_public_age_days = 3650`;
   - existing precedence for award / notification / publication;
   - existing invalid/future/inconsistent-date rules;
   - current supplier identity, contact verification/role, prebuild/public facts, and binding rules.
5. Require the fresh pure outcome to be `SEND`.

This revalidation never appends a second `DECISION_RECORDED`, changes SPEC-023 history, or mutates workflow. It is an eligibility check for a new personalization artifact, not a new commercial decision record.

If the current result is not SEND, return `PersonalizationDecisionNoLongerEligible` before Policy, artifact, or `NEXT_ACTION_SET`; no fallback copy is generated. The current pure result, captured `as_of_date`, revalidated public-context fingerprint, and decision-policy config fingerprint are material `PersonalizationInput` fields and enter its fingerprint.

Examples that must fail closed before Policy include day-61 age, a current `DOMAIN_CONFLICT`, current supplier/contact/profile binding drift, a changed public fact that now produces REVIEW/NO_SEND, invalid public timing, unresolved context, or stale verified-contact binding.

## 4. Frozen FR/EN copy catalog

The renderer creates only the following controlled structures. It does not ask any component to rephrase public facts.

| Part | French | English |
| --- | --- | --- |
| Subject | `Un marché public attribué à {awardee}` | `A public contract awarded to {awardee}` |
| Greeting with safe first name | `Bonjour {first_name},` | `Hello {first_name},` |
| Neutral greeting | `Bonjour,` | `Hello,` |
| Need inference | `Ce type de marché peut créer des besoins autour de {need_label}.` | `This type of contract may create needs around {need_label}.` |
| CTA/product copy | `Kivou repère ce type de signaux dans les marchés publics. Souhaitez-vous voir quelques exemples ?` | `Kivou identifies these kinds of signals in public procurement. Would you like to see a few examples?` |

The public-event sentence is **not a new independent wording**. It must use the existing authoritative FR/EN `signals.recency.claim` doctrine for the current public status. This preserves the distinction among award, notification, and publication. Optional contract title may be appended only as bounded, untrusted source data; it never changes, strengthens, or substitutes for the recency claim.

`need_label` comes only from the controlled existing FR/EN `NeedCategory` catalog; no raw Need Graph statement/reasoning, free text, suppressed candidate, or LLM translation is used. The one need sentence is explicitly possible (`peut` / `may`).

The catalog has one CTA only. It never says or implies that:

- the awardee is looking for a supplier;
- the awardee will purchase;
- the prospect provides the inferred need;
- the prospect is definitely a fit;
- Kivou knows a confirmed sourcing process;
- an email is authorized, queued, or sent.

Company/legal names, award identifiers, proper nouns, and factual numeric strings are inserted verbatim, never translated. No gender or honorific is inferred. V1 has no URL and no arbitrary fact, number, date, entity, claim, or CTA.

Recommended bounded output limits: subject <= 90 characters, greeting <= 80, body <= 700, two body paragraphs, <= 2 public factual claims, exactly 1 need inference, exactly 1 CTA, <= 8 claim entries, <= 16 evidence refs. They keep a cold message concise and storage bounded; they are not a score.

## 5. Contracts, grounding, and validator

### 5.1 `PersonalizationInput` (`personalization-input-v1`)

Canonical immutable input includes:

- versions: input, language policy, template/catalog, pinned Need Graph/understanding, and current frozen decision policy;
- opportunity/signal/supplier/contact refs; current SEND state/decision and `prepare_campaign` action;
- durable recorded decision reference/fingerprint, company-prebuild version/fingerprint, current supplier identity and current contact verification/role safe state;
- current public award/event keys, bounded public evidence refs/context fingerprint, awardee, bounded optional contract title, and selected recency basis/date;
- fresh pure revalidation result (`SEND`), `as_of_date`, and current eligibility fingerprint;
- exact selected Need Graph `needs[0]` category/certainty/evidence/version/fingerprint;
- selected language and safe `salutation_mode`, with contact-personalization fingerprint but no raw first name in generic snapshots;
- allowed claim catalog and output limits.

`personalization_input_fingerprint` covers every copy-affecting source/configuration: fresh eligibility/as-of, public context, current bindings, selected need, language, salutation state, decision/prebuild, catalog/template versions, and limits. It excludes secrets, policy evaluation/run/correlation IDs, raw provider payload, email, and runtime timestamps outside the semantic `as_of_date`.

### 5.2 Grounding

`GroundingPacket` is structured internal data: fixed claim IDs, bounded values, and evidence refs. Award titles, Apollo description/keywords, and public textual material are untrusted data; they are bounded and cannot define claims, alter catalog selection, or become instructions. V1 does not use Apollo description/keywords as copy support because they do not establish a prospect offering.

Each artifact claim maps to ordered `{claim_id, kind, evidence_refs}` where kind is `PUBLIC_FACT`, `KIVOU_INFERENCE`, or `KIVOU_PRODUCT_COPY`. Claim IDs plus refs answer later why a sentence was permitted without storing reasoning or raw data.

### 5.3 Deterministic validation

Before persistence require exact language/bindings/fingerprints; nonempty subject/body; all size/count limits; exact catalog sentences; allowed claim IDs/ref ordering; one CTA; and allowed proper-noun slot insertion only.

Reject output with email, phone, surname/display name, another recipient, URL, unknown text/metadata, hidden instruction, raw reasoning, unsupported language, an unsupported entity/number/date, certainty wording, or an implication of send/compliance/campaign completion. The renderer is deterministic, but validation remains mandatory as an integrity boundary.

## 6. Policy, idempotency, and workflow

### 6.1 Policy Gateway

Use existing `prepare_campaign` as the `OPPORTUNITY`-scoped `COMMERCIAL_MUTATION` gate. Its risk class is not weakened. Its action fingerprint binds the exact deterministic artifact proposal and fresh `PersonalizationInput`.

At implementation, its evidence semantics should be built internally by Kivou and cover equivalent additive claim types:

- `ACQUISITION_DECISION`;
- `PUBLIC_EVIDENCE`;
- `VERIFIED_CONTACT`;
- `ACQUISITION_PROSPECT_PREBUILD`;
- `PERSONALIZATION_INPUT`.

Do not rely on legacy `FIT_DECISION` as if it were a numerical score. `RECENT_SIGNAL` must not be a caller assertion replacing fresh Kivou-owned eligibility. Deterministic v1 has no external provider cost, quota, send control, or compliance decision; `schedule_campaign` remains the later SPEC-025/026 gate.

### 6.2 Idempotency and transaction

A new attempt requires the persisted state/action/bindings, current fresh eligibility SEND, and an eligible `needs[0]`.

- Existing artifact/evaluation for the evaluation ID: validate semantic bindings and return durable result with no new Policy call.
- Existing policy evaluation but no artifact/evaluation: `PersonalizationEvaluationRequiresFreshAttempt`; do not reuse approval.
- Otherwise: capture clock, fresh-pure revalidate, select need, build input, render/catalog-validate, then call Policy bound to proposal fingerprint.
- If executable: in one caller-owned transaction re-read all authoritative inputs using the same captured `as_of_date`, rebuild input/proposal, require input/eligibility/proposal fingerprints unchanged, insert immutable READY artifact, and append `NEXT_ACTION_SET(assess_campaign_compliance)`.

Any current public, supplier, contact, profile, decision, Need Graph, language, catalog, or freshness change rolls back artifact/workflow writes and requires a fresh evaluation ID. No duplicate artifact is created.

For SHADOW/non-executable policy, persist only a PII-minimized `POLICY_BLOCKED` artifact/evaluation identity with fingerprints and claim refs; rendered subject/greeting/body/CTA are NULL. Do not change opportunity state or next action.

### 6.3 State

On success state remains `SEND`; there is no QUEUED transition, campaign, scheduling, or send. Existing `NEXT_ACTION_SET` changes next action to canonical `assess_campaign_compliance`.

No EventType and no state-machine version change are needed. The supervisor/command registry must recognize `assess_campaign_compliance` when SPEC-024 implementation writes it; SPEC-024 does not implement SPEC-025 behavior.

## 7. Persistence recommendation

Future migration is linear:

`0012_decision_engine -> 0013_personalization`

Create exactly one table: `acquisition_personalization_artifact`.

No generation-run table, provider table, model table, model/provider nullable placeholders, score table, claim/evidence table, campaign table, or retention worker is part of v1.

The table is purpose-limited internal Acquisition Engine storage, never a customer-facing API in SPEC-024. It contains a deterministic artifact ID derived from `personalization-artifact-v1 + policy_evaluation_id`; opportunity/supplier/contact and policy/decision FKs; selected language; input/catalog/template/action/artifact fingerprints; bounded PII-minimized input identity; bounded subject/greeting/body/CTA and claim map for READY only; deterministic renderer/template/catalog provenance only; policy/counterfactual status; disposition `READY | POLICY_BLOCKED`; timestamps/correlation ID.

Constraints require policy evaluation uniqueness, READY content fields, NULL rendered content for POLICY_BLOCKED, bounded JSON/text, and immutable rows. No separate first-name field, last name, display name, business email, phone, LinkedIn, raw Apollo person payload, provider/model metadata, or raw source payload is persisted.

A separate table is justified because generic events and Policy/decision audits are PII-minimized and do not own exact rendered copy/template/claim provenance.

## 8. TDD and EVAL plan

Required deterministic tests include:

- only current `SEND + prepare_campaign` is actionable; REVIEW/NO_SEND/stale bindings/missing prebuild/decision/contact fail before Policy;
- SEND recorded at day 60 and personalized at day 60 passes fresh eligibility;
- the same durable SEND at day 61 yields `PersonalizationDecisionNoLongerEligible`, zero Policy/artifact/next-action;
- current public change or supplier identity change yielding current pure decision != SEND fails before Policy;
- fresh revalidation uses injected Kivou timezone-aware clock once, UTC `as_of_date`, frozen 60-inclusive / 3650-day semantics, and authoritative date precedence;
- Need Graph zero result yields `PersonalizationGroundingInsufficient`, zero Policy/artifact/workflow; multiple needs uses exactly `needs[0]`; suppressed/low-confidence needs cannot appear;
- exact French and English subject/catalog, authoritative recency claim invocation, publication fallback never says “vient de remporter” / “has recently won”, bounded title does not change claim;
- optional first-name greeting only; neutral fallback; no gender/honorific; no raw first-name persistence field;
- no provider/model placeholder in migration contract and no external I/O;
- injected untrusted title/description/keyword text remains data and cannot change copy/schema/claims;
- validator rejects wrong language, empty/oversized content, unknown claims/refs, email/phone/URL, extra recipient, unsupported fact/number/date/entity, certainty wording, raw reasoning, or fingerprint mismatch;
- action fingerprint binds exact fresh proposal; actor/scope/evidence changes conflict; SHADOW persists no rendered content and no workflow event;
- replay has zero new Policy call; policy-without-artifact needs fresh ID; same concurrent identity has one artifact; final input drift rolls all writes back;
- READY artifact + `NEXT_ACTION_SET(assess_campaign_compliance)` is atomic; historical acquisition streams replay identically;
- architecture proves zero Instantly/SMTP/Apollo/LLM/crawler/customer TargetICP/billing/feedback/materialized-signal ownership/Stripe and no hidden reasoning.

The review EVAL corpus evaluates invariants, not gold wording: CH/French fresh award; French LIMITED research; explicit English; day-60 edge; publication fallback; generic prospect; no safe first name; long title; low-certainty need; multiple needs; zero need; and prompt-injection-like public/Apollo text. Evaluate factual correctness, inference calibration, catalog exactness, language quality, concision, no fake familiarity/certainty, and CTA quality. Never tune upstream truth or decision thresholds to these examples.

## 9. Non-goals and approved implementation sequence

Out of scope: LLM/provider work, compliance/lawful basis/opt-out, mailboxes/send windows, campaigns, Instantly, SMTP, Apollo, crawlers/web research, contact enrichment, Need Graph tuning, customer data, billing/Stripe, scores/probabilities, deployment, and sending.

After supervisor implementation authorization:

1. add failing pure tests for fresh eligibility, selected-need grounding, catalog renderer, and validator;
2. implement public-only input/revalidation using shared resolver and frozen decision semantics;
3. add one `0013_personalization` artifact migration/store, policy integration, idempotency, and atomic `NEXT_ACTION_SET`;
4. prove replay/privacy/architecture constraints and run offline regression.

## 10. D1 conclusions

- Template-only v1 is frozen; no LLM/provider design remains.
- Fresh pure SPEC-023 eligibility revalidation is mandatory before rendering and Policy.
- No current eligible need means no personalization.
- Copy is the frozen FR/EN catalog plus existing authoritative recency claim doctrine.
- Artifact PII is limited to optional rendered first-name greeting; no separate PII fields.
- One 0013 table is the complete v1 persistence recommendation.
- Successful workflow remains SEND and advances to `assess_campaign_compliance`.
- `prepare_campaign` remains commercial mutation and uses fresh internally constructed evidence.
- No unresolved supervisor decision remains for SPEC-024 v1 design.
