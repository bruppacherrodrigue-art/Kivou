# PR de finition avant production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and verify the 15-point production finishing PR on `fix/recette-finition`, with blockers 0-6 completed before non-blockers 7-14.

**Architecture:** Establish one backend signal presentation contract and one contact-status source, then make every frontend surface consume those contracts. Keep desktop and mobile layouts as explicit variants sharing navigation, identity, and monetization primitives; optimize only the companies aggregation path.

**Tech Stack:** Python API/services, SQLAlchemy/Alembic, React/TypeScript, existing i18n/design-system components, pytest, Vitest, Playwright CLI, `kivou-deploy.sh`.

---

## File map

- Modify `src/signals/feed/view.py`, `src/signals/feed/query.py`, and `src/signals/personalization/service.py` for canonical signal presentation, deterministic sentence fallback, and missing-object filtering.
- Modify `src/signals/alerts/content.py` and `src/signals/api/routes_attribution.py` so alert and email use the canonical sentence and attribution date.
- Modify `src/signals/api/routes_signals.py`, `src/signals/api/routes_companies.py`, and `src/signals/companies/listing.py` for response shape, contact mutation, and aggregation performance.
- Add `src/signals/persistence/migrations/versions/0043_signal_display_object_backfill.py` for existing missing-object signals and any materialized aggregation needed by the chosen existing database pattern.
- Modify `frontend/src/layouts/AppShell.tsx`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/SignalsFeed.tsx`, `frontend/src/signals/components/SignalDrawer.tsx`, `frontend/src/pages/CompaniesPage.tsx`, `frontend/src/pages/Settings.tsx`, and shared frontend API/types/i18n files for the shell, responsive surfaces, settings, labels, and plan behavior.
- Add or extend focused tests beside existing backend and frontend tests, plus one Playwright CLI recipe under `tests/e2e/` or the repository's existing browser-test location.
- Add `docs/reports/2026-09-06-recette-finition.md` containing exactly 15 lines with test, staging, and performance evidence.

## Task 1: Lock the canonical signal contract

**Files:**
- Test: `tests/test_card_presentation_api.py`, `tests/test_feed_facts.py`, `tests/test_alerts_cycle.py`
- Modify: `src/signals/feed/view.py`, `src/signals/feed/query.py`, `src/signals/personalization/service.py`, `src/signals/alerts/content.py`, `src/signals/api/routes_attribution.py`

- [ ] **Step 1: Add failing contract tests** for a no-cache account asserting identical UTF-8 bytes for card, drawer, email, and alert `for_you_sentence`; reject country-code/generic-only sentences; hide needs when no timing or quantity is determined; preserve a determined need.
- [ ] **Step 2: Run only those tests and confirm the expected failures.**
- [ ] **Step 3: Implement one presentation helper** that selects persisted `for_you_sentence`, otherwise builds a deterministic sentence from short object, `zone_labels`, amount, and attributed date, and returns only determined needs.
- [ ] **Step 4: Route all four consumers through that helper** and expose `Attribué le` consistently.
- [ ] **Step 5: Run the focused backend contract tests and keep them green.**

## Task 2: Enforce object eligibility and backfill

**Files:**
- Test: `tests/test_feed_facts.py`, `tests/test_card_presentation_api.py`
- Create: `src/signals/persistence/migrations/versions/0043_signal_display_object_backfill.py`
- Modify: `src/signals/feed/query.py`, `src/signals/feed/view.py`, `src/signals/api/routes_signals.py`

- [ ] **Step 1: Add failing tests** for exclusion of a signal without an exploitable object, CPV-label fallback as display object, and absence of `—` in the object field.
- [ ] **Step 2: Run the focused tests and confirm failure.**
- [ ] **Step 3: Implement the eligibility predicate and CPV display fallback** before profile materialization and in the API projection.
- [ ] **Step 4: Add an idempotent migration/backfill** that fills display objects from CPV labels and removes/marks ineligible existing profile materializations without deleting source notices.
- [ ] **Step 5: Run migration-specific and focused API tests.**

## Task 3: Unify contact status and company aggregation

**Files:**
- Test: `tests/test_company_engagement.py`, `tests/test_companies_list.py`, `tests/test_dashboard.py`
- Modify: `src/signals/api/routes_companies.py`, `src/signals/companies/listing.py`, relevant dashboard/contact service module
- Add only if required by the existing schema in `src/signals/persistence/migrations/versions/0044_company_contact_aggregation.py`

- [ ] **Step 1: Add a failing integration test** that marks a company contacted through the panel API and asserts the Today, “Cette semaine”, segment, and panel counters all change from the same persisted row.
- [ ] **Step 2: Add a failing performance benchmark** for `client-3mois` with 1,002 signals and one-second thresholds for `/companies` and `/signals`.
- [ ] **Step 3: Run both tests and confirm failure or baseline measurements.**
- [ ] **Step 4: Make the existing contact table/service the sole read/write source** and invalidate the shared query after mutation.
- [ ] **Step 5: Add a targeted cache or materialized aggregation for companies**, preserving tenant/profile scoping and invalidation on contact changes.
- [ ] **Step 6: Re-run focused behavior and benchmark tests, recording before/after timings.**

## Task 4: Add account block, session invalidation, and ICP navigation

**Files:**
- Test: `frontend/src/layouts/AppShell.test.tsx` and existing auth/session tests
- Modify: `frontend/src/layouts/AppShell.tsx`, shared auth API/client module, `frontend/src/i18n/fr.ts`
- Modify backend session logout route/module if no invalidation endpoint exists

- [ ] **Step 1: Add failing tests** for desktop/mobile account block rendering, settings and ICP links, visible logout action, and server invalidation before `/login`.
- [ ] **Step 2: Run the focused frontend/auth tests and confirm failure.**
- [ ] **Step 3: Implement the shared account block** at the bottom of both navigation variants, using initials, name/email, and optional company.
- [ ] **Step 4: Implement logout as an awaited server invalidation followed by navigation to `/login`.**
- [ ] **Step 5: Make the active ICP name in the plan banner navigate to `/app/icps`, and run focused tests.**

## Task 5: Implement responsive signals and companies panels

**Files:**
- Test: `frontend/src/signals/feed.test.tsx`, `frontend/src/signals/components/SignalDrawer.test.tsx`, `frontend/src/companies/CompaniesPage.test.tsx`
- Modify: `frontend/src/pages/SignalsFeed.tsx`, `frontend/src/signals/components/SignalDrawer.tsx`, `frontend/src/pages/CompaniesPage.tsx`, relevant CSS/style modules

- [ ] **Step 1: Add failing viewport tests** for the mobile signal line-card, no clipped columns, desktop side-by-side company panel, and full-screen mobile panel/drawer.
- [ ] **Step 2: Run the focused tests and confirm failure.**
- [ ] **Step 3: Implement explicit `@media (max-width: 899px)` card/panel variants** with the required field order: titulaire, objet/montant, lieu, date, match points.
- [ ] **Step 4: Reduce the desktop open company list to Entreprise and Statut** and reserve the full viewport for the mobile panel.
- [ ] **Step 5: Run focused responsive tests.**

## Task 6: Align settings and save feedback

**Files:**
- Test: `frontend/src/pages/referenceAccount.test.tsx`, settings tests
- Modify: `frontend/src/pages/Settings.tsx`, `frontend/src/pages/ProfileSettings.tsx`, `frontend/src/i18n/fr.ts`, shared design-system field components
- Modify backend account export/deletion routes only if absent

- [ ] **Step 1: Add failing tests** for omitted empty fields, no forbidden placeholder strings, Data tab JSON export, account deletion, and “Enregistré” after note/settings saves.
- [ ] **Step 2: Run focused tests and confirm failure.**
- [ ] **Step 3: Implement the shared settings layout and conditional field renderer.**
- [ ] **Step 4: Add Data-tab export/deletion actions with existing auth and confirmation/error handling.**
- [ ] **Step 5: Add save confirmation state to both mutation paths and run focused tests.**

## Task 7: Finish monetization, identity, labels, and dashboard copy

**Files:**
- Test: relevant frontend signal/dashboard/reference-account tests
- Modify: `frontend/src/pages/SignalsFeed.tsx`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/signals/components/SignalDrawer.tsx`, `frontend/src/layouts/AppShell.tsx`, `frontend/src/i18n/fr.ts`, API type/normalizer files

