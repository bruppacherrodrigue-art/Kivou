# PR7 supplier families — design

## Goal

Prevent acquisition from targeting an unresolved holder or from sending a generic supplier query. Each eligible signal resolves to a named holder, then produces three to five independent, auditable Apollo searches for precise supplier families.

## Data boundaries

`ops/config/supplier-families.yaml` is the single versioned source for family labels, Apollo English tags, priorities, and the CPV/object-term mapping for six verticals: `general_building`, `interior_finishing`, `technical_installation`, `roadworks_civil`, `earthworks_demolition`, and `special_civil`. The YAML is validated at startup; every vertical has three to five families, and every family has a French label, at least one English tag, and a positive priority.

SIRET resolution is a separate read-only SIRENE/Annuaire des entreprises boundary. Its normalized result is cached with provider, lookup key, legal name, observation time, and fingerprint. Selection requires a non-empty resolved legal name; an identifier alone is never a named holder.

## Runtime flow

Selection joins the resolved holder and keeps the existing amount, date, object, department, and model-fit criteria. Supplier discovery expands one signal into one bounded search per selected family, each capped at 25 organizations. Queries narrow in this order: employee range `5–250`, more precise family tag, then signal department plus neighboring departments. A query never combines a region and a radius. Each attempt stores the exact parameter set, family, narrowing step, and Apollo `total_entries`; provider results and rejection reasons remain bounded.

The generated shadow mail carries the selected French family label and a family-specific “Pour vous” sentence, for example: `Vous fournissez du béton / des armatures ? SAS X vient de gagner…`. The signal facts remain the source for the opportunity; the family is the source for the supplier proposition. The existing SHADOW send lock remains unchanged.

## Verification

Offline tests cover YAML completeness, unresolved-holder exclusion, SIRENE normalization/cache behavior, family expansion and narrowing order, exact attempt journaling, and family-specific mail rendering. Staging and production are not relaunched until CI is green and the manual Apollo calibration has been recorded separately.
