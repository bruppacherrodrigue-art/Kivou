# Kill switch and READ ONLY

This is the emergency positive-mutation stop. It does not erase transport truth or suppression.

## Activate

1. Ensure `KIVOU_DATABASE_URL` identifies the intended environment; confirm `KIVOU_ACQUISITION_ENVIRONMENT` explicitly says `STAGING` or `PRODUCTION`.
2. Append the safety control through the tested Kivou path:

   `uv run python -m signals.operations activate-kill-switch --reason-code OPERATOR_EMERGENCY_STOP`

3. Record the returned control revision in the incident ticket.

The command converges when SHADOW + kill switch + READ ONLY is already authoritative. It neither contacts a provider nor pauses remotely by itself.

## Verify

1. Verify `schedule_campaign` and `reallocate_volume` are denied by Policy.
2. Verify campaign positive-operation and Step-2 guards fail closed.
3. Run `uv run python -m signals.operations incidents`; active campaigns with safety incidents must be pause-required.
4. Confirm `pause_campaign`, provider reconciliation, and `generate_weekly_report` remain available through their existing risk-reduction/read-only paths.
5. Reconcile every unknown provider mutation before any retry. If transport reports a send, preserve SENT and open a CRITICAL incident.
6. Inspect DLQ with `uv run python -m signals.operations dead-letters`.

Do not clear suppression, modify provider history, send a test email, or reactivate campaigns automatically.

## Reopen / rollback

There is no automatic reopen. Resolve root cause and each incident through the approved `OperationsStore.resolve_incident` operator integration, retain the incident rows, then create a separately approved Policy control revision. SPEC-031 never performs the autonomy upgrade. If verification fails, keep the hard stop and escalate.
