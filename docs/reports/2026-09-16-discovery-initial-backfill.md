# Discovery initial backfill — implementation report

Date: 2026-09-16
Starting SHA: `1711b51833bcc064f5b97e42246fca938229ff86`

## Demonstrated root cause

The pre-fix reproduction persisted four valid awards before account creation,
then created a new Discovery account and activated its target profile. The
activation materialized matching signals but created **zero** rows in
`discovery_signal_grant`; the regression test failed with `0 != 3` before any
feed read.

The chain had three independent gaps:

1. Discovery correctly declared `granted_signals=3`, `history_days=0`, but
   target activation never allocated the three named grants.
2. The only allocator was a side effect of `GET /signals`; it scanned only the
   default `freshness=new` view. `GET /dashboard` did not invoke it, so Today
   remained empty and displayed 0/3.
3. Dashboard priorities also used the default freshness view, so an older
   permanent grant could remain absent from Today even though detail access
   correctly treated named grants as age-independent.

`history_days=0` was therefore not the named-grant access failure itself. It
made the missing activation-time backfill visible: no persistent grant existed
to bypass the ordinary history window.

## Implemented behavior

- First active-profile confirmation scans existing account-owned matches with
  `freshness=all`, independently of the plan history window.
- It rejects missing title, unusable holder, missing evidence, missing usable
  date, invalid date and non-`show` matching decisions.
- It ranks deterministically by match band and score, current freshness,
  documentary completeness, commercial timing, event date and signal ID.
- It allocates at most three permanent, distinct grants while holding the
  owning account row lock; conflict-safe inserts preserve retry idempotence.
- An ordinary edit of an already confirmed active profile does not trigger a
  second historical scan or a new quota.
- Later production ingestion invokes the same reconciliation and fills only
  remaining lifetime slots.
- `/signals` is now read-only with respect to grants.
- Today reads permanent Discovery grants across freshness; the normal
  new/week counters retain their factual windows.
- Dashboard/API/UI distinguish signals **assigned** from paid signal details
  **viewed this month**, and explain 0/3 or partial availability honestly.
- A dry-run-by-default catch-up command is available at
  `python -m signals.billing.discovery_backfill`; mutation requires `--apply`.

## Fresh-account journey proof

Local HEAD-schema journey using four persisted candidates before signup:

- grants before activation: 0;
- grants immediately after activation: 3;
- two consecutive `GET /dashboard`: HTTP 200, same three signal IDs;
- Today priorities: 3;
- `GET /signals?view=history`: 4 rows, 3 unlocked and 1 locked;
- all three unlocked details: HTTP 200 with non-empty public evidence;
- fourth detail: still locked.

A separate regression proves that three 45-day-old candidates are assigned
despite `history_days=0`, appear in Today and the history-backed Signals tab,
while the ordinary default-new API view remains empty. The plan does not gain
free access to the rest of history.

## Production catch-up dry-run

Executed on 2026-09-16 in a PostgreSQL transaction explicitly set to
`READ ONLY`. No branch deployment and no `--apply` occurred.

- active accounts considered: 16;
- Discovery accounts: 16;
- existing distribution: 14 at 0/3, 0 partial, 2 at 3/3;
- 0/3 accounts with at least one proposed grant: 9;
- proposed grants: 23;
- proposed distribution across the fourteen 0/3 accounts:
  - 5 accounts: zero;
  - 2 accounts: one;
  - 0 accounts: two;
  - 7 accounts: three;
- truncated candidate scans: 0.

A second read-only post-check found the same six pre-existing grant rows:
fourteen accounts at 0/3, two at 3/3, and none above three. No production data
was changed.

## Validation

- Backend affected suites: `95 passed, 1 deselected`.
- Frontend focused suites: `27 passed`.
- Focused Playwright three-tab visual flow: `6 passed`.
- Ruff: passed on every changed Python file.
- TypeScript typecheck: passed.
- ESLint: passed.
- Git whitespace validation: passed.
- Alembic head: `0065_chief_of_staff`, unchanged.

## Files

Backend:

- `src/signals/billing/discovery.py`
- `src/signals/billing/discovery_backfill.py`
- `src/signals/api/routes_icp.py`
- `src/signals/api/routes_signals.py`
- `src/signals/api/routes_dashboard.py`
- `src/signals/dashboard/service.py`
- `src/signals/ingestion/pipeline.py`

Frontend:

- `frontend/src/api/types.ts`
- `frontend/src/layouts/AppShell.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/SignalsFeed.tsx`
- French/English copy, focused tests, harness and visual fixtures.

Tests and documentation:

- `tests/test_discovery_initial_backfill.py`
- `tests/test_discovery_backfill_cli.py`
- affected billing/dashboard regression tests
- design and implementation plan for this correction
- this implementation report

No migration was added: the existing `discovery_signal_grant` primary key and
permanent opportunity audit fields already model the required lifetime grants.
