# SPEC-016A — Production Ingestion Runtime

Date: 2026-08-19
Branch: `feat/spec016a-ingestion-runtime`
Base: `origin/main` at `1e61cc3ada3427745e3f55bd32652fcf3d9dc9e0`

## Existing architecture map

| Boundary | Existing approved implementation used by the runtime |
|---|---|
| SIMAP | `signals.connectors.simap.SimapClient` → `parse_publication()` → `map_publication()` |
| BOAMP | `signals.connectors.boamp.BoampClient` → `parse_award_notice()` |
| DECP | `signals.connectors.decp.parse_contract()`; SPEC-016A adds only the public Opendatasoft client |
| TED | `signals.connectors.ted.TedClient` → `parse_notice()` → `map_notice()` |
| Canonical facts | `PublicEvent`, `ContractAward`, `Evidence` |
| France linkage | unchanged `france-link-v0.3`: `resolve_candidates()` then `unique_strong()` |
| Persistence | `source_event`, `contract_award`, `evidence`, `opportunity_representation`, `materialized_signal` |
| Opportunity identity | `resolve_or_create_opportunity()` and explicit `OpportunityConflict` |
| Understanding | `ContractUnderstandingEngine.understand()` |
| Needs | `NeedGraphEngine.derive()` |
| Matching | `MatchingEngine.match()`; only its existing `decision == "show"` is materialized |
| Recency | unchanged `assess_recency()` with award, notification, publication, and discovery clocks |
| Customer target | persisted `target_icp`; only status `active`, converted by `to_target_icp()` |
| Materialization | unchanged signal identity/revision boundary `materialize_signal()` |
| Feed | existing ownership, name-safety, sibling-name fallback, and `feed_page()` |

The only genuine operational Python module entry point before SPEC-016A was
`python -m signals.alerts`. Connector `live_smoke` modules, verification tools,
fixture builders, SPEC scripts, benchmarks, and everything under `signals.research`
are diagnostic or research executables; none is imported or scheduled by ingestion.

## Missing-runtime finding

Current `main` contained each major business layer but no application command composed them.
Connectors were exercised by tests/live-smoke scripts, and `materialize_signal()` was called by
tests and fixtures. No production command fetched public records, persisted stable facts,
resolved opportunities, ran the approved engines for active customer ICPs, and exposed the
result through the existing feed. DECP also had an approved normalizer but no production HTTP
client. SPEC-016A supplies this missing composition, not a new inference engine.

## Files and modules added

- `signals.ingestion`: production CLI, source dispatch, window policy, checkpoint/run state,
  orchestration pipeline, failure isolation, persisted France sibling lookup, canonical fact
  reconstruction, and bounded TargetICP backfill.
- `signals.connectors.decp.client` and `signals.connectors.decp.errors`: minimal public
  Opendatasoft acquisition and typed operational failures around the unchanged DECP parser.
- `signals.connectors.boamp.errors`: typed BOAMP operational failures; normalization is unchanged.
- `signals.persistence.materialization.persist_award_facts()`: the existing fact/opportunity
  persistence steps exposed independently from customer matching.
- Alembic `0005_ingestion_runtime`: additive `ingestion_checkpoint` and `ingestion_run` tables.
- Deterministic ingestion tests: CLI, four-source dispatch, migration, checkpoints, partial
  failure, idempotence, restart, linkage/conflict, TargetICP materialization/backfill, bounded
  truncation, safe skip versus malformed failure, and feed E2E.

## Production CLI

Normal run:

```bash
python -m signals.ingestion run
```

Controls:

```text
--source {simap,boamp,decp,ted}   repeatable; default is all four
--since YYYY-MM-DD               explicit lower bound
--until ISO-8601                 explicit upper bound
--max-records N                  bounded probe; an incomplete non-dry run cannot checkpoint
--dry-run                        fetch and normalize; no business/checkpoint/run writes
```

The required environment is only `KIVOU_DATABASE_URL`. Public source clients require no
credentials. Stripe, SMTP, GitHub, SSH, and Hermes configuration are neither read nor imported.

Exit `0` means every selected source completed, including a valid zero-record window. Exit `1`
means at least one source requires operator attention. One failed source never prevents the
remaining selected sources from running.

## Source behavior

