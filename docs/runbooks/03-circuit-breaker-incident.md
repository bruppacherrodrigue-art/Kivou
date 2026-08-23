# Circuit-breaker incident

## Triage

1. Run `uv run python -m signals.operations incidents` in the explicit environment.
2. Copy only `incident_ref`, type, severity, scope, and Policy control refs into the operator ticket. Do not copy customer/provider payloads.
3. HIGH or CRITICAL means the scope is blocked. ACKNOWLEDGED is still blocked; restart does not close it.
4. For COMPLAINT, COMPLIANCE_FAILURE, UNEXPECTED_TRANSPORT_TRUTH, or BUDGET_BREACH, keep human review and pause-required state. Do not wait for a percentage or auto-close.
5. For BOUNCE_RATE, verify the authoritative unique Step-1 sample: at least 20 and strictly more than 5%. Step 2 is not part of the denominator.

## Contain and investigate

Use runbook 02 for a critical/global stop. Use existing `pause_campaign` for risk reduction. Query only durable Kivou facts; provider dashboards, Hermes opinions, and raw customer content are not breaker authority.

## Resolve

Resolution is explicit through the tested `OperationsStore.acknowledge_incident` and `OperationsStore.resolve_incident` service boundary after a bounded operator review. Do not issue SQL updates or delete the row. Re-run health/readiness and a dry local Policy evaluation. Resolution does not restore autonomy; any later increase needs a separate approved control revision.

## Rollback

If the incident was resolved in error, open a new incident from the authoritative source fact and reapply the hard stop. Never rewrite the prior lifecycle.
