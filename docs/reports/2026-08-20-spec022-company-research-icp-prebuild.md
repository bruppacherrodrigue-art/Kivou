# SPEC-022 — Company Research + Acquisition Prospect Prebuild

Date: 2026-08-20
Branch: `feat/spec022-company-research-icp-prebuild`
Pull request: #18 (DRAFT)
Authoritative base: `341011a51d94ce298c08add0f905a85a78121773`
Design commit: `fa740536b9a5da51e0397d53cf3927551c579386`

## Result

SPEC-022 implements a Kivou-owned, deterministic company-research boundary. An actionable Acquisition Opportunity receives a fresh Policy Gateway evaluation; only an executable decision can own one durable company-research run and perform one bounded Apollo exact-ID organization request. A successful safe observation becomes one opportunity-scoped `AcquisitionCompanyProfile`, then advances the existing acquisition workflow from `ENRICHING` to `READY_FOR_DECISION` with next action `evaluate_opportunity`.

The implementation creates no Decision Engine, SEND score, campaign, outbound path, website crawler, LLM research, or customer `TargetICP` dependency.

## Apollo boundary

- Fixed endpoint: `GET https://api.apollo.io/api/v1/organizations/{provider_organization_id}`.
- Identity source: the exact `acquisition_supplier.provider_organization_id` established by SPEC-020.
- `/organizations/enrich`, Organization Search, People API, Account API, rematching, and generic Apollo SDK behavior are absent.
- Maximum calls per run: 1.
- Planned provider credits per run: 1; no CHF/EUR conversion is invented.
- The client streams the response and fails with `response_too_large` above 1 MiB.
- Provider organization IDs are restricted to one bounded symbolic path segment; traversal, slash, query, and fragment forms are rejected before URL construction.
- `x-api-key` is injected at runtime and is never persisted or logged.

The following categories remain distinct: `unauthorized`, `forbidden`, `not_found`, `unprocessable_entity`, `client_error`, `rate_limited`, `timeout`, `network_error`, `server_error`, `malformed_response`, `response_too_large`, and `provider_identity_mismatch`. In accordance with the supervisor decision, both HTTP 404 and HTTP 422 fail closed: neither produces a profile nor advances the opportunity.

## Provider allowlist and degradation

Identity-critical fields are `organization.id` and `organization.name`; invalid structure, absent identity, or an ID mismatch fails the run.

Persisted provider observation fields are limited to:

- provider and exact provider organization ID;
- company name;
- primary domain and website URL;
- country and industry;
- employee count and founded year;
- bounded short description;
- at most 32 bounded keywords;
- provider observation timestamp and accepted-source fingerprint.

Annual revenue, phone, addresses, social URLs, logos, funding, investors, technologies, organization hierarchy, people identifiers, Apollo insights, raw payloads, and HTTP headers are discarded.

An absent or malformed optional field does not invalidate a usable organization. The unsafe value is discarded and a stable, sorted `research_gaps` code is recorded. The vocabulary distinguishes missing, invalid, and deliberately truncated data, including `MISSING_DOMAIN_OR_WEBSITE`, `MISSING_COUNTRY`, `MISSING_INDUSTRY`, `MISSING_EMPLOYEE_COUNT`, `INVALID_PRIMARY_DOMAIN`, `INVALID_WEBSITE_URL`, `INVALID_EMPLOYEE_COUNT`, `INVALID_FOUNDED_YEAR`, `INVALID_KEYWORDS`, `TRUNCATED_DESCRIPTION`, and `TRUNCATED_KEYWORDS`. No raw invalid value is retained.

`provider_source_fingerprint` covers the exact identity, accepted allowlisted fields, and ordered research gaps. It excludes observation time, run/evaluation IDs, HTTP metadata, ignored fields, and Kivou derivations. An identical accepted provider observation therefore has the same fingerprint when observed later.

## Distinct fingerprints

- `profile_fingerprint` binds `company-research-v1` provider-research configuration.
- `provider_request_fingerprint` binds the actual exact-ID Apollo request and response contract.
- `PolicyRequest.action_fingerprint` additionally binds the acquisition opportunity, supplier, and selected contact.
- `prebuild_fingerprint` binds every durable SPEC-023 input, including provider facts, public signal reference, supplier/contact references, role tier/version, research quality, size derivation, and prebuild version.

Two opportunities referencing the same Apollo organization share provider request semantics but have different Policy action fingerprints.

## Acquisition Prospect Prebuild

The durable representation is `AcquisitionProspectPrebuild`, version `acquisition-prospect-prebuild-v1`. It is not the customer-owned `TargetICP`; it is an opportunity-scoped, deterministic input projection for SPEC-023.

It contains acquisition/supplier/contact references, supplier identity status, bounded provider company facts, selected-contact role tier/version (never contact PII), provider research status, completeness, research gaps, and Kivou size band. It contains no fit score, lead score, probability, purchase intent, priority, or SEND/HOLD/REVIEW/NO_SEND result.

`company-size-v1` maps accepted Apollo employee counts deterministically:

- unavailable/unusable → `UNKNOWN`;
- 0–9 → `MICRO`;
- 10–249 → `SMB`;
- 250–999 → `MID_MARKET`;
- 1000+ → `ENTERPRISE`.

Research is `COMPLETE` only when exact ID/name, domain or website, country, industry, and usable employee count are present. Otherwise the valid provider response produces a `LIMITED` profile. `LIMITED` is research quality only and is not a negative commercial decision.

## Policy and run ownership