- [ ] **Step 1: Add failing tests** for locked-row mini-panel and `/tarifs`, discovery-row navigation, SIRET/IDE/TVA-only company identity while retaining drawer source reference, hidden zero strong-match line, unlimited-quota copy, zone-label-only rendering, and Sector availability for Essentiel.
- [ ] **Step 2: Run focused tests and confirm failure.**
- [ ] **Step 3: Implement the copy and navigation changes using canonical API fields**, keeping `Source : TED ...` only as notice provenance in the drawer.
- [ ] **Step 4: Enable the Sector filter capability for Essentiel and Pro in the plan capability map.**
- [ ] **Step 5: Run focused tests.**

## Task 8: Build the automated QA recipe and report

**Files:**
- Test/create: repository-standard Playwright CLI recipe under `tests/e2e/recette-finition.*`
- Create: `docs/reports/2026-09-06-recette-finition.md`
- Use: `kivou-deploy.sh`

- [ ] **Step 1: Add the Playwright flows** for Découverte, `client-3mois`, and Rodrigue at desktop and mobile widths, covering logout from each screen, account/ICP navigation, drawer/card parity, company contact propagation, settings save, locked rows, and Sector in Essentiel.
- [ ] **Step 2: Deploy staging with `kivou-deploy.sh` and run the recipe against the resulting staging URL.**
- [ ] **Step 3: Capture screenshots/traces only for failures or required evidence under `output/playwright/`.**
- [ ] **Step 4: Write exactly 15 report lines** summarizing each point, focused test status, Playwright matrix, staging result, and before/after endpoint timings.
- [ ] **Step 5: Run the complete backend/frontend suites and the final Playwright recipe before declaring the PR ready.**

## Task 9: Final integration

- [ ] **Step 1: Review the diff for unrelated files and preserve all pre-existing user changes.**
- [ ] **Step 2: Run the repository's required lint, typecheck, migration, backend, frontend, performance, and Playwright commands.**
- [ ] **Step 3: Commit implementation and report changes as one PR-ready change set after the documentation commit.**
- [ ] **Step 4: Report the exact branch, commits, test evidence, staging URL/result, performance before/after, and any external PR creation limitation.**
