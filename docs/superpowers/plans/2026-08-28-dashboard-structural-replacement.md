# Dashboard Structural Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Replace the connected Kivou dashboard legacy composition with the approved light editorial shell, real-data overview and responsive signal master-detail workspace without changing backend, billing, permission or paywall authority.

**Architecture:** Keep every existing API endpoint and account boundary. Refactor the connected shell and pages in place, make SignalsFeed own both the feed and route-backed selection, and turn SignalDetail into a reusable panel while preserving safe direct deep links. Derive each overview metric from one already fetched API resource and keep resource loading, errors and retries independent.

**Tech Stack:** React 19, React Router 7, TypeScript 5.7, CSS Modules, Vitest, Testing Library, Vite; FastAPI contracts remain unchanged.

---

## File structure

- Modify frontend/src/styles/tokens.css for the connected ivory/green system.
- Modify frontend/src/layouts/AppShell.tsx and AppShell.module.css for the light five-item rail.
- Modify frontend/src/App.tsx so both signal URLs render the workspace.
- Modify frontend/src/pages/SignalsFeed.tsx and SignalsFeed.module.css for feed, filters, selection and responsive layout.
- Create frontend/src/signals/SignalListRow.tsx and SignalListRow.module.css for the dense safe list.
- Modify frontend/src/pages/SignalDetail.tsx and SignalDetail.module.css to export an embeddable detail panel.
- Modify frontend/src/pages/Dashboard.tsx and Dashboard.module.css for real summaries and a compact working surface.
- Restyle Companies, CompanyProfile, Icps, Settings, Billing and Notifications around their existing contracts.
- Extend frontend/src/i18n/fr.ts and en.ts with parity.
- Create frontend/src/signals/signalWorkspace.test.tsx and update existing dashboard, feed, detail and fidelity tests.

### Task 1: Lock the new structure in failing tests

**Files:**
- Modify: frontend/src/pages/referenceFidelity.test.tsx
- Create: frontend/src/signals/signalWorkspace.test.tsx

- [ ] **Step 1: Replace the old dark-shell CSS assertion**

~~~tsx
it('rend le rail clair et seulement les cinq destinations client approuvées', async () => {
  mockApi({
    'GET /signals': { body: feedPage([]) },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /target-icps': { body: [ICP] },
    'GET /notification-preferences': {
      body: {
        email_enabled: true,
        notification_email: 'claire@acme.test',
        updated_at: '2026-08-18T09:00:00+00:00',
      },
    },
  })
  renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })

  const nav = screen.getByRole('navigation', { name: 'Navigation principale' })
  expect(within(nav).getAllByRole('link')).toHaveLength(5)
  expect(within(nav).getByRole('link', { name: 'Vue d’ensemble' })).toHaveAttribute(
    'aria-current',
    'page',
  )
  for (const absent of ['Marchés', 'Veille', 'Notes', 'Apollo', 'Instantly']) {
    expect(within(nav).queryByText(absent)).not.toBeInTheDocument()
  }

  const shell = read('src/layouts/AppShell.module.css')
  expect(shell).toMatch(/\.sidebar\s*\{[^}]*background:\s*var\(--kivou-connected-rail\)/s)
  expect(shell).toMatch(/\.workspace\s*\{[^}]*background:\s*var\(--kivou-connected-canvas\)/s)
})
~~~

- [ ] **Step 2: Create the workspace regression suite**

Import `feedPage` into `referenceFidelity.test.tsx`. In the new suite, import
AUTHENTICATED, DISCOVERY_STATUS, ICP, LOCKED_ITEM, UNLOCKED_ITEM,
UNLOCKED_DETAIL, callsTo, mockApi and renderApp from the existing harness. Define
this contract-shaped FeedPage fixture:

~~~tsx
const page = (items = [UNLOCKED_ITEM, LOCKED_ITEM]) => ({
  items,
  total_returned: items.length,
  page: { limit: 20, offset: 0, has_more: false, scan_truncated: false },
  excluded: { without_display_name: 0, by_freshness: 0 },
  read_at: '2026-08-28T19:15:00+00:00',
  freshness: 'new' as const,
  language: 'fr',
  plan_code: 'discovery' as const,
  policy: { feed: 'feed-v1', recency: 'recency-v1', paywall: 'paywall-v1' },
})

function routes() {
  return {
    'GET /signals': { body: page() },
    'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /target-icps': { body: [ICP] },
  }
}
~~~

Add these tests:

