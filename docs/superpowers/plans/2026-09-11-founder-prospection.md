# Founder Prospection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver and deploy the read-only `/prospection` Founder Console page using the populated production supplier directory, runtime journals, systemd timer state, and existing conversion truth.

**Architecture:** Add a focused `founder_api.prospection` read model behind one bounded authenticated endpoint. Keep the current overview intact, switch the founder shell by pathname, and place all new page rendering in a dedicated React component with server-side filtering and pagination.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Pydantic 2, PostgreSQL/SQLite tests, React 19, TypeScript, Vitest Testing Library, Vite, Playwright, nginx, systemd.

---

### Task 1: Add the Prospection read contract and real directory page

**Files:**
- Create: `src/signals/founder_api/prospection.py`
- Create: `tests/founder_api/test_prospection.py`
- Modify: `src/signals/founder_api/read_models.py`

- [ ] **Step 1: Write failing tests for totals, facets, filters, and pagination**

Seed 27 active `supplier_directory` rows plus one suppressed row in the shared SQLite test engine. Assert that `FounderReadService.prospection()` returns version `founder-prospection-v1`, global totals independent of filters, 25 rows on page 1, two rows on page 2, stable name/SIREN ordering, French-agnostic raw family keys, and exact behavior for `q`, `family`, `department`, `confirmed_domain`, `without_website`, and `reverification_required`.

```python
result = FounderReadService(engine, timer_reader=_stopped_timer).prospection(
    now=NOW,
    page=1,
    page_size=25,
    q="beton",
    family="ready_mix_concrete",
    department="69",
    directory_status="confirmed_domain",
)
assert result.version == "founder-prospection-v1"
assert result.directory.summary.company_count == 27
assert result.directory.pagination.page_size == 25
assert all(row.confirmed_domain for row in result.directory.rows)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `uv run pytest -n 0 tests/founder_api/test_prospection.py -q`

Expected: collection or import failure because `signals.founder_api.prospection` and `FounderReadService.prospection` do not exist.

- [ ] **Step 3: Implement immutable contracts and directory projection**

Create focused Pydantic models for summary counts, facets, directory rows, pagination, queue, targeting, results, timer, and the top-level response. Read active directory rows once, compute global totals/facets, apply normalized filters in the service, then slice a deterministic 25-row page.

```python
class FounderDirectoryStatus(StrEnum):
    CONFIRMED_DOMAIN = "confirmed_domain"
    WITHOUT_WEBSITE = "without_website"
    REVERIFICATION_REQUIRED = "reverification_required"

class FounderProspection(FounderContract):
    version: Literal["founder-prospection-v1"] = "founder-prospection-v1"
    generated_at: dt.datetime
    read_only: Literal[True] = True
    timer: FounderAcquisitionTimer
    queue: FounderProspectionQueue
    directory: FounderSupplierDirectory
    targeting: FounderTargetingCycle | None
    results: FounderProspectionResults
