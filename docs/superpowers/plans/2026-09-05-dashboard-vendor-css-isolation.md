# Dashboard Vendor CSS Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the pre-PR4 PostCSS boundary so Tailwind/shadcn styles exist on dashboard pages and cannot affect public pages.

**Architecture:** A dedicated `dashboard-vendor.css` owns all vendor imports. The existing local PostCSS plugin scopes every selector produced from that entry under the dashboard HTML attribute, while shared aliases live in the root design-token sheet and surface-specific values remain scoped.

**Tech Stack:** React, TypeScript, Vite, PostCSS, Tailwind CSS v4, Vitest, Playwright.

---

### Task 1: Make bundle isolation executable

**Files:**
- Create: `frontend/scripts/assert-dashboard-css-isolation.mjs`
- Modify: `frontend/package.json`
- Test: `frontend/src/styles/fonts.test.ts`

- [x] **Step 1: Write the failing test**

Add a Vitest case that runs `npm run build`, locates `dist/assets/index-*.css`, then invokes the assertion script. The assertion script must reject unprefixed selectors for `.container`, `.grid`, `.flex`, `.hidden`, `.absolute`, `.w-full`, and reset selectors containing `*`, `::before`, `::after`, or `::backdrop`; it must also require at least one dashboard-prefixed utility and reset rule.

- [x] **Step 2: Verify RED**

Run `timeout 180 npm test -- --run src/styles/fonts.test.ts` from `frontend/`. Expected: FAIL because current Tailwind utilities are emitted without the dashboard prefix.

- [x] **Step 3: Add the reusable assertion command**

Expose `check:css-isolation` in `package.json` as `node scripts/assert-dashboard-css-isolation.mjs`. The script reads the single built application stylesheet, parses selector blocks without accepting a listed selector unless every occurrence is rooted at `html[data-kivou-surface="dashboard"]`, and exits non-zero with the offending selector.

- [x] **Step 4: Keep the test RED for the production reason**

Run the isolated test again. Expected: FAIL naming an unprefixed Tailwind utility or preflight selector, not a missing script or fixture.

### Task 2: Restore the dedicated vendor entry

**Files:**
- Create: `frontend/src/presentation/dashboard/dashboard-vendor.css`
- Modify: `frontend/src/presentation/dashboard/app-shell.css`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/postcss.config.mjs`

- [x] **Step 1: Move the three vendor imports**

Create the entry with the exact leading comment `/* préfixé sous html[data-kivou-surface=dashboard] par le plugin PostCSS ; ne jamais importer globalement */`, followed by Tailwind, `tw-animate-css`, and shadcn imports. Remove them from `app-shell.css` and import the new entry from `main.tsx` immediately before `app-shell.css`.

- [x] **Step 2: Scope the completed vendor root**

Update the local PostCSS plugin to recognize `dashboard-vendor.css` and prefix every ordinary selector after Tailwind expansion. Map `:root` and `html` to the dashboard root, map `body` beneath it, avoid double-prefixing, and skip rules nested inside keyframes.

- [x] **Step 3: Verify GREEN**

Run `timeout 180 npm test -- --run src/styles/fonts.test.ts` and `timeout 180 npm run build && npm run check:css-isolation`. Expected: all tests and the bundle assertion pass; prefixed `.flex`, `.grid`, `.hidden` and preflight exist.

### Task 3: Establish shared and surface variables

**Files:**
- Modify: `frontend/src/styles/tokens.css`
- Modify: `frontend/src/presentation/public/marketing.css`
- Modify: `frontend/src/presentation/dashboard/app-shell.css`
- Test: `frontend/src/styles/referenceSurface.test.tsx`

- [x] **Step 1: Write a failing token ownership test**

Add assertions that every generic custom property consumed by both surface sheets has a declaration in `tokens.css/:root`, and that surface overrides begin under their respective `html[data-kivou-surface]` selectors.

- [x] **Step 2: Verify RED**

Run `timeout 60 npm test -- --run src/styles/referenceSurface.test.tsx`. Expected: FAIL naming the first missing root alias such as `--canvas` or `--container`.

- [x] **Step 3: Add root defaults and scope overrides**

Declare the shared aliases in `tokens.css` using existing Kivou token values. Convert the marketing top-level variable block to the public surface selector; retain the dashboard block under the dashboard selector. Do not change component values.

- [x] **Step 4: Verify GREEN**

Run both style test files and the production build assertion. Expected: PASS.

### Task 4: Restore and verify the reference surfaces

**Files:**
- Modify: `frontend/tests/visual/reference-port.spec.ts`
- Modify: `frontend/tests/visual/reference-goldens/*.png` only for the requested routes

- [x] **Step 1: Add functional visibility assertions**

For `/app`, assert that the navigation landmark, sidebar plan text, and dashboard page content are visible before capture. Preserve the existing Signaux and Entreprises structural checks.

- [x] **Step 2: Capture reference comparisons**

Extract public reference images from `83ffc7b` and dashboard reference images from `7365d92` into a temporary directory. Capture current 1440×900 and 390×844 renders for accueil, tarifs, légal, login, signup, onboarding, `/app`, `/app/signals`, and `/app/companies`; inspect diffs to separate later copy/content changes from CSS regressions.

- [x] **Step 3: Regenerate requested goldens**

Run the named Playwright tests with `--update-snapshots`, then run the complete visual suite once. Expected: all visual tests pass, including the no-scroll and drawer contracts.

### Task 5: Verify, publish, and deploy

**Files:**
- Modify: `docs/superpowers/plans/2026-09-05-dashboard-vendor-css-isolation.md` (checkboxes only)

- [x] **Step 1: Run the final local gate**

Run the focused Vitest style/page tests, full Playwright suite, build, CSS isolation assertion, typecheck, and lint with timeouts. Expected: exit 0 throughout.

- [ ] **Step 2: Commit and open the PR**

Stage only this branch's spec, plan, CSS, test, script, manifest, and golden changes. Push `fix/dashboard-vendor-css-isolation` and open a PR to `main` with the root cause and verification evidence.

- [ ] **Step 3: Use one final CI verdict**

Wait for the PR's decision workflow. Do not start redundant full-suite runs. Any failure outside the documented baseline blocks deployment.

- [ ] **Step 4: Deploy the exact PR SHA**

Run `kivou-deploy.sh staging <40-character-SHA>`, including backup and disposable-database rehearsal. Verify readiness, active links, bundle selector isolation, fonts, and the nine routes in Chromium; save before/after captures outside tracked source files.
