# Dead-letter recovery

The acquisition DLQ stores refs, never executable payloads.

## Inspect

1. Run `uv run python -m signals.operations dead-letters`.
2. Select one opaque `dead_letter_ref` and verify its work type, attempt count, failure code, component, scope, and durable source-state ref.
3. Check current kill switch, READ ONLY, breaker, staleness, suppression/compliance, and Policy state. Unknown provider mutation must use runbook 04 first.

## Requeue

Use `DeadLetterRequeueService.requeue(dead_letter_ref, at=...)` only through approved operator automation with the registered typed component handler and `PolicyCircuitRequeueGuard`. The service reconstructs work from durable refs, rechecks safety, and invokes the component's original idempotency contract. Missing handler, stale work, hard stop, or breaker fails closed.

Never copy a payload into the DLQ, update status with SQL, bypass Policy, clear suppression, or replay a provider request blindly.

## Verify and resolve

Verify the original durable component state converged, then mark the same row RESOLVED through `OperationsStore.resolve_dead_letter`. History remains. A repeated recovery request returns the same row and does not duplicate business work.

Rollback: if reconstruction fails or state is uncertain, leave/recreate OPEN evidence through the same exhaustion identity and keep positive execution blocked.
