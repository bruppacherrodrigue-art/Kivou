# SPEC-025 — Compliance CH / FR / EU — implementation report

**Status:** local implementation validation complete; executable CI pending; DRAFT implementation PR only.

**Authoritative implementation base / merged design SHA:** `ff6a070c3d7a8ad95c002fc0ffc97b3b4f93c594`

**Implementation branch:** `feat/spec025-compliance`

**Migration head:** `0014_compliance`

## Implemented architecture

SPEC-025 is a local deterministic B2B acquisition-email assessment. It consumes
the current `SEND + assess_campaign_compliance` projection and exact immutable
`READY` personalization artifact, then constructs a PII-minimized
`acquisition-compliance-input-v1`. The pure
`acquisition-compliance-ruleset-v1` emits only the existing Policy states
`ALLOWED`, `REVIEW_REQUIRED`, `UNKNOWN`, or `BLOCKED`; it has no score, model,
network, or caller-selected legal conclusion.

The orchestration service owns one injected timezone-aware clock, builds the
proposal before Policy, constructs the generic Policy request's fixed
`policy-compliance-pending-v1` object internally, and binds the exact proposal
with a distinct action fingerprint. Caller evidence claim names are replaced by
the fixed Kivou evidence vocabulary. The final executable write re-reads every
material input in one caller-owned transaction, rebuilds the input/proposal with
the same captured time, and atomically writes one `NEXT_ACTION_SET` plus one
immutable compliance assessment.

## Jurisdiction and deterministic rules

`compliance-jurisdiction-v1` uses only the supplier's durable canonical country
and the controlled normalized provider-company country. Language, names, email
TLD, and inferred nationality are absent. Equal/one-sided durable facts resolve;
conflicts, missing facts, and unknown provider text resolve to `UNRESOLVED`.

- CH uses the conservative consent/existing-customer predicate. Pure rules prove
  both qualifying predicates can produce an `ALLOWED` candidate when sender and
  objection capability are current. Current DB-backed cold Apollo acquisition
  facts have no durable consent or existing-customer proof, so ordinary CH
  execution deliberately produces `REVIEW_REQUIRED / LEGAL_BASIS_UNRESOLVED`.
- FR tiers 1–3 are the bounded professional-context predicate; tier 4 is
  `REVIEW_REQUIRED`. Automatic FR `ALLOWED` also requires verified durable
  provider provenance plus sender identity, opt-out, privacy notice, and source
  notice capability.
- Other recognized EU Member States have no generic allow rule and produce
  `REVIEW_REQUIRED / COUNTRY_RULESET_UNCONFIGURED` in v1. A known country outside
  the supported perimeter produces terminal product `BLOCKED`; unresolved
  routing produces `UNKNOWN` and human data-resolution review.
- A matched suppression always wins before jurisdiction or country rules.
  Incomplete retained-key coverage is non-resolvable `UNKNOWN` and clears the
  workflow action rather than risking outreach.

An `ALLOWED` proposal expires after 24 hours or at an earlier sender-config
boundary. Non-allowed results never carry authorization validity.

## Suppression boundary and key rotation

`SuppressionIdentityKeyring` is an explicit injected dependency; no production
secret is hardcoded or read from caller/Policy data. Email normalization is
bounded (`strip` + `casefold` + usable-address validation), and identities use
domain-separated HMAC-SHA256. The durable suppression table contains only the
opaque digest and key version, never raw or normalized email.

The matcher computes identities for all retained keys and checks every retained
database key version. Any unavailable historical version fails closed, so key
rotation cannot temporarily re-enable a recipient. Duplicate contact records
with the same normalized business email converge. Suppression is append-only,
has no active/expiry flag, retains a minimum three-calendar-year boundary, and
does not reactivate automatically when that minimum passes.

Assessment reads and suppression writes also serialize on the email-wide HMAC
identity, not merely a contact row: PostgreSQL uses sorted transaction-scoped
advisory locks derived from retained HMAC identities, while SQLite tests use an
equivalent transaction write boundary. This prevents a duplicate contact record
with the same normalized email from opening a post-read/pre-commit race. Reason
codes use a closed enum, and evidence identifiers are opaque domain-separated
SHA-256 references; caller text, names, addresses, and URLs cannot enter the
suppression audit fields.

## Policy and workflow integration