| Source | Adapter/window | Overlap | Retry/rate-limit behavior | Checkpoint behavior | Recommended cadence | Live smoke |
|---|---|---|---|---|---|---|
| SIMAP | Existing rolling `lastItem` search across all approved award families; publication detail mapping | 3 days | finite 30 s client timeout; transient failures retry twice with 1 s/2 s backoff | advances only after every selected family and detail completes; page-cap/error retains prior window | every 2 hours | **NETWORK/PARSER SMOKE PASS**: 2 current references fetched and normalized |
| BOAMP | Existing Opendatasoft `dateparution` window, stable `(dateparution,idweb)` ordering and offset pages | 7 days | finite 60 s timeout; typed timeout/network/429/5xx/4xx/malformed failures; no retry after 429 | advances only after complete acquisition and persistence; partial/error retains prior window | every 2 hours | **NETWORK/PARSER SMOKE PASS**: 2 records fetched and normalized |
| DECP | New minimal client for approved `decp-2022-marches-valides`; `datepublicationdonnees` window and stable `(date,id)` ordering | 30 days | finite 60 s timeout; same typed bounded operational failures; no retry after 429 | advances only after complete acquisition and persistence; partial/error retains prior window | every 12 hours (source is normally updated daily) | **NETWORK/PARSER SMOKE PASS**: 2 records fetched and normalized in the source-appropriate 30-day window |
| TED | Existing Search API and XML/parser path; explicit publication window, descending stable publication number, 250-row pages and 20-page safety cap | 3 days | finite 30 s timeout; bounded transient retries; immediate stop on 429 | advances only after announced total and every XML complete; truncation/429/error retains prior window | daily, off-peak; do not run concurrently | **NETWORK/PARSER SMOKE PASS**: 2 current notices searched, downloaded as XML, and normalized; an earlier HTTP 202 WAF response was transient |

The overlap deliberately re-reads recent source days. Existing deterministic keys and database
constraints absorb duplicates. Explicitly bounded probes cannot advance a checkpoint when more
records exist. A normal unbounded run advances only after complete acquisition and processing.

## Persistence

Migration: `0005_ingestion_runtime`, directly after verified `origin/main` head
`0004_alerts_feedback_analytics`. No parallel `0005` existed when created.

- `ingestion_checkpoint`: one row per approved source; cursor/window end, last start/completion,
  status, update time.
- `ingestion_run`: one row per source attempt; run id, times, status, counters, rate-limit count,
  sanitized error category/message, checkpoint before/after, dry-run marker.

Adapters carry partial acquisition counters and already-normalized publications through typed
failures. The runner safely persists that completed work, records its real counters, retains the
old checkpoint, and returns a failed source outcome. Pipeline failures likewise retain counters
for already-committed facts/signals. Invalid per-source windows are isolated and recorded instead
of leaving a run stuck as `running`; a future `--until` is rejected before any runtime state write.

`persist_award_facts()` is a narrow extraction of the pre-existing source-event, award, and
opportunity steps from `materialize_signal()`. It makes source facts durable even with zero active
or matching ICPs. `materialize_signal()` calls the same function, so existing opportunity and
revision semantics remain one implementation.

Remote requests occur outside database transactions. Each award first commits source facts and
opportunity identity in its own bounded transaction. Customer matching then runs independently;
each eligible customer signal is written in a separate bounded transaction. A matching failure
cannot erase valid public facts, and a later source failure cannot roll back prior committed awards
or another source. Final checkpoint advancement and run completion are a separate short transaction.

On a strong-link conflict, the existing `OpportunityConflict` is counted and emitted as a
sanitized structured warning with stable source identifiers and the reconciliation reason. The
new representation is kept separate; already-persistent opportunities are never silently merged.

### Safe terminal skip versus processing failure

The implementation now makes the checkpoint distinction executable:

- **SAFE TERMINAL SKIP:** a valid, recognized BOAMP non-eForms shape such as `FNSimple` or
  `MAPA` is intentionally unsupported by the deterministic adapter. It increments `rejected`,
  leaves no invented fact, and the checkpoint may advance after the rest of the window succeeds.
- **PROCESSING FAILURE:** empty/unparseable JSON, a structurally broken eForms response, typed
  source failures, persistence failures, or any pipeline exception mark the source incomplete.
  The run records the typed category (including `malformed`) and retains the previous successful
  checkpoint so overlap/idempotence can recover the record after a source or code repair.

Deterministic source and runner tests prove both outcomes. No malformed record can disappear
behind a newly advanced checkpoint.

## Deterministic E2E

Offline CI tests prove:

