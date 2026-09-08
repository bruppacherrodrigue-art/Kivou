# C001 Dashboard Award Summaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Dashboard raw-contract cards with at most six concise, truthful award summaries sourced from the feed’s immutable published artifacts, without detail calls or hidden commercial invention.

**Architecture:** `Dashboard` makes its existing feed request and maps each returned item through the shared fail-closed presentation parser. The first server-ordered row becomes the emphasis card; at most five more items form the recent list. Valid artifacts provide their exact published text; absent/invalid artifacts show no reconstructed summary and retain only typed buyer, awardee, amount, place and qualified-date facts. Locked rows retain the teaser contract and never expose presentation or company identity.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, Playwright visual regression.

---

## Dependency and branch

- Start only from the exact green `main` SHA after C002/PR 3 is squash-merged.
- Create `feat/119-dashboard-award-summaries-v2`; never rewrite the remote branch.
- This PR replaces draft #124. Do not reuse its branch or its generic match copy; port only the approved visual hierarchy.

## File map

**Modify:**

- `frontend/src/reference/dashboard/models.ts`
- `frontend/src/reference/dashboard/adapters.ts`
- `frontend/src/reference/dashboard/adapters.test.ts`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/referenceDashboardData.test.tsx`
- `frontend/src/pages/dashboard.test.tsx`
- `frontend/src/i18n/fr.ts`
- `frontend/src/i18n/en.ts`
- `frontend/src/reference/dashboard/dashboard-reference.css`
- `frontend/tests/visual/fixtures.ts`
- `frontend/tests/visual/reference-port.spec.ts`
- `frontend/tests/visual/reference-goldens/dashboard-overview-desktop.png`
- `frontend/tests/visual/reference-goldens/dashboard-overview-mobile.png`

## Task 1: Define a presentation-first Dashboard card view

**Files:**

- Modify: `frontend/src/reference/dashboard/models.ts`
- Modify: `frontend/src/reference/dashboard/adapters.ts`
- Modify: `frontend/src/reference/dashboard/adapters.test.ts`

- [ ] **Step 1: Write failing adapter tests**

```ts
it('uses the exact valid published artifact without recomposing its headline', () => {
  const item = unlockedFeedItem({ presentation: VALID_FACTUAL_FALLBACK })
  const card = toOverviewAwardCard(item)
  expect(card.headline).toBe(VALID_FACTUAL_FALLBACK.content.headline)
  expect(card.summary).toBe(VALID_FACTUAL_FALLBACK.content.award_summary)
  expect(card.artifactId).toBe(VALID_FACTUAL_FALLBACK.artifact_id)
})

it('fails closed to typed facts when the artifact is malformed', () => {
  const item = unlockedFeedItem({
    presentation: withoutEvidence(VALID_FACTUAL_FALLBACK),
    contract: { title: 'LOT 7 ACCORD-CADRE ADMINISTRATIF' },
  })
  const card = toOverviewAwardCard(item)
  expect(card.presentation).toBeNull()
  expect(card.headline).toBeNull()
  expect(JSON.stringify(card)).not.toContain('LOT 7 ACCORD-CADRE')
  expect(card.awardedCompanyName).toBe(item.company.name)
})

it('keeps buyer and awarded company in distinct fields', () => {
  const card = toOverviewAwardCard(unlockedFeedItem({
    company: { name: 'Attributaire SA' },
    contract: { buyer: { name: 'Acheteur public' } },
  }))
  expect(card.buyerName).toBe('Acheteur public')
  expect(card.awardedCompanyName).toBe('Attributaire SA')
})

it('does not synthesize fit or urgency for a factual fallback', () => {
  const card = toOverviewAwardCard(unlockedFeedItem({ presentation: VALID_FACTUAL_FALLBACK }))
  expect(card.fitReason).toBeNull()
  expect(card.timing).toBeNull()
})
```

Add locked-item assertions: `presentation=null`, company/buyer/amount absent,
teaser headline preserved and no artifact ID.

- [ ] **Step 2: Confirm RED**

Run: `cd frontend && npm test -- --run src/reference/dashboard/adapters.test.ts`

Expected: missing `toOverviewAwardCard` and raw title use.

- [ ] **Step 3: Introduce the exact view model**

```ts
export interface OverviewAwardCardView {
  id: string
  locked: boolean
  artifactId: string | null
  headline: string | null
  summary: string | null
  awardedCompanyName: string | null
  buyerName: string | null
  amount: Money | null
  location: Place | null
  eventDate: string | null
  eventDateKind: SignalEventDateKind
  fitReason: string | null
  timing: string | null
  presentation: PublishedCardPresentation | null
}
```

For unlocked rows, call `parsePublishedPresentation()` once. When null, set
both `headline` and `summary` to null and let the component expose only labelled
structured facts plus a neutral “résumé non publié” state. Never read
`event.headline` or `contract.title` in this adapter. Populate `fitReason` and `timing` only from a
valid `PASS/FULL` payload, never from legacy `analysis.fit`.

- [ ] **Step 4: Run adapter and parser tests**

Run:

```bash
cd frontend
npm test -- --run src/reference/dashboard/adapters.test.ts src/reference/dashboard/presentation.test.ts
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit the view model**

