# RTL-07 Connected Action Dashboard — Design

## Goal

Create the authenticated SaaS home at `/app/dashboard` so a ready Kivou account can see
the next server-ranked opportunities, every active ICP, its current Discovery or subscription
state, the configured alert preference and plan cadence, and one authorized company-profile
action. Every displayed value comes from the existing authenticated SaaS APIs. The dashboard
adds no acquisition metric, scoring rule, billing rule, alert rule, price, entitlement, or
company-identity rule.

## Starting point and boundaries

- Base SHA: `2481c6e88cd20ca5a78c7d3a8894bcdfdd0b48e4` (`origin/main`).
- Required company-profile commit: the same SHA, verified as an ancestor of the base.
- Branch: `feat/saas-connected-action-dashboard` in an isolated worktree because the primary
  checkout contains unrelated user changes.
- Frontend composition is the chosen architecture. No aggregate dashboard endpoint, migration,
  persistence, or new backend rule is added.
- Existing `/app/signals`, signal detail, company profile, ICP, billing, notification, checkout,
  and internal cockpit routes remain available.
- Hermes, Acquisition Engine, Campaign Factory, Apollo, Instantly, Contact Discovery, Supplier
  Discovery, Company Research, personalization, matching, scoring, policy, campaigns, leads,
  mailboxes, pricing, Stripe behavior, public pages, and operations are outside scope.

## Audited contracts reused

The implementation uses these existing account-scoped contracts through the shared frontend
HTTP boundary:

- `GET /signals`: server-ordered `FeedPage`; unlocked items contain the client-safe feed card,
  while locked items contain only the bounded paywall teaser. The call may grant permanent
  Discovery slots.
- `GET /signals/{signal_key}`: server-authoritative locked or unlocked detail. Only an unlocked
  detail may contain the opaque `company_key`.
- `GET /target-icps`: server-ordered profiles with `status`, customer input, `missing_fields`,
  and `plan_limit`.
- `GET /billing/status`: current `plan_code`, raw subscription status, scheduled cancellation,
  `billing_action`, entitlements, exact Discovery grants and remaining slots, and
  `target_icps_over_limit`.
- `GET /notification-preferences`: the user's persisted `email_enabled` choice and notification
  address.
- `GET /companies/{company_key}` remains owned by the existing company-profile page; the
  dashboard links to it but does not prefetch it.

No current API is insufficient for the approved dashboard. In particular, alert activation and
plan cadence remain two separate server facts, and `company_key` is obtained from at most one
existing signal-detail request.

## Chosen architecture

Add a focused `Dashboard` page and CSS module. The page owns independent resource states for the
feed, ICP list, billing status, notification preference, and candidate company detail. It renders
the existing `SignalCard` rather than creating a second signal-card or access system.

The alternatives are rejected:

1. An aggregate endpoint would duplicate account scoping and authorization decisions already
   enforced by the SaaS routes.
2. Extending the feed with company data would expand every feed response and risk exposing or
   generating keys for locked signals.
3. Computing an effective alert cadence would duplicate server policy. The dashboard instead
   renders the persisted activation choice and the plan entitlement separately.

## Routing and authenticated navigation

- Add `/app/dashboard` under the existing authenticated `AppShell`.
- Change the `/app` index and `homeFor()` for `ready_for_signals` accounts to the dashboard.
- Preserve a requested authenticated deep link after login. A ready account without a deep link
  uses the dashboard; an incomplete account always uses onboarding.
- A direct dashboard visit by a session whose `onboarding_status` is not `ready_for_signals`
  redirects to `/onboarding` with `replace` before dashboard API calls.
- Keep onboarding completion on `/app/signals` with `activationCompleted`; that feed-specific
  moment and its Discovery explanation are not moved or recreated.
- Keep checkout success/cancel destinations and locked-signal continuity unchanged.
- Add Dashboard as the first authenticated navigation item. The shell logo links to the
  dashboard, while all existing destinations remain present.
- Ordinary dashboard actions use links, preserving browser back and forward. Only canonical
  home and readiness redirects use `replace`.

## Data loading and concurrency

At page mount, one generation owns all initial work. Unmounting or a newer generation prevents
every older continuation from writing state.

1. Start the limited default feed, initial billing status, ICP list, and notification preference
   independently.
2. Request `GET /signals` with only a small `limit` and `offset=0`. Do not send a freshness,
   target, priority, score, or ordering override. Render `items` in the exact response order.
3. After a successful feed, issue exactly one additional `GET /billing/status`. This is required
   because the feed may have committed new Discovery grants.
4. Give the post-feed billing request a newer request version than the initial request. A billing
   result may update the page only if its version is still current, so a late initial response
   cannot overwrite the post-feed response.
5. From the successful feed, choose the first item whose server payload says `locked: false`.
   Request only that signal's detail. The detail response, never the feed assumption, decides
   whether company access exists.
6. If the detail is unlocked and contains `company_key`, expose the existing company route. If it
   fails, is locked, or lacks the key, do not infer or reconstruct one.

A feed retry starts a new feed generation and immediately invalidates the previous company-detail
candidate and result. A successful retry selects the first newly returned server-unlocked item,
issues at most one new detail request, and triggers exactly one new post-feed billing-status read.
It does not clear or restart already loaded ICP or notification-preference blocks. The existing
billing block may remain visible while its protected post-feed refresh is pending.

The detail failure affects only the company action. No dashboard data is written to
`localStorage` or `sessionStorage`.

## Dashboard hierarchy and actions

`AppShell` provides the single `<main>`. The dashboard supplies one `<h1>` and the following
decision hierarchy:

### Next opportunities

- Primary section, using a small number of the existing `SignalCard` components.
- Preserve server order and server wording for company, contract, amount, public fact, fit,
  plausible need, and timing.
