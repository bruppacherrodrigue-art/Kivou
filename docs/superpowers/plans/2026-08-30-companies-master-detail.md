# C002 Companies Master–Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an account-scoped Companies master–detail workspace whose award rows come from the feed in one bounded pass, whose selected profile uses the same published presentation artifact, and whose desktop/mobile navigation is accessible and deterministic.

**Architecture:** The feed returns `company_key` only for unlocked signals, resolved in one backend batch. The browser builds one award row per unlocked feed item without calling every signal detail. Selecting a row loads one authorized company profile; that profile attaches presentations using one backend batch read. A shared strict frontend parser rejects malformed artifacts wholesale. URL state is `/app/companies/:companyKey?signal=:signalId`, with desktop split panes and a mobile single-pane drill-down.

**Tech Stack:** Python 3.12, SQLAlchemy Core, FastAPI, Pydantic, React 19, TypeScript, React Router, Vitest, Testing Library, Playwright.

---

## Dependency and branch

- Start from the exact `main` SHA produced after PR 2 has been squash-merged and both of its exact-main CI jobs have executed real steps successfully.
- Create `feat/119-companies-master-detail-v2`; push normally only. `CONTRIBUTING.md` forbids force-push and history rewriting.
- This PR replaces draft #122. Reuse its navigation/focus intent, not its commits, topology, detail-call fan-out, raw-title summaries or placeholder roles.

## File map

**Backend modify:**

- `src/signals/companies/service.py`
- `src/signals/companies/contracts.py`
- `src/signals/companies/indexing.py`
- `src/signals/api/routes_signals.py`
- `src/signals/api/routes_companies.py`
- `src/signals/feed/view.py`
- `tests/test_saas_company_service.py`
- `tests/test_saas_company_api.py`
- `tests/test_card_presentation_api.py`

**Frontend create:**

- `frontend/src/reference/dashboard/presentation.ts`
- `frontend/src/reference/dashboard/presentation.test.ts`
- `frontend/src/reference/dashboard/MasterDetailFrame.tsx`
- `frontend/src/reference/dashboard/MasterDetailFrame.test.tsx`

**Frontend modify:**

- `frontend/src/api/types.ts`
- `frontend/src/api/endpoints.ts`
- `frontend/src/pages/Companies.tsx`
- `frontend/src/pages/CompanyProfile.tsx`
- `frontend/src/companies/referenceCompanies.test.tsx`
- `frontend/src/companies/companyProfile.test.tsx`
- `frontend/src/reference/router/ReferenceLink.tsx`
- `frontend/src/i18n/fr.ts`
- `frontend/src/i18n/en.ts`
- `frontend/src/reference/dashboard/dashboard-reference.css`
- `frontend/tests/visual/fixtures.ts`
- `frontend/tests/visual/reference-port.spec.ts`
- `frontend/tests/visual/reference-goldens/dashboard-companies-desktop.png`
- `frontend/tests/visual/reference-goldens/dashboard-companies-mobile.png`

## Task 1: Resolve company keys for an unlocked feed page in one batch

**Files:**

- Modify: `src/signals/companies/service.py`
- Modify: `src/signals/companies/indexing.py`
- Modify: `src/signals/api/routes_signals.py`
- Modify: `src/signals/feed/view.py`
- Modify: `tests/test_saas_company_service.py`
- Modify: `tests/test_saas_company_api.py`

- [ ] **Step 1: Add failing batch, privacy and identity-collision tests**

```python
def test_feed_resolves_unlocked_company_keys_in_one_bounded_batch(alice, sql_counter):
    response = alice.get("/signals", params={"freshness": "all", "limit": 20})
    assert response.status_code == 200
    unlocked = [item for item in response.json()["items"] if not item["locked"]]
    assert unlocked
    assert all(item["company_key"].startswith("cmp_") for item in unlocked)
    assert sql_counter.count_table("contract_award") <= 1
    assert sql_counter.count_table("saas_company") <= 2


def test_locked_items_never_expose_or_resolve_company_keys(alice, monkeypatch):
    observed: list[frozenset[str]] = []
    original = company_service.ensure_companies_for_unlocked_signals

    def recording(connection, *, items, now):
        observed.append(frozenset(item.signal.signal_key for item in items))
        return original(connection, items=items, now=now)

    monkeypatch.setattr(company_service, "ensure_companies_for_unlocked_signals", recording)
    body = alice.get("/signals").json()
    locked = [item for item in body["items"] if item["locked"]]
    assert all("company_key" not in item for item in locked)
    locked_ids = {item["signal_id"] for item in locked}
    assert len(observed) == 1
    assert observed[0].isdisjoint(locked_ids)
```

