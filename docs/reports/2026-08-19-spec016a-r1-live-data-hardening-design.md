# SPEC-016A-R1 — Live Data Hardening Design

Date: 2026-08-19

Branch: `fix/spec016a-live-data-hardening`

Base: `origin/main` at `2586efd4ae9f09cb4be3ab6ee98d0052e056eb44`

## Purpose

Harden the approved production ingestion runtime against three conditions observed with real staging data, without changing normalization, matching, recency, linkage, customer readiness, billing, alerts, or frontend behavior.

SPEC-018 remains paused. Its branch contains no implementation and no migration. This hotfix may therefore use the next linear revision, `0006_contract_award_text_capacity`.

## Root-cause evidence

### BOAMP DSP

A bounded scan of the same 2026-07-20 through 2026-08-19 public BOAMP window returned 3,217 records:

| Payload family | Count |
|---|---:|
| EFORMS | 2,426 |
| FNSimple | 696 |
| MAPA | 89 |
| DSP | 6 |

`DSP` is a recognized BOAMP notice family, not malformed eForms. The current `BoampSource` treats only `FNSimple` and `MAPA` as terminally unsupported and therefore raises `BoampMalformedPayload` for DSP.

### ContractAward capacity

The same public scan attempted all 2,426 eForms records, successfully normalized 2,425, retained the remaining malformed record as a processing failure, and measured every successfully normalized `contract_award` input currently bounded to 256 characters. Only `contract_reference` exceeded the limit:

| BOAMP notice | Field | Observed length |
|---|---|---:|
| `26-73510` | `contract_reference` | 317 |
| `26-74073` | `contract_reference` | 409 |
| `26-78161` | `contract_reference` | 257 |

The field comes from eForms `efac:ContractReference/cbc:ID`. It is a buyer-published business reference and is naturally variable free-form text. The current type is `sa.String(256)`. No other measured `contract_award` identity field exceeded its declared capacity.

### DECP pagination ceiling

A count-only request for the 2026-07-20 through 2026-08-19 DECP window returned `total_count=17,996`. Opendatasoft exposes `total_count` while returning only one requested result, so partition planning does not require downloading the corpus. The existing offset pagination reaches the API ceiling and receives HTTP 400 at 10,000.

## Approved design

### 1. BOAMP safe terminal skip

`BoampSource` will use a Kivou-owned mapping of recognized unsupported families to stable reason codes:

```text
FNSimple -> unsupported_notice_family_fnsimple
MAPA     -> unsupported_notice_family_mapa
DSP      -> unsupported_notice_family_dsp
```

Each recognized family increments `records_rejected`, records the structured reason count in the acquisition result, and continues to later records. A window containing DSP may complete and advance its checkpoint.

Unknown families, invalid JSON, empty payloads, incomplete eForms wrappers, and eForms notices without processable awards remain processing failures. They retain the previous checkpoint. DSP parsing and concession semantics are explicitly deferred to the post-MVP source-coverage backlog.

### 2. Exact schema correction

Only `contract_award.contract_reference` changes from `String(256)` to `Text`. Values are preserved exactly; there is no truncation, substringing, or discarded award.

Migration `0006_contract_award_text_capacity` follows `0005_ingestion_runtime`. PostgreSQL uses an in-place type widening to `TEXT`. SQLite uses Alembic batch alteration, which copies every existing row into the widened test table; migration tests verify equality before and after the copy. Previous migrations remain untouched.

A faithful regression fixture uses the real 409-character BOAMP `contract_reference` in the actual eForms `ContractReference` path and proves:

```text
source-like BOAMP record
-> normalization
-> ingestion pipeline
-> contract_award
-> opportunity_representation
-> full round-trip equality
```

### 3. DECP deterministic partitioning

The DECP client will expose a typed count operation using the same date predicate and `total_count`. Production acquisition will plan safe date windows lazily and process them chronologically.

For an inclusive date window `[since, until]`:

1. Count the window.
2. If `total_count < 10,000`, paginate it normally.
3. If `total_count >= 10,000` and the window spans multiple dates, bisect by whole dates:
   - left: `[since, midpoint]`
   - right: `[midpoint + 1 day, until]`
4. Apply the same rule recursively to each child.
5. If one calendar day still contains at least 10,000 records, raise a typed `DecpWindowLimitError` with category `source_limit`.

The adjacent inclusive date ranges cover the original interval exactly without a boundary gap. Stable ordering remains `datepublicationdonnees asc, id asc`. Source duplicates and replay duplicates remain safe because existing fact and opportunity identities are idempotent.

The planner is bounded: every split strictly reduces the number of calendar days, and a one-day dense window is the deterministic escape condition. `--max-records` remains a deliberately incomplete diagnostic run and never advances a checkpoint.

## Failure and checkpoint semantics

Acquisition retains already normalized publications when a later DECP slice fails. The existing runner processes that partial result in bounded transactions, then records source failure:

```text
earlier slice facts committed
later slice fails
-> previous checkpoint retained
-> overall source non-zero
-> rerun repeats the full overlapped window
-> existing idempotence prevents duplicate facts/opportunities/signals
```

Only all slices completing safely allows checkpoint advancement. DSP is a safe terminal skip. Malformed BOAMP eForms, malformed DECP responses, persistence failures, and dense minimum DECP windows are processing failures.

TED is unchanged. Its typed 429 behavior and unchanged checkpoint remain authoritative.

## Test design

Tests are deterministic and offline:

- DSP followed by a valid eForms award completes, increments the rejected counter with `unsupported_notice_family_dsp`, persists the supported award, and advances the checkpoint.
- Invalid JSON and malformed eForms remain failures with unchanged checkpoints.
- `contract_reference` is `Text`, the real 409-character value survives normalization and persistence exactly, and an opportunity is created.
- Migration upgrades 0005 to 0006, a fresh database reaches head, existing rows survive, and PostgreSQL DDL widens only the demonstrated field.
- DECP below 10,000 uses one window; above 10,000 partitions recursively; boundary records are not lost; duplicates remain one logical fact.
- A later slice failure preserves earlier facts and retains the checkpoint; rerun completes without duplicates.
- A single-day count at or above 10,000 raises the typed operational error.
- Existing four-source, linkage, conflict, matching, backfill, feed, checkpoint, restart, and no-alert tests remain green.

## Validation and delivery

After targeted tests, run the full backend and frontend gates. Bounded live validation will inspect a small BOAMP window containing DSP and validate DECP count/partition query syntax without downloading a large corpus.

The final report will be `docs/reports/2026-08-19-spec016a-r1-live-data-hardening.md`. Changes will be pushed to a draft PR targeting `main`; the PR will not be merged or deployed.
