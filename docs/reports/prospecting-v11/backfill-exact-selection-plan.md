# BOAMP exact selection implementation plan

> For agentic workers: execute this approved bounded extension inline with TDD and a review checkpoint. No commit or deployment is authorized for this subtask.

**Goal:** Prioritize at most 100 explicitly selected, existing BOAMP events without altering the global backfill cursor or making any request-time provider call.

**Architecture:** Add an optional exact event-key selection to the existing administrative service and repeatable `--event-key` CLI option. Validate the whole selection before processing, bind its sorted identity set to the durable cursor by SHA-256, and apply it to both pending and fresh selections. Existing unscoped cursors remain compatible; changing a scoped selection requires a separate cursor file.

**Tech stack:** Existing Python, SQLAlchemy, Pydantic cursor model, pytest and the existing BOAMP client. No new dependency, migration or runtime HTTP route.

## Approved decisions

- `backfill_notice_facts(..., event_keys: tuple[str, ...] | None = None)` accepts 1–100 distinct exact BOAMP event keys when supplied; unknown or foreign-source keys fail before processing.
- `--event-key` may be repeated. No `--account-id` extension or fabricated pending entries.
- `selection_hash` is the SHA-256 of canonical JSON for the sorted key set. An existing nonempty unscoped cursor cannot acquire a scope, and an already scoped cursor cannot change or lose it.
- The original notice limit, durable pre-fetch checkpoints, cache policy and three-attempt ceiling remain unchanged. Dry-run neither fetches nor writes.
- Relevant staging event keys are resolved by a separate read-only signal → contract award → source-event lookup, not through the prototype's offline payloads.

## Execution checklist

- [x] In `tests/test_notice_backfill.py`, add regression coverage for exact selection despite lexically earlier unrelated events, dry-run safety, unknown/duplicate/oversized selections, compatible and incompatible resume, forged out-of-scope pending entries and the repeatable CLI option.
- [x] Run `PYTEST_DEBUG_TEMPROOT=/tmp uv run pytest -q -n 2 tests/test_notice_backfill.py` and record expected RED for missing `event_keys`/CLI behavior. Twelve new selection cases failed as expected; the first focused GREEN contained 28 passing tests.
- [x] In `src/signals/client_value/notice_backfill.py`, add `selection_hash` to `NoticeBackfillCursor`, exact selection validation and fingerprinting, filtered `_selected(..., event_keys=...)`, the optional service argument and CLI plumbing.
- [x] Run the same focused suite to GREEN, then BOAMP facts/snapshot/projection/ingestion regressions with at most two workers. Confirm no raw source payload appears in report/cursor and no runtime route changes. Final combined migration/audit/BOAMP/ingestion/company-service gate: 363 passed in 262.66 seconds, SQLite and local PostgreSQL enabled, journal `/tmp/kivou-v11-backend-migrations-boamp-final-20260913.log`.
- [x] Hand off exact CLI examples and logs to the parent for independent review before staging execution. Backend files frozen after this gate; the parent's concurrent identity-quarantine correction still requires its own final global validation.

## Review

Scope is limited to administrative selection. Hashes carry no note/contact content; the source-event keys are already the existing administrative report identity. The hash is a consistency guard, not authorization: the CLI remains operator-only. Ordinary application GET handlers are untouched. No data is deleted and no stored facts are overwritten.

Each resume repeats the complete exact-key set, even when `--limit` is smaller than that set. Explicitly linked consultation notices remain bounded dependencies under the existing extraction policy (at most three per primary notice); selection does not introduce a broader source search.
