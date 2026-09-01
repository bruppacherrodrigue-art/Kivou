# Signals Phase 1 Factual History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a review-ready PR that makes Signaux a stable fact-only master-detail workspace with authorised historical pagination and auditable winner enrichment.

**Architecture:** Keep the account-scoped feed and existing `saas_company` authority, add a keyset history reader and an additive winner-enrichment work state, then make Signaux consume server-authored factual display fields. Reuse the two-scroll-pane interaction from Entreprises and keep filters and selections in the URL; introduce no commercial presentation, provider, prompt, Hermes, Acquisition or pricing path.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core, Alembic, PostgreSQL/SQLite, Pydantic, pytest, React 19, TypeScript, React Router, Vitest, Testing Library, CSS modules, Playwright.

---

## File map

- `src/signals/feed/history.py`: opaque cursor, effective factual date and keyset helpers.
- `src/signals/feed/factual_display.py`: fact-only title, summary and completeness projection.
- `src/signals/feed/query.py`: account-scoped history query and filters.
- `src/signals/feed/view.py`: factual projection at the HTTP boundary.
- `src/signals/api/routes_signals.py`: parameters, entitlements and batched projections.
- `src/signals/companies/enrichment.py`: idempotent queue, explicit worker and source state.
- `src/signals/companies/schema.py`: winner-enrichment state beside `saas_company`.
- `src/signals/persistence/migrations/versions/0030_winner_enrichment.py`: additive migration/backfill.
- `frontend/src/pages/SignalsFeed.tsx` and `.module.css`: URL state and isolated panes.
- `frontend/src/reference/dashboard/ReferenceSignalDetail.tsx`: factual detail hierarchy.
- API/model/adapter/i18n/test/visual files named in each task below.

### Task 1: Historical keyset contract

**Files:**
- Create: `src/signals/feed/history.py`
- Modify: `src/signals/feed/query.py`
- Test: `tests/test_feed_history.py`

- [x] **Step 1: Write failing effective-date and cursor tests**

Seed awards whose award, notification and publication dates conflict, then assert:

```python
first = history_page(connection, account_id=account_id, as_of=READ_ON, limit=2)
second = history_page(
    connection,
    account_id=account_id,
    as_of=READ_ON,
    limit=2,
    cursor=first.next_cursor,
)
assert set(item.signal.signal_key for item in first.items).isdisjoint(
    item.signal.signal_key for item in second.items
)
assert first.items[0].history_date_kind == "award"
```

Also cover malformed Base64/JSON, extra keys, unknown version, null/equal dates,
concurrent insertion ahead of the cursor, tenant isolation, stale ICP revisions
and batches containing unrenderable winner names.

- [x] **Step 2: Run the focused test and retain RED evidence**

Run: `uv run pytest -q tests/test_feed_history.py`  
Expected: FAIL because `signals.feed.history` and `history_page` do not exist.

- [x] **Step 3: Implement the closed cursor and factual date**

```python
@dataclasses.dataclass(frozen=True)
class HistoryCursor:
    date: dt.date | None
    signal_key: str
    version: Literal[1] = 1

def effective_date(signal: StoredSignal) -> tuple[dt.date | None, HistoryDateKind]:
    if signal.award.award_date is not None:
        return signal.award.award_date, "award"
    if signal.award.contract_notification_date is not None:
        return signal.award.contract_notification_date, "notification"
    if signal.event.published_on is not None:
        return signal.event.published_on, "publication"
    return None, "unknown"
```

Encode exact-key JSON as URL-safe Base64. Reject payloads above 512 bytes,
non-ISO dates and signal keys outside the persisted key bound.

- [x] **Step 4: Implement bounded keyset traversal**

Order the owned SQL query by `coalesce(award_date, notification_date,
published_on) DESC NULLS LAST, signal_key ASC`. Read bounded raw batches,
resolve display identities once per batch, and return a cursor that advances
past consumed rows without skipping the look-ahead result.

- [x] **Step 5: Verify history and existing pagination**

Run: `uv run pytest -q tests/test_feed_history.py tests/test_feed_pagination.py tests/test_feed_recency.py`  
Expected: PASS with no overlap or missing expected signal.

