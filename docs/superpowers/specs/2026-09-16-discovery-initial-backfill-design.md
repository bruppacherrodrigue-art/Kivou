# Discovery initial signal backfill design

**Date:** 2026-09-16
**Base:** `origin/main` at `1711b51833bcc064f5b97e42246fca938229ff86`

## Problem and demonstrated chain

Discovery advertises three permanent named grants, but target activation only
rematerializes persisted opportunities. The grant writer is currently called
later, as a side effect of `GET /signals`, and it only scans the default
`freshness=new` feed. `GET /dashboard` never performs that write, so a newly
confirmed account can remain at 0/3 with an empty Today view even though its
active target owns valid materialized signals.

`history_days=0` is not itself the access rule for a named Discovery grant:
`FeedAccess.is_unlocked` opens persisted grants regardless of age. It does,
however, make a future-right interpretation especially visible. The missing
operation is an activation-time selection and persistence of real grants,
independent of the ordinary plan history window.

## Product invariants

- A Discovery account has one lifetime budget of three named signal grants.
- Profile creation, confirmation, edits, retries and ingestion never reset that
  budget. Editing an already confirmed active profile does not rescan the old
  corpus for its unfilled slots; only later acquisitions may complete them.
- The initial selection may inspect already persisted, account-owned matches
  outside the plan's normal history window; it exposes only the selected grants,
  not the complete history.
- A candidate must belong to a current active target revision, have an
  exploitable holder, a non-empty contract object, a source URL, a factual
  commercial date and at least one persisted evidence anchor.
- Candidates are ordered deterministically by ICP fit, current freshness,
  documentary completeness, commercial timing and finally stable signal key.
- The account row is locked before the grant count is read. The existing
  `(account_id, signal_key)` primary key prevents duplicate names; the account
  lock prevents two different concurrent candidates from exceeding three.
- Fewer than three candidates are granted immediately. Later ingestion invokes
  the same reconciliation after materialization and fills only the remaining
  lifetime slots.
- Paid-plan access and history windows are unchanged.

## Integration

1. A shared billing-domain service previews/ranks eligible candidates and
   persists at most the remaining Discovery slots.
2. The first target activation calls it after rematerialization, in the same
   transaction. This includes confirmation of a provisional landing profile,
   but excludes ordinary edits of an already confirmed active profile.
3. Ingestion calls it after each successful account-specific materialization,
   in the same transaction, so retry cannot leave a durable signal without its
   eligible grant.
4. `GET /signals` stops writing grants entirely; both `/signals` and
   `/dashboard` become readers of the same persisted grant set.
5. Today uses the three named Discovery grants as its priority pool even when a
   selected grant is older than the normal “new” view. Weekly/new counters keep
   their factual time windows.
6. API/UI counters name Discovery grants as **assigned**, never as monthly views.
   Partial and zero states explain that Kivou is preparing the remaining slots.

## Existing-account catch-up

A rerunnable CLI is dry-run by default and reports Discovery accounts below the
limit, existing grant count, eligible count and proposed signal IDs. Mutation
requires an explicit `--apply`. The production deliverable runs only the
read-only mode; no apply and no deployment are part of this change request.

## Schema

No migration is required. The existing permanent grant table already carries
the correct lifetime identity and uniqueness constraint; concurrency is added
by locking the owning account row before count-and-insert.