~~~tsx
it('sélectionne une ligne accessible et affiche son détail dans le même workspace', async () => {
  const user = userEvent.setup()
  mockApi(routes())
  renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

  await user.click(await screen.findByRole('link', { name: /Constructions Bertrand SA/ }))
  const panel = await screen.findByRole('region', { name: 'Détail du signal sélectionné' })
  expect(within(panel).getByText('Commune de Villeneuve')).toBeInTheDocument()
})

it('ne demande aucun détail pour une ligne déjà déclarée verrouillée', async () => {
  const user = userEvent.setup()
  mockApi(routes())
  renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

  await user.click(await screen.findByRole('button', { name: /signal verrouillé/i }))
  expect(callsTo('/signals/sig_locked_1', 'GET')).toHaveLength(0)
  expect(screen.getByRole('link', { name: 'Gérer mon accès' })).toHaveAttribute(
    'href',
    '/app/billing',
  )
})

it('charge un lien profond dont le niveau d’accès est encore inconnu', async () => {
  mockApi(routes())
  renderApp(<AppRoutes />, {
    route: '/app/signals/sig_unlocked_1',
    session: AUTHENTICATED,
  })

  await screen.findByRole('region', { name: 'Détail du signal sélectionné' })
  expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(1)
})
~~~

- [ ] **Step 3: Run RED**

~~~bash
cd frontend
npm test -- --run src/pages/referenceFidelity.test.tsx src/signals/signalWorkspace.test.tsx
~~~

Expected: FAIL because the shell is dark and no shared master-detail workspace exists.

- [ ] **Step 4: Commit the red contract**

~~~bash
git add frontend/src/pages/referenceFidelity.test.tsx frontend/src/signals/signalWorkspace.test.tsx
git commit -m "test(frontend): require structural dashboard replacement"
~~~

### Task 2: Replace the connected shell

**Files:**
- Modify: frontend/src/styles/tokens.css
- Modify: frontend/src/layouts/AppShell.tsx
- Modify: frontend/src/layouts/AppShell.module.css
- Test: frontend/src/pages/referenceFidelity.test.tsx

- [ ] **Step 1: Add connected-only tokens**

~~~css
:root {
  --kivou-connected-canvas: #f7f3ec;
  --kivou-connected-rail: #f3eee5;
  --kivou-connected-surface: #fffdf9;
  --kivou-connected-surface-muted: #faf6ef;
  --kivou-connected-line: #ddd5c8;
  --kivou-connected-line-strong: #cbbfab;
  --kivou-connected-ink: #152b24;
  --kivou-connected-muted: #6d716d;
  --kivou-connected-accent: #b66a47;
  --kivou-connected-positive: #0f5a47;
  --kivou-connected-rail-width: 248px;
  --kivou-connected-panel-radius: 16px;
}
~~~

Do not change the public marketing variables.

- [ ] **Step 2: Change the shell to dark logo on a light rail**

Keep NAV_ITEMS, logout, Escape handling and commercial-cockpit capability. Keep
`aria-label={t.nav.mainNavigation}` on the existing `nav`; the `aside` does not need a
second navigation label. Render:

~~~tsx
<aside className={styles.sidebar}>
  <Link to="/app/dashboard" className={styles.logoLink}>
    <KivouLogo size="md" />
  </Link>
  {navigation}
  <div className={styles.sidebarFooter}>{accountPanel}</div>
</aside>
~~~

Use the same light treatment in the mobile drawer. Do not use inverse logo or inverse-only text.

- [ ] **Step 3: Replace the dark geometry**

~~~css
.shell { min-height: 100vh; background: var(--kivou-connected-canvas); }
.sidebar {
  display: none;
  background: var(--kivou-connected-rail);
  color: var(--kivou-connected-ink);
}
.navItem {
  color: var(--kivou-connected-muted);
  border: 1px solid transparent;
  border-radius: 10px;
}
.navItem:hover,
.navItemActive {
  color: var(--kivou-connected-ink);
  background: var(--kivou-connected-surface);
  border-color: var(--kivou-connected-line);
}
.navMarker { left: -1px; width: 3px; background: var(--kivou-connected-positive); }
.workspace { min-width: 0; background: var(--kivou-connected-canvas); }

@media (min-width: 1024px) {
  .shell { padding-left: var(--kivou-connected-rail-width); }
  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    display: flex;
    width: var(--kivou-connected-rail-width);
    border-right: 1px solid var(--kivou-connected-line);
  }
}
~~~

Update account, logout, topbar and drawer colours to the same variables.

- [ ] **Step 4: Verify shell GREEN**

~~~bash
cd frontend
npm test -- --run src/pages/referenceFidelity.test.tsx src/pages/dashboard.test.tsx
~~~

Expected: PASS, including current navigation and session behavior.