- [x] **Step 6: Commit**

```bash
git add src/signals/feed/history.py src/signals/feed/query.py tests/test_feed_history.py
git commit -m "feat(signals): add stable historical cursor"
```

### Task 2: Server filters, entitlements and access metadata

**Files:**
- Modify: `src/signals/api/routes_signals.py`
- Modify: `src/signals/billing/access.py`
- Modify: `src/signals/feed/query.py`
- Test: `tests/test_feed_history.py`
- Test: `tests/test_billing_paywall.py`

- [x] **Step 1: Add failing API tests**

Request `view=history`, `cursor`, `date_from`, `date_to`, `country`,
`subdivision_code`, `status` and `cpv_prefix`. Assert `date_from <= date_to`,
filter-level 403 responses, tenant isolation, exact cursor continuation,
locked-only protected data and access metadata matching existing
Discovery/Essential/Pro/Scale rights.

- [x] **Step 2: Run the API tests and retain RED evidence**

Run: `uv run pytest -q tests/test_feed_history.py tests/test_billing_paywall.py -k 'history or filter'`  
Expected: FAIL because the route does not accept the new contract.

- [x] **Step 3: Extend existing filter requirements**

```python
FILTER_REQUIREMENTS |= {
    "date_from": "minimum",
    "date_to": "minimum",
    "subdivision_code": "basic",
    "status": "basic",
    "cpv_prefix": "advanced",
}
```

Compute `filter_access` from `FILTER_RANK` and `history_access` from the existing
`history_days`/scope. Do not change catalogue plans, prices or checkout.

- [x] **Step 4: Route history through keyset pagination**

Keep offset fields for `view=recent`. For history, return additive
`cursor`/`next_cursor`, `view`, `history_access` and `filter_access`. Map a bad
cursor to closed 422 and never fall back to offset.

- [x] **Step 5: Verify feed and paywall regressions**

Run: `uv run pytest -q tests/test_feed_history.py tests/test_feed_pagination.py tests/test_feed_ownership.py tests/test_billing_paywall.py tests/test_billing_upgrade_eligibility.py`  
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add src/signals/api/routes_signals.py src/signals/billing/access.py src/signals/feed/query.py tests/test_feed_history.py tests/test_billing_paywall.py
git commit -m "feat(signals): expose authorised history filters"
```

### Task 3: Fact-only display projection

**Files:**
- Create: `src/signals/feed/factual_display.py`
- Modify: `src/signals/feed/view.py`
- Test: `tests/test_feed_factual_display.py`
- Test: `tests/test_feed_facts.py`

- [ ] **Step 1: Add failing truthfulness tests**

Cover full facts, missing amount/place/object/buyer, identifier-like winners,
buyer/winner inversion, notification versus award date, FR/EN and raw titles
containing a person or urgency. Assert no output includes plausible needs,
roles, recommendations, `analysis` values or an identifier as title.

- [ ] **Step 2: Run and retain RED evidence**

Run: `uv run pytest -q tests/test_feed_factual_display.py tests/test_feed_facts.py`  
Expected: FAIL because `factual_display` is absent.

- [ ] **Step 3: Implement bounded fact-only copy**

Return `headline`, `market_summary`, `object_short`, explicit date value/kind,
`completeness` and `missing_fields`, using only display identity, structured
contract fields and the selected event clock. Normalize whitespace and bound
lengths. Never read `analysis` or `presentation`.

- [ ] **Step 4: Publish it only on unlocked feed/detail**

Add `factual_display` in `feed_item`; keep the locked teaser key set unchanged
and keep the optional presentation contract untouched for other surfaces.

- [ ] **Step 5: Verify boundaries**

Run: `uv run pytest -q tests/test_feed_factual_display.py tests/test_feed_facts.py tests/test_billing_paywall.py tests/test_card_presentation_api.py`  
Expected: PASS and locked payloads still lack `presentation`.

- [ ] **Step 6: Commit**

```bash
git add src/signals/feed/factual_display.py src/signals/feed/view.py tests/test_feed_factual_display.py tests/test_feed_facts.py
git commit -m "feat(signals): publish factual display hierarchy"
```

### Task 4: Durable winner-enrichment state and migration

**Files:**
- Modify: `src/signals/companies/schema.py`
- Create: `src/signals/persistence/migrations/versions/0030_winner_enrichment.py`
- Create: `tests/test_winner_enrichment_migration.py`
- Modify: `tests/test_saas_company_architecture.py`

- [ ] **Step 1: Add failing migration and architecture tests**

Assert one Alembic head, upgrade from `0029_production_observation`, exact
columns/checks/indexes, set-based backfill, round-trip equality, no destructive
change to `saas_company`, and no provider/HTTP/Acquisition import in the company
boundary.

- [ ] **Step 2: Run and retain RED evidence**

Run: `uv run pytest -q tests/test_winner_enrichment_migration.py tests/test_saas_company_architecture.py`  
Expected: FAIL because revision 0030 and its table do not exist.

- [ ] **Step 3: Define the additive work-state table**

Create `winner_enrichment_job` keyed by `signal_key`, with identity fingerprint,
status, attempt count, bounded error code and queued/started/finished/updated
timestamps. Its check enforces:

```sql
(status = 'pending' AND attempt_count = 0 AND started_at IS NULL AND finished_at IS NULL)
OR (status = 'in_progress' AND attempt_count >= 1 AND started_at IS NOT NULL AND finished_at IS NULL)
OR (status IN ('completed', 'partial', 'failed') AND attempt_count >= 1
    AND started_at IS NOT NULL AND finished_at IS NOT NULL)
