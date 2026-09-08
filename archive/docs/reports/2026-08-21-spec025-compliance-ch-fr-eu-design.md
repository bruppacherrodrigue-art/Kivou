# SPEC-025 — Compliance CH / FR / EU — design

**Status:** design only; R1 freezes the Kivou product policy. Implementation
still requires a separately authorized implementation task and the remaining
external legal review described below.

**Audited base:** `f7ee297bf0e873fc5bbf02f296072e81f2a1de4f` (merged SPEC-024)

**Audited on:** 2026-08-21

**Alembic head:** `0013_personalization`

### Design R1 closeout record

The original design-only CI run `32469667785` was frontend-successful but
backend-failed with **3372 passed / 1 failed**:
`tests/test_personalization_service.py::test_concurrent_same_evaluation_converges_to_one_artifact_and_next_action`,
raising `OpportunityConcurrencyConflict`. This PR changes only this report, so
it is not a SPEC-025 runtime regression. The failed backend job is rerun without
any runtime or test modification. The rerun completed **SUCCESS** on the same
run (`32469667785`): backend **3373 passed** and Ruff passed; the previously
successful frontend job remained green. The different result establishes the
failure as an unrelated existing concurrency-test flake; no SPEC-024 runtime or
test change was made from this design PR.

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
| Switzerland | [FDPIC/EDÖB — advertising and marketing](https://www.edoeb.admin.ch/de/werbung-marketing), supervisor-verified regulator guidance | The regulator describes commercial email acquisition as personal-data processing and points to the Unfair Competition Act requirements for mass advertising: consent, correct sender identity, and a simple/free opt-out, subject to the stated customer exception. | The R1 product policy below treats a cold provider-verified contact as insufficient for automatic CH allow. | Regulator guidance describing law; Kivou’s predicate is conservative product policy. |
| Switzerland | [Federal Office of Communications — UWG Art. 3(o)](https://www.bakom.admin.ch/de/rechtstexte), official federal explanatory page | The official page describes the anti-spam conditions and the narrow existing-customer/similar-offering exception. | A CH ruleset may emit `ALLOWED` only for a legally reviewed, evidentially complete predicate. Current acquisition data does not provide that proof. | Legal provision as explained by federal authority. |
| Switzerland | [FDPIC/EDÖB — information duty](https://www.edoeb.admin.ch/de/informationspflicht) | Processing must be transparent; data collected from elsewhere requires the applicable information analysis. | Source/provenance and notice evidence need a bounded durable representation; unknown provenance must not default to `ALLOWED`. | Regulator guidance. |
| France | [CPCE Article L34-5 — Légifrance](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000042155961/), in force since 2020-07-26 | The article addresses electronic direct marketing, consent/customer exception, and valid contact details for objections in all cases. | The design must prove the final sender/objection mechanism; the personalization artifact alone cannot establish it. | Law. |
| France | [CNIL — electronic communications prospecting](https://www.cnil.fr/fr/communication-electronique-quelles-regles), 2026-06-10 supervisor-verified guidance | CNIL states that B2B commercial email can be considered without prior consent when it relates to professional activity, with source/purpose information and an easy objection mechanism. | The R1 product policy below requires a bounded deterministic proof of each listed predicate before automatic FR allow. | Regulator guidance. |
| France | [CNIL — suppression list and objections](https://www.cnil.fr/fr/comment-utiliser-une-liste-repoussoir-pour-respecter-lopposition-la-prospection-commerciale) | An objection to direct marketing is free and must be respected; a purpose-limited suppression list is an appropriate mechanism. | A Kivou suppression hit is a non-overridable hard boundary. | Regulator guidance. |
| European Union | [ePrivacy Directive 2002/58/EC, Article 13 — EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32002L0058), current consolidated source | Article 13 sets electronic-marketing rules, an existing-customer exception, and leaves treatment of legal-person electronic mail to Member State law. | “EU” cannot be a single automatic allow rule. Non-FR EU countries require a reviewed Member-State ruleset; otherwise they are not `ALLOWED`. | EU law requiring national implementation analysis. |
| European Union | [GDPR — Regulation (EU) 2016/679 — EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj), Articles 14 and 21 | GDPR includes information obligations where data were not obtained from the subject and the direct-marketing objection right. | The implementation versions source/provenance and objection handling; country-specific ePrivacy predicates remain independently reviewed. | EU law; exact national ePrivacy interaction remains open. |

### R1-frozen Kivou product policies

These are conservative Kivou routing and product controls, not a declaration
that a single company-country field decides every conflict-of-laws question.

- The durable recipient-employer/business country is the primary routing fact.
  Kivou also always applies its global sender, privacy, and suppression
  safeguards in addition to the selected destination ruleset.
- Language, TLD, company/first name, and inferred nationality are forbidden
  jurisdiction inputs. Conflicting or unavailable durable country facts fail
  closed.
- CH routes to CH; FR routes to FR; another EU Member State routes only to its
  explicit reviewed national ruleset. An unconfigured EU Member State is
  `REVIEW_REQUIRED`. France is never inherited merely because French is used;
  Belgium and Luxembourg are non-automatic until their own rulesets are frozen.
- A known country outside Kivou’s supported acquisition perimeter is a terminal
  product `BLOCKED` outcome. An unresolved/conflicting country is `UNKNOWN` and
  only reaches human data-resolution review when the missing fact can plausibly
  be corrected.

**CH MVP.** Kivou treats its automated acquisition email as subject to the
Swiss opt-in/existing-customer safeguards described by EDÖB/BAKOM. Automatic
`ALLOWED` requires durable proof of either explicit prior marketing consent, or
the reviewed existing-customer predicate (prior sale/service, Kivou’s own
similar product/service, and the required objection opportunity). In every
case, correct sender identity capability, simple/free opt-out capability, no
active suppression/objection, and current contact/binding/artifact integrity are
required. A normal provider-verified cold Apollo contact with neither predicate
is not automatically allowed. Missing but potentially obtainable evidence is
`REVIEW_REQUIRED`; when review proves no qualifying predicate, the new
assessment is `BLOCKED`. Approval cannot waive this predicate.

**FR MVP.** Automatic `ALLOWED` requires all of: a verified professional/business
contact; solicitation purpose demonstrably related to a bounded professional
role/activity predicate; known-enough source/provenance classification for the
first-contact information route; configured sender identity; simple/free
objection route; configured privacy/information route; no suppression or prior
objection; and current artifact/contact/jurisdiction/ruleset bindings. SPEC-025
checks readiness/capability and provenance only. SPEC-026 must revalidate the
actual final envelope before scheduling/sending. No arbitrary semantic
similarity and no LLM legal judgement are permitted.

### Remaining external legal questions

The remaining questions do not block a fail-closed CH/FR MVP: future BE/LU and
other Member-State ruleset content; a later legal opinion changing Kivou’s
conservative CH treatment; exact production privacy/footer wording after counsel
review; and exceptional suppression deletion requests/key-retirement cases.

## Deterministic jurisdiction resolution

Introduce a pure, versioned resolver, `compliance-jurisdiction-v1`. It consumes
only durable, normalized company/contact jurisdiction evidence and returns both
the selected jurisdiction and an evidence status.

1. Start with the durable recipient-employer/business-country fact, normalized
   to canonical ISO 3166-1 alpha-2. This is Kivou’s product routing fact, not a
   definitive statement of conflict-of-laws doctrine. An unnormalised Apollo
   country string is evidence to normalize, not a jurisdiction result by itself.
2. If independent durable country facts conflict, return `UNRESOLVED` rather
   than selecting a convenient one.
3. `CH` and `FR` are selected only from an unambiguous canonical fact. Other
   EU Member States are identified only when an explicit maintained member-state
   table recognizes the code; they still need a configured country ruleset.
4. A country outside scope, no authoritative country, or a conflict is never
   inferred from language, email TLD, company name, or first name.

The v1 result categories are `CH`, `FR`, `EU_MEMBER_STATE_CONFIGURED`,
`EU_MEMBER_STATE_UNCONFIGURED`, `OUT_OF_SCOPE`, and `UNRESOLVED`. Their mapping
is frozen: unconfigured EU is `REVIEW_REQUIRED`, `OUT_OF_SCOPE` is terminal
product `BLOCKED`, and `UNRESOLVED` is `UNKNOWN`. None becomes `ALLOWED` by
default.

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
| Jurisdiction cannot be resolved from durable facts | `UNKNOWN` | `JURISDICTION_UNRESOLVED` |
| Known country is outside Kivou’s supported acquisition perimeter | `BLOCKED` | `JURISDICTION_OUT_OF_SCOPE` |
| Jurisdiction is known but its reviewed country rule is absent, or required source/business/sender/objection evidence is inconclusive | `REVIEW_REQUIRED` | `COUNTRY_RULESET_UNCONFIGURED`, `BUSINESS_CONTEXT_INSUFFICIENT`, `LEGAL_BASIS_UNRESOLVED`, `REQUIRED_SENDER_IDENTITY_MISSING`, `REQUIRED_OPT_OUT_MECHANISM_MISSING` |
| All reviewed jurisdiction-specific predicates and hard Kivou safeguards hold | `ALLOWED` | `JURISDICTION_RULESET_SATISFIED`, `BUSINESS_CONTEXT_VERIFIED`, `SENDER_AND_OBJECTION_MECHANISM_VERIFIED` |

The labels above are design direction; final symbols must follow existing
bounded-code conventions and be frozen with counsel-approved ruleset data. A
known suppression can never be moved to `ALLOWED` by an approval, Hermes,
Instantly configuration, or another policy gate. A human may resolve evidence
ambiguity behind `REVIEW_REQUIRED`, but cannot override a hard `BLOCKED` result.

R1 refines the table’s jurisdiction row: `OUT_OF_SCOPE` is the terminal product
`BLOCKED` result, while only unavailable/conflicting routing facts are
`UNKNOWN`. The CH and FR predicates in the R1-frozen policy section are exact
v1 product requirements; no reviewer may substitute a subjective similarity or
model judgement for their bounded facts.

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

The R1 retention policy is frozen: keep suppression only for suppression
purpose, for a **minimum of three years**; never automatically reactivate a
contact at expiry; and require an explicit privacy/compliance process for
deletion or supersession after that minimum. A deletion request must not
accidentally re-enable marketing. An active recipient objection is always a
hard block. Identity-key rotation is also frozen: the matcher supports active
and retained historical `identity_key_version` values during rotation; old-key
retirement is permitted only after safe migration/re-key proof establishes that
no historical suppression loses its match. Secret/key-management implementation
belongs to operational security and is never placed in the compliance payload.

Ambiguous identity (unusable email, unavailable required matching-key version,
or conflicting suppression scope) fails closed: it produces
`UNKNOWN`/`REVIEW_REQUIRED`, never an automatic allow.

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

The existing generic `PolicyRequest` always carries a `ComplianceAssessment`.
For this command alone, the service constructs a fixed Kivou-owned neutral
pending representation (for example `state=UNKNOWN`, a fixed
`assessment_version=policy-compliance-pending-v1`, captured observed time, and
no validity time). It is never caller/Hermes supplied, never inspected as the
new assessment result because `requires_compliance=false`, and is included in
the policy semantic fingerprint so replay is stable. SPEC-025 does not redesign
the generic PolicyRequest contract unless implementation proves that unavoidable.

For an executable result, append the existing `NEXT_ACTION_SET` in the same
transaction as the assessment; no `EventType` and no state-machine version
change are necessary. The state stays `SEND` in all outcomes:

| Assessment | State | next_action | Meaning |
| --- | --- | --- | --- |
| `ALLOWED` | `SEND` | `schedule_campaign` | Compliant current assessment exists; SPEC-026 still owns scheduling/send checks. |
| `REVIEW_REQUIRED` | `SEND` | `request_human_review` | Valid facts, but bounded legal/product uncertainty requires an approved human resolution. |
| `UNKNOWN`, resolvable | `SEND` | `request_human_review` | Missing authoritative data may be corrected; no campaign handoff is permitted. |
| `UNKNOWN`, not resolvable | `SEND` | `NULL` | No safe resolution path; stop rather than create a review loop. |
| `BLOCKED` / `OUT_OF_SCOPE` | `SEND` | `NULL` | A hard no-contact/product boundary; do not misuse commercial `NO_SEND`, which has a different historical meaning. |

Current `NEXT_ACTION_SET` accepts only a non-empty string in
`ALLOWED_NEXT_ACTIONS`, although `AcquisitionOpportunity.next_action` itself
already permits `None`. Future SPEC-025 implementation must make the existing
event additive and backwards-compatible: `payload.next_action = null` is an
explicit clear, permitted only with non-empty `reason_codes`; string values keep
their current validation; historical events replay exactly unchanged. The
service—not the reducer—remains responsible for Policy/TOCTOU authorization.
Required regressions cover both a valid string set and a reasoned explicit
clear. This avoids a fake terminal command, a new EventType, and an
`acquisition-state-v2` solely for this extension.

### Shadow and assisted operation

In SHADOW or any non-executable policy result, persist only a
`POLICY_BLOCKED` PII-minimized assessment proposal. Do not write
`NEXT_ACTION_SET`; therefore no campaign action is unlocked. Because
`assess_campaign_compliance` is `PREPARATORY`, current Policy evaluator
semantics do **not** require ACTION approval merely because autonomy is
ASSISTED: the assessment may run automatically. When it produces
`REVIEW_REQUIRED`, the workflow handoff is `request_human_review`; a human must
add/correct durable evidence or configuration and trigger a **new** assessment.
Historical `REVIEW_REQUIRED` and `BLOCKED` rows are never mutated into
`ALLOWED`. A `COMPLIANCE_REVIEW` approval is relevant only to a later command
whose policy requires it, and cannot override a suppression-derived or other
hard `BLOCKED` result.

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
  known out-of-scope country, conflicting/no country; prove language/TLD/name
  never establish jurisdiction and unresolved is reviewable only when resolvable;
- rules: CH explicit consent, CH existing-customer predicate, CH cold Apollo
  contact with missing proof, FR professional-role/purpose predicate, FR
  provenance/identity/objection/privacy capability failures, unconfigured EU,
  unresolved jurisdiction, unverified contact, personalization mismatch, each
  bounded reason ordering, and no score;
- suppression: unsubscribe, explicit objection, duplicate-email/new-contact
  convergence, ambiguous identity failure closed, hard BLOCKED cannot be human
  overridden, three-year minimum/no automatic reactivation, overlapping HMAC
  key versions during rotation, and a post-assessment opt-out blocks future
  scheduling;
- policy: exact proposal action fingerprint, required Kivou evidence, no circular
  compliance gate for assessment, fixed Kivou-owned neutral pending compliance
  contract, SHADOW audit/no action, automatic ASSISTED preparatory assessment,
  and stale caller evidence cannot substitute current input;
- replay/crash/concurrency: exact replay with historical budget reconstruction,
  changed actor/scope/evidence/ruleset/artifact conflicts, policy-without-
  assessment fresh attempt, same-evaluation race convergence, and changed
  suppression race with no stale ALLOWED action;
- TOCTOU: after-policy drift in artifact, supplier/contact binding, jurisdiction,
  sender configuration, suppression, and ruleset yields `ComplianceInputChanged`
  and rolls back assessment plus action together;
- reducer: historical `NEXT_ACTION_SET` replay is unchanged; valid string
  handoffs still require `ALLOWED_NEXT_ACTIONS`; an explicit `next_action=null`
  clear needs non-empty reason codes and is rejected otherwise;
- migration: fresh DB, `0013 -> 0014`, PostgreSQL offline SQL, constraints,
  downgrade, and one linear Alembic head; and
- architecture: zero provider/network/LLM/customer/billing dependencies and no
  raw email/rendered artifact payload in generic audit structures.

The supervisor-reviewable offline EVAL corpus uses synthetic, non-personal test
fixtures: CH consent/evidence-complete candidate; CH existing-customer candidate;
CH cold provider-verified contact; FR professionally relevant candidate with and
without source/identity/objection/privacy readiness; EU configured,
unconfigured, and out-of-scope countries; resolvable and non-resolvable unknown
country; contact unverified; suppression and later objection; changed
artifact/contact/ruleset; SHADOW; and concurrent suppression. It evaluates
deterministic invariants, reason codes, provenance, and workflow safety—not a
legal-confidence score or copy quality.

## Recommended implementation sequence

1. Encode the supervisor-frozen CH/FR/EU routing, CH/FR predicates, suppression
   retention/rotation, review, and null-handoff contracts; obtain counsel review
   only for the remaining external jurisdiction/footer/exception questions.
2. Add the two-table linear `0014_compliance` migration and bounded contracts.
3. Implement pure jurisdiction, suppression matching, and ruleset evaluation
   TDD-first with the offline EVAL corpus.
4. Promote the reserved command and implement Policy metadata/replay semantics.
5. Add the atomic assessment service, TOCTOU checks, state handoff, full
   migration/concurrency/architecture regression, then open a separate draft PR.

## Design verdict and remaining external questions

R1 freezes the product decisions needed for a fail-closed CH/FR MVP. The
remaining external legal questions are limited to future BE/LU/other
Member-State rulesets, any later opinion changing the conservative CH treatment,
exact production privacy/footer wording, and exceptional suppression deletion or
key-retirement cases. The recommended topology is
`0013_personalization -> 0014_compliance`, with exactly two justified tables:
one cross-attempt suppression boundary and one immutable assessment audit. No
runtime, schema, migration, test, or deployment change is part of this design
PR.
