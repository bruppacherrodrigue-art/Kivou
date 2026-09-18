# Assisted Catalog Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Founder POST prepare and the ASSISTED timer build one globally capped, multi-family review queue from every mono-family notice and site-published supplier in the catalog, without provider or send calls.

**Architecture:** Add an explicit production `catalog` selection mode. A read-only notice selector resolves official holders and exact singleton materialized families; a transaction-bound catalog preparation service evaluates site candidates, allocates them in strict family round-robin, renders per-line kat1 artifacts, and atomically persists the batch. The CLI composes this path directly from database, runtime config, and attribution keys, so it never constructs Apollo, model, or Instantly clients.

**Tech Stack:** Python 3.12, Pydantic, SQLAlchemy, PostgreSQL/SQLite, pytest, Ruff, systemd.

---

### Task 1: Add an explicit catalog runtime contract

**Files:**

- Modify: `src/signals/acquisition_runtime/contracts.py:264-350`
- Modify: `ops/host/acquisition-runtime.production.json`
- Test: `tests/test_acquisition_runtime_contracts_production.py`
- Test: `tests/test_acquisition_runtime_config_production.py`

- [ ] Add failing tests proving that production accepts `selection.mode="catalog"` only with a region and `email_source="site"`, while forbidding a pinned vertical, family, opportunity, or allowlist.

```python
def test_production_catalog_selection_is_region_bound_and_site_only() -> None:
    deployment = AcquisitionRuntimeDeployment.model_validate(
        _production_document(
            qa_scope={**PRODUCTION_SCOPE, "vertical": None},
            selection={
                "mode": "catalog",
                "allowed_opportunity_keys": [],
                "region": "Auvergne-Rhône-Alpes",
                "email_source": "site",
            },
        )
    )
    assert deployment.selection is not None
    assert deployment.selection.mode == "catalog"
    assert deployment.selection.family_key is None
    assert deployment.selection.pinned_opportunity_key is None
```

- [ ] Run the focused tests and confirm RED because `catalog` is not yet a valid literal.

```bash
uv run pytest -q tests/test_acquisition_runtime_contracts_production.py -k catalog
```

- [ ] Extend `RuntimeSelection.mode` to `Literal["fixed", "dynamic", "catalog"]`. Validate fixed, dynamic, and catalog in separate branches. For catalog require `region` and `email_source == "site"`; forbid `vertical`, `family_key`, `pinned_opportunity_key`, and allowlist entries. In the production deployment validator, require `qa_scope.vertical` only for dynamic mode.

- [ ] Change the committed production configuration to catalog mode:

```json
"qa_scope": {
  "country": "FR",
  "language": "fr",
  "wedge": "general_building",
  "vertical": null,
  "region": "Auvergne-Rhône-Alpes"
},
"selection": {
  "mode": "catalog",
  "allowed_opportunity_keys": [],
  "region": "Auvergne-Rhône-Alpes",
  "email_source": "site",
  "window_days": 30,
  "minimum_amount": 50000.0,
  "require_named_holder": true,
  "require_nonempty_object": true,
  "require_model_fit": true
}
```

- [ ] Update the committed-config test to assert catalog mode, no pin, no family, and site source. Run both complete suites and Ruff.

```bash
uv run pytest -q tests/test_acquisition_runtime_contracts_production.py tests/test_acquisition_runtime_config_production.py
uv run ruff check src/signals/acquisition_runtime/contracts.py tests/test_acquisition_runtime_contracts_production.py tests/test_acquisition_runtime_config_production.py
```

- [ ] Commit.

```bash
git add src/signals/acquisition_runtime/contracts.py ops/host/acquisition-runtime.production.json tests/test_acquisition_runtime_contracts_production.py tests/test_acquisition_runtime_config_production.py
git commit -m "feat(acquisition): define assisted catalog mode"
```

### Task 2: Select every exact mono-family notice with an official holder

**Files:**

- Create: `src/signals/acquisition_runtime/catalog_selection.py`
- Modify: `src/signals/acquisition_runtime/selection.py:80-430`
- Test: `tests/test_acquisition_runtime_catalog_selection.py`

- [ ] Add fixtures containing: an exact electrical notice with an official holder, a multi-family timber/roofing notice, an exact insulation notice without official holder, an out-of-region notice, and a stale notice.

