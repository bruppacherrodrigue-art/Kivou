# SPEC-016A-R2 Alembic Revision-ID Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the never-durably-applied 33-character Alembic revision with the approved 24-character identifier and add a repository-wide graph/length guard.

**Architecture:** Keep Alembic's standard `VARCHAR(32)` version table and preserve the existing `contract_reference -> TEXT` migration operation. Rename only the revision identifier/file and legitimate executable expectations; validate every revision ID, parent edge, and single head through `ScriptDirectory` so SQLite can no longer hide this PostgreSQL incompatibility.

**Tech Stack:** Python 3.12, Alembic, SQLAlchemy Core, pytest, SQLite migration tests, PostgreSQL offline SQL generation.

---

### Task 1: Reproduce and guard the revision-length defect

**Files:**
- Modify: `tests/test_contract_award_text_capacity_migration.py`
- Modify: `tests/test_persistence_migrations.py`

- [ ] **Step 1: Write failing repository-wide graph tests**

Add a test which loads `ScriptDirectory.from_config(alembic_config(engine))`, walks every revision, and asserts:

```python
revisions = list(script.walk_revisions())
assert all(len(item.revision) <= 32 for item in revisions)
assert len({item.revision for item in revisions}) == len(revisions)
assert script.get_heads() == ["0006_award_text_capacity"]
for item in revisions:
    for parent in item._normalized_down_revisions:
        assert script.get_revision(parent) is not None
```

Add the focused regression:

```python
assert CAPACITY_REVISION == "0006_award_text_capacity"
assert len(CAPACITY_REVISION) <= 32
assert script.get_revision(CAPACITY_REVISION).down_revision == "0005_ingestion_runtime"
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest -q tests/test_contract_award_text_capacity_migration.py tests/test_persistence_migrations.py
```

Expected: failure because the executable migration still declares the 33-character old revision and the current head is not `0006_award_text_capacity`.

### Task 2: Apply the minimal migration identifier correction

**Files:**
- Rename: `src/signals/persistence/migrations/versions/0006_contract_award_text_capacity_contract_award_text_capacity.py` -> `src/signals/persistence/migrations/versions/0006_award_text_capacity_contract_award_text_capacity.py`
- Modify: renamed migration
- Modify: `tests/test_contract_award_text_capacity_migration.py`
- Modify: `tests/test_ingestion_migration.py`
- Modify: `tests/test_accounts_migration_and_ownership.py`
- Modify: `tests/test_billing_entitlements.py`

- [ ] **Step 1: Change only the revision identity**

The migration header becomes:

```python
revision = "0006_award_text_capacity"
down_revision = "0005_ingestion_runtime"
```

Keep `upgrade()`, `downgrade()`, the SQLite foreign-key handling, and the `String(256) <-> Text` operation byte-for-byte equivalent.

- [ ] **Step 2: Update executable head expectations**

Replace legitimate current-head constants/assertions in migration, accounts, billing, and ingestion tests with `0006_award_text_capacity`. Do not alter BOAMP, DECP, TED, matching, ingestion, or schema behavior.

- [ ] **Step 3: Verify GREEN for focused tests**

Run:

```bash
uv run pytest -q \
  tests/test_contract_award_text_capacity_migration.py \
  tests/test_persistence_migrations.py \
  tests/test_ingestion_migration.py \
  tests/test_accounts_migration_and_ownership.py \
  tests/test_billing_entitlements.py
```

Expected: all selected tests pass; fresh database and populated `0005` upgrade reach the shortened head.

### Task 3: Verify migration semantics and repository references

**Files:**
- Modify: `docs/reports/2026-08-19-spec016a-r1-live-data-hardening-design.md`
- Modify: `docs/reports/2026-08-19-spec016a-r1-live-data-hardening-plan.md`
- Modify: `docs/reports/2026-08-19-spec016a-r1-live-data-hardening.md`
- Create: `docs/reports/2026-08-19-spec016a-r2-alembic-revision-hotfix.md`

- [ ] **Step 1: Check the old identifier is absent from executable references**

Run:

```bash
rg -n '0006_contract_award_text_capacity' src tests
```

Expected: no matches.

- [ ] **Step 2: Preserve the historical incident narrative**

Update R1 future/current-head references to the executable shortened ID. In the R2 incident report, retain the old ID explicitly as the failed 33-character value and explain that no durable staging DB recorded it.

- [ ] **Step 3: Re-run migration-only verification**

Run:

```bash
uv run pytest -q tests/test_contract_award_text_capacity_migration.py tests/test_persistence_migrations.py
```

Expected: fresh -> head, populated `0005` -> head, long-value round trip, graph validation, and PostgreSQL offline SQL all pass.

### Task 4: Run full deterministic gates

**Files:**
- Modify: `docs/reports/2026-08-19-spec016a-r2-alembic-revision-hotfix.md`

- [ ] **Step 1: Backend**

```bash
uv run pytest -q
uv run ruff check .
git diff --check
```

Expected: tracked test count is at least the merged baseline, 0 skipped, Ruff and whitespace checks pass.

- [ ] **Step 2: Frontend**

```bash
cd frontend
npm test -- --run
npm run build
npx tsc -b
npm run lint
```

Expected: at least 84 tests, build/typecheck/lint pass.

- [ ] **Step 3: Record exact evidence**

Update the final R2 report with counts, revision lengths, graph, SQL, file list, `git diff --stat`, and `git status --porcelain`. Mirror the report into `/home/jaybe/projects/Kivou/docs/reports/` without touching any code in Claude's worktree.

### Task 5: Publish a CI-tested draft PR

**Files:** only the explicit R2 files above.

- [ ] **Step 1: Stage explicitly and commit**

Use explicit `git add <file...>` paths only, then:

```bash
git commit -m "fix(data): shorten Alembic revision identifier"
```

- [ ] **Step 2: Push and open a draft PR**

```bash
git push -u origin fix/spec016a-alembic-revision-id
gh pr create --draft --base main --head fix/spec016a-alembic-revision-id
```

- [ ] **Step 3: Wait for GitHub Actions**

Require backend and frontend PASS, then write the CI run ID and PR head SHA into the final report. Do not merge or deploy.