Add fixtures with identical normalized names but different official identifiers,
and different names sharing one identifier. Assert grouping follows the existing
official identity fingerprint, never a browser-side normalized name.

- [ ] **Step 2: Confirm RED**

Run: `uv run pytest -q tests/test_saas_company_service.py tests/test_saas_company_api.py -k 'batch or locked or collision'`

Expected: feed items lack `company_key` or current service performs one-signal calls.

- [ ] **Step 3: Implement one bounded service call**

Add this API to `companies/service.py`:

```python
def ensure_companies_for_unlocked_signals(
    connection: sa.Connection,
    *,
    items: tuple[feed_query.FeedSignal, ...],
    now: dt.datetime,
) -> dict[str, str | None]:
    if len(items) > feed_policy.MAXIMUM_PAGE_SIZE:
        raise ValueError("company resolution exceeds one feed page")
    indexed = index_signal_company_identities(
        connection,
        signal_keys=tuple(item.signal.signal_key for item in items),
    )
    return _persist_indexed_companies(connection, items=items, indexed=indexed, now=now)
```

Import `feed_policy` from `signals.feed.policy`. `_persist_indexed_companies`
must use existing identity fingerprints and
`get_or_create_company`; it must not group by the visible name. In
`list_signals`, derive `unlocked_items` after entitlement evaluation, resolve
their keys once, and pass a single supplied key into `feed_item`. Locked
serialization remains untouched and therefore omits the key.

- [ ] **Step 4: Run service/API suites**

Run:

```bash
uv run pytest -q tests/test_saas_company_service.py tests/test_saas_company_api.py tests/test_billing_paywall.py tests/test_feed_identity.py
uv run ruff check src/signals/companies src/signals/api/routes_signals.py src/signals/feed/view.py tests/test_saas_company_service.py tests/test_saas_company_api.py
```

Expected: PASS with bounded query assertions.

- [ ] **Step 5: Commit batch company keys**

```bash
git add src/signals/companies src/signals/api/routes_signals.py src/signals/feed/view.py tests/test_saas_company_service.py tests/test_saas_company_api.py
git commit -m "feat(companies): expose authorized company keys in batch"
```

## Task 2: Attach one immutable presentation batch to company profiles

**Files:**

- Modify: `src/signals/companies/contracts.py`
- Modify: `src/signals/companies/service.py`
- Modify: `src/signals/api/routes_companies.py`
- Modify: `tests/test_saas_company_service.py`
- Modify: `tests/test_saas_company_api.py`
- Modify: `tests/test_card_presentation_api.py`

- [ ] **Step 1: Add failing profile artifact tests**

```python
def test_company_profile_batches_presentations_for_all_related_signals(
    alice, published_fallbacks, sql_counter
):
    profile = alice.get(f"/companies/{published_fallbacks.company_key}").json()
    assert len(profile["related_signals"]) == 2
    assert {
        item["presentation"]["artifact_id"] for item in profile["related_signals"]
    } == published_fallbacks.artifact_ids
    assert sql_counter.count_table("card_presentation_artifact") == 1


def test_profile_rejects_stale_icp_revision_and_cross_tenant_artifacts(
    alice, stale_revision_artifact, bob_artifact
):
    profile = alice.get(f"/companies/{stale_revision_artifact.company_key}").json()
    serialized = json.dumps(profile)
    assert stale_revision_artifact.artifact_id not in serialized
    assert bob_artifact.artifact_id not in serialized
```

Add a concurrent-publication test: the service snapshots the selected artifact
IDs in its transaction and serializes those exact immutable rows even if a
newer row is published after selection.

- [ ] **Step 2: Confirm RED**

Run: `uv run pytest -q tests/test_saas_company_service.py tests/test_saas_company_api.py -k 'presentation or artifact or revision'`

Expected: `CompanyRelatedSignal` has no presentation.

