# Approved Company Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the authenticated company profile to match Rodrigue's approved mockup for both signal holders and directory companies, behind a disabled-by-default server flag.

**Architecture:** Extend the existing read-only `supplier_directory` projection with already persisted public-contact fields and their provenance. Render one shared React presentation for holder and directory profiles while preserving the legacy components when `KIVOU_COMPANY_PROFILE_V2_ENABLED` is false; directory-only engagement uses a stable account-scoped key derived from the SIREN.

**Tech Stack:** FastAPI, SQLAlchemy Core, Pydantic, React, TypeScript, CSS Modules.

---

### Task 1: Preserve the approved reference

**Files:**
- Create: `docs/design/kivou-maquette-fiche-entreprise.html`

- [x] Copy the supplied root mockup byte-for-byte into `docs/design/`.
- [x] Commit the reference separately so later UI changes can be compared with it.

### Task 2: Expose the approved read model behind a flag

**Files:**
- Modify: `src/signals/api/config.py`
- Modify: `src/signals/client_value/directory.py`
- Modify: `src/signals/companies/contracts.py`
- Modify: `src/signals/api/routes_companies.py`

- [x] Add `KIVOU_COMPANY_PROFILE_V2_ENABLED`, defaulting to false.
- [x] Project only persisted fields: NAF label, public contact, website, directors, location, workforce, and field-level observation/source values; omit every absent value.
- [x] Include the flag and plan-aware contact state in holder and directory profile responses.
- [x] Give directory-only profiles a stable `cmp_directory_<siren>` engagement key and account-scoped contact, note, history, and on-demand decision-maker routes.
- [x] Keep all provider calls behind the existing explicit decision-maker action.

### Task 3: Build the shared approved component

**Files:**
- Create: `frontend/src/companies/CompanyProfileV2.tsx`
- Modify: `frontend/src/companies/CompanyDrawer.tsx`
- Modify: `frontend/src/companies/DirectoryCompanyPage.tsx`
- Modify: `frontend/src/companies/CompaniesPage.tsx`
- Modify: `frontend/src/companies/CompaniesPage.module.css`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/endpoints.ts`

- [x] Render title/subtitle, Contact, Identité, Marchés publics, then Vous et cette entreprise in the exact approved hierarchy.
- [x] Merge public contact and decision-maker lookup into the first block; blur the whole public contact card for Découverte with the exact offer message and `/tarifs` action.
- [x] Apply the three market-summary states (zero, one, at least two) and the last known calendar without single-observation cadence or consortium percentages.
- [x] Reuse the component for a holder drawer and a directory profile, including real engagement actions.
- [x] Preserve the legacy render path when the flag is false and omit absent fields without placeholders.

### Task 4: Stage the two real records and capture

**Files:**
- Create: `docs/reports/2026-09-12-pr6b-company-profile/` screenshots only

- [ ] Resolve and enrich N. JOHANN SDCI by invoking the existing cached company-research chain without changing its code.
- [ ] Confirm ALYA BATIMENT SIREN `481153435` and the resolved N. JOHANN SDCI record in the same `supplier_directory` table.
- [ ] Warn before deploying the branch to shared staging, enable only `KIVOU_COMPANY_PROFILE_V2_ENABLED`, and deploy.
- [ ] Capture desktop and mobile for the two real companies with `client-3mois` and QA Découverte, showing the Essential contact action and Discovery blur.
- [ ] Restore staging to `main` after the captures and provide the images for approval.

### Explicitly deferred until Rodrigue's approval

- Component tests, API contract tests, goldens, CI, merge, and production deployment.
- Generated “Pour vous” backfill correction and activation.
- Any change inside `acquisition_runtime`, `supplier_discovery`, `company_research`, `contact_discovery`, or `personalization`.
- The general materialization-time holder enrichment hook, which crosses the session A ownership boundary; step 1 uses the existing chain operationally for the named staging holder.
