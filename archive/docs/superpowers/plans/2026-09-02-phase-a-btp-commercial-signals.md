# Phase A BTP Commercial Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reusable, deterministic local demonstration of immediately exploitable French BTP award signals without requiring a DCE.

**Architecture:** Pure Python modules evaluate source-grounded award snapshots, build bounded commercial readings, select a diverse ten-signal showcase and model offline SIRET resolution. A CLI consumes NDJSON exported through a read-only staging transaction and writes a versioned local JSON report. An explicitly gated React route renders that report without changing the production feed or invoking any provider.

**Tech Stack:** Python 3.12, Pydantic, SQLAlchemy data shapes, pytest, React 19, TypeScript, Vitest, Vite, Playwright CLI.

---

## File map

- Create `src/signals/phase_a_btp/contracts.py`: closed input/report contracts and enums.
- Create `src/signals/phase_a_btp/eligibility.py`: BTP, specificity and freshness decisions.
- Create `src/signals/phase_a_btp/reading.py`: exact operational facts, bounded potential needs, roles and action.
- Create `src/signals/phase_a_btp/selection.py`: deterministic diverse showcase selection.
- Create `src/signals/phase_a_btp/siret_resolution.py`: provider-free asynchronous resolution contracts.
- Create `src/signals/phase_a_btp/report.py`: NDJSON report builder and CLI.
- Create `src/signals/phase_a_btp/__init__.py` and `__main__.py`: package and command entry point.
- Create `tests/test_phase_a_btp.py`: domain, recovery and report tests.
- Create `frontend/src/pages/PhaseABtpDemo.tsx`: explicit local report route.
- Create `frontend/src/pages/phaseABtpDemo.test.tsx`: UI contract tests.
- Modify `frontend/src/App.tsx`: route gated by `VITE_PHASE_A_BTP_DEMO=true`.
- Modify `frontend/src/reference/dashboard/dashboard-reference.css`: scoped responsive presentation.
- Generate ignored local artifacts under `output/phase-a-btp/` and `frontend/public/local/`.

### Task 1: Define eligibility and freshness with TDD

**Files:** `tests/test_phase_a_btp.py`, `src/signals/phase_a_btp/contracts.py`, `src/signals/phase_a_btp/eligibility.py`

- [ ] Write failing tests proving: all seven dashboard gates; amount plus CPV is insufficient; one operational element is mandatory; generic objects fail; 90/180-day boundaries; post-180 eligibility only while a published duration/end date covers the evaluation date; DCE level never gates visibility.
- [ ] Run `uv run pytest tests/test_phase_a_btp.py -q` and confirm failures are caused by the missing package.
- [ ] Add strict `AwardSnapshot`, `EligibilityResult`, `CommercialState`, `EnrichmentLevel` and freshness-bucket contracts. Implement positive evidence extraction and deterministic decisions.
- [ ] Re-run the focused test until green, then run `uv run ruff check src/signals/phase_a_btp tests/test_phase_a_btp.py`.

The boundary assertions include:

```python
assert evaluate(award(age_days=90)).outbound_ready is True
assert evaluate(award(age_days=180)).outbound_ready is True
assert evaluate(award(age_days=181, duration_months=None)).outbound_ready is False
assert evaluate(award(age_days=181, duration_months=12)).outbound_ready is True
assert evaluate(award(title="Travaux de construction", amount="500000", cpv="45210000")).visible is False
```

### Task 2: Produce specific, honest commercial readings and diverse selection

**Files:** `tests/test_phase_a_btp.py`, `src/signals/phase_a_btp/reading.py`, `src/signals/phase_a_btp/selection.py`

- [ ] Add failing tests that require one to three needs, reject generic need labels, require each need to cite a named operational fact, limit unknowns to three, and keep facts separate from hypotheses.
- [ ] Add failing selection tests for newest/specific-first ordering, one opportunity per showcase, maximum two rows per awardee, and specialty diversity.
- [ ] Confirm RED with the focused pytest command.
- [ ] Implement phrase extraction from official title/lot/description and specific CPV labels. Map only extracted specialties to conditional supply/service hypotheses and functional roles. Implement deterministic round-robin diversity across specialties after ranking.
- [ ] Re-run focused pytest and Ruff.

The reading contract must preserve this shape:

```python
{
    "official_facts": {"awardee": "...", "object": "...", "source_url": "..."},
    "potential_needs_title": "Besoins potentiels à qualifier",
    "potential_needs": [{"statement": "... pourrait ...", "based_on": "..."}],
    "recommended_action": "Qualifier ...",
    "contact_roles": ["Conducteur de travaux"],
}
```

### Task 3: Prepare offline SIRET recovery

**Files:** `tests/test_phase_a_btp.py`, `src/signals/phase_a_btp/siret_resolution.py`

- [ ] Write failing tests proving existing Kivou identities are checked first, unresolved SIRETs become queued work, resolution triggers deterministic re-evaluation, and the module has no HTTP/client dependency.
- [ ] Confirm RED.
- [ ] Implement `CompanyIdentityIndex`, `SiretResolutionJob`, `ResolutionOutcome` and a pure batch coordinator taking injected local lookup and re-evaluation callables.
- [ ] Re-run pytest and Ruff. Do not instantiate an official remote adapter in this phase.

### Task 4: Build the real read-only report

**Files:** `tests/test_phase_a_btp.py`, `src/signals/phase_a_btp/report.py`, `src/signals/phase_a_btp/__main__.py`

- [ ] Add failing report tests for corpus totals, unique-opportunity counts, the four freshness buckets, outbound-ready count, recoverable-SIRET count, zero linked DCE, and ten selected entries.
- [ ] Implement an NDJSON stdin CLI that deduplicates by opportunity and writes JSON atomically to an explicit output path.
- [ ] Run the staging export inside `BEGIN TRANSACTION READ ONLY`, pipe it to the local CLI, and generate `output/phase-a-btp/report.json` plus `frontend/public/local/phase-a-btp-demo.json`. The export includes only fields used by the closed input contract.
- [ ] Independently validate report arithmetic, ten distinct opportunities, awardee cap, specialty diversity, official URLs and lack of DCE claims.

### Task 5: Render and capture the local dashboard

**Files:** `frontend/src/App.tsx`, `frontend/src/pages/PhaseABtpDemo.tsx`, `frontend/src/pages/phaseABtpDemo.test.tsx`, `frontend/src/reference/dashboard/dashboard-reference.css`

- [ ] Write failing Vitest tests for all headline metrics, freshness buckets, ten signal articles, exact facts/hypothesis heading, official links, visible/outbound states and non-eligibility motives.
- [ ] Confirm RED with `npm test -- --run src/pages/phaseABtpDemo.test.tsx`.
- [ ] Implement the gated local route and low-density hierarchy: metrics first, freshness distribution second, ten expandable signal cards third. Reuse the established spacing, typography, badge and color tokens; introduce no new design system.
- [ ] Make cards stack at mobile width, keep links/toggles at least 44px high, and show no more than three unknowns.
- [ ] Run the focused test, `npm run typecheck`, `npm run lint`, and `npm run build`.
- [ ] Start Vite locally with the explicit demo flag, use Playwright CLI snapshots at desktop and mobile widths, inspect console/network state, and save captures under `output/playwright/`.
- [ ] Stop after reporting the visual demonstration; do not open a PR or deploy.