- [ ] **Step 5: Commit**

~~~bash
git add frontend/src/styles/tokens.css frontend/src/layouts/AppShell.tsx frontend/src/layouts/AppShell.module.css
git commit -m "refactor(frontend): replace connected application shell"
~~~

### Task 3: Unify signal routes and protect selection races

**Files:**
- Modify: frontend/src/App.tsx
- Modify: frontend/src/pages/SignalsFeed.tsx
- Modify: frontend/src/pages/SignalDetail.tsx
- Modify: frontend/src/signals/signalWorkspace.test.tsx

- [ ] **Step 1: Point both routes at SignalsFeed**

~~~tsx
<Route path="signals" element={<SignalsFeed />} />
<Route path="signals/:signalKey" element={<SignalsFeed />} />
~~~

Remove the now-unused SignalDetail route import only after typecheck.

- [ ] **Step 2: Add the stale-response test**

Create a deferred first detail response, immediately select a second signal, resolve the second detail first, then resolve the first. Assert that the second company remains visible and the first buyer never replaces it.

~~~tsx
expect(await screen.findByText('Deuxième SA')).toBeInTheDocument()
resolveFirst({ body: UNLOCKED_DETAIL })
await waitFor(() => {
  expect(screen.queryByText('Commune de Villeneuve')).not.toBeInTheDocument()
})
~~~

- [ ] **Step 3: Add generation-protected detail state**

~~~tsx
const { signalKey } = useParams()
const detailGeneration = useRef(0)
const resolvedSignalKey = useRef<string | null>(null)
interface DetailState {
  data: SignalDetailPayload | null
  loading: boolean
  error: unknown | null
}

const [detailState, setDetailState] = useState<DetailState>({
  data: null,
  loading: false,
  error: null,
})

useEffect(() => {
  if (loading) return
  const selected = items.find((item) => item.signal_id === signalKey)
  if (!signalKey) {
    detailGeneration.current += 1
    resolvedSignalKey.current = null
    setDetailState({ data: null, loading: false, error: null })
    return
  }
  if (selected?.locked) {
    detailGeneration.current += 1
    resolvedSignalKey.current = signalKey
    setDetailState({ data: null, loading: false, error: null })
    return
  }
  if (resolvedSignalKey.current === signalKey) return

  const generation = ++detailGeneration.current
  resolvedSignalKey.current = signalKey
  setDetailState((current) => ({ ...current, loading: true, error: null }))
  signals.detail(signalKey).then(
    (data) => {
      if (generation === detailGeneration.current) {
        setDetailState({ data, loading: false, error: null })
      }
    },
    (error) => {
      if (generation === detailGeneration.current) {
        setDetailState((current) => ({ ...current, loading: false, error }))
      }
    },
  )
}, [items, loading, signalKey])
~~~

A locked feed selection renders its bounded feed teaser without a detail request. An unknown deep link calls the account-scoped detail endpoint because only the backend knows access.
The local retry clears `resolvedSignalKey.current`, then executes the same loader; this
preserves one request per selection while still allowing an explicit retry after error.

- [ ] **Step 4: Export an embeddable detail panel**

~~~tsx
export interface SignalDetailPanelProps {
  detail: SignalDetailPayload | null
  loading: boolean
  error: unknown | null
  embedded?: boolean
}

export function SignalDetailPanel(props: SignalDetailPanelProps) {
  const { t } = useI18n()
  if (props.loading) return <DetailSkeleton />
  if (props.error) {
    const copy = describeError(props.error, t)
    return (
      <Callout tone="danger" title={copy.title} live>
        {copy.body}
      </Callout>
    )
  }
  if (!props.detail) return <p>{t.workspace.chooseSignal}</p>
  return props.detail.locked
    ? <LockedDetailView detail={props.detail} embedded={props.embedded} />
    : <UnlockedDetailView detail={props.detail} embedded={props.embedded} />
}
~~~

Keep SignalDetail as a thin loader wrapper so focused detail tests can still mount it independently.

- [ ] **Step 5: Verify routes and races**

~~~bash
cd frontend
npm test -- --run src/signals/signalWorkspace.test.tsx src/signals/detail.test.tsx src/signals/feed.test.tsx
npm run typecheck
~~~

Expected: PASS.

- [ ] **Step 6: Commit**

~~~bash
git add frontend/src/App.tsx frontend/src/pages/SignalsFeed.tsx frontend/src/pages/SignalDetail.tsx frontend/src/signals/signalWorkspace.test.tsx
git commit -m "refactor(frontend): unify signal list and detail routes"
~~~

### Task 4: Build the reference master-detail workspace

