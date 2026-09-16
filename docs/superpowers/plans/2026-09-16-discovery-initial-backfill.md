# Discovery initial backfill implementation plan

> Execute on `fix/discovery-initial-backfill`, based on
> `1711b51833bcc064f5b97e42246fca938229ff86`. Do not deploy and do not run an
> applying production catch-up.

## Task 1: Capture the regression in backend tests

**Files:**
- Create: `tests/test_discovery_initial_backfill.py`
- Reuse fixtures from: `tests/test_ingestion_backfill.py`, `tests/feed_helpers.py`

1. Persist candidate awards before account creation.
2. Create and confirm an active Discovery target through the HTTP API.
3. Assert the desired three persisted grants, stable reload, detail/evidence,
   fourth locked, dashboard/feed coherence and account isolation.
4. Add two/zero candidate, profile-edit, paid-account and concurrency cases.
5. Run the new test file and preserve the pre-fix failure as reproduction
   evidence.

## Task 2: Implement deterministic, atomic Discovery reconciliation

**Files:**
- Modify: `src/signals/billing/discovery.py`
- Modify if needed: `src/signals/feed/query.py`

1. Add a read-only candidate preview that scans current account-owned matches
   with `freshness="all"`, independently of plan history.
2. Bulk-read evidence counts and reject incomplete, unnamed, unproved or
   undated candidates.
3. Rank by fit band/score, freshness, documentary completeness, commercial
   date and signal key.
4. Serialize grant allocation on the account row (SQLite no-op write,
   PostgreSQL `FOR UPDATE`) and insert no more than the remaining lifetime
   slots.
5. Run the focused tests until green.

## Task 3: Wire activation and future ingestion

**Files:**
- Modify: `src/signals/api/routes_icp.py`
- Modify: `src/signals/ingestion/pipeline.py`
- Modify: `src/signals/api/routes_signals.py`

1. Reconcile after first activation only: active creation, draft-to-active
   transition, or confirmation of a provisional landing profile. Never rescan
   the old corpus on an ordinary active-profile edit.
2. Carry `account_id` through active ingestion targets and reconcile after
   materialization in the same transaction.
3. Remove the old fresh-only request-time grant generator from the signals
   route.
4. Add retry/later-ingestion tests and run only the affected backend suites.

## Task 4: Make dashboard and UI semantics honest

**Files:**
- Modify: `src/signals/dashboard/service.py`
- Modify: `src/signals/api/routes_dashboard.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/layouts/AppShell.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/pages/SignalsFeed.tsx`
- Modify focused frontend tests and translations as required.

1. Build Today priorities from assigned Discovery grants across freshness while
   retaining factual new/week counters.
2. Expose separate `assigned` and `opened_this_month` fields in plan summary.
3. Label the Discovery sidebar count “signaux attribués”.
4. Show honest zero/partial progress in Today and Signals, never “Vous êtes à
   jour” for a newly underfilled Discovery account.
5. Run focused Vitest tests and frontend typecheck/lint for touched files.

## Task 5: Add the safe existing-account catch-up command

**Files:**
- Create: `src/signals/billing/discovery_backfill.py`
- Create: `tests/test_discovery_backfill_cli.py`

1. Enumerate active Discovery accounts with fewer than three grants.
2. Default to read-only JSON report; require `--apply` for mutation.
3. Make retries idempotent and report totals plus per-account proposed grants.
4. Prove dry-run performs zero writes and apply never exceeds three.

## Task 6: Verify and deliver

1. Run focused backend and frontend tests, Ruff, frontend typecheck and the
   relevant architecture/migration guards.
2. Run a complete fresh-account proof and record response/grant identities.
3. Run the catch-up CLI in read-only mode against production and retain only
   aggregate/non-secret evidence. Do not apply.
4. Review the diff for paid-plan and cross-account regressions.
5. Commit once, push the branch, open a PR, and report base SHA, root cause,
   files, migrations, test evidence, dry-run totals, final SHA and PR URL.
