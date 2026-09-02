# Phase A BTP Commercial Signals — Local Demonstration Design

Status: approved by the product owner on 2 September 2026, including the
freshness, SIRET-resolution, operational-specificity and commercial-needs
corrections supplied after the initial design.

## Objective and boundaries

Demonstrate locally that recent French BTP awards can become truthful,
commercially useful signals before a DCE is available. The demonstration uses
the current staging corpus only through read-only extraction, makes no staging
mutation or provider request, performs no deployment, and opens no pull
request.

The existing 39,336 materialized rows are the starting corpus. Reporting
deduplicates them by opportunity before counting BTP awards or selecting the
showcase. Phase A BTP is grounded in the official French award CPV division
`45`, never in a possibly stale customer match label.

## Three states and stable replacement

Every evaluated award has one commercial publication state:

- `INSUFFICIENT`: stored internally but not commercially displayed;
- `VISIBLE_DASHBOARD`: satisfies the official-fact and specificity gates;
- `OUTBOUND_READY`: is visible and also satisfies the outbound freshness gate.

Enrichment is independent of eligibility:

- `OFFICIAL_SOURCE` is the initial level;
- `DCE_ANALYZED` is the higher level when a linked DCE has actually been
  analyzed.

The opportunity key is the stable identity. A later DCE produces a new
revision for the same signal, supersedes the previous public reading, and
retains the old revision only in internal history. It never creates a second
commercial signal.

## Minimum specificity

`VISIBLE_DASHBOARD` requires all of the following official facts:

1. a published awardee with a usable legal name, not merely a SIRET;
2. a meaningful market or lot object;
3. an event date no more than two years old for dashboard history;
4. a precise execution place: locality, postal code or subdivision;
5. an HTTP(S) official-source link;
6. at least two concrete information categories; and
7. at least one genuine operational element.

Concrete information categories are detailed CPV, amount, lot/specialty,
substantive description, additional CPV, duration and published calendar.
Operational elements are a precise lot, detailed service, named material,
named equipment, identified work or structure, technical specialty, duration
or calendar, identifiable constraint, or precise execution place.

Amount plus a CPV alone is insufficient. Generic objects such as “travaux de
construction” or “rénovation de bâtiment” do not satisfy the meaningful-object
gate. The rule is deterministic and based on positive evidence categories;
there is no case-specific exclusion list.

## Freshness and outbound

Age is computed from the best typed official date in this order: award date,
contract-notification date, publication date.

- 0–90 days: `OUTBOUND_READY`, highest priority;
- 91–180 days: `OUTBOUND_READY`;
- 181–365 days: `OUTBOUND_READY` only if a published duration or end date
  indicates execution is still in progress on the evaluation date;
- more than one year: `OUTBOUND_READY` only if a published duration or end date
  still indicates active execution; otherwise dashboard-visible only.

An old award is never promoted merely to reach a target volume. The report
publishes counts for 0–90, 91–180, 181–365 and more than one year, plus the
actual outbound-ready total.

## Commercial reading

The local report and dashboard keep two visually and structurally separate
blocks:

- `Ce que les données officielles indiquent`: awardee, object and lot, buyer,
  amount, typed date, location, operational elements, CPV and official link;
- `Besoins potentiels à qualifier`: one to three bounded hypotheses directly
  tied to named source facts.

A potential need must name the relevant material, equipment, specialty or
service that appears in official text or follows from a specific CPV label. A
bare category such as “matériaux et composants”, “équipements nécessaires au
chantier” or “contacter le service achats” is invalid. Each need uses
conditional language and carries the fact that supports it. Missing products,
quantities, people, dates and requirements are never invented.

The recommended action is a qualification step, not an assertion of purchase.
Contact targets are functional roles only and are selected from the
operational evidence. At most three genuinely important unknowns are shown.

## SIRET recovery

Rows whose awardee is only a published SIRET are recoverable candidates, not
permanently insufficient. A separate asynchronous command will:

1. inspect existing Kivou company identities first;
2. enqueue unresolved SIRETs for a future official-company source adapter;
3. persist only a source-bound legal identity outside all GET paths; and
4. deterministically re-evaluate affected awards after resolution.

The local implementation defines the queue and resolver contracts and proves
the existing-data path. It performs no network call. GET handlers and React
rendering cannot instantiate or invoke a resolver.

## Local data flow and showcase

A bounded read-only extraction command evaluates staging rows and writes a
versioned local JSON snapshot under `output/phase-a-btp/`. The snapshot records
the evaluation date, rule version, source identifiers, official URLs, counts,
freshness buckets, eligibility reasons, enrichment level and ten selected
signals.

Selection orders by outbound readiness, freshness and specificity, then
enforces diversity: no repeated opportunity, no excessive awardee repetition,
and coverage across BTP specialties where the eligible pool permits it.

The frontend consumes this snapshot only when the explicit local demonstration
route is opened. It renders the totals and ten expandable cards with both
commercial states. Production API behavior and the ordinary authenticated
dashboard remain unchanged.

## Verification

Backend tests cover every eligibility gate, freshness boundary, in-progress
exception, specific-needs guard, deterministic diversity, DCE replacement
identity and offline SIRET recovery. Frontend tests cover headings, ten real
snapshot cards, required fields, status/motive rendering and the three-item
unknown limit. Typecheck, lint and build must pass. Browser verification at
desktop and mobile sizes must confirm layout, links and the absence of console
errors before screenshots are accepted.
