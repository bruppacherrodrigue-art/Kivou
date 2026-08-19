# SPEC-016A-R1 — Live Data Hardening

Date: 2026-08-19

Branch: `fix/spec016a-live-data-hardening`

Base: `2586efd4ae9f09cb4be3ab6ee98d0052e056eb44` (`origin/main`)

Scope: source/runtime hardening only; no deployment

## Result

The three production-data failures observed on staging now have deterministic, production-safe handling:

- BOAMP `DSP` is a recognized terminal skip with reason `unsupported_notice_family_dsp`; supported records later in the same run continue normally.
- The only demonstrated overflowing field, `contract_award.contract_reference`, is stored as unbounded `Text` through linear migration `0006_contract_award_text_capacity`.
- DECP counts each inclusive window, partitions any result count at or above 10,000 into exact date children, and fails closed on an irreducibly dense day or count/fetch drift.

TED, matching, Need Graph, recency, Evidence, customer readiness, materialization, backfill, billing, alerts, and frontend behavior were not changed.

## BOAMP DSP

### Real evidence

The diagnostic scan of the staging bootstrap interval, 2026-07-20 through 2026-08-19, read 3,217 public BOAMP attribution notices:

| Family | Records |
|---|---:|
| EFORMS | 2,426 |
| FNSimple | 696 |
| MAPA | 89 |
| DSP | 6 |

DSP is a distinct valid BOAMP notice family. It is not malformed eForms and this hotfix does not parse it as an award.

### Implemented behavior

`signals.ingestion.sources.BOAMP_SAFE_SKIP_REASONS` now owns the explicit registry:

```text
FNSimple -> unsupported_notice_family_fnsimple
MAPA     -> unsupported_notice_family_mapa
DSP      -> unsupported_notice_family_dsp
```

A recognized family:

- increments `records_rejected`;
- increments its structured reason count in `AcquisitionResult.rejection_reasons`;
- emits a structured log with source, public notice identifier, and reason code;
- creates no `ContractAward`;
- does not stop later supported records;
- permits checkpoint advancement when the rest of the source window completes.

Unknown families, invalid JSON, malformed eForms, and eForms without a processable award remain typed processing failures. Their source checkpoint remains at the previous successful position.

### Backlog

```text
BOAMP DSP/concession parsing
-> post-MVP source-coverage enhancement
```

No concession or winner semantics were fabricated in this hotfix.

## Contract reference capacity

### Exact field and observations

A bounded real-source scan normalized the supported BOAMP eForms notices and measured every `contract_award` input declared as `String(256)`. Only one field exceeded the capacity:

| Source | Notice | Column | Observed length | Previous type | Meaning |
|---|---|---|---:|---|---|
| BOAMP | `26-73510` | `contract_award.contract_reference` | 317 | `VARCHAR(256)` | buyer-published business contract reference |
| BOAMP | `26-74073` | `contract_award.contract_reference` | 409 | `VARCHAR(256)` | buyer-published business contract reference |
| BOAMP | `26-78161` | `contract_award.contract_reference` | 257 | `VARCHAR(256)` | buyer-published business contract reference |

The canonical value comes from eForms `efac:ContractReference/cbc:ID`. It is naturally variable free-form source text, not a Kivou identifier with a semantic 256-character maximum.

### Schema correction

Only this field changed:

```text
contract_award.contract_reference
VARCHAR(256) -> TEXT
```

`source_award_id`, `lot_identifier`, and every other persisted column remain unchanged. No truncation, substring, silent discard, or adapter normalization change was introduced.

### Round-trip regression

The deterministic regression uses the exact 409-character public BOAMP value from notice `26-74073` in the real eForms `ContractReference` path. The test proves:

```text
source-shaped BOAMP eForms
-> parse_award_notice
-> BoampSource
-> IngestionRunner / IngestionPipeline
-> contract_award
-> opportunity_representation
-> selected value equals the original 409 characters
```

Result: PASS, with one stable opportunity representation and exact character-for-character equality.

## Migration

Revision:

```text
0005_ingestion_runtime
    -> 0006_contract_award_text_capacity
```

No competing `0006` existed on `origin/main` when the migration was created. Previous migration files were not modified.

PostgreSQL offline migration SQL is exactly:

```sql
ALTER TABLE contract_award ALTER COLUMN contract_reference TYPE TEXT;
```

SQLite uses Alembic batch alteration because SQLite cannot alter a column type in place. Foreign-key enforcement is suspended only around the transactional table copy and restored immediately afterward. Tests cover populated legacy databases whose signals, evidence, and opportunity representations reference `contract_award`.

Migration results:

- upgrade `0005 -> 0006`: PASS;
- fresh database to head: PASS;
- single linear Alembic head: PASS;
- populated database rows preserved: PASS;
- 409-character value preserved: PASS;
- PostgreSQL output alters only `contract_reference`: PASS;
- SQLite foreign keys restored after migration: PASS through the existing persistence migration gate.

## DECP deterministic partitioning

### Algorithm

For each inclusive `[since, until]` window:

1. Issue a count request using the same date predicate and `limit=1`.
2. If `total_count < 10,000`, paginate that window.
3. If `total_count >= 10,000` and the interval spans several dates, bisect by calendar date.
4. Recurse left then right:

```text
left  = [since, midpoint]
right = [midpoint + 1 day, until]
```

5. If a single calendar day remains at or above 10,000, raise `DecpWindowLimitError(category="source_limit")`.

Every split strictly reduces the date span, so recursion has a deterministic end. The two adjacent children cover the parent exactly without a missing boundary date. Stable result ordering remains `datepublicationdonnees asc, id asc`.

### Ceiling edge cases

| Planned count | Implemented behavior | Deterministic result |
|---:|---|---|
| 9,999 | one window; pages of 100; final data page `offset=9900, limit=99`; drift probe `offset=9999, limit=1` | PASS |
| 10,000 | partition before any unsafe root data pagination | PASS |
| >10,000 | recursively partition into chronological safe children | PASS |
| one day ≥10,000 | typed `source_limit`; no silent loss | PASS |

Every generated request is guarded by:

```text
offset + limit <= 10,000
```

The runtime never creates an oversized final request merely because the normal page size is 100.

### Count/fetch drift

The client does not assume the count remains immutable:

- each data response's `total_count` is compared with the planned count;
- an unexpectedly short page is incomplete, not end-of-data success;
- after consuming the planned rows, a one-row boundary probe checks for newly visible data;
- any mismatch raises typed `DecpWindowLimitError(category="source_limit")`.

This hotfix uses the approved fail-closed fallback instead of trying to mutate a partition plan while records are streaming. No records are silently declared complete, and the durable source checkpoint does not advance. The next run recounts and repartitions from the previous checkpoint.

## Checkpoint and partial-commit behavior

The existing runner's bounded transaction behavior remains intact:

```text
earlier DECP child yields valid facts
-> facts committed
later child fails
-> source outcome failed/source_limit
-> checkpoint unchanged
-> rerun repeats the overlapped source window
-> existing identities absorb prior facts and boundary duplicates
-> all children complete
-> checkpoint advances
```

The deterministic integration test observed one `source_event`, one `contract_award`, and one `opportunity_representation` after the failed run. A successful rerun containing the same record twice left all three counts at one and advanced the checkpoint.

## Bounded live validation

### BOAMP

Public API validation used two records only, both published 2026-08-19:

| Record | Kind | Result |
|---|---|---|
| `26-81704` | DSP | rejected with `unsupported_notice_family_dsp` |
| `26-81286` | EFORMS | normalized and accepted |

Observed aggregate:

```text
fetched=2 accepted=1 rejected=1 complete=true
rejection_reasons={unsupported_notice_family_dsp: 1}
```

### DECP

Count-only public API validation downloaded no corpus:

```text
parent [2026-07-20, 2026-08-19] = 17,996
left   [2026-07-20, 2026-08-04] =  9,095
right  [2026-08-05, 2026-08-19] =  8,901
```

Both child predicates returned HTTP 200, are adjacent, cover the parent interval, and remain below the ceiling.

## Deterministic and regression tests

Targeted ingestion group after implementation:

```text
54 passed
```

Migration and legacy-data group after the SQLite batch correction:

```text
87 passed
```

Full local gates:

| Gate | Result |
|---|---|
| Backend pytest | `2821 passed`, `0 skipped` |
| Ruff | PASS |
| `git diff --check` | PASS |
| Frontend Vitest | `84 passed` |
| Frontend build | PASS |
| Frontend typecheck | PASS |
| Frontend lint | PASS |

## GitHub CI

Code-bearing CI is pending at the time of this first report commit. The report will be updated with the PR, head SHA, Actions run ID, and backend/frontend job results after GitHub completes.

## Files changed

Application and migration:

```text
src/signals/connectors/decp/__init__.py
src/signals/connectors/decp/client.py
src/signals/connectors/decp/errors.py
src/signals/ingestion/sources.py
src/signals/persistence/schema.py
src/signals/persistence/migrations/versions/
  0006_contract_award_text_capacity_contract_award_text_capacity.py
```

Deterministic tests:

```text
tests/test_contract_award_text_capacity.py
tests/test_contract_award_text_capacity_migration.py
tests/test_decp_client.py
tests/test_ingestion_sources.py
tests/test_ingestion_runner.py
tests/test_ingestion_migration.py
tests/test_accounts_migration_and_ownership.py
tests/test_billing_entitlements.py
```

Documentation:

```text
docs/reports/2026-08-19-spec016a-r1-live-data-hardening-design.md
docs/reports/2026-08-19-spec016a-r1-live-data-hardening-plan.md
docs/reports/2026-08-19-spec016a-r1-live-data-hardening.md
```

No `ops/`, TED implementation, frontend feature, signal-engine, SPEC-018, Hermes, Stripe, SMTP, or VPS file changed.

## Git diff and status

Staged diff before the code-bearing commit:

```text
17 files changed, 1554 insertions(+), 35 deletions(-)
```

The staged scope contains exactly the three report documents, five application/migration files plus the DECP exports/errors, and the deterministic/migration test updates listed above. `git status --porcelain` contains only these explicitly staged SPEC-016A-R1 paths; there are no unstaged or unrelated files in the isolated worktree.

Post-commit status and the immutable code-bearing SHA are recorded in the CI section after publication.

LIVE INGESTION HARDENING PARTIALLY READY