**Files:**
- Create: frontend/src/signals/SignalListRow.tsx
- Create: frontend/src/signals/SignalListRow.module.css
- Modify: frontend/src/pages/SignalsFeed.tsx
- Modify: frontend/src/pages/SignalsFeed.module.css
- Modify: frontend/src/pages/SignalDetail.tsx
- Modify: frontend/src/pages/SignalDetail.module.css
- Modify: frontend/src/i18n/fr.ts
- Modify: frontend/src/i18n/en.ts
- Test: frontend/src/signals/feed.test.tsx
- Test: frontend/src/signals/detail.test.tsx

- [ ] **Step 1: Add a failing dense-workspace test**

~~~tsx
const workspace = await screen.findByTestId('signal-workspace')
const list = within(workspace).getByRole('list', { name: 'Liste des signaux' })
const row = within(list).getByRole('article')
expect(row).toHaveTextContent('Constructions Bertrand SA')
expect(row).toHaveTextContent('Réfection de la voirie communale')
expect(row).not.toHaveTextContent('Preuves des faits publiés')
expect(within(workspace).getByRole('region', {
  name: 'Détail du signal sélectionné',
})).toBeInTheDocument()
~~~

- [ ] **Step 2: Implement SignalListRow with strict narrowing**

Unlocked row:

~~~tsx
<Link className={styles.rowLink} to={'/app/signals/' + encodeURIComponent(item.signal_id)}>
  <span className={styles.identity}>{item.company.name ?? t.common.notAvailable}</span>
  <span className={styles.contract}>{item.contract.title ?? t.common.notAvailable}</span>
  <span className={styles.meta}>
    {item.event.date ? date(item.event.date) : t.common.notAvailable}
  </span>
  <strong className={styles.amount}>
    {amount(item.contract.amount?.value, item.contract.amount?.currency) ?? t.common.notAvailable}
  </strong>
</Link>
~~~

Locked row must read only headline, event and context. It uses an explicit button callback and never a detail link.

- [ ] **Step 3: Implement desktop split and mobile drill-in**

~~~css
.workspace {
  min-height: calc(100vh - 150px);
  display: grid;
  grid-template-columns: minmax(18rem, .82fr) minmax(28rem, 1.48fr);
  border: 1px solid var(--kivou-connected-line);
  border-radius: var(--kivou-connected-panel-radius);
  background: var(--kivou-connected-surface);
  overflow: clip;
}
.master { min-width: 0; border-right: 1px solid var(--kivou-connected-line); }
.detail { min-width: 0; background: var(--kivou-connected-surface); }

@media (max-width: 899px) {
  .workspace { display: block; border: 0; }
  .masterHidden,
  .detailHidden { display: none; }
  .detail { min-height: calc(100vh - 68px); }
}
~~~

Keep filters above the workspace. Desktop may preselect the first unlocked row after the feed returns; mobile must leave the list primary until the user selects.

- [ ] **Step 4: Recompose detail without removing evidence or actions**

Wrap the existing unlocked detail content in a `section` labelled
`t.workspace.detailRegion`. Move its existing `factsSection`, `analysisSection` and
`evidenceSection` blocks intact into the embedded two-column layout, and add ordinary
anchor links to their existing ids (`#kivou-facts`, `#kivou-analysis`,
`#kivou-evidence`). The links must not use tab roles and must not hide content. Keep
the existing safe source link, company_key link, `NeedList`, `EvidencePanel` and
`FeedbackControl` instances; do not duplicate or abbreviate their payloads.

- [ ] **Step 5: Add exact FR/EN keys**

~~~ts
workspace: {
  detailRegion: 'Détail du signal sélectionné',
  detailSections: 'Sections du signal',
  chooseSignal: 'Sélectionnez un signal pour examiner ses faits et son analyse.',
  lockedSelection: 'Examiner l’aperçu du signal verrouillé',
  backToList: 'Retour à la liste',
},
~~~

~~~ts
workspace: {
  detailRegion: 'Selected signal details',
  detailSections: 'Signal sections',
  chooseSignal: 'Select a signal to review its facts and analysis.',
  lockedSelection: 'Review the locked signal preview',
  backToList: 'Back to the list',
},
~~~

- [ ] **Step 6: Verify GREEN**

~~~bash
cd frontend
npm test -- --run src/signals/feed.test.tsx src/signals/detail.test.tsx src/signals/signalWorkspace.test.tsx
npm run typecheck
~~~

Expected: PASS without unsafe union-property access.

- [ ] **Step 7: Commit**

