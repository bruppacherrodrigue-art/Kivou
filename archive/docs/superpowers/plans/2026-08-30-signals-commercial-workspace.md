# C003 Signals Commercial Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the Signals feed and detail workspace from one immutable published artifact per selection, with a truthful claim hierarchy, canonical deep links, preserved notes, and accessible desktop/mobile master–detail behavior.

**Architecture:** Feed cards parse the supplied publication once. Selecting a card carries its artifact ID in the route and sends that ID to the detail API. The detail parser accepts the response only when artifact ID and version exactly match the selection; otherwise presentation content disappears fail closed. A direct deep link first resolves authorization through the feed, pins its current artifact, then loads detail. The workspace reuses the master–detail frame from C002 while retaining current pagination, stale-response, paywall and note-safety invariants.

**Tech Stack:** FastAPI query contract regression tests, React 19, TypeScript, React Router, Vitest, Testing Library, Playwright.

---

## Dependency and branch

- Start from the exact green `main` SHA after C001/PR 4 is squash-merged.
- Create `feat/119-signals-commercial-workspace-v2`; never cherry-pick or force-push draft #125.
- This PR replaces #125. It must not contain duplicated #121/#122 changes: those arrive only through merged `main`.

## File map

**Backend regression modify:**

- `tests/test_card_presentation_api.py`
- `tests/test_billing_paywall.py`

**Frontend modify:**

- `frontend/src/api/endpoints.ts`
- `frontend/src/api/types.ts`
- `frontend/src/reference/dashboard/models.ts`
- `frontend/src/reference/dashboard/adapters.ts`
- `frontend/src/reference/dashboard/adapters.test.ts`
- `frontend/src/reference/dashboard/ReferenceSignalDetail.tsx`
- `frontend/src/pages/SignalsFeed.tsx`
- `frontend/src/signals/feed.test.tsx`
- `frontend/src/signals/detail.test.tsx`
- `frontend/src/signals/referenceSignalWorkspace.test.tsx`
- `frontend/src/signals/signalWorkspace.test.tsx`
- `frontend/src/reference/router/ReferenceLink.tsx`
- `frontend/src/i18n/fr.ts`
- `frontend/src/i18n/en.ts`
- `frontend/src/reference/dashboard/dashboard-reference.css`
- `frontend/tests/visual/fixtures.ts`
- `frontend/tests/visual/reference-port.spec.ts`
- `frontend/tests/visual/reference-goldens/dashboard-signals-desktop.png`
- `frontend/tests/visual/reference-goldens/dashboard-signals-mobile.png`

## Task 1: Expose an explicit pinned-detail client contract

**Files:**

- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/boundary.test.tsx`
- Modify: `tests/test_card_presentation_api.py`

- [ ] **Step 1: Add failing query and backend pinning tests**

```ts
it('encodes the immutable artifact id as the detail query', async () => {
  await signals.detail('sig/a', 'a'.repeat(64))
  expect(recordedCalls.at(-1)?.url).toBe(
    `/signals/${encodeURIComponent('sig/a')}?presentation_artifact_id=${'a'.repeat(64)}`,
  )
})
```

```python
def test_detail_pin_never_falls_forward_to_new_current_artifact(
    alice, artifact_a, publish_artifact_b
):
    publish_artifact_b()
    body = alice.get(
        f"/signals/{artifact_a.signal_key}",
        params={"presentation_artifact_id": artifact_a.artifact_id},
    ).json()
    assert body["presentation"]["artifact_id"] == artifact_a.artifact_id
    assert body["presentation"]["version"] == artifact_a.version


def test_unknown_or_cross_tenant_pin_fails_closed(alice, bob_artifact):
    body = alice.get(
        f"/signals/{bob_artifact.signal_key}",
        params={"presentation_artifact_id": bob_artifact.artifact_id},
    ).json()
    assert body["presentation"] is None
