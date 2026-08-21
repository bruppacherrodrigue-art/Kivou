# SPEC-025 — Compliance CH / FR / EU — design

**Status:** design only; implementation requires supervisor and legal-policy freeze.

**Audited base:** `f7ee297bf0e873fc5bbf02f296072e81f2a1de4f` (merged SPEC-024)

**Audited on:** 2026-08-21

**Alembic head:** `0013_personalization`

## Scope and non-goals

SPEC-025 assesses only business-to-business commercial email directed from the
internal Kivou Acquisition Engine. It turns the current handoff

```text
SEND + READY personalization artifact + assess_campaign_compliance
```

into a durable, bounded compliance assessment for the later campaign factory.
It does not send mail, create or schedule a campaign, call Instantly, Apollo,
an LLM, SMTP, a crawler, or any external provider. It does not cover consumer
marketing, SMS, WhatsApp, LinkedIn, telephone, post, cookies, newsletters, or
customer-owned data.

`SEND` remains a commercial-eligibility result, not legal permission to contact.
An `ALLOWED` compliance assessment is similarly not a send instruction: SPEC-026
must perform its own live schedule/send controls and fresh compliance check.

## Current implementation audited

The following are the actual contracts on the audited main, rather than roadmap
assumptions:

| Area | Current contract | SPEC-025 consequence |
| --- | --- | --- |
| `signals.personalization` | A durable `READY` or `POLICY_BLOCKED` artifact is tied to the opportunity, supplier, contact, SPEC-023 decision evaluation, policy evaluation, deterministic input/proposal/artifact fingerprints, and PII-minimized snapshot/claim map. Only `READY` contains rendered copy. | A compliance input must bind the exact `READY` artifact fingerprint; generic compliance audit must not duplicate rendered copy. |
| `signals.acquisition.state` | `acquisition-state-v1` already accepts `NEXT_ACTION_SET` values from `ALLOWED_NEXT_ACTIONS`. A successful personalization keeps `state=SEND` and changes its next action to `assess_campaign_compliance`. | No state-machine v2 or event type is required. |
| `signals.supervisor.registry` | `assess_campaign_compliance` is currently a reserved next action only: it is in `ALLOWED_NEXT_ACTIONS`, not `ALLOWED_COMMANDS`. | SPEC-025 promotes it to a real command only when its CommandPolicy is implemented. |
| `signals.policy` | `ComplianceAssessment` already carries `ALLOWED`, `BLOCKED`, `REVIEW_REQUIRED`, or `UNKNOWN`, an assessment version, observed time, and optional validity time. The evaluator blocks `BLOCKED` and `UNKNOWN`, requires `COMPLIANCE_REVIEW` approval for `REVIEW_REQUIRED`, and otherwise permits `ALLOWED` through other gates. | SPEC-025 supplies the durable, Kivou-owned assessment behind that generic policy contract. |
| Policy registry | `schedule_campaign` is an OPPORTUNITY-scoped `COMMERCIAL_MUTATION` and already has `requires_compliance=True`; its legacy evidence tuple is `VERIFIED_CONTACT`, `FIT_DECISION`, `RECENT_SIGNAL`. `prepare_campaign` already uses the newer acquisition evidence vocabulary. | SPEC-025 must not alter scheduling or send behavior. Before SPEC-026, its legacy scheduling claims need an additive, reviewed migration to exact Kivou-generated acquisition/personalization/compliance evidence; `RECENT_SIGNAL` cannot substitute for a current assessment. |
| Supplier/contact/company research | Current facts include supplier identity and provider organization ID, contact supplier binding and provider-verification status, and a bounded Apollo organization profile (including provider country when supplied). They do not prove consent, a notice given by the source, a country of legal targeting, a sender identity, or an opt-out mechanism. | A verified Apollo business email is not, by itself, a compliance basis or an automatic `ALLOWED` result. |
| Persistence | `0013_personalization` adds only `acquisition_personalization_artifact`; no compliance or suppression store exists. | A durable assessment and a durable cross-attempt suppression record are both required before an executable compliance engine exists. |

