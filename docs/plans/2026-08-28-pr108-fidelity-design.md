# PR 108 staging fidelity design

## Objective

Replace the remaining legacy public and connected UI on staging with the exact
visual language, information hierarchy, navigation and responsive layouts from
the two approved Kivou Sites references:

- `kivou-refonte` version 6, source `efaa4160f4c3bbbdb01448bf9228772491e614f5`
- `kivou-dashboard-refonte` version 17, source `05212f2da5197699e6a9bb191556afcb2dcf1bb3`

The references are authoritative for presentation and structure. The Kivou API
and existing frontend contracts remain authoritative for data, permissions and
actions.

## Public surfaces

The header, footer, typography, palette, glass cards, page spacing and responsive
breakpoints follow the public reference. The canonical routes remain `/`,
`/produit`, `/tarifs`, `/exemple-de-signal`, `/contact` and
`/informations-legales`; authentication actions remain same-origin `/login` and
`/signup` routes.

All reference copy is supplied in French and English through the existing locale
mechanism. The locale control is retained because bilingual behaviour is a
deployment requirement even though the static reference capture is French.

The home-page offer summary and the Tarifs page use `GET /billing/plans`. No
price, currency or purchasable-plan availability is reconstructed in the
browser. Contact retains the existing mail handoff and legal anchors and legacy
redirects remain canonical.

## Connected surfaces

The connected shell adopts the reference sidebar, topbar, navigation hierarchy,
canvas, cards and mobile drawer. Its five primary entries are Vue d'ensemble,
Signaux, Entreprises, Profil de ciblage and Compte.

The reference's demonstration records are never copied into the product. Each
page renders the corresponding live API state:

- dashboard: recent accessible/locked signals, targeting, billing and alerts;
- signals: the live account feed and existing paywall rules;
- companies: only companies resolved from accessible signals;
- targeting: the account's actual ICPs and existing edit/create actions;
- billing: API catalogue, billing status and existing Stripe handoffs;
- notifications and settings: current account capabilities and preferences.

Loading, error, empty and restricted states use the reference composition but
remain explicit. A missing real record results in an honest empty state, never a
reference/demo substitute.

## Boundaries

No backend, migration, matching, authentication, Stripe contract, permission,
paywall, Apollo, Instantly or Hermes behaviour is changed. Production is not in
scope. Existing accessibility semantics, keyboard navigation and reduced-motion
support remain required.

## Verification

Component tests first lock the reference shell, public hierarchy and truthful
API-backed pricing. Existing frontend tests must stay green, followed by build,
typecheck and lint. After protected GitHub integration and staging deployment,
all required public and connected routes are compared directly to the reference
at desktop and mobile sizes, with network and console checks.
