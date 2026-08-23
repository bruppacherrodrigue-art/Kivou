# Connected Action-Oriented SaaS Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/app/dashboard` the normal authenticated Kivou home and compose the existing SaaS APIs into a compact, truthful, action-oriented dashboard without adding backend contracts or business rules.

**Architecture:** The React dashboard independently loads the authoritative signal feed, target ICPs, billing status, and notification preferences. Each resource keeps its own loading, success, and error state. A successful feed load causes one generation-protected billing refresh and at most one detail request for the first server-unlocked signal. All ordering, access, billing, plan, Discovery, alert-capability, and company-key decisions remain server-owned. Existing onboarding, checkout return, locked-signal continuation, deep links, session expiry, and account-readiness routing remain intact.

**Tech Stack:** React 19, TypeScript, React Router, CSS Modules, existing Kivou component primitives and API client, Vitest, Testing Library, Playwright CLI; Python 3.12, Ruff, pytest for unchanged-backend regression validation.

---

## Global invariants

- [ ] Do not modify backend, Acquisition Engine, Hermes, Campaign Factory, Apollo, Instantly, contacts, suppliers, research, personalization, scoring, matching, Policy Engine, Stripe, checkout, portal, entitlements, pricing, the server signal engine, alert cadence, public pages, legal, or OPS files.
- [ ] Do not introduce a dashboard endpoint, persistence, migration, price, `price_id`, entitlement calculation, score, ordering, ICP preference, or company-key derivation.
- [ ] Preserve the exact order returned by `GET /signals` and `GET /target-icps`.
- [ ] Render every server-active ICP; never name or imply a primary ICP.
- [ ] Treat `billing.status().billing_action` as the sole billing-action authority and `billing.status().entitlements.alert_cadence` as the plan alert capability.
- [ ] Treat `notifications.read().email_enabled` as the user activation choice; if that request fails, make no activation claim.
- [ ] Never translate `priority` as real-time.
- [ ] Request signal detail only for the first feed item whose server payload says `locked: false`; request at most one detail per successful feed generation.
- [ ] Never call `companies.get()` from the dashboard and never store company data or keys in `localStorage` or `sessionStorage`.
- [ ] Show `scheduled_cancellation_at` only when the server supplies it. Do not model or mention a scheduled plan change or PR #58 behavior.
- [ ] Keep one `<main>` from `AppShell`, one page `<h1>`, visible focus, keyboard navigation, FR/EN parity, localized territories and money without conversion, and no horizontal overflow at 320, 390, 768, 1024, and 1440 px.

### Task 1: Lock the authenticated-home routing contract

**Files:**

- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/auth/RequireAuth.tsx`
- Modify: `frontend/src/pages/Login.tsx`
- Modify: `frontend/src/layouts/AppShell.tsx`
- Modify: `frontend/src/assets/Icons.tsx`
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`
- Create: `frontend/src/pages/Dashboard.tsx`
- Test: `frontend/src/auth/auth.test.tsx`
- Test: `frontend/src/pages/dashboard.test.tsx`

**Steps:**

- [ ] Add failing tests proving that a ready account lands on `/app/dashboard`, `/app` redirects there, the authenticated navigation exposes the localized dashboard link, a requested deep link remains authoritative, and an incomplete account reaches onboarding without dashboard API calls.
- [ ] Run `cd frontend && npm run test -- --run src/auth/auth.test.tsx src/pages/dashboard.test.tsx` and confirm RED for the missing route/home link.
- [ ] Add a minimal `Dashboard` route component. Keep the readiness guard outside the data-loading component so incomplete accounts cannot issue dashboard requests:

```tsx
export function Dashboard() {
  const me = useCurrentUser()

  if (me.onboarding_status !== 'ready_for_signals') {
    return <Navigate to="/onboarding" replace />
  }

  return <ReadyDashboard />
}
```