```

- [ ] **Step 4: Implement the migration and backfill**

Insert one row per current indexed signal. Join existing `saas_company` rows by
fingerprint: set completed only when core official identity, identifier/domain,
country, address and website are stored; otherwise partial; leave absent
company projections pending. Perform no network call.

- [ ] **Step 5: Verify migrations and core schema**

Run: `uv run pytest -q tests/test_winner_enrichment_migration.py tests/test_saas_company_migration.py tests/test_persistence_migrations.py tests/test_saas_company_architecture.py`  
Expected: PASS and head `0030_winner_enrichment`.

- [ ] **Step 6: Commit**

```bash
git add src/signals/companies/schema.py src/signals/persistence/migrations/versions/0030_winner_enrichment.py tests/test_winner_enrichment_migration.py tests/test_saas_company_architecture.py
git commit -m "feat(companies): add winner enrichment state"
```

### Task 5: Explicit fact-only worker and pure GET projections

**Files:**
- Create: `src/signals/companies/enrichment.py`
- Modify: `src/signals/companies/contracts.py`
- Modify: `src/signals/companies/service.py`
- Modify: `src/signals/persistence/materialization.py`
- Modify: `src/signals/api/routes_signals.py`
- Modify: `src/signals/api/routes_companies.py`
- Create: `tests/test_winner_enrichment.py`
- Create: `tests/test_winner_enrichment_api.py`
- Modify: `tests/test_saas_company_service.py`
- Modify: `tests/test_saas_company_api.py`

- [ ] **Step 1: Add failing worker and GET tests**

Test enqueue replay, pending/in-progress/completed/partial/failed, bounded retry,
two concurrent claims, malformed source, exact-name collisions, tenant
isolation and safe logging. Patch every provider/client entry point to raise and
assert feed/detail/company GET still succeed with constant statement counts.

- [ ] **Step 2: Run and retain RED evidence**

Run: `uv run pytest -q tests/test_winner_enrichment.py tests/test_winner_enrichment_api.py tests/test_saas_company_service.py tests/test_saas_company_api.py`  
Expected: FAIL because the state/worker contract is absent.

- [ ] **Step 3: Implement the explicit non-autostart worker API**

```python
def enqueue_winner_enrichment(
    connection: sa.Connection, *, signal_key: str, now: dt.datetime
) -> None: ...

def run_winner_enrichment_batch(
    connection: sa.Connection,
    *,
    now: dt.datetime,
    worker_ref: str,
    limit: int = 100,
    retry_failed: bool = False,
) -> WinnerEnrichmentBatch: ...

