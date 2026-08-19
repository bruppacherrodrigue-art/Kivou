# SPEC-016A-R1 Live Data Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing four-source production ingestion runtime safely handle BOAMP DSP notices, real unbounded BOAMP contract references, and DECP windows at or above Opendatasoft's 10,000-record ceiling.

**Architecture:** Keep orchestration and product semantics unchanged. Add an explicit BOAMP safe-skip registry at the source boundary, widen only `contract_award.contract_reference` through linear migration `0006`, and make the DECP client count then recursively partition inclusive date windows before paginating. Count/fetch drift fails closed with typed `source_limit`, allowing the existing partial-commit and unchanged-checkpoint behavior to recover on replay.

**Tech Stack:** Python 3.12, Pydantic domain models, SQLAlchemy Core, Alembic, httpx, pytest, SQLite CI migration tests, PostgreSQL-compatible DDL.

---

### Task 1: Reconfirm the linear migration gate

**Files:**
- Inspect: `src/signals/persistence/migrations/versions/`

- [ ] **Step 1: Fetch the authoritative main branch without changing the hotfix branch**

Run:

```bash
git fetch origin
git branch --show-current
git rev-parse origin/main
git ls-tree -r --name-only origin/main -- src/signals/persistence/migrations/versions
```

Expected: branch `fix/spec016a-live-data-hardening`; `origin/main` contains `0005_ingestion_runtime` and no `0006`.

- [ ] **Step 2: Ask Alembic for the repository head**

Run:

```bash
uv run python -c "from alembic.script import ScriptDirectory; from signals.persistence.database import alembic_config, create_database_engine; print(ScriptDirectory.from_config(alembic_config(create_database_engine('sqlite+pysqlite:///:memory:'))).get_current_head())"
```

Expected: `0005_ingestion_runtime` before the new migration exists.

### Task 2: Make BOAMP DSP an explicit terminal skip

**Files:**
- Modify: `src/signals/ingestion/sources.py`
- Modify: `tests/test_ingestion_sources.py`
- Modify: `tests/test_ingestion_runner.py`

- [ ] **Step 1: Add failing source tests**

Add a stub yielding a faithful `{"donnees": json.dumps({"DSP": {...}})}` record followed by `LINKED_BOAMP`. Assert:

```python
result.complete is True
result.fetched == 2
result.accepted == 1
result.rejected == 1
result.rejection_reasons == {"unsupported_notice_family_dsp": 1}
```

Keep the existing parametrized malformed test and add an unknown-family assertion if it is not already explicit.

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest -q tests/test_ingestion_sources.py -k 'dsp or malformed_boamp'
```

Expected: DSP fails because it currently becomes `BoampMalformedPayload`, and `AcquisitionResult` has no `rejection_reasons`.

- [ ] **Step 3: Add the minimal Kivou-owned registry and structured result**

Implement in `sources.py`:

```python
BOAMP_SAFE_SKIP_REASONS = {
    "FNSimple": "unsupported_notice_family_fnsimple",
    "MAPA": "unsupported_notice_family_mapa",
    "DSP": "unsupported_notice_family_dsp",
}
```

Add `rejection_reasons: dict[str, int]` to `AcquisitionResult` with an empty default. On a recognized unsupported kind, increment both `rejected` and the mapped reason count, emit a structured log record, and continue. Unknown/unparseable/incomplete payloads still raise `BoampMalformedPayload`.

- [ ] **Step 4: Verify GREEN at the source boundary**

Run:

```bash
uv run pytest -q tests/test_ingestion_sources.py
```

Expected: all source tests pass.

- [ ] **Step 5: Add and run a checkpoint-level DSP test**

Use `IngestionRunner` with DSP then a supported BOAMP record. Assert exit code 0, one rejected record, supported persistence, and checkpoint at the completed window. Run:

```bash
uv run pytest -q tests/test_ingestion_runner.py -k 'safe_terminal_skip or malformed_boamp'
```

Expected: DSP advances; malformed JSON retains the previous checkpoint.

### Task 3: Reproduce and fix the contract reference overflow

**Files:**
- Modify: `src/signals/persistence/schema.py`
- Create: `src/signals/persistence/migrations/versions/0006_contract_award_text_capacity_contract_award_text_capacity.py`
- Create: `tests/test_contract_award_text_capacity.py`
- Create: `tests/test_contract_award_text_capacity_migration.py`

- [ ] **Step 1: Write the failing schema and round-trip tests**

Define the exact 409-character value observed in BOAMP notice `26-74073`. Place it in a copied real eForms record at:

```text
EFORMS/ContractAwardNotice/.../efac:SettledContract/
efac:ContractReference/cbc:ID
```

Assert normalization returns that exact value, `contract_award.c.contract_reference.type` is `sa.Text`, ingestion persists it, `opportunity_representation` exists, and the selected database value equals the original character-for-character.

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest -q tests/test_contract_award_text_capacity.py
```

