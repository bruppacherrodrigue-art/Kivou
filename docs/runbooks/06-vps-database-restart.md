# VPS / database restart

This runbook validates persistence continuity; it does not authorize deployment or migration.

## Before

1. Record deployed SHA, environment identity, Alembic revision, latest Policy control revision, OPEN incident refs, DLQ refs, provider operations requiring reconciliation, and in-flight leases.
2. If continuity is uncertain, activate runbook 02.
3. Take the environment's approved backup/snapshot. Do not run destructive SQL, `DROP`, manual Alembic version updates, or rollback migrations.

## Restart

Use only the existing VPS/database service-manager procedure. Do not run application migrations as part of process import/startup and do not expose credentials to Hermes.

## Verify

1. Run `uv run python -m signals.operations health`.
2. Run `uv run python -m signals.operations incidents` and `uv run python -m signals.operations dead-letters` and compare refs/counts with the pre-restart record.
3. Verify kill switch/READ ONLY and OPEN breaker state survived.
4. Reconstruct workers against the same database. Expired leases follow their component rules; unknown remote results reconcile first.
5. Confirm no duplicate Opportunity event, conversion milestone, response finalization, learning selection/application, provider mutation, or email was created.

Rollback: restore the approved process artifact first. Restore a database backup only under the separate disaster-recovery authority; never hide a transport event by rolling local truth backward.