- frozen TED XML → existing parser/mapping → source facts → stable opportunity;
- existing understanding, Need Graph, matching and recency engines;
- active persisted TargetICP → existing `show` decision → `materialize_signal()`;
- existing feed returns the named customer signal;
- identical replay keeps event, award, opportunity, signal key, revision, and feed count stable;
- draft ICPs create no signal;
- BOAMP first, strongly linked DECP later keeps the same opportunity and logical signal;
- identifier-only DECP representation remains customer-safe through the existing named BOAMP
  sibling fallback;
- winner-name readiness remains the existing feed decision: identifier-only DECP facts do not
  become a named customer lead merely because ingestion persisted them;
- `award_date`, `contract_notification_date`, `publication_date`, and `discovered_at` remain
  separate inputs to the unchanged multi-clock recency policy;
- Evidence persistence and source/inference semantics remain the existing materialization policy;
- two already-separated strong candidates remain an explicit conflict and three separate
  opportunities, never an auto-merge;
- TED 429 leaves its checkpoint unchanged while SIMAP, BOAMP, and DECP complete;
- a restart reuses the durable checkpoint with overlap;
- ingestion never imports or invokes the alert/SMTP job.

## Safety

Unchanged:

- Contract Understanding and Need Graph rules;
- matching scores, thresholds, and the meaning of `show`;
- multi-clock recency policy and thresholds;
- Evidence semantics and signal content policy;
- opportunity identity/conflict behavior;
- billing and feed entitlements;
- alerts/email delivery;
- frontend code and behavior.

No document download, Document Intelligence auto-accept, residual-need R&D, event store, Hermes,
daemon, Redis, customer email, Stripe operation, or VPS change is part of this runtime.

## New TargetICP backfill/materialization — implemented

Before this closeout, active TargetICP creation did not evaluate opportunities persisted before
the customer existed. The API now commits the created or updated TargetICP first, then invokes a
synchronous database-only backfill whenever the resulting status is `active`. Draft profiles do
no work. A failure cannot roll back the committed customer profile, and the idempotent service
can be called again.

The service selects opportunities whose persisted publication date can still pass the
TargetICP's existing `maximum_signal_age_days` hard filter. It orders them newest first, caps
evaluation at 500, and returns `candidates_available`, `candidates_evaluated`,
`signals_materialized`, and `truncated`. More than 500 candidates yields `truncated=true` and an
operator-visible structured warning; the result is explicitly not exhaustive.

One deterministic representative is evaluated per stable `opportunity_key`: a representation
with an existing feed-valid published winner name is preferred, then `award_key` breaks ties.
The same linked opportunity therefore cannot alternate BOAMP/DECP content across replays.
Understanding, Need Graph and `MatchingEngine.match()` remain the existing implementations;
only the existing `decision == "show"` is passed to `materialize_signal()`. No network, billing,
entitlement, alert, or email path is called.

Tests persist real frozen opportunities before any account exists, then prove active creation
and draft-to-active update materialize a real `show` signal retrievable through `feed_page()`.
They also prove draft exclusion, repeat signal/revision stability, explicit 501-candidate
truncation, and deterministic named BOAMP selection for a linked BOAMP/DECP opportunity.

### Synchronous backfill performance measurement

An isolated SQLite database was seeded with 500 deterministic copies of the real frozen TED
award fixture. Data preparation was excluded from the timed interval. The actual production
service measured:

```text
candidate count: 500
evaluated count: 500
materialized count: 500
truncated: false
elapsed wall-clock: 8.203498 seconds
```

This is a measured MVP upper-bound request cost, not a latency promise. It is perceptible but did
not constitute a clear synchronous onboarding blocker on the local reference machine. The
500-candidate cap and `truncated` warning remain mandatory; scale beyond it requires a separately
approved durable asynchronous design, not hidden work in this SPEC.

## Initial production bootstrap

A fresh database should not wait for default first-run windows before the first customer. For a
deployment performed on 2026-08-19, SPEC-016 should run these isolated bounded recent bootstraps
before opening onboarding:

```bash
python -m signals.ingestion run --source simap --since 2026-07-20
python -m signals.ingestion run --source boamp --since 2026-07-20
python -m signals.ingestion run --source decp --since 2026-07-20
python -m signals.ingestion run --source ted --since 2026-08-12
```

