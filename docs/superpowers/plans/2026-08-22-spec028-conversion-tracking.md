# SPEC-028 conversion tracking implementation plan

> Execute on `feat/spec028-conversion-tracking` after the frozen design commit
> `31b6c8c`. Use focused red/green tests per task and run the full repository
> suites once for the executable candidate.

**Goal:** Add an offline, first-party, immutable campaign-to-click-to-revenue
attribution ledger without changing provider tracking, payment authority, or
the acquisition state/EventType vocabulary.

**Architecture:** A focused `signals.conversion` package owns an authenticated
opaque token, two-table append-only ledger, local milestone reconciliation, and
an explicit retention worker. Existing auth, ICP, billing-webhook, and campaign
envelope boundaries call narrow conversion methods inside their current
transactions. No new network client or automatic worker is introduced.

**Stack:** Python 3.12, Pydantic v2, SQLAlchemy Core, Alembic, FastAPI, pytest.

---

## Task 1: Freeze token and milestone domain contracts

**Files:**

- Create `src/signals/conversion/__init__.py`
- Create `src/signals/conversion/contracts.py`
- Create `src/signals/conversion/token.py`
- Test `tests/test_conversion_token.py`

Write red tests for deterministic issue/verify, retained key versions, expiry,
tamper rejection, no PII, and closed milestone/Money invariants. Implement only
the canonical keyed token/fingerprint contract needed to pass them.

## Task 2: Add the exact two-table persistence head

**Files:**

- Modify `src/signals/persistence/schema.py`
- Create `src/signals/persistence/migrations/versions/0019_conversion_tracking.py`
- Create `tests/test_conversion_tracking_migration.py`
- Modify current-head expectations in existing migration tests

Start with failing schema/migration tests. Add exactly
`acquisition_conversion_journey` and `acquisition_conversion_event`, with a
linear `0018_response_intelligence -> 0019_conversion_tracking` graph,
PostgreSQL-compatible constraints, Core parity, downgrade/re-upgrade, and no
PII columns.

## Task 3: Implement click and signup attribution TDD

**Files:**

- Create `src/signals/conversion/store.py`
- Create `src/signals/conversion/service.py`
- Create `tests/test_conversion_attribution.py`

Test event identity, duplicate click convergence, deterministic last eligible
click, 30-day eligibility, same-timestamp tie-break, immutable one-account
journey, forwarded-token semantics, crash/replay, and file-backed concurrent
signup. Implement transaction-only store/service methods; no route yet.

## Task 4: Add the fixed first-party HTTP boundary

**Files:**

- Create `src/signals/api/routes_attribution.py`
- Modify `src/signals/api/app.py`
- Modify `src/signals/api/config.py`
- Modify `src/signals/api/routes_auth.py`
- Modify `.env.example` only for empty variable names if required
- Create `tests/test_conversion_attribution_api.py`

Test fixed redirect, no redirect input, HttpOnly/Secure/SameSite/path/max-age,
no-store/no-referrer, bad-token behavior, token granting no auth, signup consume
and cookie clear. Add fail-closed key/base-url configuration and bind signup in
the existing account transaction.

## Task 5: Implement product and billing milestone reconciliation

**Files:**

- Create `src/signals/conversion/milestones.py`
- Create `src/signals/conversion/worker.py`
- Modify `src/signals/api/routes_icp.py`
- Modify `src/signals/billing/webhooks.py`
- Create `tests/test_conversion_milestones.py`
- Extend focused billing/ICP route tests

Test exact activation, active-known-plan payment, monthly/founding/unknown MRR,
duplicate/out-of-order observations, M1/M2 at 30/60 days, scheduled cancel and
past-due non-churn, actual canceled churn, monotonic acquisition outcomes, and
explicit-worker-only behavior. Reconcile only durable local facts in existing
transactions; never call Stripe.

## Task 6: Add the smallest campaign CTA transport slot

**Files:**

- Modify `src/signals/campaigns/envelope.py`
- Modify `src/signals/campaigns/contracts.py`
- Modify `src/signals/campaigns/service.py`
- Modify `src/signals/campaigns/worker.py` only if exact lead reconstruction needs it
- Create/extend `tests/test_campaign_envelope.py`
- Create `tests/test_conversion_campaign_boundary.py`

Test that approved CTA prose remains byte-exact, the Kivou-owned URL is a
separate line, is in the envelope/action fingerprint, rejects arbitrary hosts,
keeps provider tracking false, and cannot be produced without attribution
configuration. Derive the link only from immutable campaign/member/opportunity
facts; no Hermes or provider input.

## Task 7: Prove replay, privacy, and architectural boundaries

**Files:**

- Create `tests/test_conversion_replay_concurrency.py`
- Create `tests/test_conversion_pii_architecture.py`
- Create `tests/fixtures/conversion_tracking_eval_v1.json`

Seed unique PII/secret/provider markers and prove absence from conversion rows,
acquisition events, errors, and logs. Exercise crash positions and concurrent
milestone attempts. Assert no provider/Stripe/LLM clients, no worker autostart,
no SPEC-029 allocator, and no SPEC-030 dashboard dependency.

## Task 8: Create and verify the executable artifact

Run targeted conversion/campaign/billing/acquisition tests, then exactly one
full local executable validation:

```bash
uv run pytest -q
uv run ruff check .
git diff --check
cd frontend && npm test -- --run && npm run build && npm run typecheck && npm run lint
```

Require backend above 3880, only the two existing Stripe smoke skips, frontend
at least 262, and no network. Commit runtime/tests/migration/config as the
executable SHA.

## Task 9: Draft PR, CI, and docs-only closeout

Push the branch, open one DRAFT PR titled
`feat(acquisition): implement conversion tracking`, and wait for executable CI.
After it is green, add only
`docs/reports/2026-08-22-spec028-conversion-tracking-implementation.md`, commit
the docs-only closeout, and run/wait for final-head CI. Verify executable-to-
final-head is report-only, PR remains draft/unmerged, migration head is linear,
and repository status is clean.