`assess_campaign_compliance` is promoted from reserved next-action vocabulary
to a real OPPORTUNITY-scoped `PREPARATORY` command. It is present in both
`ALLOWED_COMMANDS` and `COMMAND_POLICIES`, preserving exact registry equality;
`ALLOWED_NEXT_ACTIONS` now derives directly from commands. Its six evidence
claims are acquisition decision, public evidence, verified contact, prospect
prebuild, personalization artifact, and compliance input. It uses no budget,
volume, provider quota, send control, control-plane requirement, or circular
compliance gate. Existing `schedule_campaign` policy metadata is unchanged.

Workflow mapping, with `state=SEND` throughout:

| Assessment | Next action |
| --- | --- |
| `ALLOWED` | `schedule_campaign` |
| `REVIEW_REQUIRED` | `request_human_review` |
| resolvable `UNKNOWN` | `request_human_review` |
| terminal `UNKNOWN` | explicit clear (`null`) |
| `BLOCKED` / out of scope | explicit clear (`null`) |

The existing `NEXT_ACTION_SET` reducer now permits an explicit `null` only with
non-empty reason codes. Existing strings and historical events replay unchanged.
No EventType and no `acquisition-state-v2` were added.

## Migration and persistence

The linear topology is exactly:

```text
0013_personalization -> 0014_compliance
```

Exactly two tables are added:

1. `acquisition_contact_suppression` — append-only opaque cross-attempt hard
   boundary with versioned identity-key index and no automatic expiry.
2. `acquisition_compliance_assessment` — immutable proposal/Policy/workflow
   audit with `RECORDED` and `POLICY_BLOCKED` dispositions.

SQL and Pydantic constraints bind assessment state to next action and validity,
and bind disposition to presence/absence of a workflow event. Neither table has
contact names, raw email, rendered personalization copy, raw Apollo data,
provider/model fields, or secrets.

## Replay, crash windows, atomicity, and concurrency

Durable assessment lookup occurs before the clock. Exact replay reconstructs
the original Policy control snapshot and historical BudgetUsage from stored
cost/volume remaining, then verifies request, actor, scope, evidence,
operational, supervisor/skill, action, and assessment identities. Current global
budget changes do not invalidate history; changed authorization semantics
produce `ComplianceAssessmentIdempotencyConflict`.

A Policy evaluation without its assessment produces
`ComplianceEvaluationRequiresFreshAttempt` before clock access and never reuses
the old approval. Post-Policy opportunity, artifact, supplier, contact, profile,
jurisdiction, sender-config, or suppression drift produces
`ComplianceInputChanged`; no stale assessment or next action survives. An
injected assessment-insert failure proves the event/projection/assessment write
rolls back atomically.

File-backed concurrent same-evaluation calls converge to one Policy audit, one
assessment, and one terminal event with exact replay. Concurrent changed
proposal semantics produce a typed conflict. A suppression inserted after
Policy with a later source timestamp but before the final transaction prevents
stale `ALLOWED` and leaves no assessment or `schedule_campaign` action. A second
race regression proves a writer using another contact row with the same email
cannot commit between final suppression revalidation and assessment commit.

## SHADOW, privacy, EVAL, and architecture

SHADOW persists only a PII-minimized `POLICY_BLOCKED` proposal audit and does not
advance the workflow. The assessment input/audit, Policy audit, and acquisition
event have tests excluding business email, person names, rendered copy, raw
provider payloads, and HMAC key material.

`tests/fixtures/compliance_eval_v1.json` contains the 20 frozen synthetic cases:
CH consent/existing-customer/cold-contact, FR tiers/capability/suppression,
unconfigured DE/BE/LU, out-of-scope and unresolved routing, incomplete key
coverage, SHADOW, artifact drift, and concurrent suppression. Architecture tests
prove the compliance package has no runtime import of Instantly, SMTP, Apollo
network clients, LLM/OpenRouter, crawler, Stripe/billing, TargetICP, customer
matching, or customer ownership components.

## Validation and closeout

Migration regression (fresh database, `0013 -> 0014`, PostgreSQL offline SQL,
schema/index/constraint parity, downgrade/re-upgrade, single head) is green.
The final local backend regression passed **3,489 tests with 0 skipped**. Ruff
and `git diff --check` passed. The unchanged frontend passed **150 tests**, its
production build, explicit TypeScript project build, and lint. Executable and
final-head CI identities are recorded only after GitHub completes them.

No Apollo/network, Instantly, SMTP, LLM/provider, crawler, campaign, VPS,
staging, production, Stripe, or deployment side effect was performed.