~~~bash
git add frontend/src/signals/SignalListRow.tsx frontend/src/signals/SignalListRow.module.css frontend/src/pages/SignalsFeed.tsx frontend/src/pages/SignalsFeed.module.css frontend/src/pages/SignalDetail.tsx frontend/src/pages/SignalDetail.module.css frontend/src/signals/feed.test.tsx frontend/src/signals/detail.test.tsx frontend/src/i18n/fr.ts frontend/src/i18n/en.ts
git commit -m "feat(frontend): build connected signal workspace"
~~~

### Task 5: Rebuild Overview from authoritative resources

**Files:**
- Modify: frontend/src/pages/Dashboard.tsx
- Modify: frontend/src/pages/Dashboard.module.css
- Modify: frontend/src/pages/dashboard.test.tsx
- Modify: frontend/src/i18n/fr.ts
- Modify: frontend/src/i18n/en.ts

- [ ] **Step 1: Add failing truthful-summary coverage**

~~~tsx
const summaries = await screen.findByRole('list', { name: 'Résumé du compte' })
expect(within(summaries).getByText('1 signal dans cette lecture')).toBeInTheDocument()
expect(within(summaries).getByText('1 profil actif')).toBeInTheDocument()
expect(within(summaries).getByText('Pro')).toBeInTheDocument()
expect(within(summaries).getByText(/Alertes activées/)).toBeInTheDocument()
expect(document.body).not.toHaveTextContent(/32 signaux|82%|12 540/)
~~~

Use one feed item, one ICP, PRO_STATUS and enabled notification preferences. Add separate tests proving a billing error preserves feed/ICP/alert summaries and an alert error preserves feed/ICP/billing.

- [ ] **Step 2: Implement four real summary cards**

~~~tsx
<ul className={styles.metrics} aria-label={t.dashboard.summaryLabel}>
  <Metric
    label={t.dashboard.signalsRead}
    value={feedState.data
      ? interpolate(
          plural(feedState.data.total_returned, t.dashboard.signalReadOne, t.dashboard.signalReadOther),
          { count: feedState.data.total_returned },
        )
      : null}
    loading={feedState.loading && !feedState.data}
    error={feedState.error}
    onRetry={loadFeed}
  />
  <Metric
    label={t.dashboard.activeTargeting}
    value={icpState.data
      ? interpolate(
          plural(activeIcps.length, t.dashboard.activeIcpOne, t.dashboard.activeIcpOther),
          { count: activeIcps.length },
        )
      : null}
    loading={icpState.loading && !icpState.data}
    error={icpState.error}
    onRetry={loadIcps}
  />
  <Metric
    label={t.dashboard.currentAccess}
    value={billingStatus ? t.billing.plans[billingStatus.plan_code] : null}
    loading={billingState.loading && !billingStatus}
    error={billingState.error}
    onRetry={loadBilling}
  />
  <Metric
    label={t.dashboard.alertState}
    value={alertsSummary}
    loading={notificationState.loading && !notificationPreference}
    error={notificationState.error}
    onRetry={loadNotifications}
  />
</ul>
~~~

Metric is local to Dashboard.tsx and shows one value, skeleton or compact local retry. Never calculate unavailable totals or confidence scores.

- [ ] **Step 3: Build the compact working surface**

Use SignalListRow for the three server-ordered items. Keep the current boundary: at most the first unlocked signal can cause one detail/company lookup, and a locked item causes neither.

Render `feedState.data.items` in server order through the same `SignalListRow`
component inside an ordered list labelled by `dashboard-opportunities-title`. The
adjacent context column must render only the existing `companyState`: skeleton while
loading, company link when available, explicit unavailable/error copy otherwise. It
must never construct a company name or profile URL from the feed teaser.

Move targeting, billing and notification CTAs into a compact secondary strip; do not duplicate the metrics in large legacy cards.

- [ ] **Step 4: Implement the overview grid**

