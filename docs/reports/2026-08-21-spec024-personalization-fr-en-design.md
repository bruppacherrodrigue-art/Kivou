# SPEC-024 — Personalization FR / EN: implementation design

**Status:** design only — supervisor review required before implementation  
**Audited main:** `d4e4818d9eb2f57526842335e5bd39898730acf3`  
**Audited Alembic head:** `0012_decision_engine`  
**Design branch:** `feat/spec024-personalization-design`

## 1. Executive decision

SPEC-024 creates one short, grounded French **or** English acquisition message for an opportunity already in `SEND` with `next_action = prepare_campaign`. The opportunity remains `SEND`: this stage creates a campaign-preparation artifact only. It does not send email, create a campaign, decide compliance, or change the SPEC-023 commercial decision.

The recommended v1 renderer is a **deterministic, versioned FR/EN template composer**, not a live LLM. The audited data establishes a public award, calibrated plausible need, Apollo-sourced company identity, and a verified commercial contact. It does not establish the prospect’s actual offering or crawl its web site. A free-form model would make that evidence gap harder to control. Templates make every factual and inferential sentence traceable to a bounded claim.

A future `PersonalizationComposer` LLM protocol is specified below, but is **not enabled in v1**. It needs separate supervisor approval for provider, model, data processing, cost, and STARTED-before-network run semantics. V1 has no LLM call and planned external generation cost zero.

Migration `0013_personalization` is recommended with exactly one table, `acquisition_personalization_artifact`. It keeps rendered content and limited contact personalization out of generic acquisition-event and Policy JSON while retaining immutable provenance for future compliance/campaign work.

## 2. Current-main audit

### 2.1 Acquisition and decision state

`acquisition-state-v1` already supports the starting condition. SPEC-023’s additive `DECISION_RECORDED` path establishes:

| Decision | State | Next action |
| --- | --- | --- |
| `SEND` | `SEND` | `prepare_campaign` |
| `REVIEW` | `REVIEW` | `request_human_review` |
| `NO_SEND` | `NO_SEND` | `NULL` |

`DECISION_RECORDED` changes decision, state, and next action atomically. Historical events without its new `next_action` retain prior replay behavior. No new acquisition state, state-machine version, or EventType is required for personalization.

The generic `acquisition_event` payload has bounded-size and PII/secrets guards. It is not a place to store rendered outbound text, a first-name greeting, model payloads, or copy provenance. Existing `NEXT_ACTION_SET` is the correct event if an artifact changes the next operational step.

### 2.2 Inputs actually available

The shared public resolver in `supplier_discovery.seed` is the authoritative customer-independent resolver. It accepts `procurement-opportunity:<opportunity_key>`, deterministically selects the representative award by completeness descending, publication descending, then award key ascending, and returns public event, award, and stable refs `source-event:<key>` and `contract-award:<key>`. SPEC-020’s `resolve_acquisition_seed()` adds Contract Understanding and Need Graph above that public core.

The persisted SPEC-022 `AcquisitionProspectPrebuild` has opportunity/signal/supplier/contact bindings; Apollo organization identity; bounded company name/domain/website/country/industry/employee count/founded year/short description/keywords; observation fingerprint; research completeness/gaps; size band; and contact role tier/version. It **does not** crawl, read, or understand a web site; it does not establish company capability; it contains no annual revenue and no contact PII. Supplier identity remains in `acquisition_supplier` as `PROVIDER_IDENTIFIED` or `DOMAIN_CONFLICT`.

`acquisition_contact` is the purpose-limited source for selected Apollo provider-verified contact data. It contains name/title/email, but SPEC-024 only needs an optional safe first name for a greeting. Email, full name, and LinkedIn must not appear in generic event, Policy, or decision JSON.

SPEC-023 provides the current `SEND` decision, decision/proposal/public-context fingerprints, recency basis/date, and append-only `acquisition_decision_evaluation`. Its authoritative public-clock precedence is award date, then contract-notification date only if award is absent, then publication date only if both are absent, otherwise unresolved. `discovered_at` never establishes freshness.

### 2.3 Need-data gap

The public resolver can deterministically derive Contract Understanding and `NeedGraphResult` from the representative award without customer data. Current acquisition tables, however, do **not** retain an opportunity-scoped frozen Need Graph snapshot; the SPEC-022 prebuild intentionally has no need field.

