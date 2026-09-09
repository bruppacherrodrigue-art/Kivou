# PR7 supplier families Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exclude unresolved holders, map six verticals to readable supplier families, run one bounded Apollo search per family, and personalize shadow mail by family.

**Architecture:** Add a validated YAML catalog and a small SIRENE resolver/cache boundary. Make selection consume the resolved legal name, make supplier discovery produce independent family attempts with durable exact-query evidence, and pass the chosen family into the existing shadow-mail renderer.

**Tech Stack:** Python, Pydantic, SQLAlchemy/Alembic, PyYAML, pytest.

---

### Task 1: Catalog contract

**Files:** `ops/config/supplier-families.yaml`, `src/signals/supplier_discovery/families.py`, `tests/test_supplier_families.py`

- [ ] Write failing tests for all six verticals, three-to-five families each, required French label/English tags/priority, and CPV/object-term lookup.
- [ ] Run the focused tests and verify they fail because the catalog/loader is absent.
- [ ] Add the readable YAML catalog with precise families and no generic catch-all family.
- [ ] Add strict loader and typed lookup; reject malformed or incomplete catalogs at startup.
- [ ] Run focused catalog tests and Ruff.

### Task 2: Named-holder resolution

**Files:** `src/signals/ingestion/sirene.py`, `src/signals/acquisition_runtime/selection.py`, `src/signals/persistence/schema.py`, migration, tests.

- [ ] Write failing tests showing SIRET-only awards are ineligible and resolved legal names are eligible.
- [ ] Run them red.
- [ ] Implement bounded HTTPS SIRENE/Annuaire lookup, normalized legal-name cache, and fail-closed selection integration.
- [ ] Persist provider fingerprint and observation metadata without exposing provider payloads.
- [ ] Run selection and persistence tests.

### Task 3: Family searches and exact attempts

**Files:** `src/signals/supplier_discovery/profile.py`, `src/signals/supplier_discovery/service.py`, `src/signals/supplier_discovery/store.py`, migration, tests.

- [ ] Write failing tests for three-to-five family searches, 25-result caps, narrowing order, no region-plus-radius, and exact result counts per attempt.
- [ ] Run them red.
- [ ] Expand profiles from the catalog, use only CPV/object-derived tags, and persist one attempt record per family/narrowing level.
- [ ] Make the sequence employee range → precise keyword → department plus neighboring departments; retain exact Apollo parameters and counts.
- [ ] Run supplier discovery tests and existing contract tests.

### Task 4: Family-specific shadow mail

**Files:** `src/signals/acquisition_runtime/shadow_mail.py`, `src/signals/acquisition_runtime/domain.py`, tests.

- [ ] Write failing tests requiring the family label and family-specific “Pour vous” sentence in the generated mail.
- [ ] Run them red.
- [ ] Pass family context through personalization and render the single approved bait template, retaining SHADOW status and the existing send lock.
- [ ] Run mail and review tests.

### Task 5: Verification and handoff

- [ ] Run focused tests, full CI, and static checks with foreground timeouts.
- [ ] Open the PR from `main`; do not deploy until CI is green.
- [ ] Record the manual Apollo calibration only if an authenticated browser session is available; otherwise report the blocker without substituting an API search.
- [ ] After explicit deployment approval, deploy staging then production and report only measured first-cycle evidence.