- [ ] **Step 3: Extend the closed profile contract**

Add only these fields:

```python
class CompanyRelatedSignal(CompanyContract):
    signal_id: ShortText
    amount: CompanySignalAmount | None = None
    event: CompanySignalEvent
    buyer_name: ShortText | None = None
    awarded_company_name: ShortText
    presentation: PublishedCardPresentation | None = None
```

Narrow `CompanySignalEvent` to `status`, `clock`, `date` and
`award_date_note`; remove its `headline` and `why_now`. Remove `contract_title`,
`plausible_needs` and `fit` from the public profile contract. In
`company_profile_for_account`, finish the authorized signal scan,
build `{signal_key: (signal_revision, target_icp_revision)}`, call
`published_for_signals()` exactly once, and pass the selected artifact into
`_related_signal`. No generator, QA or provider is reachable.

- [ ] **Step 4: Run profile, presentation and architecture tests**

Run:

```bash
uv run pytest -q tests/test_saas_company_contracts.py tests/test_saas_company_service.py tests/test_saas_company_api.py tests/test_card_presentation_api.py tests/test_saas_company_architecture.py
uv run ruff check src/signals/companies src/signals/api/routes_companies.py tests/test_saas_company_service.py tests/test_saas_company_api.py
```

Expected: PASS, one artifact SELECT for any profile size up to 100.

- [ ] **Step 5: Commit profile artifacts**

```bash
git add src/signals/companies/contracts.py src/signals/companies/service.py src/signals/api/routes_companies.py tests/test_saas_company_service.py tests/test_saas_company_api.py tests/test_card_presentation_api.py
git commit -m "feat(companies): bind profiles to published presentations"
```

## Task 3: Centralize a strict fail-closed presentation parser

**Files:**

- Create: `frontend/src/reference/dashboard/presentation.ts`
- Create: `frontend/src/reference/dashboard/presentation.test.ts`
- Modify: `frontend/src/api/types.ts`

- [ ] **Step 1: Write the complete malformed-payload matrix**

```ts
it.each([
  ['not an object', 'broken'],
  ['unknown top-level key', { ...VALID_FALLBACK, rewrite: 'no' }],
  ['bad pair', { ...VALID_FALLBACK, status: 'PASS' }],
  ['missing evidence', withoutClaimEvidence(VALID_FALLBACK)],
  ['unknown variant', { ...VALID_FALLBACK, content: { ...VALID_FALLBACK.content, variant: 'SHORT' } }],
  ['invalid artifact id', { ...VALID_FALLBACK, artifact_id: '../latest' }],
  ['invalid datetime', { ...VALID_FALLBACK, published_at: 'yesterday' }],
] as const)('fails closed for %s', (_name, raw) => {
  expect(parsePublishedPresentation(raw)).toBeNull()
})

it('accepts only PASS/FULL and FALLBACK/FACTUAL_FALLBACK', () => {
  expect(parsePublishedPresentation(VALID_FULL)?.content.variant).toBe('FULL')
  expect(parsePublishedPresentation(VALID_FALLBACK)?.content.variant).toBe('FACTUAL_FALLBACK')
})
```

Add cases for duplicate claim IDs, empty evidence, recommendation evidence,
inference without confidence, extra nested keys, too many roles/claims,
`javascript:` URL, credentialed HTTPS URL, localhost and IP literals.

- [ ] **Step 2: Confirm RED**

Run: `cd frontend && npm test -- --run src/reference/dashboard/presentation.test.ts`

Expected: module missing.

- [ ] **Step 3: Implement an exact-key runtime parser**

```ts
export function parsePublishedPresentation(raw: unknown): PublishedCardPresentation | null {
  if (!isExactRecord(raw, PUBLISHED_KEYS)) return null
  if (!/^[0-9a-f]{64}$/.test(asString(raw.artifact_id))) return null
  if (!isIsoInstant(raw.published_at)) return null
  if (!parseContent(raw.content)) return null
  const pairIsValid = (
    (raw.status === 'PASS' && raw.content.variant === 'FULL')
    || (raw.status === 'FALLBACK' && raw.content.variant === 'FACTUAL_FALLBACK')
  )
  return pairIsValid ? raw as PublishedCardPresentation : null
}
```