V1 may re-derive bounded public-only need output using pinned `need-graph-v0.2`/understanding configuration, then put its category, calibrated certainty, evidence refs, and fingerprint in immutable `PersonalizationInput`. It must never query a materialized signal, TargetICP, customer match, or customer data. Need-Graph version/output changes are material input changes. If there is no usable supported need, omit the inference; never invent a fallback keyword. A minimal public-award template is permitted only if the approved claim catalog has adequate factual grounding; otherwise return `PersonalizationGroundingInsufficient` before Policy.

### 2.4 Existing copy/localization doctrine

`alerts.content`, `feed.copy`, and `recency.claim` already use structured localized public-event copy. `feed.copy` supports exactly `fr`/`en` and fails unsupported locales. Customer-feed rendering is ineligible because it relies on customer materialized-signal/TargetICP context.

SPEC-024 reuses the public resolver, recency semantics, controlled need labels, and FR/EN copy-catalog discipline in an acquisition-only `GroundingPacket`; it does not create a second LLM-derived event description. Existing “why now” text is reused only where its own freshness status applies. For the SPEC-023 60-day window, templates state explicit date/basis rather than call an older award “recent” under a different threshold.

### 2.5 Policy and providers

Current `prepare_campaign` is an `OPPORTUNITY`-scoped `COMMERCIAL_MUTATION`. `schedule_campaign` is the later commercial command with budget/quota/send/compliance controls. `evaluate_opportunity` is preparatory. SPEC-024 must never invoke `schedule_campaign`, Instantly, SMTP, or a mailbox.

The existing OpenRouter document-intelligence client demonstrates bounded JSON/timeout/error handling only. It is not an approved acquisition-copy provider/model.

## 3. Truth and content policy

Every sentence belongs to one of three tagged classes:

| Class | Allowed meaning | Form |
| --- | --- | --- |
| `PUBLIC_FACT` | Directly supported by resolved award/event. | “A public source identifies X as awardee of Y.” |
| `KIVOU_INFERENCE` | Bounded Need Graph conclusion, explicitly calibrated. | “This type of award may make capacity around Z relevant.” |
| `KIVOU_PRODUCT_COPY` | Controlled claim about Kivou, not an external fact. | “Kivou helps teams monitor public signals.” |

Apollo company data may identify the prospect, but it does not prove its offering. V1 may name the company and use a safe greeting; it must not say the company can supply a particular service. Limited research weakens/omits relevance rather than inviting invention.

Forbidden: confirmed purchase/sourcing process, quantities, deadlines, budget, urgency, certifications, geography, customer references, ROI, capability claims, fabricated contacts, or an assertion that email is authorized/sent. Public fact is never converted into confirmed purchase.

## 4. Proposed architecture

Future implementation components:

1. `PersonalizationInputBuilder` loads/revalidates opportunity, recorded SEND decision, supplier/contact bindings, company prebuild, public context, and pinned Need Graph output.
2. `AcquisitionLanguagePolicy` validates explicit `fr`/`en`; it never derives language from name, country, email domain, or title.
3. `GroundingPacketBuilder` creates bounded approved claim slots. External text is untrusted data.
4. `DeterministicPersonalizationRenderer` fills fixed FR/EN templates only from approved slots.
5. `PersonalizationValidator` validates binding, claims, PII limits, and fingerprints.
6. `PersonalizationStore` owns artifact idempotency and final transaction.
7. `PersonalizationService` owns actionability, idempotency/crash preflight, Policy binding, and persistence.

There is no LLM client, HTTP client, crawler, campaign factory, or mail adapter in v1.

### 4.1 Language policy

`personalization-language-policy-v1` accepts only explicit, Kivou-validated `fr` or `en` as authorization/action input. Language and policy version enter input, proposal, and policy-action fingerprints.

- French uses controlled French template and neutral `Bonjour`.
- English uses controlled English template and neutral `Hello`.
- Unsupported locale yields `PersonalizationLanguageUnsupported` before Policy/artifact/state mutation.
- Legal/company names, IDs, proper nouns, and factual numeric strings are inserted verbatim, never translated.
- Dates come from authoritative selected date in a locale-specific numerically lossless representation; v1 omits currency unless an authorized public-amount claim is added.

Persist **only selected language**. Two variants duplicate contact PII, create unused content, and may double future LLM cost. A different language is a new explicit action, not fallback.

### 4.2 Contact use