def winner_enrichments_for_signals(
    connection: sa.Connection, *, signal_keys: tuple[str, ...]
) -> dict[str, WinnerEnrichmentView]: ...
```

The implementation may call only existing exact identity/index/store functions.
Use PostgreSQL skip-locked claims and a bounded SQLite compare-and-set path. It
must not import Company Research, Apollo, HTTP, Hermes or Acquisition.

- [ ] **Step 4: Enqueue at materialization and make GET routes consume only**

After exact indexing, enqueue in the caller transaction. Replace on-GET
`ensure_*` calls by one fingerprint/company lookup and one enrichment-state
lookup per page. Do not expose either lookup for locked items.

- [ ] **Step 5: Expose closed source/state contracts**

Return status, missing fields, last verification, bounded error code and a
source containing only `public_notice`, connector/system, notice ID, safe HTTPS
URL and retrieval timestamp. Never return raw validation payloads or paths.

- [ ] **Step 6: Verify worker, company, ingestion and provider boundaries**

Run: `uv run pytest -q tests/test_winner_enrichment.py tests/test_winner_enrichment_api.py tests/test_saas_company_service.py tests/test_saas_company_api.py tests/test_ingestion_e2e.py tests/test_saas_company_architecture.py`  
Expected: PASS with no provider call on GET and no N+1.

- [ ] **Step 7: Commit**

```bash
git add src/signals/companies src/signals/persistence/materialization.py src/signals/api/routes_signals.py src/signals/api/routes_companies.py tests/test_winner_enrichment.py tests/test_winner_enrichment_api.py tests/test_saas_company_service.py tests/test_saas_company_api.py
git commit -m "feat(companies): process winner facts asynchronously"
```

### Task 6: Frontend factual contracts and adapters

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/reference/dashboard/models.ts`
- Modify: `frontend/src/reference/dashboard/adapters.ts`
- Modify: `frontend/src/reference/dashboard/adapters.test.ts`
- Modify: `frontend/src/test/harness.tsx`

- [ ] **Step 1: Add failing adapter tests**

Assert titles, summaries and states are copied from the server; malformed state
fails closed; locked cards expose none of it; and Signaux adapters read no
presentation, plausible need, fit, target role or recommended action.

- [ ] **Step 2: Run and retain RED evidence**

Run: `cd frontend && npm test -- --run src/reference/dashboard/adapters.test.ts`  
Expected: FAIL on missing factual/enrichment contracts.

- [ ] **Step 3: Add exact TypeScript contracts**

Define `SignalFactualDisplay`, `WinnerEnrichment`, `HistoryAccess`,
`FilterAccess`, optional cursor page fields and new FeedQuery parameters. Keep
presentation compatible on unlocked payloads and forbidden on locked payloads.

- [ ] **Step 4: Convert only server-authored facts**

Populate `SignalCardView` and `SignalDetailView` from `factual_display` and
`winner_enrichment`. Leave `publishedPresentation` for other dashboard
surfaces, but remove it from Signaux conversions.

- [ ] **Step 5: Verify adapters and typecheck**

Run: `cd frontend && npm test -- --run src/reference/dashboard/adapters.test.ts && npm run typecheck`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api frontend/src/reference/dashboard frontend/src/test/harness.tsx
git commit -m "refactor(signals): consume factual display contract"
```

### Task 7: Signaux navigation, filters and cursor pagination

**Files:**
- Modify: `frontend/src/pages/SignalsFeed.tsx`
- Create: `frontend/src/pages/SignalsFeed.module.css`
- Modify: `frontend/src/signals/signalWorkspace.test.tsx`
- Modify: `frontend/src/signals/feed.test.tsx`
- Modify: `frontend/src/companies/referenceCompanies.test.tsx`
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`

- [ ] **Step 1: Add failing workspace tests**

Cover first/long-scroll/repeated selection, active state during slow detail,
detail error, independent pane scroll positions, mobile focus, back/forward,
reload, recent/history switch, cursor Load More, deduplication, filter URL
persistence, terminal/empty/error states, entitlement explanation and the
unchanged Entreprises workspace.

```tsx
listPanel.scrollTop = 720
detailPanel.scrollTop = 410
await user.click(secondSignal)
expect(listPanel.scrollTop).toBe(720)
expect(detailPanel.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'auto' })
expect(detailTitle).toHaveFocus()
```