```

Expose a `prospection(...)` method on `FounderReadService` that delegates to this module and accepts the bounded query values.

- [ ] **Step 4: Run the directory tests and make them GREEN**

Run: `uv run pytest -n 0 tests/founder_api/test_prospection.py -q`

Expected: directory tests pass with 25-row pagination and filters.

- [ ] **Step 5: Commit the directory read model**

```bash
git add src/signals/founder_api/prospection.py src/signals/founder_api/read_models.py tests/founder_api/test_prospection.py
git commit -m "feat(founder): expose supplier directory read model"
```

### Task 2: Add runtime targeting, timer state, and real zero-capable results

**Files:**
- Modify: `src/signals/founder_api/prospection.py`
- Modify: `tests/founder_api/test_prospection.py`

- [ ] **Step 1: Write failing tests for the last cycle and stopped timer**

Seed one runtime cycle, its stage journal, the matching `supplier_discovery_run`, signal/award representation, and a cycle-created acquisition supplier. Inject a stopped timer fixture and assert exact cycle date/status, title, amount, families, SIRENE count, role-tier buckets, and merged deviation reasons.

```python
assert result.timer.state == "STOPPED"
assert result.timer.inactive_since == NOW - dt.timedelta(hours=2)
assert result.targeting.signal.title == "INSTALLATION CHANTIER - GROS-OEUVRE"
assert result.targeting.sirene_account_count == 75
assert result.targeting.email_counts_by_level[0].level == 1
assert result.targeting.deviation_counts[0].reason_code == "VERIFIED_CONTACT_NOT_FOUND"
```

Also assert that a cycle older than 48 hours is returned with `recent=False`, while an empty database produces `targeting=None` without losing timer state.

- [ ] **Step 2: Write failing tests for all result counters**

Assert an empty database returns numeric zero for all six counts, an empty tuple for MRR, and `no_sends_yet=True`. Seed campaign members, accepted provider openings, conversion clicks, non-QA landings, profile confirmations, PAID/MRR/CHURNED events, then assert distinct account counts and latest known MRR grouped by currency.

- [ ] **Step 3: Run the tests and verify RED**

Run: `uv run pytest -n 0 tests/founder_api/test_prospection.py -q`

Expected: assertions fail because targeting, timer, and results still return their minimal defaults.

- [ ] **Step 4: Implement bounded systemd inspection**

Use `subprocess.run` with an argument tuple, `shell=False`, `LC_ALL=C`, a two-second timeout, and the fixed unit `kivou-acquisition-production.timer`. Parse only allowlisted `key=value` properties. Map loaded active states to `RUNNING`, a loaded inactive state to `STOPPED`, and failures to `UNKNOWN`; use aware UTC timestamps.

```python
completed = subprocess.run(
    ("systemctl", "show", ACQUISITION_TIMER_UNIT, "--no-pager", *properties),
    capture_output=True,
    check=False,
    text=True,
    timeout=2,
    env={**os.environ, "LC_ALL": "C"},
)
```

- [ ] **Step 5: Implement targeting and commercial queries**

Resolve the most recently updated runtime cycle. Select its exact discovery journal inside the cycle window, the deterministic representative award, cycle-created opportunities, contacts, and stage reasons. Query only persisted campaign/provider/conversion/landing facts for Results and compute latest MRR without estimates.

- [ ] **Step 6: Run focused backend tests and static checks**

Run: `uv run pytest -n 0 tests/founder_api/test_prospection.py tests/founder_api/test_read_models.py -q`

Run: `uv run ruff check src/signals/founder_api tests/founder_api`

Expected: all pass, with no Ruff diagnostics.

- [ ] **Step 7: Commit runtime projections**

```bash
git add src/signals/founder_api/prospection.py tests/founder_api/test_prospection.py
git commit -m "feat(founder): report acquisition runtime and results"
```

### Task 3: Publish the authenticated endpoint

**Files:**
- Modify: `src/signals/founder_api/app.py`
- Modify: `tests/founder_api/test_prospection.py`

- [ ] **Step 1: Write failing API boundary tests**

Call `/api/founder/prospection?page=1&page_size=25` with the origin/user headers and assert 200 plus the versioned payload. Assert 403 without trusted headers, 422 for page 0, page size 26, overlong search, and an invalid status, and 503 when no read service is mounted.

- [ ] **Step 2: Run the route test and verify RED**

Run: `uv run pytest -n 0 tests/founder_api/test_prospection.py -q`

Expected: authenticated request returns 404.

- [ ] **Step 3: Add the GET-only route**

Declare bounded FastAPI `Query` parameters and map SQLAlchemy, timer, and runtime read failures to the same fail-closed 503 semantics as the overview. Do not mount POST, PATCH, DELETE, or `/api/founder/actions/*`.

- [ ] **Step 4: Run Founder API tests**

Run: `uv run pytest -n 0 tests/founder_api -q`

Expected: all Founder API tests pass.

- [ ] **Step 5: Commit the endpoint**

```bash
git add src/signals/founder_api/app.py tests/founder_api/test_prospection.py
git commit -m "feat(founder): add prospection endpoint"
```

### Task 4: Build the routed Prospection interface

**Files:**
- Create: `frontend/founder/src/ProspectionPage.tsx`
- Create: `frontend/founder/src/ProspectionPage.test.tsx`
- Modify: `frontend/founder/src/FounderApp.tsx`
- Modify: `frontend/founder/src/FounderApp.test.tsx`
- Modify: `frontend/founder/src/api.ts`
- Modify: `frontend/founder/src/types.ts`
- Modify: `frontend/founder/src/styles.css`

- [ ] **Step 1: Add TypeScript contracts and a failing routed-page test**

Mirror `founder-prospection-v1` exactly. In jsdom, push `/prospection`, mock session plus a production-shaped Prospection response with an empty queue and 27 directory rows, and assert navigation order `Aujourd'hui`, `Prospection`, `Système`; Annuaire before File du jour; global counters; 25 visible rows; stopped-since text; compact Ciblage; and seven numeric Results metrics.

- [ ] **Step 2: Add failing interaction tests**

Assert changing family, department, status, search, and page calls `/api/founder/prospection` with encoded parameters. With one fixture queue item, assert the four disabled actions expose `Disponible quand le mode assisté sera livré`, `Mail` opens the right drawer with the full subject/body, and Escape closes it.

- [ ] **Step 3: Run Vitest and verify RED**

Run: `npm test -- --run founder/src/ProspectionPage.test.tsx founder/src/FounderApp.test.tsx`

Working directory: `frontend`

Expected: tests fail because the page, contracts, and API loader do not exist.

- [ ] **Step 4: Implement the pathname-aware shell and loader**

Keep the existing overview components unchanged. On `/prospection`, load session plus `loadFounderProspection(query, signal)`; on other paths load the overview. Render plain same-origin links so nginx's existing Founder-only SPA fallback remains authoritative.

- [ ] **Step 5: Implement the four blocks and right drawer**

Render Annuaire first only when `queue.items.length === 0`. Use labelled controls, a dense table, previous/next buttons, compact timer/targeting/results cards, exact empty copy, disabled action wrappers with keyboard-focusable tooltips, and an accessible right-side mail detail.

- [ ] **Step 6: Apply the existing visual system and responsive rules**

Reuse the existing CSS custom properties and Instrument Sans. Add only `control-prospection-*` selectors; keep rows compact, preserve horizontal table scrolling, and collapse filters/metrics cleanly below 760px.

- [ ] **Step 7: Run frontend verification**

Run from `frontend`:

```bash
npm test -- --run founder/src/FounderApp.test.tsx founder/src/ProspectionPage.test.tsx
npm run typecheck
npm run lint
npm run build:founder
```

Expected: all tests and checks pass; `dist-founder/index.html` and hashed assets are produced.

- [ ] **Step 8: Commit the interface**

```bash
git add frontend/founder/src
git commit -m "feat(founder): add prospection page"
```

### Task 5: Verify, integrate, deploy, and capture production

**Files:**
- Modify: `docs/superpowers/plans/2026-09-11-founder-prospection.md` only to tick completed steps
- Create outside Git tracking: `artifacts/founder-prospection-production.png`

- [ ] **Step 1: Run the complete relevant verification**

Run:

```bash
uv run pytest -n 0 tests/founder_api tests/test_ops_nginx_routes.py -q
uv run ruff check src/signals/founder_api tests/founder_api
cd frontend && npm test -- --run founder/src && npm run typecheck && npm run lint && npm run build:founder
```

Expected: zero failures and a successful Founder production build.

- [ ] **Step 2: Rebase, push, and integrate through GitHub**

Fetch `origin/main`, rebase the feature branch, rerun the focused verification, push the branch, open a concise PR, wait for required GitHub checks, and merge only after every required check is green.

- [ ] **Step 3: Deploy the merged SHA**

Run the repository's production deployment entry point `kivou-deploy.sh` against the exact merged `origin/main` SHA. Confirm migration head, the active `kivou-founder-api` service, and the deployed frontend files before public HTTP checks.

- [ ] **Step 4: Smoke-test the protected production route**

Verify unauthenticated `https://control.kivou.eu/prospection` returns 401; authenticated page and `/api/founder/prospection?page=1&page_size=25` return 200; `https://kivou.eu/api/founder/prospection` remains 404; the JSON reports real counts and `read_only=true`.

- [ ] **Step 5: Capture the populated page with Playwright**

Use Playwright HTTP credentials without writing them into the repository, open `https://control.kivou.eu/prospection` at desktop width, wait for the real `supplier_directory` rows, and save `artifacts/founder-prospection-production.png`. Inspect the image for legible counters, filters, at least several real businesses, the stopped timer, and no error state.

- [ ] **Step 6: Report evidence**

Return the merged and deployed SHA, test command outcomes, production HTTP statuses, live directory totals, timer text, and a clickable link to the screenshot. Never repeat the Basic Auth password.