Use first name only if present, single-line, bounded, and locally valid; otherwise use `Bonjour,` or `Hello,`. Never infer gender/honorific or use surname, display name, email, phone, personal LinkedIn, or location. The rendered artifact may contain a first-name greeting; its purpose-limited table is the only non-contact location allowed to contain it.

### 4.3 Template shape and limits

V1 is a subject, optional greeting, two body paragraphs, and exactly one CTA. It allows at most two public facts and one calibrated need inference, with no URL.

| Field | Limit | Rationale |
| --- | ---: | --- |
| Subject | 90 chars | inbox-readable, bounded storage |
| Greeting | 80 chars | optional first name only |
| Body | 700 chars | concise cold note and bounded PII text |
| Paragraphs | 2 | fact then relevance/CTA |
| Public claims | 2 | avoids fact dumping |
| Need inferences | 1 | avoids speculation stacking |
| CTA | 1 | one bounded ask |
| Claim/evidence entries | 8 / 16 refs | auditable but bounded |

Paragraph one is an approved public award/date claim. Paragraph two may contain one “may/could” need inference and controlled Kivou CTA. It never asserts prospect capability. If a fact cannot fit safely, omit it rather than change its meaning.

## 5. Contracts and fingerprints

### 5.1 `PersonalizationInput` (`personalization-input-v1`)

Canonical PII-minimized input includes:

- input/language/language-policy versions;
- opportunity, signal, supplier, contact refs; state/decision SEND; `prepare_campaign`;
- recorded decision-evaluation ref; decision/proposal fingerprints; company prebuild version/fingerprint;
- current supplier identity and contact role/verification safe state, not identity PII;
- award/event keys, public refs/context fingerprint, bounded contract context, awardee name, selected recency basis/date;
- pinned Need Graph/understanding version, one bounded plausible-need snapshot (or no-need), certainty and evidence;
- company identity/context fields only (name, industry, country, research completeness/gaps), not capability;
- `salutation_mode` and purpose-limited contact-personalization fingerprint, not raw first name in generic audit JSON;
- template/claim-catalog versions, limits, and canonical `personalization_input_fingerprint`.

The input fingerprint covers every copy-affecting fact/configuration: public context, bindings, language, Need snapshot, company/decision profile, salutation state, template/version/limits. It excludes secrets, evaluation/run/correlation IDs, timestamp, email, and raw payload. Existing profile/decision/public-context fingerprints remain distinct.

### 5.2 `PersonalizationArtifact` (`personalization-artifact-v1`)

Durable output has artifact ID/ref; opportunity/supplier/contact refs; language; subject/greeting/body/one CTA; ordered bounded `{claim_id, kind, evidence_refs}`; input/template/action/artifact fingerprints; renderer kind/version; Policy status/disposition; timestamps and policy-evaluation binding.

No raw Need Graph reasoning, raw Apollo/public payload, email, full contact identity, model chain of thought, score, or arbitrary URL is stored. `artifact_fingerprint` is canonical SHA-256 over selected language, rendered content, ordered claim map, input fingerprint, and render profile. It is distinct from Policy action and source-data fingerprints.

## 6. Grounding, safety, validation

`GroundingPacket` is structured internal data, not prose. It carries approved values/claim IDs. Award titles, public text, Apollo descriptions and keywords are untrusted data; they are normalized/bounded and cannot define a claim or alter a template. V1 should avoid Apollo description/keywords entirely absent separately approved controlled use.

If a future LLM is approved, it receives typed JSON after fixed system/developer instruction, with untrusted strings labelled as data. It has no tools/URLs, cannot alter policy/language/schema/budget/next action/evidence, and uses strict structured output. Injection-like strings in public/Apollo data are inert.

The deterministic validator requires:

- exact supported language/bindings; nonempty fields; field/paragraph/claim/ref limits; canonical output fingerprint;
- only renderer-approved claim IDs in deterministic order and allowed refs;
- no email, phone, second recipient, URL, hidden instruction, raw reasoning, or unexpected metadata;
- no new entities/numbers/dates because only enumerated slots are rendered;
- no prohibited certainty templates, exactly one CTA, and no send/compliance/campaign-completion claim.

For future free-form LLM, JSON is insufficient: unprovable extra entity, number/date, URL, certainty claim, language, or assertion outside claim map fails safely to generation failure/review.

## 7. Policy, idempotency, and workflow

