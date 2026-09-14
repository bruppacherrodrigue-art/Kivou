# Company Public Contacts Implementation Plan

> **For agentic workers:** Execute the approved component inline with TDD; root performs integration and independent review. Root alone stages and commits.

**Goal:** Make supported public company contacts consistently available in Signal and Company dossiers while preserving exact company identity and paid-field rights.

**Architecture:** Read latest typed BOAMP facts through exact stored company identities, selecting individual winning organizations. Both company contracts expose bounded `public_contacts`, `available_contact_fields`, and `contacts_locked`; existing directory data remains the public website/register projection, while Apollo and account-private contacts retain their separate ownership. Reuse compact public contact rows in the existing UI sections.

**Tech Stack:** Python, SQLAlchemy, Pydantic, FastAPI, React, TypeScript, pytest and Vitest.

## Task 1: Publication evidence and regression tests

Files: `tests/test_client_directory.py`, `tests/test_company_public_contacts.py`, `frontend/src/prospecting/__tests__/company-dossier.test.tsx`.

- [x] Add a regression asserting a nominative address retained by model enrichment is published when its exact address is present in an own-site rendered page and the stored evidence URL agrees.
- [x] Run `uv run pytest -n 0 tests/test_client_directory.py -q`; confirm missing `published_email` fails before implementation.
- [x] Add dossier regression expecting a BOAMP public contact link and its notice source while preserving the manual-contact controls; run `npm test -- --run src/prospecting/__tests__/company-dossier.test.tsx` in `frontend` and confirm missing contact fails.

## Task 2: Common server projection

Files: `src/signals/client_value/company_contacts.py`, `src/signals/client_value/directory.py`, `src/signals/api/notice_projection.py`, `src/signals/companies/contracts.py`, `src/signals/api/routes_companies.py`, `src/signals/api/routes_signals.py`.

- [x] Define closed `CompanyPublicContact` with `organization_name`, notice-local `organization_ref`, exact `identifiers`, `source="boamp"`, `source_notice_id`, safe optional `source_url`, aware `observed_at`, and optional validated `email`, `phone`, `website`, `contact_name`.
- [x] Add to each profile `public_contacts: tuple[CompanyPublicContact, ...]` (maximum 100), `available_contact_fields: tuple[Literal["phone", "email", "website"], ...]`, `contacts_locked: bool`.
- [x] Implement pure holder extraction and exact SIRET/identifier matching; only canonical SIREN requests may aggregate establishments. Reject name-only matches, conflicting French identifiers, buyer organizations and quarantined aliases.
- [x] Read latest notice fact versions in one window-ranked query over exact candidate awards, including the stored source award for surviving dossiers. Resolve canonical candidates using existing quarantine-aware identity selection; never scan all notice payloads or read account notes/contact caches.
- [x] Filter directory suppressions before calculating availability; apply the same suppression to signal notice projection. Discovery serializes no contact names, values, or source metadata.
- [x] Replace localpart allowlisting with syntax and own-site public-evidence validation. Model publication requires exact retained address evidence; no director-name inference, raw model payload response, or MX-based personal verification label.
- [x] Wire GET company responses without altering enrichment POST endpoints or private context.

## Task 3: Common rendering

Files: `frontend/src/api/types.ts`, `frontend/src/prospecting/models.ts`, `frontend/src/prospecting/components/PublicContactFacts.tsx`, `HolderSummary.tsx`, `SignalDetail.tsx`, `CompanyDossier.tsx`.

- [x] Add shared contact types and render rows with actual organization attribution, source link/date, and validated mail/tel/web actions.
- [x] Combine current notice contacts with dossier contacts, deduplicating the same organization and values while preserving distinct agency evidence.
- [x] Render contacts within existing holder/dossier sections; use server lock state and capabilities, and leave private note/contact controls unchanged.
- [x] Integrate the other component's `initialDirectoryEnrichment` hook option and `CompanyEnrichmentStatus` display through narrow patches.

## Task 4: Focused verification and handoff

- [x] Test exact consortium member, sibling establishment exclusion, canonical SIREN aggregation, spaced SIRET normalization, latest version replacement, suppression, quarantine and Discovery removal. API tests verify both company URL forms and surviving tracked identities.
- [x] Test model/site published generic and nominative addresses; reject missing publication, unsafe/mismatched evidence, placeholders and suppressed contacts. Preserve valid contacts when unrelated family enrichment is partial.
- [x] Run `uv run pytest -n 0 tests/test_company_public_contacts.py tests/test_notice_projection.py tests/test_client_directory.py tests/test_saas_company_api.py tests/test_company_dossier_fallback.py -q`.
- [x] Run affected Vitest files, `npm run typecheck`, frontend lint and Ruff on changed Python files. Report exact results and remaining concerns to root; no provider calls or production mutation.

## Validation recorded

- RED: publication tests failed for missing site/model nominative emails; dossier test failed for the missing BOAMP contact link. Additional identity tests failed for name-only transfer, conflicting identifiers and a quarantined co-winner reappearing through a shared notice.
- GREEN: 35 public-contact, notice, directory and architecture tests passed; one pre-existing architecture xfail remains. The broader run passed 67 tests, with only the parallel enrichment contract's then-present error field failing; the final architecture rerun passed after that component removed it.
- GREEN: 29 affected frontend tests passed; TypeScript check passed. ESLint exited zero with one warning in the parallel enrichment hook, reported to its owner. Ruff and `git diff --check` passed.
- Publication intentionally validates email syntax; historical test-only `.test` mailbox fixtures were replaced with valid synthetic addresses.
- Public company source reads are bounded to 250 award fact sets and responses to 100 contacts. Latest versions are selected in one query; raw notice archives and private contact stores are not consulted.
# Review follow-up: preserve facts across manual refreshes

Root-approved bounded follow-up to Task3 quality review: add opt-in
`preserve_known_fields=False` to `SupplierDirectoryStore.upsert_identity`;
the manual worker alone opts in. Missing registry fields retain their existing
values and observation dates, and an existing confirmed family is not downgraded
by an incomplete register/model response. Actual new registry values, including
zero employees, still update normally. Model phone values must pass the existing
public phone predicate before replacing a known number. Regressions exercise the
real worker/store/enrichment service with only external collection/model responses
replaced by offline doubles, in `tests/test_company_enrichment_preservation.py`.

Verification: the preservation regressions first failed in five relevant cases
(missing registry values and unusable model phone), then all six passed after
the opt-in worker wiring (24.46s). The wider supplier-directory, enrichment,
notice-projection and public-contact suite passed 43 tests (78.07s). Ruff on the
changed store/tests and `git diff --check` passed. The phone-only Discovery
availability regression passed before any proposed production change because
the contact contract already excludes null fields; no unnecessary fix was made.
