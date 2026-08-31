# Signal Truthfulness Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace misleading or reconstructed signal copy with typed, evidence-bound facts while preserving locked-teaser confidentiality and every existing navigation and note behavior.

**Architecture:** The API remains authoritative. Frontend adapters convert typed event, need and fit fields into conservative view models; components render only those view-model fields. Administrative titles stay secondary source facts and are never promoted into card summaries. This PR consumes the factual Card Presentation boundary from PR 1 but does not activate `PASS/FULL` generation.

**Tech Stack:** React 19, TypeScript 5.7, Vitest, Testing Library, Playwright, FastAPI/pytest regression tests.

---

## Dependency and branch

- Start only after the foundation replacement PR has been squash-merged and its exact `main` SHA has two successful GitHub Actions jobs with non-empty step lists.
- Fetch that `main`, create `fix/119-signal-truthfulness-guardrails-v2`, and never rebase or force-push the published branch.
- This PR replaces draft #121. Do not cherry-pick its commits; port only the reviewed semantics listed below.

## File map

**Modify:**

- `frontend/src/api/types.ts` — type the strict presentation envelope exposed by PR 1 and document typed date sources.
- `frontend/src/reference/dashboard/models.ts` — add date-kind and source-fact view-model fields.
- `frontend/src/reference/dashboard/adapters.ts` — select targeted needs, concrete fit and typed dates conservatively.
- `frontend/src/reference/dashboard/adapters.test.ts` — adversarial adapter matrix.
- `frontend/src/reference/dashboard/ReferenceSignalDetail.tsx` — transparent source facts and no inferred contact role.
- `frontend/src/pages/SignalsFeed.tsx` — conservative interim feed copy without raw-title reconstruction.
- `frontend/src/signals/feed.test.tsx`
- `frontend/src/signals/detail.test.tsx`
- `frontend/src/signals/referenceSignalWorkspace.test.tsx`
- `frontend/src/i18n/fr.ts`
- `frontend/src/i18n/en.ts`
- `frontend/src/reference/dashboard/dashboard-reference.css`
- `frontend/tests/visual/fixtures.ts`
- `frontend/tests/visual/reference-port.spec.ts`
- `frontend/tests/visual/reference-goldens/dashboard-signals-desktop.png`
- `frontend/tests/visual/reference-goldens/dashboard-signals-mobile.png`

**Backend regression only:**

- `tests/test_billing_paywall.py`
- `tests/test_card_presentation_api.py`

## Task 1: Type event dates and select only targeted needs

**Files:**

- Modify: `frontend/src/reference/dashboard/models.ts`
- Modify: `frontend/src/reference/dashboard/adapters.ts`
- Modify: `frontend/src/reference/dashboard/adapters.test.ts`

- [ ] **Step 1: Write failing adapter cases**

Add the exact matrix below to `adapters.test.ts`:

```ts
it.each([
  [{ clock: 'AWARD', status: 'AWARDED' }, 'award'],
  [{ clock: 'NOTICE', status: 'NOTIFIED' }, 'notification'],
  [{ clock: 'PUBLICATION', status: 'PUBLISHED' }, 'publication'],
] as const)('maps %j to the qualified date kind %s', (event, expected) => {
  expect(eventDateKind(event.clock, event.status)).toBe(expected)
})

it('selects the first non-blank targeted need, never a generic need', () => {
  const detail = signalDetail({
    needs: [
      { need: '  ', targeted: true, evidence_refs: ['source:empty'] },
      { need: 'Personnel', targeted: false, evidence_refs: ['source:generic'] },
      { need: 'Matériaux', targeted: true, evidence_refs: ['source:materials'] },
    ],
  })
  expect(toSignalDetailView(detail).primaryNeed).toEqual({
    label: 'Matériaux',
    evidenceRefs: ['source:materials'],
  })
})

it('does not synthesize a fit reason from a score or category', () => {
  const item = unlockedFeedItem({ fit: { score: 0.91, reasons: [] } })
  expect(toFeedCardView(item).fitReason).toBeNull()
})

it('does not promote the administrative contract title into card copy', () => {
  const item = unlockedFeedItem({
    contract: { title: 'ACCORD-CADRE LOT 7 PERSONNEL ET MATÉRIAUX' },
    presentation: null,
  })
  const view = toFeedCardView(item)
  expect(JSON.stringify(view)).not.toContain('ACCORD-CADRE LOT 7')
})
```

- [ ] **Step 2: Confirm RED**

Run: `cd frontend && npm test -- --run src/reference/dashboard/adapters.test.ts`

Expected: missing `eventDateKind`, wrong need selection, synthetic fit, or raw-title leakage.

- [ ] **Step 3: Add the narrow view model**

Use these types in `models.ts`:

```ts
export type SignalEventDateKind = 'award' | 'notification' | 'publication'

export interface EvidenceBoundLabel {
  label: string
  evidenceRefs: string[]
}

export interface SignalFactView {
  signalId: string
  locked: boolean
  eventDate: string | null
  eventDateKind: SignalEventDateKind
  buyerName: string | null
  awardedCompanyName: string | null
  primaryNeed: EvidenceBoundLabel | null
  fitReason: string | null
  presentation: CardPresentation | null
}
```