```

Keep invalid artifact syntax as HTTP 422 and locked detail as the existing
paywall response without a `presentation` key.

- [ ] **Step 2: Confirm RED**

Run:

```bash
uv run pytest -q tests/test_card_presentation_api.py -k 'pin or tenant'
cd frontend
npm test -- --run src/api/boundary.test.tsx
```

Expected: client has no artifact argument; any backend failure must be fixed in
the foundation API before continuing.

- [ ] **Step 3: Implement the client method**

```ts
detail: (signalKey: string, presentationArtifactId: string | null = null) =>
  request<SignalDetail>(`/signals/${encodeURIComponent(signalKey)}`, {
    query: presentationArtifactId
      ? { presentation_artifact_id: presentationArtifactId }
      : {},
  }),
```

Only an ID returned by the strict parser may reach this method. Do not accept a
free-form URL value without the same `/^[0-9a-f]{64}$/` check.

- [ ] **Step 4: Run contract tests**

Run:

```bash
uv run pytest -q tests/test_card_presentation_api.py tests/test_billing_paywall.py
cd frontend
npm test -- --run src/api/boundary.test.tsx
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit the pinned client**

```bash
git add frontend/src/api/endpoints.ts frontend/src/api/types.ts frontend/src/api/boundary.test.tsx tests/test_card_presentation_api.py tests/test_billing_paywall.py
git commit -m "feat(signals): pin detail presentation artifacts"
```

## Task 2: Bind list and detail view models to one artifact identity

**Files:**

- Modify: `frontend/src/reference/dashboard/models.ts`
- Modify: `frontend/src/reference/dashboard/adapters.ts`
- Modify: `frontend/src/reference/dashboard/adapters.test.ts`

- [ ] **Step 1: Write failing identity and malformed-payload tests**

```ts
it('accepts detail presentation only when id and version match the selected feed artifact', () => {
  const selected = toSignalFeedCard(unlockedFeedItem({ presentation: ARTIFACT_A }))
  expect(toSignalDetailView(unlockedDetail({ presentation: ARTIFACT_A }), selected).presentation)
    .toEqual(parsePublishedPresentation(ARTIFACT_A))
  expect(toSignalDetailView(unlockedDetail({ presentation: ARTIFACT_B }), selected).presentation)
    .toBeNull()
})

it.each([
  malformedJsonPresentation(),
  extraKeyPresentation(),
  statusVariantMismatch(),
  claimWithoutEvidence(),
] as const)('never renders a partially valid artifact', (presentation) => {
  const view = toSignalFeedCard(unlockedFeedItem({ presentation }))
  expect(view.presentation).toBeNull()
  expect(view.headline).toBeNull()
})
```

Add an equal-ID/different-version case, language mismatch, stale revision
represented by null API presentation, and a `FULL` artifact whose
recommendation claim has no evidence.

- [ ] **Step 2: Confirm RED**

Run: `cd frontend && npm test -- --run src/reference/dashboard/adapters.test.ts`

Expected: no selected-artifact comparison or legacy raw title appears.

- [ ] **Step 3: Implement presentation-bound views**

```ts
export interface SignalFeedCardView {
  id: string
  locked: boolean
  artifactId: string | null
  artifactVersion: number | null
  headline: string | null
  summary: string | null
  buyerName: string | null
  awardedCompanyName: string | null
  eventDate: string | null
  eventDateKind: SignalEventDateKind
  fitReason: string | null
  timing: string | null
  presentation: PublishedCardPresentation | null
}
```

`toSignalDetailView(detail, selected)` calls the common parser and retains the
artifact only if both ID and version equal `selected`. An unlocked item with an
absent or invalid artifact gets no headline or summary substitution. If
`selected` has no artifact, any detail artifact is suppressed so a concurrent
publication cannot silently change what the user selected. Official `contract.title` may remain
only in `facts.officialTitle`; it never fills `headline`, `summary`, fit or
timing.

- [ ] **Step 4: Run adapter/parser tests**

Run:

