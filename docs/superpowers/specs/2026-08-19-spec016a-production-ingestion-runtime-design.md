# SPEC-016A Production Ingestion Runtime — Design

## Goal

Add one production-safe, one-shot command that composes Kivou's existing public-source
connectors, canonical normalization, durable persistence, France linkage, approved signal
engine, active customer ICPs, and existing feed. The runtime must be restartable and
idempotent, without changing signal, recency, billing, feed-safety, or alert semantics.

## Boundaries

- Base and target: `origin/main`; branch `feat/spec016a-ingestion-runtime`.
- No VPS access, deployment, `ops/` changes, alert delivery, Hermes, or frontend work.
- Research and benchmark modules are references only and are never imported by the runtime.
- Network smoke validation is bounded and separate from deterministic offline CI.

## Chosen architecture

Create `signals.ingestion`, an application package with a small CLI, source acquisition
adapters, an orchestrator, a pipeline composition service, and durable run/checkpoint
storage. Existing connector parsers and engine components remain authoritative.

The alternatives were rejected:

1. Local checkpoint files do not provide transactional durability or useful shared run audit.
2. Wrapping research scripts would make experimental entry points operational dependencies.
3. A queue/event-store architecture belongs to SPEC-018 and exceeds this runtime's scope.

## Processing flow

For each selected source, independently:

1. Start an `ingestion_run` using the previous durable checkpoint.
2. Apply the source-specific overlap and acquire a bounded source window.
3. Normalize through the existing SIMAP, BOAMP, DECP, or TED parser/mapping path.
4. Persist each normalized event/award atomically, independently of customer matching.
5. Resolve opportunity identity. France candidates are evaluated by the unchanged
   `signals.france.link.resolve_candidates()` and `unique_strong()` policy.
6. Run the existing understanding, Need Graph, matching, and recency components for every
   persisted active TargetICP. Materialize only when the existing matching result is `show`.
7. Record counters and diagnostics. Advance the checkpoint only after a complete safe source
   success. A source failure keeps its previous checkpoint while other sources continue.

`materialize_signal()` remains the sole signal persistence boundary. A narrow fact persistence
function is extracted from its existing fact/opportunity steps so awards remain durable even
when no active ICP matches. `materialize_signal()` reuses that function, preserving current
identity and revision behavior.

## Source behavior

- SIMAP: existing search cursor and publication fetch; published-date lookback; typed connector
  errors and bounded existing pagination.
- TED: existing page-number search and notice XML fetch; bounded publication-date query;
  polite bounded retry for typed transient/rate-limit failures.
- BOAMP: existing Opendatasoft date window/offset pagination and parser; add typed operational
  failures without changing payload or normalization behavior.
- DECP: add a minimal Opendatasoft client for the already-authoritative dataset and parser;
  date-window/offset pagination; no normalization changes.

Explicit `--since`/`--until` override checkpoint-derived windows. `--max-records` deliberately
limits acquisition and therefore does not advance a production checkpoint unless the adapter
can prove the selected window complete. `--dry-run` fetches and normalizes but writes neither
business facts nor checkpoints.

## Persistence and transactions

Alembic `origin/main` was verified at `0004_alerts_feedback_analytics` before design approval.
Migration `0005_ingestion_runtime` adds only:

- `ingestion_checkpoint`: one row per source with last successful window/cursor and run times.
- `ingestion_run`: one row per source attempt with status, bounded counters, error category,
  and checkpoint before/after.

Transactions are bounded to logical database operations, never remote calls. Each award can
commit safely before the next. Run audit updates and final checkpoint advancement are separate
durable operations. Opportunity conflicts are recorded, then the representation remains
separate; no existing opportunities are silently merged.

## Failure and concurrency behavior

The all-source orchestrator catches source-scoped typed failures, completes the remaining
sources, prints one structured summary per source, and returns non-zero if any source requires
operator attention. Retries are bounded and only apply to typed transient categories. Every
network request retains a finite connector timeout.

Application identity constraints make repeated and overlapping runs safe. The future host timer
should additionally use systemd non-overlap or `flock`; no distributed lock or daemon is added.

## Verification

Deterministic tests cover CLI dispatch, all four source paths, checkpoint success/failure,
idempotence, restart/resume, active versus draft ICPs, feed visibility, France late linkage,
explicit conflict preservation, partial rate-limit failure, and absence of alert side effects.
Migration upgrade tests run from `0004` to `0005`. Live source smoke tests are manually bounded,
use an isolated local database or dry-run, and are excluded from CI.

## Final closeout: new TargetICP backfill

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

Deterministic closeout tests prove facts-first/customer-second feed visibility, draft exclusion,
repeat idempotence without a new revision, deterministic representation choice, and the explicit
500-candidate truncation signal. The existing source tests additionally distinguish a supported
terminal BOAMP skip from a malformed/transient processing failure that retains the previous
checkpoint.