~~~css
.metrics {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.metric,
.workingSurface {
  border: 1px solid var(--kivou-connected-line);
  background: var(--kivou-connected-surface);
  border-radius: var(--kivou-connected-panel-radius);
}
.workingSurface {
  display: grid;
  grid-template-columns: minmax(20rem, .9fr) minmax(28rem, 1.4fr);
  overflow: clip;
}
@media (max-width: 980px) {
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .workingSurface { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .metrics { grid-template-columns: 1fr; }
}
~~~

- [ ] **Step 5: Run dashboard tests**

~~~bash
cd frontend
npm test -- --run src/pages/dashboard.test.tsx src/pages/referenceFidelity.test.tsx
~~~

Expected: all independent loader, retry, billing_action, company-boundary and navigation tests PASS.

- [ ] **Step 6: Commit**

~~~bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/Dashboard.module.css frontend/src/pages/dashboard.test.tsx frontend/src/i18n/fr.ts frontend/src/i18n/en.ts
git commit -m "refactor(frontend): rebuild connected overview"
~~~

### Task 6: Align Companies, Targeting and Account surfaces

**Files:**
- Modify: frontend/src/pages/Companies.tsx and Companies.module.css
- Modify: frontend/src/pages/CompanyProfile.tsx and CompanyProfile.module.css
- Modify: frontend/src/pages/Icps.tsx and Icps.module.css
- Modify: frontend/src/pages/Settings.tsx and Settings.module.css
- Modify: frontend/src/pages/Billing.module.css
- Modify: frontend/src/pages/Notifications.module.css
- Modify: frontend/src/pages/dashboard.test.tsx for the Companies index boundary.
- Modify: frontend/src/companies/companyProfile.test.tsx only if profile markup changes.
- Modify: frontend/src/pages/onboarding.test.tsx only if ICP markup changes.
- Modify: frontend/src/billing/billing.test.tsx only if billing markup changes.
- Modify: frontend/src/notifications/notifications.test.tsx only if notification markup changes.

- [ ] **Step 1: Add the unlocked-only Companies regression**

With one unlocked and one locked feed item:

~~~tsx
expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(1)
expect(callsTo('/signals/sig_locked_1', 'GET')).toHaveLength(0)
expect(screen.queryByText('Identité protégée')).not.toBeInTheDocument()
~~~

- [ ] **Step 2: Recompose Companies as a compact directory**

Keep the current all-history feed and Promise.allSettled boundary. Replace the card grid with real company rows:

~~~tsx
<ul className={styles.rows}>
  {entries.map((entry) => (
    <li key={entry.key}>
      <Link className={styles.companyRow}
        to={'/app/companies/' + encodeURIComponent(entry.key)}>
        <BuildingIcon />
        <span>
          <strong>{entry.name}</strong>
          <small>{entry.country ?? t.common.notAvailable}</small>
        </span>
        <span>{t.companiesIndex.count} · {entry.signalCount}</span>
      </Link>
    </li>
  ))}
</ul>
~~~

- [ ] **Step 3: Apply editorial CompanyProfile layout**

Use two columns for official facts and related real signals above 900px and one column below. Render unavailable_fields through existing unavailable copy only. Never substitute website, address, phone or identifiers.

- [ ] **Step 4: Compact ICP cards without changing mutations**

Keep the current payload, validation, create/edit actions and plan-limit callouts. Put profile list and focused editor in:

~~~css
.workspace {
  display: grid;
  grid-template-columns: minmax(17rem, .72fr) minmax(28rem, 1.28fr);
  border: 1px solid var(--kivou-connected-line);
  border-radius: var(--kivou-connected-panel-radius);
  background: var(--kivou-connected-surface);
}
@media (max-width: 900px) {
  .workspace { grid-template-columns: 1fr; }
}
~~~

- [ ] **Step 5: Make Settings the Account landing surface**

~~~tsx
<section className={styles.accountSurface} aria-labelledby="account-identity">
  <header className={styles.identityHeader}>
    <h2 id="account-identity">{me.account_display_name}</h2>
    <p>{me.email}</p>
  </header>
  <nav className={styles.accountActions} aria-label={t.settings.actionsLabel}>
    <ButtonLink to="/app/billing" variant="secondary">
      {t.settings.billingAction}
    </ButtonLink>
    <ButtonLink to="/app/notifications" variant="secondary">
      {t.settings.notificationsAction}
    </ButtonLink>
  </nav>
</section>
~~~

Billing and Notifications retain current React logic and Stripe/preference actions; update only composition CSS and outer surfaces.

- [ ] **Step 6: Run all affected suites**

~~~bash
cd frontend
npm test -- --run \
  src/pages/dashboard.test.tsx \
  src/companies/companyProfile.test.tsx \
  src/pages/onboarding.test.tsx \
  src/billing/billing.test.tsx \
  src/notifications/notifications.test.tsx
~~~

Expected: all API payload, Stripe handoff, permission and paywall assertions PASS. Do not create duplicate suites for differently named existing tests.

- [ ] **Step 7: Commit exact changed files**

~~~bash
git add \
  frontend/src/pages/Companies.tsx frontend/src/pages/Companies.module.css \
  frontend/src/pages/CompanyProfile.tsx frontend/src/pages/CompanyProfile.module.css \
  frontend/src/pages/Icps.tsx frontend/src/pages/Icps.module.css \
  frontend/src/pages/Settings.tsx frontend/src/pages/Settings.module.css \
  frontend/src/pages/Billing.module.css frontend/src/pages/Notifications.module.css \
  frontend/src/pages/dashboard.test.tsx frontend/src/companies/companyProfile.test.tsx \
  frontend/src/pages/onboarding.test.tsx frontend/src/billing/billing.test.tsx \
  frontend/src/notifications/notifications.test.tsx
git commit -m "refactor(frontend): align connected account surfaces"
~~~

Before staging, run `git status --short` and omit any listed test file that was not
actually changed. Do not use a broad glob.

### Task 7: Full responsive, language and repository verification

**Files:**
- Modify: frontend/src/pages/referenceFidelity.test.tsx
- Modify: frontend/src/i18n/fr.ts and en.ts only if parity gaps remain.
- Modify connected CSS only for defects found by verification.

- [ ] **Step 1: Add FR/EN landmark parity**

~~~tsx
it.each([
  ['fr', 'Signaux', 'Détail du signal sélectionné'],
  ['en', 'Signals', 'Selected signal details'],
] as const)('conserve la structure connectée en %s', async (locale, title, detailLabel) => {
  mockApi(WORKSPACE_ROUTES)
  renderApp(<AppRoutes />, {
    route: '/app/signals/sig_unlocked_1',
    session: { status: 'authenticated', me: { ...ME, locale } },
    locale,
  })
  expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: detailLabel })).toBeInTheDocument()
  expect(screen.getAllByRole('main')).toHaveLength(1)
})
~~~