- [ ] Add a failing test for this public contract:

```python
inventory = select_assisted_catalog_signals(
    engine,
    country="FR",
    region="Auvergne-Rhône-Alpes",
    observed_at=NOW,
)
assert [x.signal.opportunity_key for x in inventory["electrical"].notices] == [
    "opp-electrical"
]
assert inventory["timber_carpentry"].zero_reason == "no_mono_avis"
assert inventory["insulation"].zero_reason == "no_official_holder"
assert set(inventory) == supplier_family_keys()
```

- [ ] Run the test and confirm RED because the selector module does not exist.

```bash
uv run pytest -q tests/test_acquisition_runtime_catalog_selection.py
```

- [ ] Expose the existing family calculation as `opportunity_family_keys(...)`. Implement immutable `CatalogNotice` and `CatalogFamilyInventory` records and `select_assisted_catalog_signals(...)`. Use only materialized public facts, the official-holder cache, the 30-day window, minimum amount, model-fit record if present, and configured region. Catch a malformed opportunity inside its own family accounting; do not fail other families.

- [ ] Prove deterministic ordering and that no cycle table is read by changing cycle rows between two calls and asserting identical inventories.

- [ ] Run tests and Ruff, then commit.

```bash
uv run pytest -q tests/test_acquisition_runtime_catalog_selection.py tests/test_acquisition_runtime_selection.py
uv run ruff check src/signals/acquisition_runtime/catalog_selection.py src/signals/acquisition_runtime/selection.py tests/test_acquisition_runtime_catalog_selection.py
git add src/signals/acquisition_runtime/catalog_selection.py src/signals/acquisition_runtime/selection.py tests/test_acquisition_runtime_catalog_selection.py
git commit -m "feat(acquisition): select mono-family catalog notices"
```

### Task 3: Build the transaction-bound catalog queue

**Files:**

- Create: `src/signals/prospection_actions/catalog_preparation.py`
- Test: `tests/test_assisted_catalog_preparation.py`

- [ ] Create test helpers for two electrical notices, one insulation notice, family-confirmed directory rows in and out of geography, and a deterministic link issuer/renderer.

- [ ] Add and run a RED test proving strict round-robin across families and use of a second notice only after all rank-one pools are exhausted.

```python
result = service.prepare(inventory)
rows = queued_rows(engine)
assert [row.family_key for row in rows[:4]] == [
    "electrical", "insulation", "electrical", "insulation"
]
assert rows[0].opportunity_key == "opp-electrical-best"
assert next(row for row in rows if row.opportunity_key == "opp-electrical-second")
```

```bash
uv run pytest -q tests/test_assisted_catalog_preparation.py -k round_robin
```

- [ ] Define these result contracts:

```python
@dataclass(frozen=True)
class CatalogFamilyResult:
    family_key: str
    eligible: int
    queued: int
    refused_by_reason: Mapping[str, int]
    deferred_global_cap: int
    opportunity_keys: tuple[str, ...]
    zero_reason: str | None

@dataclass(frozen=True)
class CatalogPreparationResult:
    prepared: int
    active_before: int
    active_after: int
    cycle_ref: str | None
    target_ids: tuple[str, ...]
    families: tuple[CatalogFamilyResult, ...]
```

- [ ] Implement candidate qualification for exact family, geo, confirmed family, usable published-site email, MX verification, and suppression state. Count precisely: `sent_30j`, `rejected_history`, `holder`, `non_site_email`, `active_duplicate`, and `historical_target`.

- [ ] Implement level-by-level notice allocation and strict family round-robin. Keep an in-batch SIREN set; classify later occurrences as `active_duplicate`. When the active queue plus selected delta reaches 25, count remaining unique candidates as `deferred_global_cap` without persisting rejection.

- [ ] Build every row with its own signal and family, issue its kat1, render, and verify that the exact `attribution_url` is the only `/a/` URL present in both text and HTML. Only after every row validates, insert all targets and history rows in one transaction.

- [ ] Insert or update one summary `acquisition_runtime_cycle` under the same transaction. Its representative opportunity is display-only; selection code must never consume it. Give every new target that catalog batch `cycle_ref`.