Expected: the type assertion fails because the field is still `VARCHAR(256)`.

- [ ] **Step 3: Change only the demonstrated schema field**

In `schema.py`, replace only:

```python
sa.Column("contract_reference", sa.String(256))
```

with:

```python
sa.Column("contract_reference", sa.Text)
```

- [ ] **Step 4: Write migration tests before the migration**

Tests must upgrade a SQLite database to `0005`, insert an existing source event and contract award containing the 409-character value, then upgrade to head and assert revision `0006_contract_award_text_capacity`, type `TEXT`, and exact data equality. A second test upgrades a fresh database to head. A PostgreSQL dialect assertion must compile the target type as `TEXT`.

- [ ] **Step 5: Verify migration tests are RED**

Run:

```bash
uv run pytest -q tests/test_contract_award_text_capacity_migration.py
```

Expected: failure because revision `0006_contract_award_text_capacity` does not exist.

- [ ] **Step 6: Add the linear migration**

Create a migration with:

```python
revision = "0006_contract_award_text_capacity"
down_revision = "0005_ingestion_runtime"
```

Use `op.batch_alter_table("contract_award")` and alter only `contract_reference` from `sa.String(256)` to `sa.Text()`. The downgrade reverses the type and lets the database reject unsafe shrinking rather than truncating data.

- [ ] **Step 7: Verify GREEN**

Run:

```bash
uv run pytest -q tests/test_contract_award_text_capacity.py tests/test_contract_award_text_capacity_migration.py
```

Expected: all capacity and migration tests pass.

### Task 4: Add DECP count-first partitioning and ceiling-safe pagination

**Files:**
- Modify: `src/signals/connectors/decp/client.py`
- Modify: `src/signals/connectors/decp/errors.py`
- Modify: `src/signals/connectors/decp/__init__.py`
- Modify: `tests/test_decp_client.py`

- [ ] **Step 1: Add failing tests for 9,999, 10,000, and greater than 10,000**

Use `httpx.MockTransport` to return `total_count` based on the inclusive `where` predicate. Assert:

```text
9,999  -> one date window; final data request offset=9900 limit=99;
          final drift probe offset=9999 limit=1; all 9,999 rows returned
10,000 -> root is split before data pagination
>10,000 -> recursive chronological children; every synthetic row returned
```

Also assert every request satisfies `offset + limit <= 10_000`.

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest -q tests/test_decp_client.py -k '9999 or 10000 or partitions'
```

Expected: failure because the current client has no count-first partitioning and always requests page size 100.

- [ ] **Step 3: Add typed limit failure and payload reader**

Add:

```python
class DecpWindowLimitError(DecpError):
    category = "source_limit"