- [ ] Change only the normal ready-account home returned by `homeFor()` to `/app/dashboard`. Keep onboarding completion navigating to `/app/signals`; keep checkout and locked-signal return paths unchanged.
- [ ] Update login so a ready account honors `location.state.from`, regardless of whether the normal home is the feed:

```tsx
const home = homeFor(me)
const destination =
  me.onboarding_status === 'ready_for_signals' ? state?.from ?? home : home
navigate(destination, { replace: true })
```

- [ ] Add `/app/dashboard` before the existing feed entry in `AppShell`, add a code-native dashboard SVG icon, and point both authenticated Kivou logos to `/app/dashboard`. Preserve every existing SaaS route.
- [ ] Add `nav.dashboard` and the dashboard dictionary skeleton to both locales, keeping `en.ts` checked by the shared `Dictionary` type.
- [ ] Verify GREEN with the focused command above.
- [ ] Commit:

```bash
git add frontend/src/App.tsx frontend/src/auth/RequireAuth.tsx frontend/src/pages/Login.tsx frontend/src/layouts/AppShell.tsx frontend/src/assets/Icons.tsx frontend/src/i18n/fr.ts frontend/src/i18n/en.ts frontend/src/pages/Dashboard.tsx frontend/src/auth/auth.test.tsx frontend/src/pages/dashboard.test.tsx
git commit -m "feat(dashboard): add authenticated home route"
```

### Task 2: Build generation-safe independent resource loading

**Files:**

- Modify: `frontend/src/pages/Dashboard.tsx`
- Test: `frontend/src/pages/dashboard.test.tsx`

**Steps:**

- [ ] Write failing tests with deferred HTTP responses proving:
  - signals, initial billing, ICPs, and notification preferences start independently;
  - every successful `GET /signals` produces exactly one later `GET /billing/status`;
  - the initial billing response cannot overwrite the later post-feed response;
  - a failed resource leaves already loaded blocks visible;
  - retrying one resource does not reset unrelated resource data.
- [ ] Run `cd frontend && npm run test -- --run src/pages/dashboard.test.tsx` and confirm RED.
- [ ] Introduce an explicit reusable state shape that preserves last good data during a retry or refresh:

```tsx
interface ResourceState<T> {
  data: T | null
  loading: boolean
  error: unknown | null
}

const emptyResource = <T,>(): ResourceState<T> => ({
  data: null,
  loading: true,
  error: null,
})
```

- [ ] Implement separate generation refs for feed, billing, ICP, notification, and company-detail requests. A state update is allowed only when its captured generation still equals the current ref and the component remains mounted.
- [ ] Implement `loadBilling()` so every invocation increments `billingGenerationRef`; therefore the post-feed call necessarily supersedes the initial call:

```tsx
const loadBilling = useCallback(async () => {
  const generation = ++billingGenerationRef.current
  setBilling((current) => ({ ...current, loading: true, error: null }))
  try {
    const data = await billing.status()
    if (mountedRef.current && generation === billingGenerationRef.current) {
      setBilling({ data, loading: false, error: null })
    }
  } catch (error) {
    if (mountedRef.current && generation === billingGenerationRef.current) {
      setBilling((current) => ({ ...current, loading: false, error }))
    }
  }
}, [])
```