- [ ] Add RED/GREEN tests for:

  - active rows from any date reduce the delta to 25;
  - a second prepare inserts zero rows and mints zero links;
  - holder and rejected SIRENs never queue;
  - recent sent means `instantly_accepted_at` within 30 days;
  - a renderer failure on the second row rolls back every target and the summary cycle;
  - one family qualification error leaves that family at zero and lets another family queue;
  - target fields and attribution payload match the row's family and opportunity;
  - no cross-family bait appears in either preview.

- [ ] Run the full new suite and Ruff, then commit.

```bash
uv run pytest -q tests/test_assisted_catalog_preparation.py
uv run ruff check src/signals/prospection_actions/catalog_preparation.py tests/test_assisted_catalog_preparation.py
git add src/signals/prospection_actions/catalog_preparation.py tests/test_assisted_catalog_preparation.py
git commit -m "feat(acquisition): prepare catalog queue atomically"
```

### Task 4: Route POST prepare and the timer through the same provider-free composition

**Files:**

- Create: `src/signals/acquisition_runtime/catalog_composition.py`
- Modify: `src/signals/acquisition_runtime/cli.py:20-285`
- Modify: `src/signals/founder_api/acquisition_actions.py:35-115`
- Test: `tests/test_acquisition_runtime_cli.py`
- Test: `tests/founder_api/test_acquisition_prepare_action.py`

- [ ] Add a failing CLI test with an injected catalog executor. Assert it is called once, the legacy runtime executor is never called, and bounded per-family output is printed.

```python
assert main(
    ["prepare-queue"],
    execute=lambda _allow: pytest.fail("legacy cycle must not run"),
    prepare_catalog=lambda: catalog_result,
) == 0
```

- [ ] Implement `execute_assisted_catalog_preparation()` using only:

  - `load_runtime_config()`;
  - `load_runtime_link_config()`;
  - `create_database_engine()`;
  - `AttributionProspectLinkIssuer`;
  - `select_assisted_catalog_signals()`;
  - `AssistedCatalogPreparationService`.

Reject non-production, non-ASSISTED, or non-catalog configurations with sanitized configuration codes. Do not import connectivity, Apollo, model, webhook, campaign, or Instantly modules.

- [ ] Replace the `prepare-queue` loop with exactly one catalog call. Print a summary and one safe line per family. Preserve `run-once` unchanged.

- [ ] Change Founder launcher's cap precheck to count every active `pending_review`/`approved` row, regardless of creation date. Preserve the existing response field name for wire compatibility.

- [ ] Add a source-boundary test asserting forbidden provider imports are absent from `catalog_composition.py` and that provider builders patched to raise are not touched.

- [ ] Run CLI and Founder tests plus Ruff, then commit.

```bash
uv run pytest -q tests/test_acquisition_runtime_cli.py tests/founder_api/test_acquisition_prepare_action.py
uv run ruff check src/signals/acquisition_runtime/catalog_composition.py src/signals/acquisition_runtime/cli.py src/signals/founder_api/acquisition_actions.py tests/test_acquisition_runtime_cli.py tests/founder_api/test_acquisition_prepare_action.py
git add src/signals/acquisition_runtime/catalog_composition.py src/signals/acquisition_runtime/cli.py src/signals/founder_api/acquisition_actions.py tests/test_acquisition_runtime_cli.py tests/founder_api/test_acquisition_prepare_action.py
git commit -m "feat(founder): launch catalog preparation"
```

### Task 5: Make the Founder read model treat rows as truth

**Files:**

- Modify: `src/signals/founder_api/prospection.py:390-575`
- Test: `tests/founder_api/test_prospection.py`

- [ ] Add a failing test with one catalog summary cycle and targets from electrical and insulation opportunities. Assert the queue items retain their own bait and the targeting summary returns both family keys without rewriting either row from the representative cycle.

- [ ] Keep the cycle signal as display-only. Derive prepared family keys from the target rows sharing the catalog `cycle_ref`; derive every queue item's family/bait from its own `prospect_target` columns.

- [ ] Run the Founder suite and Ruff, then commit.

```bash
uv run pytest -q tests/founder_api/test_prospection.py
uv run ruff check src/signals/founder_api/prospection.py tests/founder_api/test_prospection.py
git add src/signals/founder_api/prospection.py tests/founder_api/test_prospection.py
git commit -m "fix(founder): report catalog rows independently"
```