- [ ] **Step 2: Run and retain RED evidence**

Run: `cd frontend && npm test -- --run src/signals/signalWorkspace.test.tsx src/signals/feed.test.tsx src/companies/referenceCompanies.test.tsx`  
Expected: FAIL on pane isolation, URL filters and cursor pagination.

- [ ] **Step 3: Reuse the Entreprises pane behavior**

Add list/detail refs, `useLayoutEffect` detail reset,
`focus({preventScroll:true})`, responsive `data-pane=list|detail` CSS and mobile
Back focus restoration. Remove window `scrollIntoView`.

- [ ] **Step 4: Make view and filters URL-owned**

Parse/serialize `view`, `from`, `to`, `country`, `subdivision`, `status` and
`cpv`; retain the search string on `/app/signals/:signalKey`. A new filter starts
a generation, ignores stale responses and keeps prior data during refresh.

- [ ] **Step 5: Page recent by offset and history by cursor**

Append only unseen signal IDs, pass `next_cursor` verbatim, and never derive a
cursor. Display the server access/filter metadata and local retry/end states.

- [ ] **Step 6: Render factual cards and compact real states**

Show company, object, amount, place, useful date, buyer and server status. Do
not show administrative identifiers, a repeated large facts-only badge or any
commercial presentation text.

- [ ] **Step 7: Verify focused frontend regressions**

Run: `cd frontend && npm test -- --run src/signals src/companies/referenceCompanies.test.tsx src/reference/dashboard/adapters.test.ts`  
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/SignalsFeed.tsx frontend/src/pages/SignalsFeed.module.css frontend/src/signals frontend/src/companies/referenceCompanies.test.tsx frontend/src/i18n
git commit -m "fix(signals): preserve list detail navigation"
```

### Task 8: Factual detail hierarchy and sources

**Files:**
- Modify: `frontend/src/reference/dashboard/ReferenceSignalDetail.tsx`
- Create: `frontend/src/reference/dashboard/ReferenceSignalDetail.module.css`
- Modify: `frontend/src/signals/detail.test.tsx`
- Modify: `frontend/src/signals/referenceSignalWorkspace.test.tsx`
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`

- [ ] **Step 1: Add failing hierarchy/no-commercial tests**

Assert DOM order: winner, market summary, amount/date/place/buyer, company
facts, Kivou award history, sources/proofs, missing data, then collapsed
identifiers. Cover completed/partial/pending/failed and missing amount/place.
Even with a legacy PASS fixture, assert the DOM omits its importance, fit,
timing, role, need and recommendation strings.

- [ ] **Step 2: Run and retain RED evidence**

Run: `cd frontend && npm test -- --run src/signals/detail.test.tsx src/signals/referenceSignalWorkspace.test.tsx`  
Expected: FAIL because the current detail is presentation-first.

- [ ] **Step 3: Rebuild around factual blocks**

Use the server title/summary and render the discrete notice: “Analyse
commerciale non disponible pour ce signal. Les informations affichées
ci-dessous proviennent des sources vérifiées.” Render enrichment honestly and
never block the detail while it is pending/failed.

- [ ] **Step 4: Collapse sources/technical facts by default**

Use native `<details>` with “Sources et vérification”. List safe official links,
evidence excerpts and retrieval dates before identifiers, references, CPV and
opportunity ID. Absent/unsafe URLs are text, not links.

- [ ] **Step 5: Verify detail, accessibility and Companies**

