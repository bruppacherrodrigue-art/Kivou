# Milo Mail Acquisition Engine Implementation Plan

> **For agentic workers:** implement each lot test-first, verify it, and commit it separately. Do not deploy, merge, or invoke live providers.

**Goal:** Add a configured Milo Mail acquisition program to Kivou with explainable theoretical decisions and an inviolable SHADOW transport boundary.

**Architecture:** Reuse Kivou's acquisition event store, Apollo adapters, Policy Gateway, suppression identity, Instantly shadow provider, and conversion token pattern. Add program configuration and program-specific eligibility rules. Keep outbound credentials and all Gmail product data outside the program.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy Core, Alembic, dnspython, pytest, Ruff.

---

## L0 — audited base

- [x] Read applicable instructions and repository state; fetch `origin` without moving `main`.
- [x] Record base `b4373d08`, migration head `0067_acceptance_error_cleanup`, and dirty/divergent local `main`.
- [x] Map SPEC-014–020 and actual components in the design document.
- [x] Create isolated worktree `feat/milomail-acquisition-engine` from `origin/main`.
- [x] Verify baseline: 46 relevant tests passed.

## L1 — generic program and persistence

**Files:** `src/signals/acquisition_programs/contracts.py`, `config.py`, `store.py`; `src/signals/persistence/schema.py`; `src/signals/persistence/migrations/versions/0068_acquisition_program.py`; `ops/examples/milomail-acquisition.json.example`; `tests/test_acquisition_program_contracts.py`; `tests/test_acquisition_program_migration.py`.

- [ ] RED: reject an enabled or sending Milo Mail default, invalid program keys, unsafe landing/sender URLs, and missing program isolation.
- [ ] GREEN: add versioned program config with `milomail` example disabled/SHADOW and all volume/cost caps zero; add additive program, eligibility, and token-binding tables linked to existing acquisition opportunity/supplier/contact identities.
- [ ] Verify fresh upgrade, downgrade, schema parity, FK/unique/idempotency, and unchanged historical rows; commit `feat(acquisition): add versioned program boundary`.

## L2 — discovery, provider, capacity, scoring

**Files:** `src/signals/acquisition_programs/discovery.py`, `mail_provider.py`, `qualification.py`; existing Apollo adapter imports; `tests/test_milomail_discovery.py`, `tests/test_milomail_mail_provider.py`, `tests/test_milomail_qualification.py`.

- [ ] RED: fake Apollo service firms and contacts retain source status; invalid domains, timeout, mixed MX, expired cache, and Gmail consumer cannot become Workspace; professional capacity requires evidence; score decomposes to 100 with configurable thresholds.
- [ ] GREEN: use bounded Apollo search/people/research adapters, injectable DNS MX resolver, explicit source/inference/unknown facts, deterministic capacity and score policies. Persist only evidence IDs, times, MX and bounded facts.
- [ ] Verify targeted tests and Ruff; commit `feat(acquisition): qualify Milo Mail prospects with evidence`.

## L3 — compliance and SHADOW orchestration

**Files:** `src/signals/compliance/contracts.py`, `rules.py`, `suppression.py`, `store.py`, `milomail.py`; `src/signals/acquisition_programs/engine.py`; `tests/test_milomail_policy.py`, `tests/test_milomail_shadow_e2e.py`, existing compliance tests.

- [ ] RED: theoretical SEND for complete FR B2B Workspace facts; HOLD only for temporary gaps; NO_SEND for exclusions; Kivou ruleset refuses Milo purpose; suppression and zero budgets block export; SHADOW never calls an Instantly mutation.
- [ ] GREEN: add `MILOMAIL_GMAIL_AUDIT_B2B` purpose and distinct frozen ruleset, scope-aware suppression preserving Kivou legacy identity semantics, program decision audit and no-export SHADOW runner.
- [ ] Verify policy and migration tests; commit `feat(acquisition): enforce Milo Mail B2B shadow policy`.

## L4 — draft sequence and minimal attribution

**Files:** `src/signals/acquisition_programs/templates.py`, `attribution.py`; `src/signals/campaigns/envelope.py` where generic envelope reuse is safe; `tests/test_milomail_templates.py`, `tests/test_milomail_attribution.py`, `tests/test_milomail_instantly_isolation.py`.

- [ ] RED: copy must be evidence-safe and say the audit is free and read-only; missing French landing and sender block export; token is opaque; signed duplicate events persist once; cross-program webhook binding fails.
- [ ] GREEN: render two versioned French draft steps with existing footer primitives, route provider simulation through `ShadowInstantlyProvider`, and append minimal authenticated conversion milestones to Kivou acquisition events.
- [ ] Verify targeted tests and Ruff; commit `feat(acquisition): prepare Milo Mail sequence and conversion events`.

## L5 — validation and reviewable PR

**Files:** `docs/runbooks/14-milomail-acquisition-shadow.md`, implementation report, tests above.

- [ ] Run targeted and relevant full backend suite, `uv run ruff check .`, migration upgrade/downgrade and PostgreSQL DDL test, secret-pattern diff scan, and `git diff --check`.
- [ ] Document decision matrix, MX evidence, professional evidence, config, SHADOW runbook, future activation, kill switch/suppression, KPIs/costs, legal limits, and minimal Milo Mail event contract.
- [ ] Commit docs as `docs(acquisition): document Milo Mail SHADOW operations`; push branch and open a draft PR for review. Verify CI on the exact PR head. Do not merge or deploy.