```bash
cd frontend
npm test -- --run src/reference/dashboard/adapters.test.ts src/reference/dashboard/presentation.test.ts
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit artifact-bound adapters**

```bash
git add frontend/src/reference/dashboard/models.ts frontend/src/reference/dashboard/adapters.ts frontend/src/reference/dashboard/adapters.test.ts
git commit -m "refactor(signals): bind views to one published artifact"
```

## Task 3: Rebuild truthful commercial feed cards

**Files:**

- Modify: `frontend/src/pages/SignalsFeed.tsx`
- Modify: `frontend/src/signals/feed.test.tsx`
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`

- [ ] **Step 1: Add failing list-card semantics**

```tsx
it('uses the approved feed hierarchy and exact published fallback', async () => {
  renderSignals([unlockedFeedItem({ presentation: VALID_FALLBACK })])
  const list = await screen.findByRole('region', { name: 'Signaux détectés' })
  expect(within(list).getByText(VALID_FALLBACK.content.headline)).toBeVisible()
  expect(within(list).getByText(VALID_FALLBACK.content.award_summary)).toBeVisible()
  expect(within(list).getByText('Voir l’analyse')).toBeVisible()
})

it('shows no commercial fit, role or urgency for factual fallback', async () => {
  renderSignals([unlockedFeedItem({ presentation: VALID_FALLBACK })])
  expect(screen.queryByText(/urgent|responsable|adéquation/i)).not.toBeInTheDocument()
})

it('locked rows remain presentation-free and never become selectable detail', async () => {
  renderSignals([LOCKED_ITEM])
  expect(screen.getByText(LOCKED_ITEM.headline)).toBeVisible()
  expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}/note`, 'GET')).toHaveLength(0)
})
```

Add FR/EN date labels, missing buyer/amount/place, invalid presentation,
`PASS/FULL` with exact fit/timing, and no administrative title in the card DOM.

- [ ] **Step 2: Confirm RED**

Run: `cd frontend && npm test -- --run src/signals/feed.test.tsx`

Expected: old heading/copy or raw-title behavior fails.

- [ ] **Step 3: Implement feed-card hierarchy and canonical selection URLs**

Use page title `Signaux commerciaux`, list accessible name `Signaux détectés`
and CTA `Voir l’analyse`. Cards show: awardee, published headline, published
summary, qualified date/buyer/amount/place, then optional `FULL` fit/timing.
Selection navigates with the parsed artifact ID:

```ts
const selectionPath = card.artifactId
  ? `/app/signals/${encodeURIComponent(card.id)}?presentation=${encodeURIComponent(card.artifactId)}`
  : `/app/signals/${encodeURIComponent(card.id)}`
```

Store the artifact version in navigation state as a consistency assertion, not
as authority. Locked selection keeps the existing billing redirect and never
calls detail or notes.

- [ ] **Step 4: Run list and URL tests**

Run:

```bash
cd frontend
npm test -- --run src/signals/feed.test.tsx src/signals/referenceSignalWorkspace.test.tsx
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit feed cards**

```bash
git add frontend/src/pages/SignalsFeed.tsx frontend/src/signals/feed.test.tsx frontend/src/i18n/fr.ts frontend/src/i18n/en.ts
git commit -m "feat(signals): render grounded commercial feed cards"
```

## Task 4: Render conclusion, facts, inferences and recommendations separately

**Files:**

- Modify: `frontend/src/reference/dashboard/ReferenceSignalDetail.tsx`
- Modify: `frontend/src/signals/detail.test.tsx`
- Modify: `frontend/src/pages/SignalsFeed.tsx`
- Modify: `frontend/src/reference/router/ReferenceLink.tsx`

- [ ] **Step 1: Add failing detail hierarchy tests**