All object levels use `isExactRecord`; every claim has at least one stable
evidence ref. The parser validates but never repairs or partially returns a
payload. URL safety is a separate helper applied only to actual link fields.

- [ ] **Step 4: Run parser tests and static checks**

Run:

```bash
cd frontend
npm test -- --run src/reference/dashboard/presentation.test.ts
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit the parser**

```bash
git add frontend/src/api/types.ts frontend/src/reference/dashboard/presentation.ts frontend/src/reference/dashboard/presentation.test.ts
git commit -m "feat(frontend): parse card presentations fail closed"
```

## Task 4: Replace detail fan-out with one award row per feed item

**Files:**

- Modify: `frontend/src/pages/Companies.tsx`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/companies/referenceCompanies.test.tsx`

- [ ] **Step 1: Add failing no-N+1 and duplicate-award tests**

```tsx
it('loads feed pages and only the selected company profile', async () => {
  renderCompanies('/app/companies')
  await screen.findByRole('heading', { name: 'Entreprises attributaires' })
  expect(api.calls('/signals')).toHaveLength(2)
  expect(api.callsMatching(/^\/signals\/[^?]+$/)).toHaveLength(0)
  await user.click(screen.getByRole('button', { name: /Egli Bau · attribution/i }))
  expect(api.calls('/companies/cmp_egli_bau_1234')).toHaveLength(1)
  expect(api.callsMatching(/^\/signals\/[^?]+$/)).toHaveLength(0)
})

it('keeps two awards for the same company as two selectable rows', async () => {
  renderCompaniesWithFeed([award('sig-a', COMPANY), award('sig-b', COMPANY)])
  expect(await screen.findAllByRole('button', { name: /Egli Bau · attribution/i })).toHaveLength(2)
})
```

Also cover a locked row (absent), missing `company_key` (not linked), repeated
signal across pages (deduplicated by `signal_id`), partial page failure and a
malformed presentation (conservative source-fact label only).

- [ ] **Step 2: Confirm RED**

Run: `cd frontend && npm test -- --run src/companies/referenceCompanies.test.tsx`

Expected: current code calls every signal detail and groups awards into company summaries.

- [ ] **Step 3: Replace the access model**

Delete `DETAIL_CONCURRENCY`, `boundedDetails`, `details` and `unresolved`.
Introduce:

```ts
export interface AuthorizedCompanyAward {
  signalId: string
  companyKey: string
  companyName: string
  country: string | null
  eventDate: string | null
  eventDateKind: SignalEventDateKind
  presentation: PublishedCardPresentation | null
}
```

Each unlocked feed item with a non-null `company_key` yields one award. The list
key is `signalId`; never group or deduplicate by company name/key. Continue
bounded pagination using the backend page cursor semantics. The only
company-specific request is `companies.get(companyKey)` after selection.

- [ ] **Step 4: Run Companies tests**

Run:

```bash
cd frontend
npm test -- --run src/companies/referenceCompanies.test.tsx src/api/boundary.test.tsx
npm run typecheck
npm run lint
```

Expected: PASS and zero `/signals/:id` requests.

- [ ] **Step 5: Commit the data-flow replacement**

```bash
git add frontend/src/pages/Companies.tsx frontend/src/api/types.ts frontend/src/api/endpoints.ts frontend/src/companies/referenceCompanies.test.tsx
git commit -m "refactor(companies): remove signal detail fan-out"
```

## Task 5: Build accessible desktop and mobile master–detail navigation

**Files:**

- Create: `frontend/src/reference/dashboard/MasterDetailFrame.tsx`
- Create: `frontend/src/reference/dashboard/MasterDetailFrame.test.tsx`
- Modify: `frontend/src/pages/Companies.tsx`
- Modify: `frontend/src/reference/dashboard/dashboard-reference.css`
- Modify: `frontend/src/reference/router/ReferenceLink.tsx`
- Modify: `frontend/src/companies/referenceCompanies.test.tsx`

- [ ] **Step 1: Write failing interaction tests**

Cover this exact sequence:

```tsx
it('keeps URL, focus and scroll coherent across select, back and forward', async () => {
  const { history } = renderCompanies('/app/companies')
  const second = await screen.findByRole('button', { name: /sig-b/i })
  second.focus()
  await user.click(second)
  expect(location()).toBe('/app/companies/cmp_egli_bau_1234?signal=sig-b')
  expect(await screen.findByRole('heading', { name: 'Egli Bau AG' })).toHaveFocus()
  history.back()
  expect(await screen.findByRole('button', { name: /sig-b/i })).toHaveFocus()
  history.forward()
  expect(await screen.findByRole('heading', { name: 'Egli Bau AG' })).toHaveFocus()
})
```

Add desktop independent-scroll assertions, mobile single-pane list→detail,
visible `Retour aux entreprises`, Escape returning to list, invalid deep link
without selected award returning a transparent not-found state, and stale
request resolution unable to replace a newer selection.

- [ ] **Step 2: Confirm RED**

Run: `cd frontend && npm test -- --run src/reference/dashboard/MasterDetailFrame.test.tsx src/companies/referenceCompanies.test.tsx`

Expected: missing frame or wrong URL/focus behavior.

- [ ] **Step 3: Implement the shared frame**

`MasterDetailFrame` receives list/detail slots, `mobilePane`, back callback and
label IDs. At `min-width: 1180px`, use two columns with
`height: calc(100dvh - var(--app-header-height))`; each pane owns
`overflow-y: auto` and `overscroll-behavior: contain`. Below 1180px, mount only
the active pane so hidden interactive controls cannot retain focus.

Selection uses:

```ts
navigate(
  `/app/companies/${encodeURIComponent(companyKey)}?signal=${encodeURIComponent(signalId)}`,
)
```

Browser Back must not be implemented with `replace: true`. Restore list scroll
and the initiating award button after return. A directly loaded deep link first
loads feed authorization; it loads the profile only when the requested
`signalId` is present with the same `companyKey`.

Use the normative FR labels `Entreprises attributaires`, `Attributions
détectées`, `Contexte de l’attribution` and the pluralized `n attributions`,
with exact semantic equivalents in EN. Add role/name assertions for all four
labels to `referenceCompanies.test.tsx`.

- [ ] **Step 4: Run interaction and accessibility tests**

Run:

```bash
cd frontend
npm test -- --run src/reference/dashboard/MasterDetailFrame.test.tsx src/companies/referenceCompanies.test.tsx
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit master–detail navigation**

```bash
git add frontend/src/reference/dashboard/MasterDetailFrame.tsx frontend/src/reference/dashboard/MasterDetailFrame.test.tsx frontend/src/pages/Companies.tsx frontend/src/reference/dashboard/dashboard-reference.css frontend/src/reference/router/ReferenceLink.tsx frontend/src/companies/referenceCompanies.test.tsx
git commit -m "feat(companies): add accessible master detail navigation"
```

## Task 6: Render the selected award from its published artifact

**Files:**

- Modify: `frontend/src/pages/CompanyProfile.tsx`
- Modify: `frontend/src/pages/Companies.tsx`
- Modify: `frontend/src/companies/companyProfile.test.tsx`
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`

- [ ] **Step 1: Add failing semantic profile tests**

```tsx
it('renders the selected immutable fallback and qualified public facts', async () => {
  renderProfile({ selectedSignalId: 'sig-b', profile: PROFILE })
  expect(await screen.findByRole('heading', { name: 'Attribution publiée pour Egli Bau AG' })).toBeVisible()
  expect(screen.getByText('Acheteur')).toBeVisible()
  expect(screen.getByText('Entreprise attributaire')).toBeVisible()
  expect(screen.queryByText('LOT 7 ACCORD-CADRE ADMINISTRATIF')).not.toBeInTheDocument()
})

it('does not show placeholder people, roles or urgency', async () => {
  renderProfile({ selectedSignalId: 'sig-b', profile: PROFILE })
  expect(screen.queryAllByText('—')).toHaveLength(0)
  expect(screen.queryByText(/urgent|directeur|responsable/i)).not.toBeInTheDocument()
})
```

Also assert the selected signal must exist in `profile.related_signals`, invalid
presentation content falls back to typed date/buyer/awardee facts, and the
signal link is exactly
`/app/signals/${encodeURIComponent(signalId)}?presentation=${encodeURIComponent(artifactId)}`.

- [ ] **Step 2: Confirm RED**

Run: `cd frontend && npm test -- --run src/companies/companyProfile.test.tsx`