### Task 6: Run consolidated verification and publish

**Files:**

- Verify all files changed since `2d7dfa2aa7fafa51f058d7a36153794a3746176f`

- [ ] Run all focused tests together, then the broader acquisition/prospection suites.

```bash
uv run pytest -q \
  tests/test_acquisition_runtime_catalog_selection.py \
  tests/test_assisted_catalog_preparation.py \
  tests/test_acquisition_runtime_cli.py \
  tests/test_acquisition_runtime_contracts_production.py \
  tests/test_acquisition_runtime_config_production.py \
  tests/test_acquisition_runtime_selection.py \
  tests/test_assisted_prospect_preparation.py \
  tests/founder_api/test_acquisition_prepare_action.py \
  tests/founder_api/test_prospection.py
uv run ruff check src/signals/acquisition_runtime src/signals/prospection_actions src/signals/founder_api tests/test_acquisition_runtime_catalog_selection.py tests/test_assisted_catalog_preparation.py tests/test_acquisition_runtime_cli.py tests/founder_api/test_acquisition_prepare_action.py tests/founder_api/test_prospection.py
```

- [ ] Prove there is no provider/send path in the catalog composition and inspect the complete diff.

```bash
rg -n "Instantly|Apollo|model|/send|prospection/send" src/signals/acquisition_runtime/catalog_composition.py src/signals/prospection_actions/catalog_preparation.py
git diff --check 2d7dfa2aa7fafa51f058d7a36153794a3746176f..HEAD
git diff --stat 2d7dfa2aa7fafa51f058d7a36153794a3746176f..HEAD
```

Expected: the search has no provider/send construction; diff check exits zero.

- [ ] Push `main`, record the immutable SHA, and ensure the worktree is clean.

```bash
git push origin HEAD:main
git rev-parse HEAD
git status --short
```

### Task 7: Deploy and run one production catalog preparation

**Files:**

- Deploy immutable SHA from Task 6
- Atomically update `/etc/kivou/acquisition-production.json`

- [ ] Read-only snapshot: active SHA, active queue count, total `sent`, timer state, and current host config. Stop the acquisition preparation timer only if active; never touch the send service.

- [ ] Resolve the immutable executable SHA, deploy it, then atomically back up and install the tested catalog JSON from the release.

```bash
KIVOU_CATALOG_SHA=$(git rev-parse HEAD)
test "${#KIVOU_CATALOG_SHA}" -eq 40
ssh -tt kivou-production "sudo bash -lc 'set -a; source /etc/kivou/production.env; set +a; git -c safe.directory=/srv/kivou/source -C /srv/kivou/source fetch origin main; /srv/kivou/source/ops/bin/kivou-deploy.sh production $KIVOU_CATALOG_SHA'"
ssh -tt kivou-production "sudo bash -lc 'set -Eeuo pipefail; cp -a /etc/kivou/acquisition-production.json /etc/kivou/acquisition-production.json.pre-catalog-20260918.bak; install -o root -g kivou -m 0640 /srv/kivou/app/ops/host/acquisition-runtime.production.json /etc/kivou/acquisition-production.json; python3 -m json.tool /etc/kivou/acquisition-production.json >/dev/null'"
```

- [ ] Before preparation, recheck active queue and `sent`. Abort on unexpected drift.

- [ ] Run exactly one locked command:

```bash
python -m signals.acquisition_runtime prepare-queue
```

under the production environment and `kivou` user. Do not retry automatically.

- [ ] Restore the preparation timer if it was active.

- [ ] Verify the recipe from PostgreSQL and the local Founder GET:

  - active queue total `<= 25`, new rows `pending_review` only;
  - rows may span families, but each has one scalar family and a matching mono-family opportunity;
  - all new email evidence is site-published;
  - no holder, recent sent, rejected-history, active duplicate, or historical target was inserted;
  - each row's field/text/HTML contains the same attribution URL;
  - electrical preview and one other family preview, if present, contain no cross-trade bait;
  - total `sent` unchanged;
  - journal since the operation has no send or Instantly call.

- [ ] Report deployed SHA and a table per family: eligible, queued, refused by reason, deferred cap, used opportunity keys, and zero reason.
