# Official SaaS Company Profile Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for every task and superpowers:verification-before-completion before delivery.

**Goal:** Add a protected, official-source company profile reachable only from an unlocked Kivou signal, without Apollo or any Acquisition Engine dependency.

**Architecture:** A new `signals.companies` boundary owns client-safe contracts, exact official identity resolution, one additive SaaS table, account-scoped reads, and response assembly. Signal detail creates or resolves an opaque random Kivou key only after the existing paywall grants access. Company reads independently re-evaluate account ownership, current ICP revision, invalidation, plan limits, and Discovery/paid access before returning official facts and currently unlocked related signals. The React page renders only that API contract inside the existing protected app shell.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy Core, Alembic, pytest; React 19, TypeScript, React Router, CSS Modules, Vitest/Testing Library, Playwright CLI.

---

## Global invariants

- Do not modify any file under the prohibited acquisition modules listed in the mission.
- Do not add Apollo, another enrichment provider, people data, contact data, campaign behavior, billing behavior, or a new entitlement.
- Do not put company facts in URLs, navigation state, or browser storage; only `company_key` may travel.
- A missing company, a foreign company, a company with only locked signals, and a company with no remaining current signal all return the same `404 company_not_found` envelope.
- Reuse `feed_access(...).is_unlocked(item)` as the final access decision.
- Preserve official and Kivou provenance; never promote a plausible need into a published fact.

### Task 1: Client-safe contracts and exact official identity

**Files:**

- Create: `src/signals/companies/__init__.py`
- Create: `src/signals/companies/contracts.py`
- Create: `src/signals/companies/identity.py`
- Test: `tests/test_saas_company_contracts.py`
- Test: `tests/test_saas_company_identity.py`

**Step 1: Write failing contract tests**

Cover:

- frozen, extra-forbidden `CompanyProfile`, `CompanyOfficialIdentity`, `CompanyRelatedSignal`, and coverage contracts;
- bounded identifier arrays, needs, fit reasons, and related signals;
- no Apollo ID, acquisition ref, contact ref, supplier ref, score, person, email, or phone field in serialized contracts;
- timezone-aware `observed_at` and HTTPS-only optional official website.

**Step 2: Run the contract tests and verify RED**

Run: `uv run pytest tests/test_saas_company_contracts.py -q`

Expected: import failure because `signals.companies.contracts` does not exist.

**Step 3: Implement the minimal contracts**

Use Pydantic v2 with `extra="forbid"`, frozen models, explicit bounds, literal provenance values, and the existing signal vocabulary where client-safe.

**Step 4: Write failing identity tests**

Cover this resolution order:

1. first exact official identifier + scheme + country;
2. exact domain from a safe official HTTPS website + country;
3. opportunity-scoped fallback;
4. name-only homonyms never merge;
5. normalization is deterministic but never fuzzy;
6. opaque keys are random `cmp_…` values and contain no source facts.

**Step 5: Run identity tests and verify RED**

Run: `uv run pytest tests/test_saas_company_identity.py -q`

Expected: missing identity implementation.

**Step 6: Implement minimal identity helpers**

Extract one display organization from normalized `awardee_parties`, validate HTTPS URLs with `urlsplit`, normalize exact identifiers/domain, hash the Kivou identity namespace, and generate random opaque keys with `secrets`.

**Step 7: Verify GREEN**

Run: `uv run pytest tests/test_saas_company_contracts.py tests/test_saas_company_identity.py -q`

Expected: PASS.

**Step 8: Commit**

```bash
git add src/signals/companies tests/test_saas_company_contracts.py tests/test_saas_company_identity.py
git commit -m "feat(companies): define official company identity"
```

### Task 2: Additive SaaS persistence and migration

**Files:**

- Create: `src/signals/companies/schema.py`
- Create: `src/signals/companies/store.py`
- Create: `src/signals/persistence/migrations/versions/0022_saas_company_profile.py`
- Modify: `src/signals/persistence/migrations/env.py`
- Modify: migration head assertions under `tests/` that intentionally track the current head
- Test: `tests/test_saas_company_migration.py`
- Test: `tests/test_saas_company_store.py`

**Step 1: Write the failing migration test**

Assert:

- `0022_saas_company_profile` is the single head after `0021_reliability_operations`;
- upgrade adds exactly `saas_company`;
- downgrade returns to `0021_reliability_operations` and drops only that table;
- migrated SQLite columns match the Core table;
- PostgreSQL offline SQL contains the table, unique identity fingerprint, source-award foreign key, and no acquisition/PII/provider columns.

**Step 2: Run migration test and verify RED**

Run: `uv run pytest tests/test_saas_company_migration.py -q`

Expected: missing revision/table.

**Step 3: Implement schema and migration**

Create `saas_company` with:

- `company_key` primary key;
- unique `identity_fingerprint`;
- `identity_method` and bounded normalized validation evidence;
- `source_award_key` foreign key;
- `origin_signal_key` foreign key;
- official name, country, address, normalized identifiers JSON, optional safe website;
- official observation, creation, and update instants.

Import the new schema into Alembic metadata. Update only tests whose constants mean “current repository head”; keep historical migration relationships unchanged.

**Step 4: Verify migration GREEN**

Run: `uv run pytest tests/test_saas_company_migration.py tests/test_persistence_migrations.py -q`

Expected: PASS.

**Step 5: Write failing store tests**

Cover:

- idempotent exact identity creation;
- same official identifier converges;
- name-only distinct opportunities remain separate;
- conflicting random insert converges through the unique fingerprint;
- stored JSON contains only normalized official identifiers, never a full notice payload;
- source facts remain separate and are not overwritten by later calls.

**Step 6: Run store tests and verify RED**

Run: `uv run pytest tests/test_saas_company_store.py -q`

Expected: missing store behavior.

**Step 7: Implement store and verify GREEN**

Use SQLAlchemy Core and a nested transaction/savepoint for portable concurrent insert convergence.

Run: `uv run pytest tests/test_saas_company_store.py tests/test_saas_company_migration.py -q`

Expected: PASS.

**Step 8: Commit**

```bash
git add src/signals/companies src/signals/persistence/migrations tests
git commit -m "feat(companies): persist opaque company profiles"
```

### Task 3: Account-scoped company service and authorization

**Files:**

- Create: `src/signals/companies/service.py`
- Test: `tests/test_saas_company_service.py`
- Test: `tests/test_saas_company_architecture.py`

**Step 1: Write failing service tests**

Using real account, ICP, award, materialization, billing, and Discovery helpers, cover:

- one current unlocked signal authorizes and renders official identity;
- account B cannot access account A’s company;
- locked-only matches do not authorize;
- invalidated materializations are excluded;
- an old ICP revision is excluded;
- a permanent Discovery grant still authorizes after aging;
- paid history rules remain final;
- no remaining unlocked signal returns no profile;
- only currently unlocked related signals are included;
- identical exact official identities link; name-only homonyms do not;
- official address and all identifiers survive independently of Kivou analysis;
- related signal order follows the server’s existing signal ordering;
- response contains no acquisition or locked teaser fields.

**Step 2: Run service tests and verify RED**

Run: `uv run pytest tests/test_saas_company_service.py -q`

Expected: missing service.

**Step 3: Implement the minimum service**

Add:

- `ensure_company_for_unlocked_signal(connection, item, now)` to load the exact public organization from `display.from_award_key`, persist/resolve the opaque company, and return the key;
- `company_profile_for_account(...)` to load the opaque row, query only current account-owned materializations, re-resolve official identities, filter by exact fingerprint, apply `FeedAccess.is_unlocked`, and build client-safe related-signal projections.

Keep a bounded maximum related-signal response and never expose a truncation as completeness if the bound is reached.

**Step 4: Write architecture tests**

Reject forbidden imports and forbidden serialized names across the new package. Assert there is no HTTP client, Apollo string, people/contact field, acquisition table, browser-facing provider ID, new entitlement, or mutation of feed ordering.

**Step 5: Verify GREEN**

Run: `uv run pytest tests/test_saas_company_service.py tests/test_saas_company_architecture.py -q`

Expected: PASS.

**Step 6: Commit**

```bash
git add src/signals/companies tests/test_saas_company_service.py tests/test_saas_company_architecture.py
git commit -m "feat(companies): enforce company profile access"
```

### Task 4: Authenticated API and unlocked signal link

**Files:**