```tsx
it('separates every claim by published kind and keeps evidence visible', () => {
  renderDetail(FULL_DETAIL)
  expect(screen.getByRole('heading', { name: 'Conclusion publiée' })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Faits publiés' })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Inférences contrôlées' })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Action recommandée' })).toBeVisible()
  for (const claim of FULL_DETAIL.presentation!.content.claims) {
    expect(screen.getByText(claim.text)).toBeVisible()
    expect(screen.getByTestId(`evidence-${claim.claim_id}`)).not.toBeEmptyDOMElement()
  }
})

it('a factual fallback has no inference, recommendation, target person or urgency section', () => {
  renderDetail(FALLBACK_DETAIL)
  expect(screen.getByRole('heading', { name: 'Faits publiés' })).toBeVisible()
  expect(screen.queryByRole('heading', { name: 'Inférences contrôlées' })).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Action recommandée' })).not.toBeInTheDocument()
})

it('uses the canonical authorized company URL', () => {
  renderDetail(FULL_DETAIL)
  expect(screen.getByRole('link', { name: /Voir l’entreprise/i })).toHaveAttribute(
    'href', `/app/companies/${FULL_DETAIL.company_key}?signal=${FULL_DETAIL.signal_id}`,
  )
})
```

Add missing company key (no link), invalid/mismatched artifact (source facts
only), buyer/awardee never swapped, publication date not labelled award date,
materials claim without staffing, no placeholder questions/scopes, and official
title visible only under `Titre officiel de la source`.

- [ ] **Step 2: Confirm RED**

Run: `cd frontend && npm test -- --run src/signals/detail.test.tsx`

Expected: current commercial brief, placeholder scopes/questions and raw headline fail.

- [ ] **Step 3: Implement claim-led detail**

Render the exact artifact headline and award summary as the published
conclusion. Partition `content.claims` by `FACT`, `INFERENCE` and
`RECOMMENDATION`; keep each claim’s evidence refs adjacent and inference
confidence explicit. `recommended_action`, roles and timing may appear only for
a valid `PASS/FULL`, and their associated claim evidence must exist. QA status
is metadata only; never rewrite presentation copy.

Below, render source facts: amount, qualified date, buyer, awardee, place,
notice/source and official administrative title. Remove synthetic five-scope
and three-question placeholders. Preserve the signal note component and its
independent loading/retry/save state exactly.

- [ ] **Step 4: Run detail and note suites**

Run:

```bash
cd frontend
npm test -- --run src/signals/detail.test.tsx src/signals/signalWorkspace.test.tsx
npm run typecheck
npm run lint
```

Expected: PASS, including note serialization and no locked-note reads.

- [ ] **Step 5: Commit detail rendering**

```bash
git add frontend/src/reference/dashboard/ReferenceSignalDetail.tsx frontend/src/signals/detail.test.tsx frontend/src/pages/SignalsFeed.tsx frontend/src/reference/router/ReferenceLink.tsx
git commit -m "feat(signals): separate grounded signal conclusions"
```

## Task 5: Reuse master–detail while preserving deep links, focus, scroll and notes

**Files:**

- Modify: `frontend/src/pages/SignalsFeed.tsx`
- Modify: `frontend/src/signals/referenceSignalWorkspace.test.tsx`
- Modify: `frontend/src/signals/signalWorkspace.test.tsx`
- Modify: `frontend/src/reference/dashboard/dashboard-reference.css`

- [ ] **Step 1: Add failing full interaction matrix**

Cover:

1. selection from feed pins ID in URL and detail request;
2. publication B becoming current after feed A still returns/displays A;
3. detail B returned for selected A suppresses all presentation copy;
4. direct deep link without `presentation` resolves feed authorization, then
   replaces the URL with the current artifact ID before detail;
5. direct deep link with a valid prior artifact renders that immutable artifact
   and uses it for the selected list row;
6. malformed `presentation` query is ignored and replaced by the authorized
   feed artifact, never sent raw;
