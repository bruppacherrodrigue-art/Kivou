# Prospect drawer mail parity — implementation plan

> **Goal:** Make the production prospect landing show the exact commercial
> sentence rendered by the current mail, normalize holder names across every
> customer surface, and render an honest three-slot landing cohort.

**Architecture:** Keep source facts untouched. Reuse the mail's pure family
sentence renderer at landing time, freeze that sentence in the existing
`for_you_sentence` record, and make the drawer choose only that trusted mail
sentence or the deterministic factual fallback. Normalize company names only
at customer-facing projection boundaries. Expose explicit landing-cohort
metadata so React never guesses whether inventory is missing.

**Stack:** Python 3.12, FastAPI, SQLAlchemy Core, React 19, TypeScript, Vitest,
Testing Library, Playwright CLI.

---

## Task 1: One mail sentence generator and no legacy drawer generator

**Files:**

- Modify: `tests/test_personalization_prospect_mail.py`
- Modify: `tests/test_attribution_landing.py`
- Modify: `tests/test_feed_facts.py`
- Modify: `src/signals/personalization/prospect_mail.py`
- Modify: `src/signals/api/routes_attribution.py`
- Modify: `src/signals/api/routes_signals.py`
- Delete: `src/signals/api/commercial_context.py`
- Delete: `tests/test_commercial_context.py`
- Modify: `frontend/src/prospecting/components/SignalContent.tsx`
- Modify: `frontend/src/prospecting/models.ts`
- Modify: `frontend/src/prospecting/__tests__/signal-content.test.tsx`
- Modify: `frontend/src/prospecting/__tests__/signal-detail-regression.test.tsx`
- Modify: `frontend/tests/visual/prospecting-v11.spec.ts`

### Step 1: Write failing sentence tests

Add a pure-renderer assertion for `roofing` + `SILLINGY`:

```python
assert prospect_relevance_sentence(
    family_key="roofing", company_city="SILLINGY", department="Savoie"
) == (
    "Sur ce type de lot, le titulaire sous-traite souvent la couverture et "
    "la zinguerie, et vous êtes couvreur-zingueur à Sillingy."
)
```

Add an assisted-prospect landing regression: create the target through the
real preparation service, follow its signed link in QA mode, and assert the
promised signal's persisted sentence equals the sentence present in its mail.
Also assert no lot reference, engine key or retired copy survives.

Run:

```bash
.venv/bin/pytest -q tests/test_personalization_prospect_mail.py tests/test_attribution_landing.py
```

Expected: RED because the family sentence is private and assisted targets are
not read by the landing.

### Step 2: Expose and reuse the pure family renderer

In `prospect_mail.py`, extract the current `family_sentence` construction into
`prospect_relevance_sentence(...)`. Make `render_prospect_mail()` call it.
Keep normal case and optional distance behavior in this single function.

In `routes_attribution.py`, resolve `prospect_target` first by
`attribution_member_ref`, call the same renderer with its stored family and
company location, and freeze the result in the promised signal's existing
`for_you_sentence` row. Do not reuse the legacy acquisition artifact's generic
`for_you_sentence`; if no current mail context exists, leave the drawer to its
factual fallback.

### Step 3: Remove the legacy drawer generator

Delete `commercial_context.py` and its tests. In signal detail, publish a
minimal `commercial_context.reason` selected as follows:

1. the safe frozen sentence for the exact landing appât;
2. otherwise the deterministic factual fallback already built by the feed
   view.

Do not inspect profile offer categories or plausible-need category keys.
Update `SignalContent` and its fixtures so the UI renders only this contract.

Run:

```bash
.venv/bin/pytest -q tests/test_personalization_prospect_mail.py tests/test_attribution_landing.py tests/test_feed_facts.py
```

```bash
cd frontend && npm test -- --run src/prospecting/__tests__/signal-content.test.tsx src/prospecting/__tests__/signal-detail-regression.test.tsx
```

Expected: GREEN.

### Step 4: Prove retirement

Run:

```bash
rg -n "une opportunité de positionner" . --glob '!frontend/node_modules/**' --glob '!.git/**'
```

Expected: exit 1 and no output.

Commit:

```bash
git add -A
git commit -m "fix(prospecting): share mail reason with signal drawer"
```

## Task 2: Normalize holder identity on every customer surface

**Files:**

- Modify: `tests/test_feed_facts.py`
- Modify: `tests/test_dashboard.py`
- Modify: `tests/test_companies_list.py`
- Modify: `tests/test_company_directory_api.py`
- Modify: `src/signals/feed/view.py`
- Modify: `src/signals/feed/factual_display.py`
- Modify: `src/signals/api/cards.py`
- Modify: `src/signals/api/routes_signals.py`
- Modify: `src/signals/companies/contracts.py`
- Modify: `src/signals/companies/listing.py`
- Modify: `src/signals/client_value/directory.py`
- Modify: `src/signals/api/routes_company_directory.py`

### Step 1: Write CMCD projection regressions

Use `CONSTRUCTION DE MAISONS ET CHARPENTES DU DAUPHINE - CMCD` as the raw
source name and assert `CMCD` in:

- a signal card and detail;
- an Aujourd'hui card;
- the company list and follow-up block;
- an annuaire row and dossier identity.

Also assert the raw value remains stored unchanged where the test has direct
database access.

Run only the added test nodes. Expected: RED on customer projections.

### Step 2: Apply the mail normalizer at projection boundaries

Import and call the existing `normalize_holder_name()` rather than adding a
frontend helper or a second backend implementation. Cover base display names,
winner-enrichment overrides, official company views and directory views.
Leave identifiers, matching values and stored legal names unchanged.

Run the exact backend test files above. Expected: GREEN.

Commit:

```bash
git add src tests
git commit -m "fix(companies): normalize holder names across customer views"
```

## Task 3: Correct clocks, locations and incomplete landing inventory

**Files:**

- Modify: `tests/test_attribution_landing.py`
- Modify: `src/signals/accounts/service.py`
- Modify: `src/signals/api/routes_signals.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/test/harness.tsx`
- Modify: `frontend/src/prospecting/adapters.ts`
- Modify: `frontend/src/prospecting/components/SignalContent.tsx`
- Modify: `frontend/src/pages/SignalsFeed.tsx`
- Modify: `frontend/src/prospecting/Prospecting.module.css`
- Modify: `frontend/src/prospecting/__tests__/adapters.test.ts`
- Modify: `frontend/src/prospecting/__tests__/signal-content.test.tsx`
- Modify: `frontend/src/prospecting/__tests__/signal-feed-regression.test.tsx`

### Step 1: Write failing display tests

Assert:

- award date wins over notice publication in `signalClock()`;
- `SAINT-ONDRAS` + `ISÈRE` renders `Saint-Ondras (Isère)`;
- the calendar says `Avis publié le`, never `BOAMP publié le`;
- a provisional cohort of one or two real items renders all available items
  plus exactly one non-interactive row `Vos prochains signaux arriveront ici`;
- a complete three-item cohort has no waiting row.

Run:

```bash
cd frontend && npm test -- --run src/prospecting/__tests__/adapters.test.ts src/prospecting/__tests__/signal-content.test.tsx src/prospecting/__tests__/signal-feed-regression.test.tsx
```

Expected: RED.

### Step 2: Expose cohort metadata

Add an account-scoped read returning the exact landing signal key, expected
cohort size (`3`) and materialized active cohort size. Return this metadata
from `GET /signals` only for provisional landing profiles. Do not synthesize
feed items and do not change counters or pagination.

Add backend cases for zero, one and two compatible neighbours and assert the
appât remains in every materialized cohort.

### Step 3: Render the corrected UI contract

In `signalClock`, check `contract.dates.award` before notice publication. Keep
publication as the final factual fallback. Reuse `signalPlace` and
`normalCasePlace` for city + department.

Rename the calendar label to `Avis publié le`. In `SignalsFeed`, append one
semantic, non-clickable waiting row when `landing_cohort.materialized < 3`.
Do not include it in `items.length`, server counts, navigation or pagination.

Run the focused backend landing tests and the three frontend files. Expected:
GREEN.

Commit:

```bash
git add src tests frontend
git commit -m "fix(prospecting): complete the prospect landing cohort"
```

## Task 4: Focused pre-deploy verification

Run:

```bash
.venv/bin/pytest -q tests/test_personalization_prospect_mail.py tests/test_attribution_landing.py tests/test_feed_facts.py tests/test_dashboard.py tests/test_companies_list.py tests/test_company_directory_api.py
```

```bash
cd frontend && npm test -- --run src/prospecting/__tests__/adapters.test.ts src/prospecting/__tests__/signal-content.test.tsx src/prospecting/__tests__/signal-detail-regression.test.tsx src/prospecting/__tests__/signal-feed-regression.test.tsx
```

```bash
cd frontend && npm run typecheck && npm run lint && npm run build
```

```bash
rg -n "une opportunité de positionner" . --glob '!frontend/node_modules/**' --glob '!.git/**'
```

Review `git diff --check` and the complete branch diff. Do not run unrelated
test suites locally.

## Task 5: Pull request, production deploy and Playwright proof

Push the branch, open a PR and wait for its required CI. Merge only a green,
mergeable head. Deploy the exact merged SHA with the production deployer and
existing backup/rollback guard.

Generate a short-lived signed QA attribution token for an eligible production
opportunity without printing it. Use the Playwright CLI wrapper to:

1. open the QA landing URL and follow the redirect;
2. assert the drawer heading and `Pourquoi ça vous concerne` are visible;
3. assert the page and reason exclude `une opportunité de positionner`, lot
   references, CPV labels and engine keys;
4. assert `Attribué le`, normal-case city + department, and `Avis publié le`
   when those facts exist;
5. assert either three real signals or the waiting row behind the open appât;
6. save a full-page screenshot under `output/playwright/`.

Finally verify the deployed API/frontend report the merged SHA and that the
production health endpoints remain healthy. Never expose the QA token or
session cookie in command output or the final report.