Inspected code/tests include `signals/personalization`, `signals/acquisition`,
`signals/contact_discovery`, `signals/company_research`,
`signals/supplier_discovery`, `signals/policy/{contracts,evaluator,gateway,registry}`,
`signals/supervisor/registry`, `signals/persistence/schema`, migrations through
`0013_personalization`, and policy/personalization/state/migration tests.

## Legal-source matrix — facts, product policy, and open legal work

This design is not legal advice and does not translate incomplete source facts
into a universal permission rule. Sources were consulted on 2026-08-21. “Product
policy” below is a conservative Kivou choice, not a statement of law.

| Jurisdiction | Primary source / status | Authoritative operational fact | Kivou technical implication | Classification |
| --- | --- | --- | --- | --- |
| Switzerland | [FDPIC/EDÖB — advertising and marketing](https://www.edoeb.admin.ch/de/werbung-marketing), current regulator guidance | The regulator describes commercial email acquisition as personal-data processing and points to the Unfair Competition Act requirements for mass advertising: consent, correct sender identity, and a simple/free opt-out, subject to the stated customer exception. | A cold provider-verified contact alone cannot establish an automatic CH allow; identity and opt-out must be proven at the future campaign envelope. | Regulator guidance describing law; implementation policy remains to be frozen. |
| Switzerland | [Federal Office of Communications — UWG Art. 3(o)](https://www.bakom.admin.ch/de/rechtstexte), official federal explanatory page | The official page describes the anti-spam conditions and the narrow existing-customer/similar-offering exception. | A CH ruleset may emit `ALLOWED` only for a legally reviewed, evidentially complete predicate. Current acquisition data does not provide that proof. | Legal provision as explained by federal authority. |
| Switzerland | [FDPIC/EDÖB — information duty](https://www.edoeb.admin.ch/de/informationspflicht) | Processing must be transparent; data collected from elsewhere requires the applicable information analysis. | Source/provenance and notice evidence need a bounded durable representation; unknown provenance must not default to `ALLOWED`. | Regulator guidance. |
| France | [CPCE Article L34-5 — Légifrance](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000042155961/), in force since 2020-07-26 | The article addresses electronic direct marketing, consent/customer exception, and valid contact details for objections in all cases. | The design must prove the final sender/objection mechanism; the personalization artifact alone cannot establish it. | Law. |
| France | [CNIL — electronic communications prospecting](https://www.cnil.fr/fr/communication-electronique-quelles-regles), updated 2026-06-10 | CNIL states that B2B commercial email can be considered without prior consent when it relates to professional activity, with source/purpose information and an easy objection mechanism. | FR can be ruleset-configured only once legal validation defines the evidence predicate for professional relevance, source notice, sender identity, and objection path. | Regulator guidance. |
| France | [CNIL — suppression list and objections](https://www.cnil.fr/fr/comment-utiliser-une-liste-repoussoir-pour-respecter-lopposition-la-prospection-commerciale) | An objection to direct marketing is free and must be respected; a purpose-limited suppression list is an appropriate mechanism. | A Kivou suppression hit is a non-overridable hard boundary. | Regulator guidance. |
| European Union | [ePrivacy Directive 2002/58/EC, Article 13 — EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32002L0058), current consolidated source | Article 13 sets electronic-marketing rules, an existing-customer exception, and leaves treatment of legal-person electronic mail to Member State law. | “EU” cannot be a single automatic allow rule. Non-FR EU countries require a reviewed Member-State ruleset; otherwise they are not `ALLOWED`. | EU law requiring national implementation analysis. |
| European Union | [GDPR — Regulation (EU) 2016/679 — EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj) | GDPR includes bases for processing, information obligations where data were not obtained from the subject, and the direct-marketing objection right. | The implementation must version source/provenance and objection handling, but counsel must freeze applicable territorial/basis predicates. | EU law; exact national ePrivacy interaction remains open. |

### Deliberately unfrozen legal decisions

1. The legally relevant jurisdictional connecting factor(s): recipient location,
   employer establishment, controller/sender establishment, and any channel
   specific rule must be confirmed by counsel for each supported country.
2. The exact evidence required to treat a CH contact as consented or inside an
   existing-customer exception, and whether absence of such proof is `BLOCKED`
   or `REVIEW_REQUIRED` under Kivou policy.
3. The precise French B2B professional-relevance, source-notice, purpose, and
   objection predicate for Kivou’s data provenance and final email envelope.
4. A country-by-country EU ruleset inventory and review process. `EU_OTHER` is
   not a legal rule; it is an explicit unsupported jurisdiction until added.
5. Retention periods, access controls, and lawful handling of suppression HMACs,
   including secret rotation and a response to a deletion request that must not
   accidentally re-enable marketing.
6. The identity and information/opt-out content of the future Kivou sender and
   campaign footer. SPEC-024’s frozen copy intentionally does not contain it.

Until those decisions are frozen, a production ruleset must fail closed and must
not issue automatic legal `ALLOWED` outcomes for evidence it cannot prove.

## Deterministic jurisdiction resolution

Introduce a pure, versioned resolver, `compliance-jurisdiction-v1`. It consumes
only durable, normalized company/contact jurisdiction evidence and returns both
the selected jurisdiction and an evidence status.

1. Start with a validated, canonical ISO 3166-1 alpha-2 business-country fact
   from a durable prospect/company record. An unnormalised Apollo country string
   is evidence to normalize, not a jurisdiction result by itself.
2. If independent durable country facts conflict, return `UNRESOLVED` rather
   than selecting a convenient one.
3. `CH` and `FR` are selected only from an unambiguous canonical fact. Other
   EU Member States are identified only when an explicit maintained member-state
   table recognizes the code; they still need a configured country ruleset.
4. A country outside scope, no authoritative country, or a conflict is never
   inferred from language, email TLD, company name, or first name.

The v1 result categories are `CH`, `FR`, `EU_MEMBER_STATE_CONFIGURED`,
`EU_MEMBER_STATE_UNCONFIGURED`, `OUT_OF_SCOPE`, and `UNRESOLVED`. Their mapping
is conservative: unconfigured EU is `REVIEW_REQUIRED`; unresolved or out of
scope is `UNKNOWN`. Neither becomes `ALLOWED` by default.

## Compliance contracts and rule matrix

### Input

`ComplianceInput` is an immutable `acquisition-compliance-input-v1` contract.
It is constructed inside Kivou, never supplied as an arbitrary Hermes object,
and is fingerprinted using canonical SHA-256. It contains only the following
safe fields:

- opportunity, supplier, contact, and `READY` personalization-artifact refs;
- artifact/input/proposal/action fingerprints, selected language, template and
  catalog versions (not rendered subject/body/greeting/CTA);
- current supplier/contact bindings, provider-verification status, and a
  PII-minimized contact identity/provenance fingerprint;
- jurisdiction resolution result, its normalized evidence refs, and resolver
  version; no TLD/name/language inference inputs;
- business-contact classification and email-provenance classification/version;
- sender-compliance configuration identity/version and declared capabilities
  (sender identity, valid objection route, and required notices), never secrets;
- acquisition purpose, exact public-signal and personalization evidence refs;
- active suppression/objection match status and the opaque matching-key version;
- ruleset version/config fingerprint, Kivou-owned `assessed_at` and UTC
  `as_of_date`, optional validity time, and `input_fingerprint`.

The service reads the contact email only in the narrow suppression matcher where
necessary to derive an opaque keyed identity; email, name, raw provider data,
and rendered copy are excluded from the input snapshot, policy arguments,
generic events, and reason/evidence fields.

### Ruleset and result

`acquisition-compliance-ruleset-v1` is callable-free, jurisdiction-specific,
and includes a legal-review identifier/effective interval, required evidence
predicates, sender-capability requirements, and a canonical config fingerprint.
It has no numeric score and no LLM.

The pure result, `ComplianceProposal`, emits exactly one of the existing
`ComplianceState` values with ordered, bounded reason codes (maximum eight) and
bounded evidence refs (maximum sixteen):

| Ordered condition | Result | Illustrative bounded reason family |
| --- | --- | --- |
| Exact active suppression, unsubscribe, or objection match | `BLOCKED` | `SUPPRESSION_MATCH`, `PRIOR_OBJECTION` |
| Artifact/binding/contact/prebuild integrity is missing before a valid input exists | typed pre-policy failure | `PersonalizationNotReady` / binding failure, not a legal review result |
| Jurisdiction cannot be resolved or is outside reviewed scope | `UNKNOWN` | `JURISDICTION_UNRESOLVED`, `JURISDICTION_OUT_OF_SCOPE` |
| Jurisdiction is known but its reviewed country rule is absent, or required source/business/sender/objection evidence is inconclusive | `REVIEW_REQUIRED` | `COUNTRY_RULESET_UNCONFIGURED`, `BUSINESS_CONTEXT_INSUFFICIENT`, `LEGAL_BASIS_UNRESOLVED`, `REQUIRED_SENDER_IDENTITY_MISSING`, `REQUIRED_OPT_OUT_MECHANISM_MISSING` |
| All reviewed jurisdiction-specific predicates and hard Kivou safeguards hold | `ALLOWED` | `JURISDICTION_RULESET_SATISFIED`, `BUSINESS_CONTEXT_VERIFIED`, `SENDER_AND_OBJECTION_MECHANISM_VERIFIED` |

The labels above are design direction; final symbols must follow existing
bounded-code conventions and be frozen with counsel-approved ruleset data. A
known suppression can never be moved to `ALLOWED` by an approval, Hermes,
Instantly configuration, or another policy gate. A human may resolve evidence
ambiguity behind `REVIEW_REQUIRED`, but cannot override a hard `BLOCKED` result.

## Suppression and objection: a separate hard-boundary record

One assessment table alone is not sufficient. An assessment is scoped to an
artifact/attempt and cannot reliably stop a later contact reference, refreshed
artifact, or campaign from targeting the same email. The minimum safe migration
recommendation is **`0014_compliance` with two tables**, not a speculative table
explosion:

1. `acquisition_contact_suppression` — durable, append-only, queryable hard
   boundary; and
2. `acquisition_compliance_assessment` — immutable proposal/policy/workflow
   audit tied to one assessment attempt.

`acquisition_contact_suppression` uses an opaque, domain-separated keyed HMAC
of normalized business email plus `identity_key_version`; no raw email is stored
there. The email is read only transiently in the matcher. Its primary scope is
`KIVOU_ACQUISITION_EMAIL`, so duplicate contact rows with the same normalized
email converge. `contact_ref` and supplier refs are optional provenance links,
not the only matching identity. The table records source (`UNSUBSCRIBE`,
`RECIPIENT_OBJECTION`, `MANUAL_VERIFIED`, `SYSTEM_IMPORT`), reason code,
received/effective time, immutable evidence ref, lifecycle/supersession fields,
and key version. Domain/company-wide suppression is never inferred; it requires
an explicit, separately evidenced instruction and a counsel-approved scope.

Ambiguous identity (unusable email, HMAC-key version unavailable, conflicting
suppression scope) fails closed: it produces `UNKNOWN`/`REVIEW_REQUIRED`, never
an automatic allow. Retention and HMAC rotation are the legal-policy questions
listed above; implementation must never delete an active objection in a way that
reactivates outreach.

`acquisition_compliance_assessment` is the sole assessment artifact. Proposed
bounded fields are: deterministic `compliance_assessment_id` derived from
`policy_evaluation_id`; opportunity/artifact/supplier/contact refs; jurisdiction
and resolver version; ruleset version/config fingerprint; input version and
fingerprint; state; reason codes and evidence refs; optional `valid_until`;
policy evaluation/status/counterfactual status; expected post-policy stream
version; disposition (`RECORDED` or `POLICY_BLOCKED`); optional recorded
`NEXT_ACTION_SET` event ref; and `created_at`. It stores neither rendered copy,
raw email/name, raw Apollo data, hidden legal reasoning, nor a model/provider
field. Constraints require an event for `RECORDED`, none for `POLICY_BLOCKED`,
and valid state/next-action pairs.

## Policy, workflow, and state-machine design

SPEC-025 promotes `assess_campaign_compliance` from reservation to real command:
`ALLOWED_COMMANDS` gains it and `COMMAND_POLICIES` gains exactly the same key,
preserving `set(COMMAND_POLICIES) == set(ALLOWED_COMMANDS)`. Then
`ALLOWED_NEXT_ACTIONS` can derive from `ALLOWED_COMMANDS`; the reservation-only
exception disappears. This promotion is future implementation work only.

Recommended `CommandPolicy`:

```text
command: assess_campaign_compliance
risk_class: PREPARATORY
target_scope: OPPORTUNITY
required_evidence:
  ACQUISITION_DECISION
  PUBLIC_EVIDENCE
  VERIFIED_CONTACT
  ACQUISITION_PROSPECT_PREBUILD
  PERSONALIZATION_ARTIFACT
  COMPLIANCE_INPUT
uses_budget / uses_volume / uses_provider_quota / uses_send_controls: false
requires_control_plane: false
requires_compliance: false
```

`requires_compliance=false` avoids circularly requiring the assessment that the
command creates. The command makes no external mutation and is preparatory; its
result does not bypass the later `schedule_campaign` policy or compliance gate.
Every claim is constructed by Kivou and action fingerprint binds the exact
`ComplianceProposal`, not caller assertions such as `RECENT_SIGNAL`.

For an executable result, append the existing `NEXT_ACTION_SET` in the same
transaction as the assessment; no `EventType` and no state-machine version
change are necessary. The state stays `SEND` in all four outcomes:

| Assessment | State | next_action | Meaning |
| --- | --- | --- | --- |
| `ALLOWED` | `SEND` | `schedule_campaign` | Compliant current assessment exists; SPEC-026 still owns scheduling/send checks. |
| `REVIEW_REQUIRED` | `SEND` | `request_human_review` | Valid facts, but bounded legal/product uncertainty requires an approved human resolution. |
| `BLOCKED` | `SEND` | `NULL` | A hard no-contact boundary; do not misuse commercial `NO_SEND`, which has a different historical meaning. |
| `UNKNOWN` | `SEND` | `request_human_review` | Not enough authoritative information to permit campaign handoff; implementation must fail closed. |

The supervisor must freeze whether `UNKNOWN` should instead set `NULL` for
unresolvable cases. This report recommends `request_human_review` so a durable
data-resolution path exists, while the state remains non-schedulable.

### Shadow and assisted operation

In SHADOW or any non-executable policy result, persist only a
`POLICY_BLOCKED` PII-minimized assessment proposal. Do not write
`NEXT_ACTION_SET`; therefore no campaign action is unlocked. In ASSISTED mode,
the normal Policy approval flow governs whether the assessment workflow mutation
may be recorded. A compliance-review approval is only relevant for a bounded
`REVIEW_REQUIRED` case and cannot override a suppression-derived `BLOCKED`.

## Idempotency, revalidation, and atomicity

Every assessment gets four distinct SHA-256 identities:

1. `compliance_ruleset_config_fingerprint` — reviewed deterministic rules;
2. `compliance_input_fingerprint` — current factual input including artifact,
   jurisdiction, suppression status, sender configuration, as-of date, and
   ruleset identity;
3. `compliance_proposal_fingerprint` — input plus state/reasons/evidence/next
   action/validity; and
4. `PolicyRequest.action_fingerprint` — command, opportunity bindings, and the
   exact proposal fingerprint.

For a genuinely new attempt, service captures its timezone-aware Kivou clock
once, reads current facts, constructs/evaluates the pure proposal, and submits
the exact action to Policy Gateway. A durable assessment found first by policy
evaluation ID is an exact replay only when request/actor/actor-ref/scope/evidence
and historical policy semantics match. Historical budget usage is reconstructed
from the persisted PolicyDecision plus immutable control snapshot, not caller-
current BudgetUsage. A changed artifact, contact identity, jurisdiction,
suppression state, sender configuration, as-of date, or ruleset version needs a
new evaluation ID and a fresh assessment.

If a policy evaluation exists but its assessment is absent, raise a typed
`ComplianceEvaluationRequiresFreshAttempt`; never reuse an old approval. For an
executable policy result, one caller-owned transaction locks/reloads the
opportunity, requires its exact post-policy stream version and
`SEND/assess_campaign_compliance`, reloads the `READY` artifact and durable
bindings, matches suppression, resolves jurisdiction, rebuilds input/proposal
with the same captured as-of date/ruleset, and compares both fingerprints. It
then appends `NEXT_ACTION_SET`, inserts one `RECORDED` assessment bound to that
event, and commits. Any material post-policy change raises
`ComplianceInputChanged`; no stale assessment or next-action event survives.

Concurrent equal attempts converge through deterministic assessment identity and
insert-if-absent semantics. A semantic mismatch produces a typed idempotency
conflict, never an exposed database integrity error or last-write-wins result.

An `ALLOWED` assessment is time-bounded, not permanent. At the SPEC-026 schedule
boundary, scheduling must require a currently valid assessment and rerun the
suppression/objection, contact identity, artifact binding, jurisdiction, ruleset
and expiry checks. A later opt-out, ruleset change/expiry, contact change, or
suppression hit blocks scheduling even if an older assessment was ALLOWED.

## Privacy and architecture boundaries

The compliance package may depend on durable acquisition, personalization,
policy, supervisor, and contact/suppression primitives only. It must not import
or call Instantly, SMTP, Apollo/network clients, an LLM/OpenRouter, crawler,
Stripe/billing, TargetICP, customer MatchingEngine, customer feedback, or
materialized customer-signal ownership. There are no external calls during the
assessment. Generic event, Policy, and assessment JSON remain PII-minimized;
the email remains in the contact store and is transiently HMACed only for
suppression matching.

## TDD and offline evaluation plan

Before implementation, add failing deterministic tests for:

- actionability: only `SEND + assess_campaign_compliance` with a correctly bound
  `READY` artifact, current verified contact, supported profile and durable
  decision; all other states/binding failures are typed pre-policy failures;
- resolver: CH, FR, configured EU member state, unconfigured EU member state,
  conflicting/no country; prove language/TLD/name never establish jurisdiction;
- rules: counsel-approved CH/FR candidates, unresolved jurisdiction, unverified
  contact, insufficient business context, missing sender identity/opt-out,
  personalization mismatch, each bounded reason ordering, and no score;
- suppression: unsubscribe, explicit objection, duplicate-email/new-contact
  convergence, ambiguous identity failure closed, hard BLOCKED cannot be human
  overridden, and a post-assessment opt-out blocks future scheduling;
- policy: exact proposal action fingerprint, required Kivou evidence, no circular
  compliance gate for assessment, SHADOW audit/no action, ASSISTED review
  approval, and stale caller evidence cannot substitute current input;
- replay/crash/concurrency: exact replay with historical budget reconstruction,
  changed actor/scope/evidence/ruleset/artifact conflicts, policy-without-
  assessment fresh attempt, same-evaluation race convergence, and changed
  suppression race with no stale ALLOWED action;
- TOCTOU: after-policy drift in artifact, supplier/contact binding, jurisdiction,
  sender configuration, suppression, and ruleset yields `ComplianceInputChanged`
  and rolls back assessment plus action together;
- migration: fresh DB, `0013 -> 0014`, PostgreSQL offline SQL, constraints,
  downgrade, and one linear Alembic head; and
- architecture: zero provider/network/LLM/customer/billing dependencies and no
  raw email/rendered artifact payload in generic audit structures.

The supervisor-reviewable offline EVAL corpus uses synthetic, non-personal test
fixtures: CH consent/evidence-complete candidate; CH missing proof; FR
professionally relevant candidate with and without source/objection evidence;
EU configured and unconfigured countries; unresolved country; contact
unverified; suppression and later objection; changed artifact/contact/ruleset;
SHADOW; and concurrent suppression. It evaluates deterministic invariants,
reason codes, provenance, and workflow safety—not a legal-confidence score or
copy quality.

## Recommended implementation sequence

1. Obtain counsel/supervisor freeze for the legal matrix, scope connecting
   factors, sender profile, opt-out route, ruleset predicates, and unknown
   workflow choice.
2. Add the two-table linear `0014_compliance` migration and bounded contracts.
3. Implement pure jurisdiction, suppression matching, and ruleset evaluation
   TDD-first with the offline EVAL corpus.
4. Promote the reserved command and implement Policy metadata/replay semantics.
5. Add the atomic assessment service, TOCTOU checks, state handoff, full
   migration/concurrency/architecture regression, then open a separate draft PR.

## Design verdict and open supervisor decisions

The architecture is ready for supervisor/legal review, but implementation must
not begin until the six legal/product decisions listed above are frozen. The
recommended topology is `0013_personalization -> 0014_compliance`, with exactly
two justified tables: one cross-attempt suppression boundary and one immutable
assessment audit. No runtime, schema, migration, test, or deployment change is
part of this design PR.