```bash
git add frontend/src/reference/dashboard/models.ts frontend/src/reference/dashboard/adapters.ts frontend/src/reference/dashboard/adapters.test.ts
git commit -m "refactor(dashboard): map immutable award summaries"
```

## Task 2: Render one emphasis card and at most five recent awards

**Files:**

- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/pages/referenceDashboardData.test.tsx`
- Modify: `frontend/src/pages/dashboard.test.tsx`

- [ ] **Step 1: Add failing hierarchy, order and request tests**

```tsx
it('renders at most six awards in the backend feed order', async () => {
  const items = Array.from({ length: 9 }, (_, index) => awardItem(`sig-${index}`))
  renderDashboard(feedPage(items))
  const cards = await screen.findAllByRole('link', { name: /Voir l’attribution/i })
  expect(cards).toHaveLength(6)
  expect(cards.map((card) => card.getAttribute('href'))).toEqual(
    items.slice(0, 6).map((item) => `/app/signals/${item.signal_id}?presentation=${item.presentation!.artifact_id}`),
  )
})

it('never requests signal detail to render Dashboard summaries', async () => {
  renderDashboard(feedPage([UNLOCKED_ITEM, LOCKED_ITEM]))
  await screen.findByRole('heading', { name: 'Vue d’ensemble' })
  expect(callsTo('/signals', 'GET')).toHaveLength(1)
  expect(recordedCalls.filter(({ url }) => /^\/signals\/[^?]+/.test(url))).toHaveLength(0)
})

it('qualifies a publication date and keeps buyer separate from awardee', async () => {
  renderDashboard(feedPage([publicationItem()]))
  expect(await screen.findByText('Date de publication')).toBeVisible()
  expect(screen.queryByText("Date d’attribution")).not.toBeInTheDocument()
  expect(screen.getByText('Acheteur')).toBeVisible()
  expect(screen.getByText('Entreprise attributaire')).toBeVisible()
})
```

Also cover: first row locked then first unlocked emphasis, all rows locked,
empty feed, feed refresh retaining prior cards, partial count with `has_more`,
malformed presentation, missing buyer/amount/date/location, and duplicate
companies with distinct signal IDs.

- [ ] **Step 2: Confirm RED**

Run: `cd frontend && npm test -- --run src/pages/referenceDashboardData.test.tsx src/pages/dashboard.test.tsx`

Expected: raw title, unbounded list or wrong CTA assertions fail.

- [ ] **Step 3: Implement the six-card layout**

Compute:

```ts
const visibleAwards = toOverviewAwardCards(feed.data).slice(0, 6)
const [priority = null, ...recent] = visibleAwards
```

The priority card order is: awarded company, published headline and factual
award summary when present, qualified date, buyer, amount and place. Show fit and
timing only when non-null. Locked priority renders only the teaser and real
billing action. Each unlocked CTA pins its artifact when present:

```ts
const signalHref = card.artifactId
  ? `/app/signals/${encodeURIComponent(card.id)}?presentation=${encodeURIComponent(card.artifactId)}`
  : `/app/signals/${encodeURIComponent(card.id)}`
```

The recent list uses the same fields, not a separate reconstruction. Keep
`total_returned` and `has_more` semantics; do not claim the visible six are the
complete account total.

- [ ] **Step 4: Run Dashboard tests and static checks**

Run:

```bash
cd frontend
npm test -- --run src/pages/referenceDashboardData.test.tsx src/pages/dashboard.test.tsx
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit Dashboard rendering**

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/referenceDashboardData.test.tsx frontend/src/pages/dashboard.test.tsx
git commit -m "feat(dashboard): show grounded award summaries"
```

## Task 3: Make compact cards legible and honest in FR/EN

**Files:**

- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`
- Modify: `frontend/src/reference/dashboard/dashboard-reference.css`
- Modify: `frontend/src/pages/referenceDashboardData.test.tsx`

