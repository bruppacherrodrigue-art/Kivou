# SPEC-019 — Policy Gateway implementation plan

Date: 2026-08-20
Branch: `feat/spec019-policy-gateway`
Base: `ea116a25d58bd5de9a80a607c22ad0c82bbd1b81`

## Execution rules

Each production behavior follows RED → GREEN → refactor. No executor, provider integration, customer mutation, deployment artifact, or migration beyond the approved two-table `0008_policy_gateway` is permitted.

## Task 1 — Corrected contracts and registry

1. Add failing contract tests for symbolic command validation, bounded dual-purpose approval grants, SHADOW target invariants, aware timestamps, Decimal/currency bounds, secret/hidden-reasoning guards, and optional validity.
2. Add failing registry tests covering all SPEC-017 commands, exact risk/scope metadata, and absence of callables.
3. Implement immutable contracts and the static metadata registry; run the focused tests.

## Task 2 — Pure policy evaluator

1. Add failing table-driven tests for autonomy, READ ONLY, kill switch, unknown command, compliance grants, evidence, budget, operational readiness, exact precedence, validity, and SHADOW counterfactual behavior.
2. Implement the pure `acquisition-policy-v1` evaluator without I/O, clocks, UUIDs, randomness, Hermes, or persistence.
3. Add and run a deterministic 1,000-evaluation measurement.

## Task 3 — Intent mapper

1. Add failing tests for validated SPEC-017 action mapping, canonical fingerprints, malformed payload rejection, and Hermes isolation.
2. Implement the bounded Kivou mapper; persist no raw arguments.

## Task 4 — Schema and migration 0008

1. Reconfirm `origin/main` and local Alembic head `0007_acquisition_event_store`, and absence of another 0008.
2. Add failing schema/migration tests for exactly `acquisition_policy_snapshot` and `policy_evaluation`, linear graph, constraints, fresh-to-head, 0007-to-0008, SQLite, PostgreSQL offline SQL, and unchanged prior tables.
3. Add the two Core tables and linear migration `0008_policy_gateway`; run focused migration tests.

## Task 5 — Durable controls

1. Add failing tests for append-only monotonic revisions, exact effective-snapshot selection, expired/future handling, emergency kill-switch dominance, no-snapshot failure, and restart continuity.
2. Implement the narrow snapshot store with append/select only; no default seed or mutation API.

## Task 6 — Retry-safe universal and opportunity audit

1. Add `POLICY_EVALUATED` tests first: old stream replay unchanged and the new event state/decision/retry/reference neutral.
2. Add failing audit tests for global rows, opportunity dual writes, deterministic event idempotency, same-ID replay, semantic conflict, fresh evaluations, both rollback directions, and optimistic-concurrency rollback.
3. Refactor SPEC-018 append internals to accept an existing transaction, preserving its public semantics.
4. Implement policy audit/store/gateway so evaluation ID exists before transaction and no executable decision escapes a failed audit.

## Task 7 — Security and isolation regression

1. Add tests proving secret/hidden reasoning rejection, bounded reasons/evidence/arguments/grants, Hermes absence, and no executor/Apollo/Instantly/Stripe/SMTP/shell imports or calls.
2. Run all policy/acquisition tests and Ruff; refactor only while green.

## Task 8 — Full verification and report

1. Run `uv run pytest -q`, `uv run ruff check .`, and `git diff --check`.
2. Run frontend tests, build, typecheck, and lint; require at least 84 tests.
3. Write the completed report with measured results, migration graph, changed files, diff stat, status, and explicit no-side-effect proof. Mirror all SPEC-019 reports to `/home/jaybe/projects/Kivou/docs/reports/`.

## Task 9 — GitHub draft PR and CI

1. Secret-scan and explicitly stage only SPEC-019 files; never use `git add .`.
2. Commit `feat(acquisition): add Kivou policy gateway`, push normally, and open/update a draft PR to `main`.
3. Wait for GitHub backend/frontend CI and record run ID/head SHA/results in the final report. Do not merge.