Run: `cd frontend && npm test -- --run src/signals src/reference/dashboard/adapters.test.ts src/companies`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/reference/dashboard/ReferenceSignalDetail.tsx frontend/src/reference/dashboard/ReferenceSignalDetail.module.css frontend/src/signals frontend/src/i18n
git commit -m "fix(signals): prioritise verified award facts"
```

### Task 9: Visual fixtures and responsive inspection

**Files:**
- Modify: `frontend/tests/visual/fixtures.ts`
- Modify: `frontend/tests/visual/reference-port.spec.ts`
- Modify: `frontend/tests/visual/reference-goldens/dashboard-signals-desktop.png`
- Modify: `frontend/tests/visual/reference-goldens/dashboard-signals-mobile.png`
- Create: `output/playwright/signals-phase1/` inspection artifacts (untracked).

- [ ] **Step 1: Add deterministic rich/old/missing/state scenarios**

Include rich current, old, no amount, no place and all real enrichment states.
Add browser assertions for list scroll retention, active selection, history
Load More, mobile Back/focus and zero console errors.

- [ ] **Step 2: Run Signals visual regression before recapture**

Run: `cd frontend && npx playwright test tests/visual/reference-port.spec.ts --grep 'dashboard-signals'`  
Expected: FAIL only on intentional Signaux snapshots/assertions.

- [ ] **Step 3: Recapture only two Signaux goldens**

Run: `cd frontend && npx playwright test tests/visual/reference-port.spec.ts --grep 'dashboard-signals' --update-snapshots`  
Expected: PASS and exactly desktop/mobile Signaux files updated.

- [ ] **Step 4: Inspect original-resolution desktop/mobile images**

Verify hierarchy, no clipping, isolated panes, filters, compact states,
collapsed sources, mobile single pane and focus. Use Playwright CLI to save
additional rich/old/missing/error captures under `output/playwright/signals-phase1/`.

- [ ] **Step 5: Run full visual suite and commit**

Run: `cd frontend && npm run test:visual`  
Expected: PASS with no non-Signaux golden changed.

```bash
git add frontend/tests/visual/fixtures.ts frontend/tests/visual/reference-port.spec.ts frontend/tests/visual/reference-goldens/dashboard-signals-desktop.png frontend/tests/visual/reference-goldens/dashboard-signals-mobile.png
git commit -m "test(signals): recapture factual history goldens"
```

### Task 10: Full verification and review-ready PR

**Files:**
- Modify: `docs/superpowers/plans/2026-09-01-signals-phase1-factual-history.md`
- Create: `docs/superpowers/reports/2026-09-01-signals-phase1-factual-history-verification.md`

- [ ] **Step 1: Run backend gates**

```bash
uv run pytest -q
uv run ruff check .
uv run pytest -q tests/test_persistence_migrations.py tests/test_winner_enrichment_migration.py
```

Expected: all tests PASS, Ruff clean, one head 0030.

- [ ] **Step 2: Run frontend gates**

```bash
cd frontend
npm test -- --run
npm run typecheck
npm run lint
npm run build
npm run test:visual
```

Expected: all PASS.

- [ ] **Step 3: Run integration/repository checks**

```bash
uv run pytest -q tests/test_ingestion_e2e.py tests/test_winner_enrichment_api.py tests/test_feed_history.py
git diff --check origin/main...HEAD
git status --short
```

Expected: PASS and only intended committed files.

- [ ] **Step 4: Review every requirement and write the report**

Search changed production files for provider/model/prompt/Hermes/Acquisition/
pricing imports and commercial copy. Inspect locked contracts, statement-count
tests and screenshots. Record causes, architecture, exact results, migration,
backfill, captures, limitations, risks, rollback and `IA commerciale :
DÉSACTIVÉE` in the verification report.

- [ ] **Step 5: Commit report**

```bash
git add docs/superpowers/plans/2026-09-01-signals-phase1-factual-history.md docs/superpowers/reports/2026-09-01-signals-phase1-factual-history-verification.md
git commit -m "docs(signals): record phase one verification"
```

- [ ] **Step 6: Push without force and open the PR**

```bash
git push -u origin fix/signals-phase1-factual-history
gh pr create --base main --head fix/signals-phase1-factual-history --title "fix(signals): factual history and stable detail navigation" --body-file /tmp/kivou-signals-phase1-pr.md
```

The body lists scope, root causes, test counts, screenshots, migration/backfill,
risks, limits, rollback, no deploy, no merge and AI disabled. Never force-push.

- [ ] **Step 7: Verify remote state without merging**

Run: `gh pr view --json number,url,state,isDraft,headRefName,baseRefName,headRefOid,statusCheckRollup`  
Expected: open PR against main at the exact head SHA, not merged and not deployed.