- [ ] Make one mount effect start `loadFeed`, `loadBilling`, `loadIcps`, and `loadNotifications` without awaiting one another. Do not use `Promise.all` for UI state.
- [ ] Make `loadFeed` call `loadBilling()` exactly once after a successful feed response and never after a failed response. Do not embed billing values in the feed state.
- [ ] Verify focused GREEN.
- [ ] Commit:

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/dashboard.test.tsx
git commit -m "feat(dashboard): load SaaS resources independently"
```

### Task 3: Bound company discovery to one authorized signal detail

**Files:**

- Modify: `frontend/src/pages/Dashboard.tsx`
- Test: `frontend/src/pages/dashboard.test.tsx`

**Steps:**

- [ ] Add failing tests proving:
  - only the first item with `locked: false` is selected, in server order;
  - no detail request is made when all items are locked or the feed is empty;
  - only one detail request occurs per successful feed generation;
  - a locked detail response never creates a company action;
  - an unlocked detail with an opaque `company_key` creates `/app/companies/:companyKey` directly;
  - an unlocked detail without `company_key` says “Fiche indisponible”;
  - a detail error offers only a local retry and does not claim the profile is unavailable;
  - a feed retry immediately invalidates the old company result, selects from the new feed, starts at most one new detail, and leaves ICP/notification call counts unchanged.
- [ ] Confirm RED with the focused dashboard test command.
- [ ] Model detail state so successful absence, access denial, and transport failure cannot be conflated:

```tsx
type CompanyState =
  | { status: 'idle'; signal: null }
  | { status: 'loading'; signal: UnlockedFeedItem }
  | { status: 'available'; signal: UnlockedFeedItem; companyKey: string }
  | { status: 'unavailable'; signal: UnlockedFeedItem }
  | { status: 'error'; signal: UnlockedFeedItem; error: unknown }
```

- [ ] At the beginning of every feed load, increment `companyGenerationRef` and set company state to `idle`. After feed success, find only the first `item.locked === false` and pass it to one detail loader.
- [ ] In the detail loader, trust both server gates:
  - if the response has `locked: true`, set `idle` and reveal nothing;
  - if it has `locked: false` and a non-empty `company_key`, set `available`;
  - if it has `locked: false` and no key, set `unavailable`;
  - on exception, set `error` and retain only the feed-safe candidate needed for retry copy.
- [ ] Encode the opaque key only as a route segment. Do not parse it, derive it, call the company API, or persist it.
- [ ] Verify focused GREEN and commit:

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/dashboard.test.tsx
git commit -m "feat(dashboard): expose authorized company action"
```

### Task 4: Render server-authoritative opportunities and ICPs

**Files:**

- Modify: `frontend/src/pages/Dashboard.tsx`
- Create: `frontend/src/pages/Dashboard.module.css`
- Modify: `frontend/src/signals/SignalCard.tsx`
- Modify: `frontend/src/signals/SignalCard.module.css`
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`
- Test: `frontend/src/pages/dashboard.test.tsx`
- Test: `frontend/src/signals/feed.test.tsx`

**Steps:**

- [ ] Write failing tests proving:
  - the limited dashboard signal list keeps exact server order;
  - each unlocked CTA links to its own `/app/signals/:signalId` detail;
  - a locked card exposes only the existing teaser allowlist and billing path, never company name, buyer, reference, amount, source URL, analysis, or `company_key`;
  - no score, priority, freshness, match, timing, or rank is recomputed;
  - every `status === 'active'` ICP is shown in server order with label, offer summary, all territories, and `plan_limit`;
  - identifiers from `billing.target_icps_over_limit` visibly mark the corresponding active ICP without changing order;
  - no active ICP yields an honest empty state and one `/app/icps` action;
  - there is only one global “Gérer mes ciblages” action.
- [ ] Confirm RED with `cd frontend && npm run test -- --run src/pages/dashboard.test.tsx src/signals/feed.test.tsx`.
- [ ] Reuse `SignalCard` without a dashboard-specific card system. Make its visible action a real link named “Examiner le signal” / “Review signal” while preserving the existing whole-card click area and lock behavior. Keep the company name a semantic heading, not a second competing link.
- [ ] Render `feed.items.slice(0, DASHBOARD_SIGNAL_LIMIT)` directly. Never sort, filter by client score, or derive an access rule. Add a single feed-full link to `/app/signals`.
- [ ] Render ICPs with this exact selection, preserving array order:

```tsx
const activeIcps = icpState.data?.filter((profile) => profile.status === 'active') ?? []
const overLimit = new Set(billingState.data?.target_icps_over_limit ?? [])
```

- [ ] For territories, reuse `MVP_TERRITORIES` and `territoryLabel`; display an unknown server code verbatim rather than inventing geography. Format `minimum_contract_value` with `Intl.NumberFormat` and its server currency, without conversion.
- [ ] Render a non-decorative opportunities section with distinct loading, empty, error/retry, and success states. If there is no unlocked opportunity, explain company-profile absence inside this state and render no company block.
- [ ] Verify focused GREEN and commit:

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/Dashboard.module.css frontend/src/signals/SignalCard.tsx frontend/src/signals/SignalCard.module.css frontend/src/i18n/fr.ts frontend/src/i18n/en.ts frontend/src/pages/dashboard.test.tsx frontend/src/signals/feed.test.tsx
git commit -m "feat(dashboard): render opportunities and active ICPs"
```