Implement `eventDateKind(clock, status)` with an exhaustive mapping. Add a
test that fails compilation if a new API clock is introduced without a mapping.
`concreteMatchReasons()` may return only non-empty backend reasons; it must not
derive prose from scores, CPV, categories or the contract title.

- [ ] **Step 4: Run adapter tests and static checks**

Run:

```bash
cd frontend
npm test -- --run src/reference/dashboard/adapters.test.ts
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit typed adapters**

```bash
git add frontend/src/reference/dashboard/models.ts frontend/src/reference/dashboard/adapters.ts frontend/src/reference/dashboard/adapters.test.ts
git commit -m "fix(signals): ground signal facts in typed sources"
```

## Task 2: Render date, buyer, awardee and fit semantics honestly

**Files:**

- Modify: `frontend/src/reference/dashboard/ReferenceSignalDetail.tsx`
- Modify: `frontend/src/pages/SignalsFeed.tsx`
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`
- Modify: `frontend/src/signals/feed.test.tsx`
- Modify: `frontend/src/signals/detail.test.tsx`

- [ ] **Step 1: Add failing component tests**

```tsx
it.each([
  ['award', "Date d’attribution"],
  ['notification', 'Date de notification'],
  ['publication', 'Date de publication'],
] as const)('labels a %s date without changing its meaning', async (kind, label) => {
  renderSignal({ eventDateKind: kind, eventDate: '2026-08-15' })
  expect(await screen.findByText(label)).toBeVisible()
})

it('never labels a publication date as an award date', async () => {
  renderSignal({ eventDateKind: 'publication', eventDate: '2026-08-15' })
  expect(await screen.findByText('Date de publication')).toBeVisible()
  expect(screen.queryByText("Date d’attribution")).not.toBeInTheDocument()
})

it('omits fit copy when the API has no concrete reason', async () => {
  renderSignal({ fitReason: null })
  expect(screen.queryByText(/correspond à votre ciblage/i)).not.toBeInTheDocument()
})

it('states an unavailable contact role without inventing a person', async () => {
  renderSignal({ targetRoles: [], people: [] })
  expect(await screen.findByText('Rôle cible non disponible')).toBeVisible()
  expect(screen.queryByText(/directeur|responsable|chef de projet/i)).not.toBeInTheDocument()
})
```

Also assert the buyer and awarded company appear under distinct labels and can
never swap positions.

- [ ] **Step 2: Confirm RED**

Run: `cd frontend && npm test -- --run src/signals/feed.test.tsx src/signals/detail.test.tsx`

Expected: at least the publication/award label and invented-role cases fail.

- [ ] **Step 3: Implement literal qualified labels**

Add these dictionary keys in both languages without changing the dictionary
shape:

```ts
signalDateAward: "Date d’attribution",
signalDateNotification: 'Date de notification',
signalDatePublication: 'Date de publication',
signalBuyer: 'Acheteur',
signalAwardee: 'Entreprise attributaire',
signalTargetRoleUnavailable: 'Rôle cible non disponible',
```

Use the existing locale date formatter only after choosing the label. Remove
the `reviewFirst` badge and any copy implying urgency. When `presentation` is
`null`, show a neutral localized “présentation non publiée” state plus the
structured buyer, awardee and qualified-date facts. Do not substitute either
`event.headline` or `contract.title`; the official title may remain in a clearly
labelled source-facts section in detail.

- [ ] **Step 4: Run focused UI tests**

Run:

```bash
cd frontend
npm test -- --run src/signals/feed.test.tsx src/signals/detail.test.tsx src/signals/referenceSignalWorkspace.test.tsx
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit truthful rendering**

```bash
git add frontend/src/reference/dashboard/ReferenceSignalDetail.tsx frontend/src/pages/SignalsFeed.tsx frontend/src/i18n/fr.ts frontend/src/i18n/en.ts frontend/src/signals
git commit -m "fix(signals): label commercial facts truthfully"
```

## Task 3: Preserve fail-closed privacy and GET purity

**Files:**

- Modify: `tests/test_card_presentation_api.py`
- Modify: `tests/test_billing_paywall.py`
- Modify: `frontend/src/signals/feed.test.tsx`

- [ ] **Step 1: Add locked and malformed boundary regressions**

```python
def test_locked_teaser_has_an_exact_public_surface(alice):
    locked = next(item for item in alice.get("/signals").json()["items"] if item["locked"])
    assert set(locked) == {
        "signal_id", "target_icp_id", "locked", "unlock_required",
        "event", "context", "headline",
    }
    assert "presentation" not in locked
    assert "company_key" not in locked


def test_get_routes_do_not_resolve_generator_qa_or_provider(alice, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("provider path reached during GET"))
    monkeypatch.setattr("signals.card_intelligence.service.generate_and_publish", forbidden)
    assert alice.get("/signals").status_code == 200
    signal_id = first_unlocked_signal_id(alice)
    assert alice.get(f"/signals/{signal_id}").status_code == 200
    forbidden.assert_not_called()
