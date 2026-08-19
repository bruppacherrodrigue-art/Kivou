# SPEC-016A-R2 — Alembic Revision-ID Hotfix

Date: 2026-08-19
Branch: `fix/spec016a-alembic-revision-id`
Base: `origin/main` at `2bb72ef8e1b7598248f0a1422c0e6005f6a42362`
Scope: migration-identifier compatibility only

## PostgreSQL failure cause

Alembic's standard version table stores `version_num` as `VARCHAR(32)`. The R1 migration declared:

```text
0006_contract_award_text_capacity
```

That identifier is 33 characters long. SQLite accepted it because SQLite does not enforce the declared `VARCHAR(32)` length like PostgreSQL. PostgreSQL correctly rejected Alembic's attempt to write the 33-character value into `alembic_version.version_num`.

The replacement is:

```text
0006_award_text_capacity
```

It is 24 characters long and preserves Alembic's standard `VARCHAR(32)` contract. The internal Alembic version table was deliberately not widened: keeping standard Alembic compatibility is safer than customizing framework-owned storage for one application identifier.

## Durable-use audit

Repository/runtime evidence checked before editing:

- `origin/main` contained the broken R1 migration.
- No merged `0007` or downstream migration depended on the old identifier.
- SPEC-018 remained paused and had created no migration implementation.
- Repository tests and documentation referenced the old identifier, but there was no persistent database fixture representing it as a durable applied state.
- Per the supervisor's staging incident record, the failed PostgreSQL transaction was rolled back and staging remained coherently at `0005_ingestion_runtime`; no VPS access was performed for this hotfix.

This makes an in-place revision-ID correction safe. No durable environment is known to have recorded the failed 33-character revision.

## Migration correction

The existing migration file is renamed to:

```text
src/signals/persistence/migrations/versions/
  0006_award_text_capacity_contract_award_text_capacity.py
```

Its graph metadata is now:

```text
revision      = 0006_award_text_capacity
down_revision = 0005_ingestion_runtime
```

The migration operation is unchanged:

```text
contract_award.contract_reference
VARCHAR(256) -> TEXT
```

No second `0006`, merge revision, table change, data rewrite, truncation, or additional schema change was introduced. PostgreSQL offline SQL still contains exactly:

```sql
ALTER TABLE contract_award ALTER COLUMN contract_reference TYPE TEXT;
```

## Migration graph and repository-wide length gate

The executable graph is a single line with one head:

```text
0001_initial (12)
  -> 0002_account_auth_target_icp (28)
  -> 0003_billing (12)
  -> 0004_alerts_feedback_analytics (30)
  -> 0005_ingestion_runtime (22)
  -> 0006_award_text_capacity (24) [HEAD]
```

Numbers in parentheses are revision-ID lengths. Every ID is at most 32 characters.

The new deterministic repository-wide test loads every Alembic revision and verifies:

- every revision identifier has length `<= 32`;
- identifiers are unique;
- every `down_revision` resolves;
- exactly one expected head exists;
- `0006_award_text_capacity` is the linear child of `0005_ingestion_runtime`.

This explicit gate covers the PostgreSQL behavior that SQLite's type system cannot expose.

## Migration regression results

Completed deterministic coverage proves:

- fresh SQLite database -> head: PASS;
- populated `0005_ingestion_runtime` database -> `0006_award_text_capacity`: PASS;
- the real 409-character BOAMP `contract_reference` survives the upgrade exactly: PASS;
- SQLAlchemy schema type is PostgreSQL `TEXT`: PASS;
- PostgreSQL offline SQL widens only `contract_reference`: PASS;
- all selected migration/account/billing tests: `78 passed`;
- focused R2 migration suite: `6 passed`.

## R1 data behavior unchanged

No source/runtime or product-engine implementation changed. The hotfix leaves intact:

- BOAMP DSP safe terminal skips and malformed-record failures;
- DECP deterministic partitioning;
- strict `offset + limit < 10000` requests;
- count/fetch drift failure behavior;
- checkpoints, source isolation, restart/resume, and idempotence;
- Signal Engine, matching, recency, active/new-ICP backfill, billing, alerts, and frontend behavior;
- TED behavior.

SPEC-018 remains paused. After this hotfix merges, it must re-sync `main` and use:

```text
0006_award_text_capacity
  -> 0007_acquisition_event_store
```

## Full local quality gates

```text
backend pytest: 2826 passed
backend skipped: 0
ruff: PASS
git diff --check: PASS

frontend tests: 84 passed
frontend build: PASS
frontend typecheck: PASS
frontend lint: PASS
```

The backend count increased from the merged baseline of 2824 because two revision-graph regression tests were added.

## GitHub CI

```text
Draft PR: #10
Validated executable PR head SHA: d476e5006cb1977db00ca3edd1f42cb5c58878bf
GitHub Actions run ID: 32300248115
Backend job: PASS — 2826 passed, Ruff PASS
Frontend job: PASS — 84 passed, build/typecheck/lint PASS
```

## Files changed

```text
docs/reports/2026-08-19-spec016a-r1-live-data-hardening-design.md
docs/reports/2026-08-19-spec016a-r1-live-data-hardening-plan.md
docs/reports/2026-08-19-spec016a-r1-live-data-hardening.md
docs/reports/2026-08-19-spec016a-r2-alembic-revision-hotfix-plan.md
docs/reports/2026-08-19-spec016a-r2-alembic-revision-hotfix.md
src/signals/persistence/migrations/versions/0006_award_text_capacity_contract_award_text_capacity.py
tests/test_accounts_migration_and_ownership.py
tests/test_billing_entitlements.py
tests/test_contract_award_text_capacity_migration.py
tests/test_ingestion_migration.py
```

The old migration filename is removed as the rename counterpart. No `ops/`, VPS, frontend feature, source runtime, Signal Engine, Hermes, or SPEC-018 implementation file is part of the hotfix.

## Current diff summary

The committed diff consists only of the migration filename/revision correction, two graph guards, legitimate head expectations, and the R1/R2 reports:

```text
10 files changed, 388 insertions(+), 15 deletions(-)
git status --porcelain: clean at validated executable head
```

## Verdict

ALEMBIC REVISION HOTFIX READY
