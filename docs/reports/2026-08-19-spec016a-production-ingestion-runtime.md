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
  orchestration pipeline, failure isolation, and persisted France sibling lookup.
- `signals.connectors.decp.client` and `signals.connectors.decp.errors`: minimal public
  Opendatasoft acquisition and typed operational failures around the unchanged DECP parser.
- `signals.connectors.boamp.errors`: typed BOAMP operational failures; normalization is unchanged.
- `signals.persistence.materialization.persist_award_facts()`: the existing fact/opportunity
  persistence steps exposed independently from customer matching.
- Alembic `0005_ingestion_runtime`: additive `ingestion_checkpoint` and `ingestion_run` tables.
- Deterministic ingestion tests: CLI, four-source dispatch, migration, checkpoints, partial
  failure, idempotence, restart, linkage/conflict, TargetICP materialization, and feed E2E.

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

## Operational contract for SPEC-016

Application command to schedule after merge:

```bash
python -m signals.ingestion run
```

Contract:

```text
WorkingDirectory: checked-out Kivou application release root
Environment: KIVOU_DATABASE_URL only (plus normal process PATH/Python environment)
Process model: one shot; exit after one bounded all-source cycle
Success: exit 0 only when all four source outcomes are successful
Failure: exit 1 after all selected sources have been attempted
Host lock: systemd non-overlap or flock -n /run/kivou-ingestion.lock
Timeout: 45 minutes initially; tune from measured production duration, never infinite
Alerts: separately scheduled `python -m signals.alerts`; never chained from ingestion
```

Suggested systemd `ExecStart` application portion:

```bash
/usr/bin/flock -n /run/kivou-ingestion.lock python -m signals.ingestion run
```

SPEC-016 owns the actual interpreter path, working directory, timer units, and environment file.
This branch intentionally does not modify `ops/`.

## Closeout design — new TargetICP backfill/materialization

The current application creates or activates a TargetICP without evaluating facts that were
persisted before that customer existed. Waiting for a public source overlap to replay an award
does not satisfy the Discovery onboarding requirement.

The approved closeout adds a synchronous, bounded application service invoked after an API
create/update has committed an active TargetICP. It reads persisted opportunity
representations only; it performs no network acquisition and changes no public fact. Candidates
are limited to publications that can still pass the TargetICP's existing
`maximum_signal_age_days` hard filter, ordered newest first, and capped at the existing feed
candidate ceiling of 500 opportunities. This SQL preselection is only a resource bound:
`MatchingEngine.match()` remains the sole authority, and only its existing
`decision == "show"` result may be materialized.

One deterministic representative is evaluated per stable `opportunity_key`, preferring a
customer-nameable representation and then a stable award key. This prevents two linked source
representations from alternately rewriting one logical signal on repeated backfills. The
existing feed sibling-name fallback remains unchanged.

The service returns a structured count and an explicit `truncated` flag when more than 500
eligible-window opportunities exist. Truncation is never presented as complete success: it is
logged for operator attention and documented as the current MVP capacity boundary. The
operation is safe to repeat because `materialize_signal()` retains the existing
`(opportunity_key, target_icp_id)` identity and content-fingerprint revision semantics.

Draft TargetICPs return without evaluating candidates. Active creation and draft-to-active
updates invoke the service after the TargetICP transaction commits, so a materialization
failure cannot roll back or corrupt the customer profile. No billing entitlement or alert
delivery path participates.

Deterministic closeout tests will prove facts-first/customer-second feed visibility, draft
exclusion, repeat idempotence without a new revision, deterministic representation choice, and
the explicit 500-candidate truncation signal. Existing source tests will additionally distinguish
a supported terminal BOAMP skip from a malformed/transient processing failure that retains the
previous checkpoint.

## Tests

```text
backend tracked/collected: 2740
backend passed: 2740
backend skipped: 0
frontend tests: 84 passed
ruff: PASS
frontend build: PASS
frontend typecheck: PASS
frontend lint: PASS
git diff --check: PASS
```

## Git

```text
branch: feat/spec016a-ingestion-runtime
design commit: b56f5a2
implementation commit: d5f242c57dfc5ec947572d9ad5ad80d02d9c0d14
draft PR: https://github.com/bruppacherrodrigue-art/Kivou/pull/7
git status --porcelain: clean after report finalization commit
git diff --stat against origin/main: 34 files changed, 3556 insertions, 25 deletions
```
