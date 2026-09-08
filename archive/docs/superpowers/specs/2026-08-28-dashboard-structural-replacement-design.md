# Dashboard connected structural replacement design

## Objective

Replace the remaining legacy connected-interface structure with the approved
Kivou dashboard reference. This is a structural reconstruction, not a token,
colour or spacing pass.

The approved dashboard reference controls composition, hierarchy, density,
responsive behaviour and visual language. Existing Kivou APIs control every
fact, entitlement and executable action. When a reference block has no
authoritative API value or action, the connected product omits it or substitutes
an explicitly labelled real account value; it never inserts a demonstration
record, inferred total or inert control.

## Proven gap

The staging interface currently retains the previous application skeleton:

- a dark green sidebar rather than the light editorial rail;
- vertically stacked, full-width signal cards rather than a dense master-detail
  workspace;
- a separate detail-page composition rather than persistent contextual detail;
- a summary dashboard made from the previous card grid rather than the
  reference's compact overview and working surface.

The PR 110 styling pass improved palette and spacing but did not replace these
structures. The replacement must therefore change React composition and
responsive layout as well as CSS.

## Authorities and invariants

Presentation authority:

- the approved SaaS overview and client signal-feed captures under
  `docs/designPattern/Kivou_Design_System_v1_0/assets/reference/`;
- the approved `kivou-dashboard-refonte` reference identified by the existing
  fidelity specification as version 17, source
  `05212f2da5197699e6a9bb191556afcb2dcf1bb3`.

Runtime authority:

- `GET /signals` and `GET /signals/{signal_key}` for the feed and selected
  signal;
- company routes only after an unlocked signal supplies a `company_key`;
- `GET /target-icps` for targeting;
- `GET /billing/status` and `GET /billing/plans` for access and pricing;
- notification preferences for the real alert state;
- the existing feedback, note and contacted endpoints for customer actions.

The work does not change backend behaviour, matching, authentication, Stripe,
permissions, paywall decisions, Apollo, Instantly, Hermes, migrations or
production infrastructure.

## Connected shell

`AppShell` becomes the light editorial frame shown by the reference:

- warm off-white navigation rail with dark green typography and a restrained
  active marker;
- compact logo, route-aware title area and neutral canvas;
- consistent maximum working width, dividers and panel borders;
- the five approved primary entries only: Vue d'ensemble, Signaux, Entreprises,
  Profil de ciblage and Compte;
- account identity and logout at the bottom of the rail;
- a mobile top bar and modal drawer that expose the same five entries and close
  after navigation or Escape.

Unsupported reference entries such as Marchés, Veille or Notes are not shown.
Billing and notifications remain reachable from Compte and from contextual
dashboard actions.

## Overview

`/app/dashboard` becomes the compact command surface from the reference rather
than a sequence of large legacy cards.

The top row uses four equally weighted real summaries:

1. signals returned by the current new-signals read, explicitly labelled as
   this reading rather than an invented account-wide total;
2. active targeting profiles from `GET /target-icps`;
3. the current server-provided plan and subscription status;
4. the real notification activation state and plan cadence.

Below the summaries, a dense recent-signal list occupies the primary column.
Selecting an unlocked item reveals a compact factual preview and the real
company action when `company_key` exists. Locked signals retain the bounded
paywall teaser and never trigger a forbidden detail request. Targeting, billing
and alert errors retain independent retry controls so one failed resource does
not erase the other sections.

## Signal workspace

`/app/signals` and `/app/signals/:signalKey` share one responsive signal
workspace:

- a compact filter header driven by the existing freshness and profile inputs;
- a dense master list showing the real company, public event, amount, timing and
  access state returned by the API;
- a detail panel for the current selection, loaded through the existing detail
  endpoint only when access permits;
- existing customer actions only: mark contacted, relevance feedback and note
  handling where those endpoints are already available;
- source and company links only when the corresponding API fields exist.

The deep-link route preselects its signal in the same workspace. On desktop the
list and detail remain side by side. On mobile the list is primary and the
selected detail becomes a full-width drill-in view with an explicit back
control. No selection produces an honest invitation to choose a signal.

The default freshness remains `new`. Empty results retain the existing action
to widen the period. A paid plan changes access, not signal production; the UI
does not claim that subscribing creates matches.

## Companies, targeting and account

`/app/companies` adopts the reference's compact directory rhythm. It continues
to derive companies exclusively from unlocked feed items and never reveals a
company reachable only through a locked signal. Loading, partial-result, empty
and retry states remain explicit.

`/app/companies/:companyKey` uses the same editorial detail surfaces while
rendering only the account-scoped company contract returned by the backend.

`/app/icps` is restructured into compact targeting cards and a focused editor
while preserving create, edit, validation and plan-limit behaviour verbatim.

`/app/settings` becomes the reference Account landing surface. It displays the
real account identity and provides the existing routes to billing and
notifications. `/app/billing` retains the API catalogue and Stripe handoffs;
`/app/notifications` retains the real preference controls. These pages share the
new shell and surface system without changing their contracts.

## Visual system

The connected experience uses one constrained system:

- ivory canvas and light navigation surfaces;
- deep green for primary text and actions;
- warm neutral borders and limited terracotta/gold semantic accents;
- editorial display typography for primary opportunity titles and a legible
  sans-serif for controls and metadata;
- compact rows and information panels instead of oversized marketing cards;
- a shared spacing and radius scale with no page-specific arbitrary palette.

Focus visibility, semantic headings, keyboard navigation, reduced motion and
WCAG-readable contrast remain required.

## Data flow and error behaviour

Pages preserve independent resource state. A feed failure, billing failure,
targeting failure or notification failure has a local error surface and local
retry. Existing data remains visible during a refresh where it is safe to do so.

Selection is route-backed. Changing a filter clears a selection that is no
longer present. Stale asynchronous detail responses cannot overwrite a newer
selection. Selecting a feed item already declared locked does not call the
detail or company endpoints. A direct deep link whose access state is not yet
known calls the existing account-scoped detail endpoint and renders only its
bounded locked response when access is refused. Unknown or absent API values
render an explicit unavailable state rather than a fallback demo value.

## Verification

Tests first lock the new structure and truthful data mapping:

- light shell, five-item navigation, desktop split layout and mobile drill-in;
- route-backed signal selection and stale-request protection;
- no detail request for locked signals;
- overview summaries derived only from their authoritative resources;
- independent loading, error, retry and empty states;
- company visibility restricted to unlocked signals;
- billing, notification, feedback, note, contacted and paywall behaviour
  preserved;
- FR and EN copy for every new label.

The complete frontend suite, typecheck, lint and production build must pass.
The repository-wide CI must pass before merge. Staging deployment is limited to
the merged commit and is validated directly at desktop and mobile sizes across
all connected routes, with network and console inspection. Production is never
deployed.

## Success criteria

The work is complete only when the staging dashboard is recognisably the
approved reference in structure, hierarchy and responsive behaviour; all shown
facts come from the current account APIs; all shown actions execute existing
endpoints; and no legacy layout remains merely recoloured inside the connected
experience.
