# Provider reconciliation

Use this runbook when a provider mutation result is unknown. Never translate uncertainty into an ordinary retry.

1. Activate or retain the relevant breaker/hard stop when safety is uncertain.
2. Identify the Kivou `operation_ref`, kind, correlation, campaign/member refs, and state. Do not copy a raw request/response or lead address.
3. Confirm the operation is `RECONCILE_REQUIRED`. A lease expiry after a remote call means the outcome is unknown, not absent.
4. Reconstruct the desired request from durable Kivou state and use the existing typed campaign adapter reconciliation path. Do not use a generic HTTP method/path and do not call provider endpoints from an unapproved environment.
5. If provider absence is authoritatively proven, let the existing operation identity schedule its allowed retry. If provider effect is found, record the bounded result fingerprint and converge. If still uncertain, leave reconciliation required and create/retain a DLQ item after component exhaustion.
6. A risk-reducing `pause_campaign` remains allowed; never restore the unsupported per-lead pause mutation.

Verification: inspect campaign/member state, operation ledger, provider-event truth, incident state, and Policy control. A sent event after STOP remains SENT and becomes CRITICAL.

Rollback: no destructive rollback exists. Preserve the operation ledger and keep the breaker open until exact reconciliation.