Expected: current raw `contract_title`, placeholder role slots and old signal URL fail.

- [ ] **Step 3: Implement selected-award detail**

Parse the selected related signal using `parsePublishedPresentation`. Render
headline and award summary from a valid artifact; otherwise render only the
typed date, buyer, awardee, amount and official-identity facts. Do not substitute
the removed event headline. Show commercial importance, fit, timing, action and target roles
only for a valid `PASS/FULL` artifact. Do not render empty placeholder rows.
The public official identity and amount remain labelled source facts.

- [ ] **Step 4: Run Companies frontend suites**

Run:

```bash
cd frontend
npm test -- --run src/companies/companyProfile.test.tsx src/companies/referenceCompanies.test.tsx src/reference/dashboard/presentation.test.ts
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit profile rendering**

```bash
git add frontend/src/pages/CompanyProfile.tsx frontend/src/pages/Companies.tsx frontend/src/companies/companyProfile.test.tsx frontend/src/i18n/fr.ts frontend/src/i18n/en.ts
git commit -m "feat(companies): render selected award presentations"
```

## Task 7: Recapture and inspect Companies desktop/mobile goldens

**Files:**

- Modify: `frontend/tests/visual/fixtures.ts`
- Modify: `frontend/tests/visual/reference-port.spec.ts`
- Modify: `frontend/tests/visual/reference-goldens/dashboard-companies-desktop.png`
- Modify: `frontend/tests/visual/reference-goldens/dashboard-companies-mobile.png`

- [ ] **Step 1: Update the deterministic scenario**

Provide at least six award rows, including two awards for one company, one
missing buyer and one null presentation. Preselect a valid company/signal pair.
Assert visual API calls contain feed pages and one company profile, with zero
signal-detail requests.

- [ ] **Step 2: Generate the intentional diff**

Run: `cd frontend && npx playwright test tests/visual/reference-port.spec.ts --grep 'dashboard-companies'`

Expected: only Companies desktop/mobile snapshots fail.

- [ ] **Step 3: Recapture the two goldens**

Run: `cd frontend && npx playwright test tests/visual/reference-port.spec.ts --grep 'dashboard-companies' --update-snapshots`

- [ ] **Step 4: Inspect both PNGs at original resolution**

Verify independent pane scroll, selected row, detail hierarchy, buyer/awardee,
no raw title, no placeholder roles, visible mobile Back control, no clipping,
no horizontal scroll and a usable 390×844 touch layout. Record the inspection
in the PR body.

- [ ] **Step 5: Run the complete visual suite and commit**

Run: `cd frontend && npm run test:visual`

Expected: PASS with no browser error.

```bash
git add frontend/tests/visual
git commit -m "test(companies): recapture master detail goldens"
```

## Task 8: Verify, publish and merge PR 3

- [ ] **Step 1: Run complete backend/frontend gates**

```bash
uv run pytest -q
uv run ruff check .
cd frontend
npm test -- --run
npm run test:visual
npm run build
npm run build:founder
npm run typecheck
npm run lint
```

Expected: every command exits 0.

- [ ] **Step 2: Audit architecture**

Run:

```bash
git diff --check origin/main...HEAD
git diff --name-status origin/main...HEAD
rg -n "signals\.detail|DETAIL_CONCURRENCY|contract_title|event\.headline" frontend/src/pages/Companies.tsx frontend/src/pages/CompanyProfile.tsx
```

Expected: no detail fan-out and no raw administrative-title rendering. Fixture
property names used only inside tests must not be shipped in runtime code.

- [ ] **Step 3: Create the replacement PR without force**

Push `feat/119-companies-master-detail-v2` normally and create a PR targeting
current `main`. Its body must link #119/#127, replace #122, name dependency
SHAs, document batch bounds, deep-link behavior, partial-data limits, capture
inspection and AI-disabled state.

- [ ] **Step 4: Require real Backend and Frontend job execution**

Inspect `gh run view --json jobs`; both jobs require non-empty steps and
`success`. Do not use draft #122 CI as evidence.

- [ ] **Step 5: Squash merge and verify exact-main CI**

After PR jobs succeed, squash-merge, fetch `origin/main`, compare the merge tree
to the reviewed head tree, and wait for both real jobs on that exact SHA. Close
#122 only after exact-main CI succeeds.
