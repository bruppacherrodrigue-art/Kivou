# Company Drawer Optimistic Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make company contact actions immediate and reversible while tightening missing-field and compact-signal rendering in both drawers.

**Architecture:** `CompaniesPage` owns the optimistic transaction because it already owns the list, segment counts, and selected company profile. `CompanyDrawer` receives the current state and reports requested transitions; a dedicated compact `SignalRow` presentation handles company markets, while small display helpers omit unavailable drawer facts instead of rendering placeholders.

**Tech Stack:** React 19, TypeScript, CSS Modules, Vitest, Testing Library.

---

### Task 1: Optimistic company contact transitions

**Files:**
- Modify: `frontend/src/companies/CompaniesPage.test.tsx`
- Modify: `frontend/src/companies/CompaniesPage.tsx`
- Modify: `frontend/src/companies/CompanyDrawer.tsx`
- Modify: `frontend/src/companies/CompaniesPage.module.css`

- [ ] Add deferred-response tests proving that both contact actions update the drawer, table status, segment counts, and history before the request settles.
- [ ] Run `timeout 120s npm test -- --run src/companies/CompaniesPage.test.tsx` and confirm the new assertions fail for missing optimistic behavior.
- [ ] Move the contact request orchestration into `CompaniesPage`, snapshot list/profile/count state, apply the transition synchronously, and restore the snapshot with an accessible error message when the request rejects.
- [ ] Make the current-status button filled and inert; keep the alternative outlined.
- [ ] Re-run the focused tests and confirm success and rollback paths pass.

### Task 2: Compact company-market rows

**Files:**
- Modify: `frontend/src/signals/components/SignalRow.test.tsx`
- Modify: `frontend/src/signals/components/SignalRow.tsx`
- Modify: `frontend/src/signals/components/signals.module.css`
- Modify: `frontend/src/companies/CompanyDrawer.tsx`
- Modify: `frontend/src/companies/CompaniesPage.module.css`

- [ ] Add a failing test for a company-drawer row without holder cell and with object, amount, place, and match visible.
- [ ] Run the focused `SignalRow` test and verify the new test fails.
- [ ] Add an explicit company-drawer variant that renders the object across the available width and retains the requested facts.
- [ ] Add one-line overflow styling with ellipsis only when the available width is exceeded.
- [ ] Re-run both focused component suites.

### Task 3: Omit missing drawer fields

**Files:**
- Modify: `frontend/src/companies/CompaniesPage.test.tsx`
- Modify: `frontend/src/signals/components/SignalDrawer.test.tsx`
- Modify: `frontend/src/companies/CompanyDrawer.tsx`
- Modify: `frontend/src/signals/components/SignalDrawer.tsx`

- [ ] Add failing tests for identity segments without `· —`, the empty-history sentence, and absent signal facts omitted from the definition list.
- [ ] Run the focused suites and verify the failures describe current placeholder rendering.
- [ ] Filter identity segments and signal facts by displayable values; render `Aucune action pour l'instant` for empty company history.
- [ ] Re-run focused tests, TypeScript, and lint with timeouts.

### Task 4: Verify and deliver

**Files:**
- Review all files above.

- [ ] Run the complete frontend unit suite once with a bounded timeout.
- [ ] Inspect `git diff --check`, the scoped diff, and `git status --short` while preserving unrelated dirty files.
- [ ] Commit only the plan, components, styles, and tests; push the branch and open a PR against `main`.
