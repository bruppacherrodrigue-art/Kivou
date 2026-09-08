# Discovery token quota

Approved scope: backend allocation, landing materialization, feed ordering,
account-scoped QA reconciliation and focused backend tests. No frontend,
migration, deployment, commit, provider enrichment or real email work.

## Contract

- The persisted Discovery grant ledger is authoritative for access and both
  counters. New token cohorts allocate the bait first, then at most two others.
- Serialize allocation on the account row. Reloads, confirmation and token
  replay preserve granted membership. Later better matches cannot replace it.
- Select distinct source procedures; fall back to a source notice identifier
  in its source namespace. Never deduplicate by lot, award or opportunity key.
  Missing public grouping identifiers exclude a new candidate.
- Require an actual object and holder name, rejecting identifier-only names.
  Check existing representations and existing matching; do not invent facts
  or call enrichment providers. Preserve the existing 30-day bait policy.
- Spread bounded candidate selection across procedures before applying the
  existing fit ranking. Keep persisted/materialized work bounded and show an
  honest partial cohort when insufficient eligible candidates exist.
- Order existing granted rows first, then locked rows by fit, before pagination.
  Keep existing locked-card and locked-drawer payload contracts.
- Preserve historical non-QA grants. A full allocation without the bait is an
  explicit legacy conflict, never an implicit fourth grant or silent eviction.

## Implementation

1. Add RED regressions for immediate bait-inclusive counters, three-procedure
   allocation, many recent lots, numeric holders, ranking, replay, ownership,
   legacy conflicts and account-lock serialization.
2. Centralize allocation in `billing/discovery.py`; remove implicit landing
   access in `billing/access.py` and `accounts/service.py`. Allocate inside
   the landing transaction and share filling with signals/dashboard routes.
3. Update `ingestion/backfill.py` to qualify a bounded, procedure-diverse pool
   and use existing fit ranking. Update `feed/query.py` and signals routing
   for grant-first ordering before pagination.
4. Add `qa/discovery_grants.py`: explicit account ID, QA-marker guard, default
   read-only dry-run, before/after grant-to-procedure audit and explicit apply.
   Only this opt-in QA path may replace allocations; it must preserve the bait.
5. Run focused GREEN tests with `--maxfail=1 --tb=short`. PostgreSQL concurrency
   cases reuse the existing `KIVOU_TEST_POSTGRES_DSN` fixture and skip locally
   when absent. Do not run server migrations or reconcile a real account.

Planned production files: `billing/discovery.py`, `billing/access.py`,
`accounts/service.py`, `ingestion/backfill.py`, `feed/query.py`,
`api/routes_signals.py`, `api/routes_dashboard.py`, `qa/discovery_grants.py`.
Focused tests: `test_discovery_cohort.py`, attribution landing, ingestion
backfill and billing paywall. Existing frontend counters need no new API field.

## Known QA data limitation

The supplied read-only audit finds one BOAMP procedure with many named lots
and two older DECP notice groups whose current holder names are numeric IDs.
Those DECP candidates qualify only if an existing representation supplies a
real holder name and the existing matching policy admits them. Three grants
are not guaranteed by the candidate count alone.

## QA audit supplied by parent/Hume (read-only, 2026-09-07)

Account `acc_JqYSbhwmDQVGNiIroQkL_g` has zero persisted Discovery grants.
Bait `490b27c93a8def24298e98bfde67571d211c1179` is the only eligible procedure.
The geographic/CPV/30-day audit found three procedure groups, not 22 independent gifts:
20 named BOAMP lots share procedure `c382e651-045b-49a2-be21-58be5c7a0a66`
and notice `26-84973`. Neighbours from that procedure are rejected as
`SAME_PROCEDURE`. DECP notice fallbacks `2026TV2` and `2026PA431055` are
rejected as `WINNER_NAME_UNRESOLVED`: three SIRETs have no genuine company,
research or enrichment names. Twelve winner jobs are pending, with zero attempts.
Expected allocation is honestly **1/3**, with two lifetime places remaining.
No enrichment provider is invoked by allocation or reconciliation.

## Explicit reconciliation recipe (not executed)

`python -m signals.qa.discovery_grants --account-id <approved-QA-account>`
uses the existing `DATABASE_URL` and performs a read-only dry-run. Review its
before allocation, proposed grants, public procedure references, rejection codes
and truncation indicator. Applying requires the same explicit account and
`--apply --expected-audit <audit_token>` from that reviewed preview. Any changed
audit or missing QA marker refuses the write. No schema migration is performed.
Only the named account's ledger is replaced; bait identity must be preserved.
All ordinary token reloads preserve existing grants, including legacy conflicts.
Three is a lifetime ceiling, never a monthly reset, irrespective of UI wording.

UUID procedure references are global across sources; non-UUID identifiers are
namespaced by country/source. Notice aliases prevent separate lots being offered
from one notice. Missing references fail closed; no award, lot or opportunity
key is used as a procedure identity. The landing scan interleaves procedure groups
before its 40-candidate bound and materializes at most five rows, including locked
previews. Existing band/normalized-score/date ordering ranks qualified candidates.

## Executable handoff and focused regressions

Use `PYTHONPATH=src python -m signals.qa.discovery_grants --account-id <QA-account> --dry-run`
with the existing database URL supplied securely as `DATABASE_URL`. The command
performs no migrations. Omitting both mode flags is also read-only. After reviewing
that JSON, the sole write form is the same command with
`--apply --expected-audit <audit_token>` instead of `--dry-run`.

Output fields are `account_id`, `as_of`, `dry_run`, `audit_token`, `before`, `after`,
`proposed_grants`, `bait_preserved`, `eligible_procedures`, `remaining`, `candidates`
and `scan_truncated`. Each proposed grant carries `signal_key`, `opportunity_key`
and public `procedure_references`; the resulting `after.grants` additionally carries
`granted_at`. Dry-run's `after` remains the unchanged current allocation.

Frontend/QA mapping: compare unlocked API card `signal_id` values to audit
`after.grants[].signal_key` after apply, or `proposed_grants[].signal_key` before
apply. Compare `dashboard.plan.opened` and
`billing/status.discovery.granted_signal_count` to `after.used`. No new public
frontend API field or client-side selection is required. This handoff is for
Noether; backend tooling exposes no direct agent-message channel.

Malformed canonical title representations are excluded with
`SIGNAL_OBJECT_UNRESOLVED`, without preventing a valid named alternative from
qualifying. Valid canonical awards retain prospect policy's CPV object fallback.
The focused tests include a sixty-lot starvation case, zero-DML preview, reviewed
QA-only replacement, stale-audit rejection, and three PostgreSQL concurrency cases.
The PostgreSQL cases use the existing `KIVOU_TEST_POSTGRES_DSN` isolated-schema
fixture, not a new service, and skip when that variable is absent.