SIMAP, BOAMP and DECP therefore request 30 recent days; TED requests 7 recent days because its
real endpoint is more rate-limit/WAF-sensitive. For a later launch date, use the equivalent
relative dates rather than these historical literals. Each command advances only its own source
checkpoint after a complete safe success. Rate limiting, a page safety cap, malformed data, or a
processing failure retains the previous checkpoint.

The initial bootstrap may require multiple smaller consecutive date slices if a source window
hits its existing page safety cap or operational limit. Complete each older slice with explicit
`--since`/`--until`, then run the final slice to the current time; idempotent overlap makes retries
safe. Do not use `--max-records` for checkpointed bootstrap completion because an intentionally
truncated window does not advance.

### HISTORY COVERAGE LAUNCH LIMITATION

This bounded bootstrap provides real recent opportunities for MVP onboarding. It does **not**
populate twelve months of history. At launch, Essential/Pro/Scale can expose only records that
have actually been bootstrapped or accumulated since ingestion started. A Pro entitlement may
permit twelve-month access while the fresh database initially contains materially less than
twelve months. SPEC-016A does not fake that history and does not introduce a historical warehouse.

## Corrected source-specific scheduling contract for SPEC-016

All commands use the release root as `WorkingDirectory`, the production virtual environment on
`PATH`, and `KIVOU_DATABASE_URL`. They share one host lock so fact/opportunity writes do not run
concurrently. A collision waits up to five minutes; if the preceding run is still active,
`flock --conflict-exit-code 0` records a clean skipped invocation instead of permanent failed-unit
noise. Timer offsets should make collision exceptional.

| Group | Exact application command | Cadence | Process timeout |
|---|---|---|---|
| Fast public sources | `/usr/bin/flock --exclusive --timeout 300 --conflict-exit-code 0 /run/kivou-ingestion.lock python -m signals.ingestion run --source simap --source boamp` | every 2 hours, offset e.g. minute 05 | 30 minutes |
| DECP | `/usr/bin/flock --exclusive --timeout 300 --conflict-exit-code 0 /run/kivou-ingestion.lock python -m signals.ingestion run --source decp` | every 12 hours, offset e.g. minute 35 | 30 minutes |
| TED | `/usr/bin/flock --exclusive --timeout 300 --conflict-exit-code 0 /run/kivou-ingestion.lock python -m signals.ingestion run --source ted` | daily off-peak, e.g. 02:30 UTC | 45 minutes |

Once the lock is acquired, exit `0` means every selected source completed, including a valid
zero-record window; non-zero means at least one selected source requires operator attention.
Lock contention alone exits `0` after the bounded wait. The journal should still record the
skipped invocation, and the next normal timer retries from the unchanged durable checkpoint.
Alerts remain a separate `python -m signals.alerts` job and are never chained from ingestion.

SPEC-016 owns the actual interpreter path, environment file and unit definitions. This branch
does not create or modify anything under `ops/`.

## Tests

```text
backend tracked/collected: 2755
backend passed: 2755
backend skipped: 0
frontend tests: 84 passed
ruff: PASS
frontend build: PASS
frontend typecheck: PASS
frontend lint: PASS
git diff --check: PASS
```

The closeout adds 15 deterministic backend tests over the previous 2740-test branch baseline.
The final full backend run completed in 266.13 seconds. No live-source smoke was repeated because the
closeout does not change network acquisition and the previously accepted four-source smoke remains
valid.

## Git

```text
branch: feat/spec016a-ingestion-runtime
design commit: b56f5a2
implementation commit: d5f242c57dfc5ec947572d9ad5ad80d02d9c0d14
closeout implementation commit: 809880ef95020c0214a2f93bf8cd3294a6dc4202
draft PR: https://github.com/bruppacherrodrigue-art/Kivou/pull/7
git status --porcelain: clean after report finalization commit
git diff --stat against origin/main before report finalization: 40 files changed, 4465 insertions, 28 deletions
```

The branch remains independently based on `origin/main`; PR #7 is open as a draft and targets
`main`. It was neither merged nor deployed.

## GitHub CI result

The code-bearing closeout head `809880ef95020c0214a2f93bf8cd3294a6dc4202` completed GitHub
Actions run `32253374215` successfully:

```text
backend job: PASS
frontend job: PASS
tracked backend tests: 2755 passed, 0 skipped
frontend tests: 84 passed
```

No production deployment, VPS access, SPEC-016 infrastructure modification, alert delivery, or
Hermes work occurred.

PRODUCTION INGESTION RUNTIME READY