```

In the frontend test, inject a presentation with a missing claim evidence list
and assert the card renders only conservative source facts, not partial
presentation copy.

- [ ] **Step 2: Run focused boundary tests**

Run:

```bash
uv run pytest -q tests/test_card_presentation_api.py tests/test_billing_paywall.py
cd frontend
npm test -- --run src/signals/feed.test.tsx
```

Expected before the frontend parser lands in PR 3: backend tests pass and the
malformed presentation fixture documents the required fail-closed behavior.

- [ ] **Step 3: Implement only the smallest boundary correction**

If the backend exact-surface test fails, remove the leaking key at the locked
serializer. Do not add a frontend reconstruction. Until PR 3 centralizes the
strict runtime parser, treat a structurally incomplete presentation as absent.

- [ ] **Step 4: Commit boundary regressions**

```bash
git add tests/test_card_presentation_api.py tests/test_billing_paywall.py frontend/src/signals/feed.test.tsx
git commit -m "test(signals): preserve teaser and GET boundaries"
```

## Task 4: Recapture and inspect the Signals goldens

**Files:**

- Modify: `frontend/tests/visual/fixtures.ts`
- Modify: `frontend/tests/visual/reference-port.spec.ts`
- Modify: `frontend/tests/visual/reference-goldens/dashboard-signals-desktop.png`
- Modify: `frontend/tests/visual/reference-goldens/dashboard-signals-mobile.png`
- Modify: `frontend/src/reference/dashboard/dashboard-reference.css`

- [ ] **Step 1: Make the visual fixture adversarial**

Include one publication date, one award date, missing buyer, no fit reason and
one locked teaser. Keep the fixture deterministic and ensure its unlocked
presentation is `FALLBACK/FACTUAL_FALLBACK` with null provider metadata.

- [ ] **Step 2: Run the Signals visual spec and confirm the intentional delta**

Run: `cd frontend && npx playwright test tests/visual/reference-port.spec.ts --grep 'dashboard-signals'`

Expected: desktop and mobile snapshots fail only where truthfulness copy changed.

- [ ] **Step 3: Recapture only the two Signals goldens**

Run: `cd frontend && npx playwright test tests/visual/reference-port.spec.ts --grep 'dashboard-signals' --update-snapshots`

Expected: exactly the desktop and mobile Signals PNGs change.

- [ ] **Step 4: Inspect both images at original resolution**

Open:

- `frontend/tests/visual/reference-goldens/dashboard-signals-desktop.png`
- `frontend/tests/visual/reference-goldens/dashboard-signals-mobile.png`

Record in the PR body: date labels, buyer/awardee separation, locked teaser,
line wrapping, selection/focus state, no invented role, and no clipped content.
If either image is ambiguous, correct CSS or fixture and repeat Steps 2–4.

- [ ] **Step 5: Run the complete visual suite and commit**

Run: `cd frontend && npm run test:visual`

Expected: all visual tests pass with no unhandled request, console error or
request failure.

```bash
git add frontend/tests/visual frontend/src/reference/dashboard/dashboard-reference.css
git commit -m "test(signals): recapture truthful signal goldens"
```

## Task 5: Verify, publish and merge PR 2

**Files:** Only files listed above.

- [ ] **Step 1: Run all repository gates**

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

- [ ] **Step 2: Audit scope against the merged dependency**

```bash
git diff --check origin/main...HEAD
git diff --name-status origin/main...HEAD
git log --oneline --decorate origin/main..HEAD
```

Expected: no foundation duplication, no migration, no provider wiring, no
unplanned file and no history rewrite.

- [ ] **Step 3: Push normally and create the replacement PR**

```bash
git push -u origin fix/119-signal-truthfulness-guardrails-v2
gh pr create --repo bruppacherrodrigue-art/Kivou --base main --head fix/119-signal-truthfulness-guardrails-v2 --title "fix(signals): enforce truthful signal copy" --body-file /tmp/kivou-pr2-body.md
```

Create the body with `apply_patch`. Link #119/#127, mark #121 as replaced,
name the merged foundation SHA, list inspected captures, and state that AI is
disabled and only factual artifacts are expected in staging.

- [ ] **Step 4: Require both jobs to execute real steps**

Resolve `KIVOU_PR_RUN_ID` from the PR head SHA, then use `gh pr checks` and
`gh run view "$KIVOU_PR_RUN_ID" --json headSha,status,conclusion,jobs`.
For both Backend and Frontend, require `conclusion=success`, at least checkout,
dependency install and test steps, and no empty `steps` array. A pre-runner
failure, cancellation or queued job is not evidence.

- [ ] **Step 5: Squash merge and verify exact-main CI**

Squash-merge without force-pushing, fetch `main`, verify the merged tree, then
wait for both real jobs on the exact new `origin/main` SHA. Close #121 with a
replacement link only after that CI succeeds.