### 7.1 Policy recommendation

Use existing `prepare_campaign`; do not add a parallel personalization command. It aligns with `SEND -> prepare_campaign` and is the commercial-mutation authorization for durable campaign-preparation content. Policy action fingerprint binds exact deterministic artifact proposal.

At implementation review, retain risk class/scope and update required evidence to actual inputs:

`FIT_DECISION`, `VERIFIED_CONTACT`, `ACQUISITION_PROSPECT_PREBUILD`, `PERSONALIZATION_INPUT`.

Remove `RECENT_SIGNAL` as independent precondition: SPEC-023 already evaluated timing; stale valid signals are NO_SEND and cannot reach this action. Deterministic v1 uses no budget/provider quota/send controls/compliance. `schedule_campaign` remains later compliance/send-control gate.

If paid LLM later becomes enabled, revisit metadata with supervisor-approved budget/quota/control-plane requirements; Hermes cannot choose arbitrary cost/model.

### 7.2 Idempotency/crash/concurrency

For each new attempt:

1. require SEND + `prepare_campaign`, exact recorded decision/profile/public/supplier/contact bindings, and still provider-verified contact;
2. preflight evaluation ID: existing artifact/evaluation with matching semantics returns durable result without new Policy call;
3. policy evaluation exists but artifact/evaluation absent returns `PersonalizationEvaluationRequiresFreshAttempt`; old approval is never an execution token;
4. build/revalidate input, render/validate proposal, then call Policy Gateway bound to proposal fingerprint;
5. for executable policy, in one final transaction re-read all inputs/public context, rebuild exact input/proposal, require fingerprints unchanged, insert immutable READY artifact, and append `NEXT_ACTION_SET`.

Changed decision/public fact/company profile/contact/language/template/Need Graph/render profile is a new semantic action, not old replay. Final mismatch rolls back artifact/workflow writes and requires fresh evaluation ID.

For non-executable/SHADOW Policy, persist PII-minimized `POLICY_BLOCKED` row with input/proposal/action fingerprints and claim refs but no rendered content; do not mutate state/next action. This gives counterfactual audit without executable content.

### 7.3 State/next action

On successful artifact commit, remain `SEND` and append only `NEXT_ACTION_SET`. Proposed next action: `assess_campaign_compliance`, a future SPEC-025 command name requiring supervisor confirmation. No EventType/state-v2 is required and historical replay remains exact. Leaving `prepare_campaign` after artifact is rejected because re-entry becomes ambiguous. No QUEUED transition, campaign ref, scheduling, or sending occurs.

## 8. Persistence recommendation

Create linear migration `0013_personalization`, down revision `0012_decision_engine`, with one table `acquisition_personalization_artifact`. No generation-run, claim/evidence, score, campaign, or provider table in deterministic v1.

Suggested bounded fields:

- deterministic artifact ID from `personalization-artifact-v1 + policy_evaluation_id`;
- opportunity/supplier/contact refs, policy evaluation ID unique/RESTRICT, recorded decision evaluation ref;
- language/policy version; input/template/action/artifact fingerprints; bounded PII-minimized input snapshot;
- subject/greeting/body/CTA and bounded claim map only for READY;
- renderer kind/version; nullable provider/model identity reserved for separately approved future use;
- policy/counterfactual status, disposition `READY | POLICY_BLOCKED`, timestamps/correlation ID.

Constraints require content for READY and NULL content for POLICY_BLOCKED; unique policy evaluation; bounded JSON/content; immutable rows/dispositions. Event payloads are PII-minimized/size-bounded and Policy/decision records do not own exact message/template/claim provenance, so this one table is the minimum safe persistence model.

A paid LLM needs durable STARTED-before-network, request identity, timeout/retry/token/cost accounting and single-owner semantics. Do not prebuild this complexity: reconsider it in a separately approved revision after provider selection.

## 9. LLM and cost recommendation

V1 external calls: **zero**. Planned generation cost: **zero**. No model, API key, token budget, quota lookup, automatic retry, or budget debit exists.

Future narrow interface:

`PersonalizationComposer.compose(grounding_packet, generation_profile) -> StructuredComposerOutput`

It has bounded data and strict output only, no tools/crawler. Tests use offline fake. Before enabling it, supervisor must approve provider/model/version, data processing/retention, max tokens/single-call timeout/retry, planned/observed cost model, template fallback vs review, durable run design, and Policy budget/quota controls. OpenRouter is a pattern candidate only, not selected.