### Task 5: Render exact billing and alert states with actionable local failures

**Files:**

- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/pages/Dashboard.module.css`
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`
- Test: `frontend/src/pages/dashboard.test.tsx`

**Steps:**

- [ ] Write failing table-driven tests covering all `billing_action` values and proving that visible plan, subscription status, Discovery `granted_signal_count`, `remaining_slots`, `limit`, alert cadence, and scheduled cancellation date equal server values.
- [ ] Add negative tests proving no catalogue request, price, `price_id`, checkout request, entitlement arithmetic, scheduled plan change, or PR #58 field exists in the dashboard behavior.
- [ ] Add failing alert tests for:
  - enabled + daily: “Alertes activées · Cadence quotidienne”;
  - disabled + daily: “Alertes désactivées · Votre formule permet une cadence quotidienne”;
  - notification failure + daily: cadence shown, no enabled/disabled claim;
  - billing failure + successful preferences: activation choice shown, no cadence claim;
  - `priority`: localized as priority, never real-time;
  - `none`, `weekly`, and `daily` exact server capability rendering.
- [ ] Add partial-error tests proving billing failure does not hide signals and notification failure does not hide ICPs, with each retry calling only its own API except the mandated successful-feed billing refresh.
- [ ] Confirm RED with the focused dashboard test command.
- [ ] Map billing actions only to action copy and the existing `/app/billing` surface:

```tsx
const billingActionLabel = {
  choose_plan: t.dashboard.billing.choosePlan,
  manage_subscription: t.dashboard.billing.manageSubscription,
  recover_payment: t.dashboard.billing.recoverPayment,
  contact_support: t.dashboard.billing.contactSupport,
} satisfies Record<BillingAction, string>
```