- Create: `src/signals/api/routes_companies.py`
- Modify: `src/signals/api/app.py`
- Modify: `src/signals/api/errors.py`
- Modify: `src/signals/api/routes_signals.py`
- Test: `tests/test_saas_company_api.py`
- Modify: existing billing/paywall API tests only to assert the new unlocked field and unchanged locked allowlist

**Step 1: Write failing API tests**

Cover:

- anonymous `GET /companies/{key}` returns 401;
- unlocked signal detail contains `company_key`;
- locked detail never contains `company_key`;
- company GET returns the approved contract;
- missing, foreign, locked-only, invalidated, wrong-revision, and no-current-signal cases share the same 404 body;
- account A/B leakage is absent even when the opaque key is known;
- Discovery permanent grants work;
- no browser field contains official facts except in the authenticated company response;
- exact divergence between two official source values is not silently merged.

**Step 2: Run API tests and verify RED**

Run: `uv run pytest tests/test_saas_company_api.py -q`

Expected: route and link missing.

**Step 3: Implement route and link**

Register `company_not_found` in the stable error catalogue, include the router, and keep all work inside existing request transactions. Generate the company key only in the already-unlocked detail branch. Do not change locked response shape.

**Step 4: Verify GREEN and paywall regressions**

Run:

```bash
uv run pytest tests/test_saas_company_api.py tests/test_billing_paywall.py tests/test_feed_ownership.py tests/test_target_icp_revision.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add src/signals/api tests
git commit -m "feat(companies): expose protected company profiles"
```

### Task 5: Frontend contract, protected route, and RED tests

**Files:**

- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/test/harness.tsx`
- Create: `frontend/src/companies/companyProfile.test.tsx`
- Modify: `frontend/src/signals/detail.test.tsx`

**Step 1: Define the exact frontend API types**

Mirror only the backend contract. Add `company_not_found` to `ApiErrorCode`; add no provider, acquisition, contact, score, or raw notice type.

**Step 2: Add fixtures and failing tests**

Cover:

- official name and source;
- absolute observation date;
- official address/identifiers when present;
- absent-field hiding and one compact coverage notice;
- safe HTTPS external website link and rejected unsafe URL defense;
- currently accessible signal links, amount, timing, needs, and fit;
- no locked signal rendering;
- loading, partial official identity, inaccessible, and expired-session flows;
- FR and EN;
- one `h1`, correct section heading hierarchy, keyboard-focusable actions;
- unlocked signal CTA navigation using only `company_key`;
- no CTA on locked detail;
- navigation state and `sessionStorage` contain no company facts.

**Step 3: Run tests and verify RED**

Run:

```bash
cd frontend
npm run test -- --run src/companies/companyProfile.test.tsx src/signals/detail.test.tsx
```

Expected: missing page, route, and CTA.

**Step 4: Commit test/contract checkpoint**

```bash
git add frontend/src/api frontend/src/test frontend/src/companies frontend/src/signals/detail.test.tsx frontend/src/App.tsx
git commit -m "test(companies): specify company profile UI"
```

### Task 6: Implement the Kivou company page and translations

**Files:**

- Create: `frontend/src/pages/CompanyProfile.tsx`
- Create: `frontend/src/pages/CompanyProfile.module.css`
- Modify: `frontend/src/pages/SignalDetail.tsx`
- Modify: `frontend/src/pages/SignalDetail.module.css`
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`
- Modify: files from Task 5 as needed for implementation

**Step 1: Implement the minimum page**

Use existing Kivou `Card`, `Callout`, `Badge`, `SectionHeading`, `ButtonLink`, and `ButtonExternalLink` surfaces. Follow the approved editorial order. Never render an empty data row.

**Step 2: Implement safe actions**

- `Examiner le signal` / `Review signal` routes to `/app/signals/:signalKey`.
- `Retour aux signaux` / `Back to signals` routes to `/app/signals`.
- The official website action appears only after a defensive frontend HTTPS validation and uses the shared external-link component.

**Step 3: Add all FR/EN copy**

Keep identical certainty in both dictionaries. Source labels and coverage messages are translated in the dictionaries, not supplied as display copy by the backend.

**Step 4: Verify targeted GREEN**

Run:

```bash
cd frontend
npm run typecheck
npm run lint
npm run test -- --run src/companies/companyProfile.test.tsx src/signals/detail.test.tsx
```

Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(companies): add official company profile page"
```

### Task 7: Technical documentation and invariant audit

**Files:**

- Create: `docs/reports/2026-08-23-saas-company-profile.md`
- Modify: `docs/ROAD_TO_LIVE.md` only where the shipped profile gate/status must be recorded
- Test: `tests/test_saas_company_architecture.py`

**Step 1: Document the delivered boundary**

Record:

- official-only field allowlist;
- identity resolution and homonym policy;
- opaque-key lifecycle;
- authorization and 404 behavior;
- no enrichment/provider cost;
- no PII or Acquisition Engine dependency;
- migration and rollback;
- operational limitations and future contract gate for any external enrichment.

**Step 2: Audit forbidden paths**

Run:

```bash
git diff --name-only origin/main...HEAD
rg -n "Apollo|apollo|AcquisitionCompanyProfile|contact_ref|supplier_ref|acquisition_opportunity_id|business_email|phone" src/signals/companies frontend/src/pages/CompanyProfile.tsx frontend/src/api/types.ts
```

Expected: no provider/internal/PII field in implementation; any documentation mention must describe absence only.

**Step 3: Commit**

```bash
git add docs tests/test_saas_company_architecture.py
git commit -m "docs(companies): document official profile boundary"
```

### Task 8: Full backend and frontend verification

**Files:** None unless a test reveals a defect; fix defects via a new RED test first.

**Step 1: Backend checks**

Run:

```bash
uv run ruff check .
uv run pytest
```

Expected: all tests pass; only existing environment-dependent skips remain.

**Step 2: Frontend checks**

Run:

```bash
cd frontend
npm run typecheck
npm run lint
npm run test -- --run
npm run build
```

Expected: all commands pass.

**Step 3: Repository checks**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and only intended changes.

### Task 9: Browser validation at required widths

**Files:**

- Modify: `frontend/src/pages/CompanyProfile.module.css` only if browser evidence exposes a defect.
- Add or update frontend tests before each functional fix.

**Step 1: Start deterministic local API/frontend fixtures**

Use the repository's local app setup with seeded official data. Do not call any provider.

**Step 2: Inspect with a real browser**

At 1440, 1024, 768, 390, and 320 pixels verify:

- `document.documentElement.scrollWidth <= clientWidth`;
- one visible `h1` and ordered `h2` headings;
- no clipped description, identifier, URL, keyword-like token, or amount;
- all actions keyboard reachable with visible focus;
- external link semantics;
- browser back returns to the unlocked signal;
- session expiry redirects to login;
- no essential content disappears at any width.

Capture screenshots for review but do not commit generated artifacts unless repository convention requires it.

**Step 3: Run focused tests after any CSS fix**

Run:

```bash
cd frontend
npm run typecheck
npm run lint
npm run test -- --run src/companies/companyProfile.test.tsx
```

Expected: PASS.

### Task 10: Final commit, push, and dedicated PR

**Files:** All intended task files.

**Step 1: Review the complete change**

Run:

```bash
git diff --stat origin/main...HEAD
git diff --name-only origin/main...HEAD
git log --oneline origin/main..HEAD
git diff --check origin/main...HEAD
```

Verify no prohibited module path appears.

**Step 2: Create the final targeted implementation commit if uncommitted fixes remain**

```bash
git add <exact intended files>
git commit -m "feat(companies): add official SaaS company profiles"
```

**Step 3: Push without force**

```bash
git push -u origin feat/saas-company-profile-apollo
```

**Step 4: Open the PR without merging**

The PR body must document:

- the official-only field allowlist;
- no provider call and zero enrichment cost;
- exact identity resolution and homonym fail-closed behavior;
- cache policy: not applicable because no provider enrichment exists;
- cross-account, current-revision, invalidation, Discovery, and paywall protections;
- no personal data;
- no Acquisition Engine file or contract changes;
- backend/frontend/browser verification results;
- remaining limitation: no third-party firmographic enrichment.

**Step 5: Verify remote state**

Run:

```bash
gh pr view --json url,number,state,isDraft,headRefName,baseRefName,commits,statusCheckRollup
git status --short
```

Expected: dedicated open PR, base `main`, no merge/deploy, clean worktree.