- Make the unlocked card's accessible CTA explicitly mean "Review signal" / "Examiner le
  signal" and link to `/app/signals/{signal_id}`.
- Keep the existing locked teaser and billing continuity. Only the signal key may travel in
  navigation state; no protected company, amount, need, evidence, source, or company key may
  appear.
- Include one action to the complete feed.

If there are no feed items, render the honest opportunity empty state. When no unlocked item
exists, this empty or locked-opportunity state also accounts for the absence of a company action;
no standalone company block is rendered.

### Active ICPs

- Render every profile whose server response has `status === "active"`, in the exact response
  order.
- Never select, label, style, or imply a primary ICP.
- For each active profile, render its label, existing offer summary when present, and all
  territories. Territory labels reuse the existing localization helper; React does not reproduce
  territory entitlement rules.
- Render the server-provided `plan_limit` on the affected profile and
  `target_icps_over_limit` membership from billing when available.
- A long list may use compact visual rows, but no active profile is hidden, prioritized, or
  truncated.
- One global action links to `/app/icps`: "Gérer mes ciblages" / "Manage my targeting".
- If no active profile exists, render an honest corrective state with the same `/app/icps`
  action.

### Discovery or subscription

- Render `plan_code`, the localized raw subscription status when supported, exact
  `granted_signal_count`, and exact `remaining_slots`.
- Render `scheduled_cancellation_at` only when the server provides it. The base contract has no
  `scheduled_plan_change`; do not anticipate or depend on the future plan-change contract from
  pull request #58.
- Never derive a price, `price_id`, entitlement, renewal, cancellation date, or safe billing
  action.
- Map the server's `billing_action` only to honest localized copy and link to the existing billing
  surface. The billing page remains responsible for checkout, portal, recovery, or support.
- Zero remaining Discovery slots is a real state, not an error and not a missing value.

### Alerts

- `email_enabled` is displayed as the user's persisted activation choice.
- `entitlements.alert_cadence` is displayed as the capacity of the current plan.
- Enabled example: "Alertes activées · Cadence quotidienne".
- Disabled example: "Alertes désactivées · Votre formule permet une cadence quotidienne".
- If preferences fail but billing succeeds, display the available plan cadence and make no claim
  about activation.
- If billing fails but preferences succeed, display the activation choice and make no cadence
  claim.
- `priority` is translated as "prioritaire" / "priority", never real-time or instant.
- One action links to `/app/notifications`.

### Company profile

- Render the company block only when the feed has at least one server-unlocked item.
- Use the name already authorized in that unlocked feed item.
- If its server detail supplies `company_key`, link directly to
  `/app/companies/{encodeURIComponent(company_key)}`.
- Display "Fiche indisponible" only when that accessible signal exists but its detail succeeds
  without a company key. A detail error instead uses a local retry state without exposing facts
  from a response that was not received.
- Never request details for locked items, iterate over all signals, search by name, construct a
  company key, or call the company-profile endpoint from the dashboard.

## Loading, partial failure, and session behavior

Each resource has `loading`, `success`, and `error` state. ICP, billing, and notification errors
each have a local retry that starts a new protected generation for only that resource. A feed
retry follows the explicit feed/company/post-feed-billing sequence above while preserving the
already loaded ICP and notification blocks. Already loaded blocks remain mounted and usable.

- Feed failure does not hide ICP, billing, or alert data.
- Billing failure does not hide signals or ICP data.
- Notification failure does not hide plan cadence when billing is available.
- Company-detail failure removes only the company link and offers a local retry.
- No failure substitutes zero, a plan, a cadence, a count, a company, or any other invented
  fallback.
- Any API 401 continues through the shared HTTP unauthenticated listener. `RequireAuth` then
  redirects to login with the existing expired-session state. Generation guards prevent late
  dashboard responses from writing after unmount.

## Semantics, localization, and responsive behavior

- Use existing cards, surfaces, buttons, typography, spacing, focus styles, and monetary/date
  formatters.
- Add matching `dashboard` and navigation keys to FR and EN dictionaries; dictionary parity
  remains enforced.
- Server-authored signal claims are rendered verbatim. Machine codes are translated only through
  existing approved dictionaries.
- Use responsive grids that collapse to one column without horizontal overflow at 1440, 1024,
  768, 390, and 320 px.
- Keep complete keyboard navigation, visible focus, semantic sections and lists, one `<main>`,
  one `<h1>`, and a useful loading heading.

## Verification

Frontend tests prove:

1. server signal order and correct detail CTA;
2. locked teaser isolation and no protected-data navigation/storage leak;
3. exact Discovery used/remaining values and zero-remaining state;
4. plan and action from `billing/status`, with no browser price or entitlement decision;
5. every active ICP in server order, with summaries, territories, and both limit forms;
6. an honest no-active-ICP state;
7. exact alert activation/cadence combinations and preference-error behavior;
8. company access only after an unlocked server detail containing `company_key`;
9. no detail call for a locked item and no company block when no unlocked item exists;
10. independent partial failures and local retry;
11. exactly one post-feed billing refresh and protection against stale billing responses;
12. expired session and incomplete onboarding;
13. FR/EN parity, browser back/forward, semantic headings, and storage prohibition.

Existing auth, onboarding, feed, paywall-continuity, company-profile, billing, and API-boundary
tests are adapted only where the canonical authenticated home legitimately changes.

Run the complete backend and frontend validation requested by RTL-07. Then perform a real-browser
responsive and keyboard check at all five widths, verify no console errors or horizontal overflow,
and record the evidence in the technical report. Update only the RTL-07 section of
`docs/ROAD_TO_LIVE.md`; mark it "livré en PR" until merge. Do not merge or deploy.