- [ ] **Step 2: Run the complete frontend gates**

~~~bash
cd frontend
npm test -- --run
npm run build
npm run typecheck
npm run lint
~~~

Expected: every command exits 0 and no test is newly skipped.

- [ ] **Step 3: Capture desktop and mobile evidence**

Use Playwright CLI with existing development/test data only:

~~~text
1440x900: light rail, filters, master list and selected detail visible together
390x844: drawer closed by default, list first, detail drill-in and explicit back
both: one main, one h1, visible focus, no horizontal viewport overflow
~~~

Do not add demo data to a production route for screenshots.

- [ ] **Step 4: Review forbidden boundaries**

~~~bash
git diff origin/main...HEAD --name-only
git diff --check
git status --short
rg -n "Apollo|Instantly|Hermes|demo|mock" frontend/src/pages frontend/src/signals frontend/src/layouts
~~~

Expected: no backend, migration, ops, Stripe contract or provider file changed. Any demo/mock occurrence is existing development/test-only content.

- [ ] **Step 5: Commit verification changes if any**

~~~bash
git status --short
git add frontend/src/pages/referenceFidelity.test.tsx frontend/src/i18n/fr.ts frontend/src/i18n/en.ts
git commit -m "test(frontend): verify responsive dashboard replacement"
~~~

Add a connected CSS file explicitly only if Step 3 changed it. Skip unchanged paths
and skip the commit entirely if verification changes nothing.

### Task 8: Protected GitHub integration and staging-only deployment

**Files:**
- No product changes unless CI reveals a concrete tested defect.

- [ ] **Step 1: Re-run final verification from a clean tree**

~~~bash
git status --short
git diff --check origin/main...HEAD
cd frontend
npm test -- --run
npm run build
npm run typecheck
npm run lint
~~~

Expected: clean worktree and all gates PASS.

- [ ] **Step 2: Push and create the PR**

~~~bash
git push -u origin feat/dashboard-structural-replacement
gh pr create --repo bruppacherrodrigue-art/Kivou \
  --base main \
  --head feat/dashboard-structural-replacement \
  --title "Remplace structurellement le dashboard connecté" \
  --body "$(printf '%s\n' \
    '## Résumé' \
    '- remplace le shell connecté par la structure claire validée' \
    '- unifie la liste et le détail des signaux en master-detail responsive' \
    '- conserve les APIs, Stripe, permissions, paywall et providers sans modification' \
    '' \
    '## Vérifications' \
    '- npm test -- --run' \
    '- npm run build' \
    '- npm run typecheck' \
    '- npm run lint')"
~~~

The body must state that backend, Stripe, permissions, paywall and providers are unchanged and include exact local results.

- [ ] **Step 3: Wait for PR CI once**

~~~bash
PR_NUMBER=$(gh pr view --repo bruppacherrodrigue-art/Kivou --json number --jq .number)
test -n "$PR_NUMBER"
gh pr checks "$PR_NUMBER" --repo bruppacherrodrigue-art/Kivou --watch --interval 20
~~~

Expected: Backend and Frontend jobs SUCCESS. Do not rerun unless a real commit changes the result.

- [ ] **Step 4: Re-read exact merge state**