`enrich_company` remains `PREPARATORY` and opportunity-scoped. Its evidence profile is `SUPPLIER`, `VERIFIED_CONTACT`, and `COMPANY_RESEARCH_PROFILE`; it uses monetary budget, provider quota, and provider control-plane gates, but no compliance, mailbox, or send-window gate.

Before any new Policy evaluation, the service requires:

- state `ENRICHING` and next action `enrich_company`;
- non-null supplier and contact references;
- Apollo supplier identity;
- a selected contact bound to the same supplier with Apollo `PROVIDER_VERIFIED` status.

The company-research path selects no business-email column and duplicates no contact PII.

The SPEC-021 crash-window doctrine is preserved. An existing run for an evaluation is returned without a new policy/provider call. An existing policy evaluation without a run raises `CompanyResearchEvaluationRequiresFreshAttempt`; the caller must supply a new evaluation ID so the current stream version and controls are re-evaluated.

`company_research_run.policy_evaluation_id` is unique. `STARTED` commits before HTTP; only the process that owns that row may call Apollo. Same-evaluation races converge on one run, while a reused run ID with a different evaluation raises `CompanyResearchRunIdentityConflict` without a provider call.

## Clocks and CAS

The service and client use injectable timezone-aware clocks:

`policy.evaluated_at <= run.started_at <= provider_observed_at <= run.completed_at`.

`provider_observed_at` is captured after the successful HTTP response body has been fully received. Failed calls have no successful provider observation.

The opportunity-scoped profile uses deterministic compare-and-set behavior:

- newer observation → update bounded mutable observation/prebuild;
- equal timestamp plus equal provider and prebuild fingerprints → replay/no-op;
- equal timestamp plus different semantics → `CompanyResearchObservationConflict`;
- older observation → no overwrite;
- opportunity, supplier, contact, or signal binding mismatch → conflict.

## Migration 0011

Alembic remains linear:

`0010_contact_discovery -> 0011_company_research`

Revision length is within the repository-wide 32-character limit. Migration 0011 creates exactly:

- `acquisition_company_profile` — one current opportunity-scoped prebuild, with FK `RESTRICT` bindings;
- `company_research_run` — the narrow one-call authorization/provider audit, with unique policy evaluation ownership.

It creates no cache, history table, company master, queue, Event Bus, worker, or 0012 revision. Fresh upgrade, 0010→0011 upgrade, Core schema parity, constraints, and PostgreSQL offline SQL are tested.

## Atomic workflow mutation

After Policy Gateway records `POLICY_EVALUATED`, the run stores the expected post-policy stream version. A single caller-owned transaction then re-locks and revalidates the opportunity, supplier, and contact, rebuilds the prebuild from those current durable supplier/contact values plus the accepted Apollo observation, upserts the profile, appends `STATE_TRANSITIONED(READY_FOR_DECISION)`, appends `NEXT_ACTION_SET(evaluate_opportunity)`, and finishes the run `SUCCESS` or `LIMITED`. Concurrent supplier identity or selected-contact role refreshes therefore cannot leave stale SPEC-023 inputs in the profile.

Any CAS, optimistic-concurrency, profile, event, projection, or terminal-run failure rolls back all profile/workflow terminal writes. The pre-existing STARTED run is marked FAILED separately with a bounded safe category. Tests inject terminal-write failure and concurrent workflow mutation to prove no partially READY opportunity or orphan profile results.

No new acquisition EventType is required. `acquisition-state-v1` remains unchanged; the existing `STATE_TRANSITIONED` and `NEXT_ACTION_SET` events fully represent the workflow change.

## Privacy and architecture proof

Architecture tests prohibit dependencies on customer accounts, billing, entitlements, matching, `TargetICP`, materialized customer signal ownership, and customer feedback. Company research persists only `contact_ref` plus role profile version/tier; it does not persist contact name, email, LinkedIn, or phone.

Static boundary tests also prove the company-research package contains no Apollo alternate endpoint, outbound mail, Instantly, crawler, Hermes, or OpenAI/LLM integration.

## TDD and performance

The SPEC-022 suite contains 79 targeted tests covering contracts, safe exact-ID URL construction, fingerprints, normalization, optional-field degradation, error taxonomy, actionability, Policy crash windows, run ownership/races, observation CAS, supplier/contact refresh concurrency, transaction rollback, migration, privacy, and forbidden side effects.

The diagnostic for 100 deterministic accepted organization observations performs parse, normalization, prebuild, and persistence in `2.211118s` locally. This is diagnostic only; no SLA or cache is introduced.

## Full regression

- Backend: `3218 passed in 468.57s`, `0 skipped`.
- Ruff: PASS.
- `git diff --check`: PASS.
- Frontend: `84 passed`.
- Frontend build: PASS.
- TypeScript `tsc -b`: PASS.
- Frontend lint: PASS.
- Live Apollo calls: 0.
- GitHub Actions executable run: `32380698387` — SUCCESS (backend and frontend).

## Files changed

- Added `src/signals/company_research/` contracts, profile/fingerprint, prebuild, provider, Apollo client, store, and service modules.
- Added migration `0011_company_research` and the two SQLAlchemy Core tables.
- Updated `enrich_company` callable-free Policy metadata.
- Added SPEC-022 tests and updated legitimate current-head migration expectations.
- Added the implementation plan and this closeout report under `docs/reports/`.

## Git closeout

- Executable SHA: `5aff700c44cd3ad39de3769204b755f1a7ce06d8`.
- CI run: `32380698387` — SUCCESS.
- Executable diff stat: 28 files changed, 3931 insertions(+), 10 deletions(-).
- `git status --porcelain`: clean after the documentation-only closeout commit.