7. locked deep links redirect before detail/note;
8. historical pagination and scan-truncated behavior remain transparent;
9. previous/next history restores selection, list scroll and row focus;
10. mobile list→detail and `Retour aux signaux` restore focus;
11. late feed/detail/note responses cannot replace the current selection;
12. pending note is flushed/serialized before leaving a signal.

Core concurrency assertion:

```tsx
expect(callsTo(`/signals/${SIGNAL_ID}`, 'GET').at(-1)?.search.get('presentation_artifact_id'))
  .toBe(ARTIFACT_A.artifact_id)
expect(await screen.findByText(ARTIFACT_A.content.headline)).toBeVisible()
expect(screen.queryByText(ARTIFACT_B.content.headline)).not.toBeInTheDocument()
```

- [ ] **Step 2: Confirm RED**

Run:

```bash
cd frontend
npm test -- --run src/signals/referenceSignalWorkspace.test.tsx src/signals/signalWorkspace.test.tsx
```

Expected: current detail calls omit the artifact and mobile behavior is not
fully shared with `MasterDetailFrame`.

- [ ] **Step 3: Implement selection pin state**

Use one `PinnedSignalSelection` value:

```ts
interface PinnedSignalSelection {
  signalId: string
  artifactId: string | null
  artifactVersion: number | null
}
```

For ordinary list selection, derive it from the strict feed-card parser. For a
deep link with a syntactically valid prior ID, request that ID; when detail
returns it, use that artifact for the selected list row as well. Without a query
ID, authorize through the feed, derive the current ID/version, `replace` only to
canonicalize the initial deep link, then request detail. If detail cannot return
the requested artifact, show source facts plus a local presentation-unavailable
message; never fall forward to another publication.

Mount `MasterDetailFrame` with independent desktop scroll and mobile mono-pane.
Do not replace the existing generation counters, pagination guards, history
state, locked redirect, billing refresh or `useSignalNote` lifecycle; adapt them
to the pinned selection.

- [ ] **Step 4: Run workspace and accessibility tests**

Run:

```bash
cd frontend
npm test -- --run src/signals/referenceSignalWorkspace.test.tsx src/signals/signalWorkspace.test.tsx src/reference/dashboard/MasterDetailFrame.test.tsx
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit workspace behavior**

```bash
git add frontend/src/pages/SignalsFeed.tsx frontend/src/signals/referenceSignalWorkspace.test.tsx frontend/src/signals/signalWorkspace.test.tsx frontend/src/reference/dashboard/dashboard-reference.css
git commit -m "feat(signals): preserve pinned master detail navigation"
```

## Task 6: Consolidate the adversarial frontend publication suite

**Files:**

- Modify: `frontend/src/reference/dashboard/presentation.test.ts`
- Modify: `frontend/src/reference/dashboard/adapters.test.ts`
- Modify: `frontend/src/signals/feed.test.tsx`
- Modify: `frontend/src/signals/detail.test.tsx`

- [ ] **Step 1: Add one named test for every #127 adversary**

The test names must include:

- `buyer_awardee_roles_cannot_swap`
- `fr_en_and_short_dates_keep_source_kind`
- `legal_name_collision_fails_closed`
- `stale_icp_revision_is_absent`
- `cross_tenant_artifact_is_absent`
- `concurrent_publication_keeps_pinned_artifact`
- `malformed_json_fails_closed`
- `bounded_fallback_has_facts_only`
- `locked_teaser_omits_presentation`
- `get_routes_never_reach_provider`
- `materials_cannot_become_staffing`
- `recommendation_claim_requires_evidence`

Backend tests own tenant/revision/provider behavior; frontend fixtures assert
the corresponding absent/null boundary and never simulate authority it does
not possess.

- [ ] **Step 2: Run the named matrix**

Run:

```bash
uv run pytest -q tests/test_card_intelligence_validation.py tests/test_card_presentation_store.py tests/test_card_presentation_api.py
cd frontend
npm test -- --run src/reference/dashboard/presentation.test.ts src/reference/dashboard/adapters.test.ts src/signals/feed.test.tsx src/signals/detail.test.tsx
```

Expected: PASS and every named case is collected.

- [ ] **Step 3: Commit missing adversarial coverage**

```bash
git add tests/test_card_intelligence_validation.py tests/test_card_presentation_store.py tests/test_card_presentation_api.py frontend/src/reference/dashboard/presentation.test.ts frontend/src/reference/dashboard/adapters.test.ts frontend/src/signals/feed.test.tsx frontend/src/signals/detail.test.tsx
git commit -m "test(signals): consolidate publication adversaries"
```

## Task 7: Recapture and inspect the final Signals goldens

**Files:**

- Modify: `frontend/tests/visual/fixtures.ts`
- Modify: `frontend/tests/visual/reference-port.spec.ts`
- Modify: `frontend/tests/visual/reference-goldens/dashboard-signals-desktop.png`
- Modify: `frontend/tests/visual/reference-goldens/dashboard-signals-mobile.png`

- [ ] **Step 1: Replace stale fixture expectations**

Use six rows with a selected factual fallback, one valid `FULL` fixture only to
exercise layout offline, one missing buyer, one publication date, one duplicate
company award and one locked teaser. All claims have evidence. Visual fixtures
do not imply that `FULL` is enabled in staging.

Update `waitForScenario` to wait for published headline, detail note enabled,
six rows and zero unhandled calls. Assert the detail request carries the
selected artifact ID.

- [ ] **Step 2: Run Signals regression before update**

Run: `cd frontend && npx playwright test tests/visual/reference-port.spec.ts --grep 'dashboard-signals'`

Expected: only the two Signals snapshots differ.

- [ ] **Step 3: Recapture the two Signals goldens**

Run: `cd frontend && npx playwright test tests/visual/reference-port.spec.ts --grep 'dashboard-signals' --update-snapshots`

- [ ] **Step 4: Inspect desktop and mobile at original resolution**

Verify exact list/detail headline match, claim grouping/evidence, source facts,
buyer/awardee, qualified dates, authorized Company link, independent desktop
scroll, mobile Back, focus ring, note area, locked teaser, no raw title as
headline, no clipping and no horizontal overflow. Record the inspection.

- [ ] **Step 5: Run full visual suite and commit**

Run: `cd frontend && npm run test:visual`

Expected: PASS without console error, request failure or unhandled API call.

```bash
git add frontend/tests/visual
git commit -m "test(signals): recapture pinned signal goldens"
```

## Task 8: Verify, publish and merge PR 5

- [ ] **Step 1: Run every local gate**

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

- [ ] **Step 2: Audit the clean final scope**

```bash
git diff --check origin/main...HEAD
git diff --name-status origin/main...HEAD
git log --oneline origin/main..HEAD
rg -n "contract\.title|analysis\.fit|Hermes|provider_registry" frontend/src/pages/SignalsFeed.tsx frontend/src/reference/dashboard/ReferenceSignalDetail.tsx src/signals/api/routes_signals.py
```

Expected: official title is referenced only by the explicitly labelled source
fact; no frontend fit reconstruction and no GET-side provider coupling.

- [ ] **Step 3: Create the replacement PR**

Push `feat/119-signals-commercial-workspace-v2` normally. Create a PR to current
`main` linking #119/#127, replacing #125, naming all dependency SHAs, tests,
captures, pinning risks/limits and factual-only staging policy.

- [ ] **Step 4: Require real green jobs**

Both Backend and Frontend jobs must have non-empty step lists and successful
checkout, dependency, test and lint/build/visual steps. Runs #328–#330 and the
old #125 result are never accepted as validation.

- [ ] **Step 5: Squash merge and require final-main CI**

Squash-merge only after PR CI. Fetch the resulting `main` SHA, compare its tree
with the reviewed head, then wait for both real GitHub Actions jobs on that
exact final SHA. Do not begin staging until this exact-main run is green. Close
#125 only after that proof.
