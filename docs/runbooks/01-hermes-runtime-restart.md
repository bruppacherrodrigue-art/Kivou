# Hermes runtime restart

Use this runbook only for the pinned Kivou supervisor boundary. It does not authorize outbound or a dependency upgrade.

## Before the restart

1. Record the deployed Kivou SHA, environment identity, current Policy control revision, and incident reference in the operator ticket.
2. Run `uv run python -m signals.supervisor health`. A mismatch against `v2026.8.18` / `e624e9fde561e1add9388384012b295fde669ade` is `NOT_READY`; do not download another Hermes revision.
3. Run `uv run python -m signals.operations readiness` and retain the bounded output.
4. If acquisition truth or provider outcome is uncertain, activate the kill switch using runbook 02 before restarting.

## Restart

Stop and start only the already-approved deployment service through the environment's service manager. This repository deliberately provides no production install/restart command and no systemd unit because no tested persistent Hermes entry point exists. Do not improvise one, run Hermes `main`, change the lock, upgrade skills, or expose production secrets.

## Verification

1. Run `uv run python -m signals.supervisor health` again.
2. Run `uv run python -m signals.operations health` and `uv run python -m signals.operations readiness`.
3. Verify Opportunity streams, OPEN incidents, DLQ rows, Policy revision, and any `RECONCILE_REQUIRED` provider operation are unchanged.
4. Execute only a SHADOW observation until the recorded runtime identity and supervisor heartbeat are healthy.

## Rollback

Restore the previously approved Kivou process artifact and the same Hermes pin. Never roll back the database or delete audit rows. Keep kill switch/READ ONLY active until the root cause is resolved explicitly.