~~~bash
gh pr view "$PR_NUMBER" --repo bruppacherrodrigue-art/Kivou \
  --json state,isDraft,mergeable,headRefOid,baseRefName,statusCheckRollup
~~~

Expected: OPEN, not draft, MERGEABLE, base main, reviewed head and all checks SUCCESS.

- [ ] **Step 5: Squash merge without bypass**

~~~bash
gh pr merge "$PR_NUMBER" --repo bruppacherrodrigue-art/Kivou --squash --delete-branch
~~~

On timeout, re-read PR and main before any second mutation.

- [ ] **Step 6: Verify exact main CI**

~~~bash
git fetch origin main
MAIN_SHA=$(git rev-parse origin/main)
gh run list --repo bruppacherrodrigue-art/Kivou --branch main --commit "$MAIN_SHA" --limit 5
RUN_ID=$(gh run list --repo bruppacherrodrigue-art/Kivou --branch main --commit "$MAIN_SHA" \
  --limit 5 --json databaseId --jq '.[0].databaseId')
test -n "$RUN_ID"
gh run watch "$RUN_ID" --repo bruppacherrodrigue-art/Kivou --interval 20
~~~

Expected: both jobs SUCCESS for that SHA.

- [ ] **Step 7: Build only the reviewed main frontend**

Build from a detached worktree at the exact reviewed SHA:

~~~bash
BUILD_ROOT=$(mktemp -d /tmp/kivou-dashboard-build.XXXXXX)
BUILD_WORKTREE="$BUILD_ROOT/checkout"
git worktree add --detach "$BUILD_WORKTREE" "$MAIN_SHA"
cd "$BUILD_WORKTREE/frontend"
npm ci
npm run build
test -f dist/index.html
~~~

Record current staging links first:

~~~bash
ssh kivou-staging 'readlink -f /srv/kivou/frontend; readlink -f /srv/kivou/app'
~~~

- [ ] **Step 8: Publish an immutable frontend release atomically**

~~~bash
RELEASE_UTC=$(date -u +%Y%m%dT%H%M%SZ)
RELEASE_SHORT=$(printf '%s' "$MAIN_SHA" | cut -c1-12)
FRONTEND_RELEASE="/srv/kivou/releases/frontend-${RELEASE_UTC}-${RELEASE_SHORT}"
ssh kivou-staging "test ! -e '$FRONTEND_RELEASE' && sudo install -o kivou -g kivou -m 755 -d '$FRONTEND_RELEASE'"
tar -C "$BUILD_WORKTREE/frontend/dist" -cf - . | \
  ssh kivou-staging "sudo -u kivou tar -C '$FRONTEND_RELEASE' -xf -"
ssh kivou-staging "test -f '$FRONTEND_RELEASE/index.html' && find '$FRONTEND_RELEASE/assets' -type f -name '*.*' -print -quit | grep -q ."
ssh kivou-staging "sudo ln -s '$FRONTEND_RELEASE' /srv/kivou/frontend.new && sudo chown -h kivou:kivou /srv/kivou/frontend.new && test \"\$(readlink -f /srv/kivou/frontend.new)\" = '$FRONTEND_RELEASE' && sudo mv -Tf /srv/kivou/frontend.new /srv/kivou/frontend"
ssh kivou-staging "test \"\$(readlink -f /srv/kivou/frontend)\" = '$FRONTEND_RELEASE'"
cd /home/jaybe/.config/superpowers/worktrees/Kivou/dashboard-structural-replacement
git worktree remove "$BUILD_WORKTREE"
rmdir "$BUILD_ROOT"
~~~

Do not restart or modify kivou-api. Keep the old frontend release for rollback. Do not touch production.

- [ ] **Step 9: Validate real staging desktop and mobile**

Using the authenticated test account, inspect network and console on:

~~~text
/app/dashboard
/app/signals
/app/companies
/app/icps
/app/settings
/app/billing
/app/notifications
~~~

On `/app/signals`, select the first real unlocked row and verify that the resulting
`/app/signals/{signal_id}` deep link renders the same real detail. Do not paste a
fixture identifier into staging.

Required evidence:

~~~text
- light five-item shell
- real overview values only
- desktop master-detail and mobile drill-in
- accessible signals and companies from 200 API responses
- locked rows reveal no identity and cause no forbidden detail request
- billing and Customer Portal remain server-authoritative
- honest loading, empty and error states
- no new critical console error
- frontend symlink suffix matches MAIN_SHA
- backend symlink and production remain untouched
~~~

The verdict can be STAGING DÉPLOYÉ ET VALIDÉ only after this direct inspection.