```

Refactor one private HTTP response decoder to validate both `results` and non-negative integer `total_count`. Keep `fetch_page()` public behavior compatible.

- [ ] **Step 4: Implement deterministic window planning**

Add `DECP_RESULT_CEILING = 10_000`, a count method, and a lazy recursive planner. For a dense multi-day interval, compute:

```python
midpoint = since + dt.timedelta(days=(until - since).days // 2)
left = (since, midpoint)
right = (midpoint + dt.timedelta(days=1), until)
```

For a dense one-day interval raise `DecpWindowLimitError`. Process children left then right.

- [ ] **Step 5: Implement exact remaining-page sizes and a drift probe**

For each safe subwindow, page only the planned count using:

```python
limit = min(PAGE_SIZE, remaining)
```

After the planned count is consumed, request one row at `offset=planned_total`, `limit=1`. If a row exists, or a page is unexpectedly short, raise `DecpWindowLimitError("DECP window changed during pagination")`. This is the approved fail-closed fallback for count/fetch drift.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
uv run pytest -q tests/test_decp_client.py
```

Expected: all DECP query, typed failure, partition, ceiling, and drift tests pass.

### Task 5: Prove DECP checkpoint recovery and persistence idempotence

**Files:**
- Modify: `tests/test_ingestion_sources.py`
- Modify: `tests/test_ingestion_runner.py`
- Modify: `tests/test_ingestion_pipeline.py` only if the existing idempotence assertion cannot be reused

- [ ] **Step 1: Add failing partition-boundary and partial-failure tests**

Use deterministic DECP records derived from the frozen real DECP fixture. Simulate two child windows, including a repeated boundary/logical record. Make the later child raise `DecpWindowLimitError` after earlier publications have been yielded.

Assert after the first run:

```text
earlier facts and opportunity representations exist
source outcome is failed/source_limit
checkpoint window_end equals its previous successful value
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest -q tests/test_ingestion_sources.py tests/test_ingestion_runner.py -k 'decp and (partition or boundary or rerun or source_limit)'
```

Expected: failure until partition-aware behavior is connected through `DecpSource`.

- [ ] **Step 3: Make only the minimal integration adjustments**

Keep `DecpSource` consuming `fetch_contracts_since()` as a generator. Its existing `AcquisitionFailure.partial` captures publications yielded before a later slice failure; the runner already persists those publications before failing the source and retaining its checkpoint. Adjust only structured propagation needed for `source_limit`.

- [ ] **Step 4: Add restart/rerun assertions**

On the second run, make all slices succeed. Assert the checkpoint advances and counts of `source_event`, `contract_award`, `opportunity_representation`, and logical signals do not duplicate previously committed facts.

- [ ] **Step 5: Verify GREEN across ingestion runtime tests**

Run:

```bash
uv run pytest -q tests/test_decp_client.py tests/test_ingestion_sources.py tests/test_ingestion_runner.py tests/test_ingestion_pipeline.py tests/test_ingestion_e2e.py tests/test_ingestion_backfill.py
```

Expected: all selected ingestion tests pass.

### Task 6: Run bounded public-source validation

**Files:**
- Update: `docs/reports/2026-08-19-spec016a-r1-live-data-hardening.md`

- [ ] **Step 1: Validate BOAMP without persistence**

Use a small public date window known to include at least one DSP and supported eForms notice. Run `BoampSource.acquire()` with a low `max_records` only if it still reaches both forms; otherwise query the known DSP by public identifier and one supported record through a bounded client stub. Record DSP rejection reason and successful supported normalization.

- [ ] **Step 2: Validate DECP predicates without a corpus download**

Issue count-only real API requests for the 30-day parent and its calculated date children. Confirm response 200, stable inclusive predicates, child ranges cover the parent, and each planned leaf is below 10,000. Do not fetch all rows.

### Task 7: Run complete regression gates and finalize the report

**Files:**
- Create: `docs/reports/2026-08-19-spec016a-r1-live-data-hardening.md`
- Update: `docs/reports/2026-08-19-spec016a-r1-live-data-hardening-plan.md` checklist state

- [ ] **Step 1: Run backend gates**

```bash
uv run pytest -q
uv run ruff check .
git diff --check
```

Expected: test count is at least merged-main baseline, zero skipped unless explicitly reported, ruff and whitespace checks pass.

- [ ] **Step 2: Run frontend gates**

```bash
cd frontend
npm test -- --run
npm run build
npx tsc -b
npm run lint
```

Expected: at least 84 tests; build, typecheck, and lint pass.

- [ ] **Step 3: Write the evidence-based report**

Include exact observed lengths, DSP registry and backlog, migration lineage/results, 9,999/10,000/>10,000 behavior, drift fallback, checkpoint/replay results, bounded live validation, exact test counts, changed files, `git diff --stat`, `git status --porcelain`, and a provisional verdict pending CI.

### Task 8: Publish one intentional hotfix commit and verify CI

**Files:**
- Stage only the files listed by this plan and the final report

- [ ] **Step 1: Secret and scope review**

Run targeted secret-pattern scans over the diff, verify no `ops/`, TED, engine, frontend feature, SPEC-018, or unrelated research changes, and inspect `git diff --stat` plus `git diff --check`.

- [ ] **Step 2: Create the requested commit**

Stage explicit paths only; never use `git add .`. Commit:

```text
fix(data): harden ingestion for live source data
```

- [ ] **Step 3: Push and open a draft PR**

Push `fix/spec016a-live-data-hardening` normally and open a DRAFT PR against `main`. Do not merge.

- [ ] **Step 4: Wait for GitHub Actions**

Record PR number, head SHA, Actions run ID, backend result/count, frontend result/count, and skipped count. If CI fails, diagnose and fix through a new tested commit; do not rewrite history.

- [ ] **Step 5: Finalize the report and verdict**

Update the report with actual CI evidence and end it with exactly one approved verdict. Preserve the worktree and branch for supervisor review.