- [ ] Display `scheduled_cancellation_at` only when non-null, formatted from that field itself. Never derive it from `current_period_end` or `cancel_at_period_end`.
- [ ] Compose alert prose only from independently available values. A preferences error may leave capability prose visible; it must not synthesize an activation state.
- [ ] Use one local retry button per failed resource and preserve last good data during retries.
- [ ] Verify focused GREEN and commit:

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/Dashboard.module.css frontend/src/i18n/fr.ts frontend/src/i18n/en.ts frontend/src/pages/dashboard.test.tsx
git commit -m "feat(dashboard): show exact billing and alert states"
```

### Task 6: Complete navigation, session, history, storage, accessibility, and responsive proof

**Files:**

- Modify: `frontend/src/pages/dashboard.test.tsx`
- Modify: existing cross-route tests under `frontend/src/auth/`, `frontend/src/api/`, and `frontend/src/pages/` only where the legitimate ready-home destination changed
- Modify: `frontend/src/pages/Dashboard.module.css`

**Steps:**

- [ ] Add or adapt tests proving:
  - a dashboard 401 follows the existing session-expired path and login messaging;
  - onboarding-incomplete accounts never render dashboard data or call its APIs;
  - FR/EN route and navigation copy parity;
  - browser back and forward restore dashboard/feed/detail routes correctly;
  - neither `localStorage` nor `sessionStorage` receives company data or a company key;
  - exactly one `<main>` and one `<h1>` exist;
  - all actions are links or buttons with accessible names.
- [ ] Run the affected test files first and confirm any failures are the expected route-contract delta, not weakened assertions.
- [ ] Add a router-history test that seeds only client-safe API responses and exercises dashboard → signal → back → company → back/forward. Keep it in `frontend/src/pages/dashboard.test.tsx` so it runs in the existing Vitest suite.
- [ ] Use the Playwright skill and a real browser to inspect 1440, 1024, 768, 390, and 320 px. Confirm visible focus, complete keyboard traversal, no clipped text/action, no hidden active ICP, and no duplicate page landmark/title.
- [ ] Keep the opportunities section full width; use a responsive support grid that becomes one column on narrow screens. Condense ICP rows through spacing and wrapping only—never truncation, pagination, prioritization, or a collapsed subset.
- [ ] Run:

```bash
cd frontend
npm run typecheck
npm run lint
npm run test -- --run
npm run build
```

- [ ] Fix only dashboard-caused failures, rerun until GREEN, and commit:

```bash
git add frontend
git commit -m "test(dashboard): verify connected home safeguards"
```

### Task 7: Document RTL-07, verify scope, and prepare the draft PR

**Files:**

- Modify only the RTL-07 subsection: `docs/ROAD_TO_LIVE.md`
- Create: `docs/reports/2026-08-23-rtl07-connected-dashboard.md`

**Steps:**

- [ ] Update only RTL-07 to “livré en PR”; do not change another gate.
- [ ] Write the technical report with APIs reused (`GET /signals`, `GET /signals/{key}`, `GET /target-icps`, `GET /billing/status`, `GET /notification-preferences`), no added endpoint, authorization decisions, available actions, partial-failure behavior, remaining limits, and explicit absence of Acquisition Engine dependency.
- [ ] Run the complete required validation from the repository root:

```bash
uv run ruff check .
uv run pytest
cd frontend
npm run typecheck
npm run lint
npm run test -- --run
npm run build
cd ..
git diff --check
git status --short
```

- [ ] Run boundary checks over the branch diff. Confirm no prohibited engine, Stripe, checkout, portal, pricing, Apollo, Instantly, public, legal, OPS, backend, migration, or persistence file changed.
- [ ] Commit documentation only after tests and scope checks pass:

```bash
git add docs/ROAD_TO_LIVE.md docs/reports/2026-08-23-rtl07-connected-dashboard.md
git commit -m "docs(road-to-live): record RTL-07 dashboard delivery"
```

- [ ] Fetch `origin/main`, record its current SHA, and merge it normally into the feature branch if it advanced. Resolve only in-scope conflicts; do not rebase destructively or force-push.
- [ ] Rerun the complete validation on the synchronized SHA and keep the worktree clean.
- [ ] Push `feat/saas-connected-action-dashboard` and open a draft PR titled `feat(dashboard): add connected action-oriented SaaS home`.
- [ ] Wait for GitHub Actions to complete. Treat concurrency cancellation as non-failure only after locating and verifying its successor run; do not merge or deploy.
- [ ] Record for final reporting: starting SHA, final feature SHA, branch, commits, PR URL, draft/mergeable state, changed files, route, APIs, no endpoint, block behavior, locked-signal protections, backend/frontend results, CI result, FR/EN/responsive/accessibility evidence, prohibited-scope confirmation, and remaining limits.
- [ ] Keep RTL-07 described as “livré en PR”; it is not complete until a later explicit merge puts it on `main` and CI is green on that final `main` SHA.

## Final self-review checklist

- [ ] Every mission test requirement 1–18 has a named automated or browser proof above.
- [ ] Feed retry semantics cover company invalidation, first unlocked reselection, one detail maximum, one billing reread after success, and no ICP/alert reset.
- [ ] Billing race protection is based on invocation generation, not response timing.
- [ ] `scheduled_cancellation_at` is the only scheduled billing state.
- [ ] Company-unavailable copy is limited to a successful unlocked detail without `company_key`.
- [ ] No placeholder, deferred contract, or invented fallback value remains.
