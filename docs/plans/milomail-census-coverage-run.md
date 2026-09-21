# Milo Mail zero-cost coverage implementation plan

Base: `68f0da0ac674b94c2a27e1ba036b53617d8cd007` (#280 squash merge).
Scope: operator diagnostics and aggregate evidence around the existing census;
no paid Apollo call, contact enrichment, Instantly mutation or deployment.

1. Add failing tests for a machine-readable `bootstrap` and `preflight --phase
   COVERAGE`: nine deterministic partitions, missing secrets and database
   reported without disclosure, and a zero-credit gate that rejects the
   documented one-credit organization-search operation before transport.
2. Implement those diagnostics in the current census CLI/readiness modules.
   Keep all default limits at zero and preserve the existing scoped permit
   mechanism. A zero-credit permit cannot authorize a positive-credit call.
3. Persist public MX evidence during COVERAGE using the existing detector and
   candidate cache, without contact enrichment or an Instantly path. Test that
   phase A reports Google Workspace and phase B reuses the observation.
4. Add failing tests for coverage reporting: distinguish Apollo's declared
   totals, traversed results, observed unique companies, partition overlap,
   truncation, verified contacts and optional rate-based extrapolation.
   Implement a privacy-safe aggregate report from persisted rows only.
5. Add a failing test for cache purge preserving suppression, permits and
   usage receipts. Extend the existing purge to organization-page snapshots
   when the run is complete or retention has elapsed.
6. Document exact bootstrap/preflight/A0/A1 commands and the present
   zero-credit incompatibility. Validate targeted and global tests, SQLite
   and disposable PostgreSQL migrations, Ruff, mypy, compilation, lockfile,
   secret scan and PR CI. No real Apollo run unless an account-specific
   zero-credit operation and an authorized database are both proved.

The official current-plan Apollo documentation prices organization search at
one credit per page. Since the existing nine-partition COVERAGE pipeline uses
that endpoint, A0 and A1 must remain blocked under this mission's zero-credit
limit. A future free-path change would need a separately verified operation
with equivalent coverage semantics; saved-account search does not cover
Apollo's prospect company database.