- [ ] **Step 1: Add failing copy tests**

Assert these exact FR labels and their semantic EN equivalents:

```tsx
expect(screen.getByRole('heading', { name: 'Attributions récentes pertinentes' })).toBeVisible()
expect(screen.getByRole('link', { name: 'Voir l’attribution' })).toBeVisible()
expect(screen.queryByText(/à contacter en priorité|urgent|à appeler/i)).not.toBeInTheDocument()
```

Assert missing fields show `Non publié`/`Not published`, not invented defaults.

- [ ] **Step 2: Implement dictionary and layout changes**

Replace `reviewFirst`, `whyFirst` and generic match fallbacks on this screen.
Use a two-line headline clamp and three-line summary clamp only in compact list
cards; the priority summary stays fully readable. Normalize card minimum height
without hiding focus outlines. At 390 px, stack facts and keep touch targets at
least 44 px.

- [ ] **Step 3: Run copy and CSS-linked tests**

Run:

```bash
cd frontend
npm test -- --run src/pages/referenceDashboardData.test.tsx src/api/boundary.test.tsx
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 4: Commit copy and style**

```bash
git add frontend/src/i18n/fr.ts frontend/src/i18n/en.ts frontend/src/reference/dashboard/dashboard-reference.css frontend/src/pages/referenceDashboardData.test.tsx
git commit -m "style(dashboard): clarify award summary hierarchy"
```

## Task 4: Recapture and inspect Dashboard desktop/mobile goldens

**Files:**

- Modify: `frontend/tests/visual/fixtures.ts`
- Modify: `frontend/tests/visual/reference-port.spec.ts`
- Modify: `frontend/tests/visual/reference-goldens/dashboard-overview-desktop.png`
- Modify: `frontend/tests/visual/reference-goldens/dashboard-overview-mobile.png`

- [ ] **Step 1: Build the deterministic visual data**

Use six visible awards: factual fallback, missing buyer, publication date,
missing amount/place, second award for the same company and one locked teaser.
All valid artifacts are `FALLBACK/FACTUAL_FALLBACK` with evidence and null
provider/model/prompt metadata.

- [ ] **Step 2: Confirm only intended snapshot deltas**

Run: `cd frontend && npx playwright test tests/visual/reference-port.spec.ts --grep 'dashboard-overview'`

Expected: desktop and mobile overview snapshots fail.

- [ ] **Step 3: Recapture only overview goldens**

Run: `cd frontend && npx playwright test tests/visual/reference-port.spec.ts --grep 'dashboard-overview' --update-snapshots`

- [ ] **Step 4: Inspect images at original resolution**

Verify six-card maximum, headline/summary hierarchy, explicit buyer/awardee,
date labels, missing values, locked privacy, CTA focus outline, no clipping,
mobile stacking and no horizontal overflow. Record results in the PR body.

- [ ] **Step 5: Run full visual regression and commit**

Run: `cd frontend && npm run test:visual`

Expected: PASS, no unhandled API call, request failure or console error.

```bash
git add frontend/tests/visual
git commit -m "test(dashboard): recapture award summary goldens"
```

## Task 5: Verify, publish and merge PR 4

- [ ] **Step 1: Run all local gates**

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

- [ ] **Step 2: Audit forbidden reconstruction and scope**

```bash
git diff --check origin/main...HEAD
git diff --name-status origin/main...HEAD
rg -n "contract\.title|analysis\.fit|signals\.detail" frontend/src/pages/Dashboard.tsx frontend/src/reference/dashboard/adapters.ts
```

Expected: Dashboard summary code contains none of those raw reconstruction/detail
paths. Detail adapters serving other screens may still expose the official title
only as a labelled source fact.

- [ ] **Step 3: Create replacement PR #124**

Push `feat/119-dashboard-award-summaries-v2` without force. Create a PR to
current `main`, linking #119/#127, declaring dependencies and limits, naming
inspected captures and stating that staging remains factual-fallback-only.

- [ ] **Step 4: Require actual green jobs**

Inspect both GitHub Actions jobs and their step arrays. Do not merge on a check
rollup alone and do not reuse #124’s historical result.

- [ ] **Step 5: Squash merge and verify exact-main CI**

After real PR CI succeeds, squash-merge, fetch the new SHA, compare its tree to
the reviewed tree and wait for both Backend and Frontend jobs on that exact
`main` SHA. Then close #124 with the replacement link.