## 10. TDD and EVAL plan

Required tests:

- entry/actionability: only SEND + prepare_campaign; REVIEW/NO_SEND/wrong/missing binding, unverified contact, unsupported locale/public context fail before Policy/artifact;
- grounding: representative award deterministic; selected recency/evidence preserved; discovered_at never fresh; pinned Need output and no invented need;
- FR/EN: explicit selection, no name/country inference, proper nouns/IDs/numbers unchanged, neutral greeting, no gender/honorific;
- truth: award preserved; need plausible; no purchase/sourcing claim; LIMITED research cannot invent capability; no dates/numbers/entities/URLs introduced;
- PII: no body email and no generic event/Policy PII; only purpose-limited first-name text in READY artifact;
- validator: missing/empty/oversized/unknown claims, excess refs/paragraphs, unsupported language, URL, extra recipient, certainty claim, fingerprint mismatch, and injection-like source text fail closed;
- Policy: exact action binding; actor/scope/evidence conflicts; atomic READY artifact + NEXT_ACTION_SET; SHADOW POLICY_BLOCKED has no content/state/event;
- idempotency/concurrency: exact replay no new Policy; policy-without-artifact fresh ID; semantic changes new identity; concurrent creation one artifact; final input change rolls back;
- state/replay: no EventType; state stays SEND; historical replay unchanged;
- architecture: no Instantly/SMTP/Apollo/LLM/crawler/Stripe/customer TargetICP/billing/feedback/materialized ownership/hidden reasoning.

For later LLM enablement add offline fake tests for malformed JSON, timeout/rate-limit/refusal, schema violation, STARTED ownership, one call, crash before/after response, bounded retry and cost accounting.

Supervisor-reviewable invariant corpus (not exact “gold” wording): CH/French fresh award/strong identity; French LIMITED research; explicit English; age-60 SEND edge; publication fallback; generic prospect; no first name; long title; low-certainty need; and adversarial injection text. Evaluate factual correctness, inference calibration, grounded relevance, language quality, concision, no fake familiarity/certainty, and CTA quality. Do not tune prompts/thresholds against it.

## 11. Non-goals

No compliance/lawful-basis/opt-out/mailbox/send-window logic; no campaign, Instantly, SMTP, Apollo, web crawler, web research, LLM call, contact enrichment, Need Graph tuning, customer TargetICP/matching, billing/entitlement/Stripe, fit score, probability, or delivery. SPEC-023’s 60-day decision contract is unchanged. SEND means commercial eligibility only, never permission or legal authorization to email.

## 12. Recommended implementation sequence

1. Freeze language policy, FR/EN claim/CTA catalog, template version, and future compliance next-action name.
2. TDD pure contracts, grounding, renderer, and validator.
3. Add input builder using shared public resolver and pinned public-only Need derivation; prove customer boundary.
4. Add one 0013 artifact migration/store and idempotency/Shadow/atomic-next-action tests.
5. Integrate approved `prepare_campaign` evidence contract; prove replay/no external I/O.
6. Run corpus/full offline regression. Paid LLM remains separate approval.

## 13. Supervisor decisions required

1. Approve deterministic-template v1 with no live LLM, or authorize a named provider/model/data/cost/run design.
2. Approve future SPEC-025 next-action name `assess_campaign_compliance`, or specify canonical alternative.
3. Approve exact FR/EN claim/CTA catalog and whether a no-need case may use minimal public-award copy or must route to human review.
4. Approve retention/access posture for artifact text containing optional first name; detailed compliance remains SPEC-025.
5. Confirm one-table 0013 shape and `prepare_campaign` evidence-metadata correction.

## 14. Conclusions

- **Personalization:** grounded public award + optional calibrated need + company identity + optional safe first-name greeting.
- **No false claims:** never purchase, sourcing process, prospect capability, or email authorization.
- **No LLM yet:** deterministic templates are safer for current bounded evidence.
- **Evidence:** public resolver and controlled catalog supply facts; each claim has durable refs.
- **PII:** only rendered first-name text lives in purpose-specific artifact storage.
- **Workflow:** successful artifact stays SEND and moves by `NEXT_ACTION_SET` to future compliance.
- **Migration:** one immutable artifact table is the minimum safe record for later campaign creation.

