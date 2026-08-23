# Staging-to-production promotion

SPEC-031 readiness is evidence, not promotion authority.

## Required evidence

1. Exact Kivou SHA and Hermes pin are approved; `uv run python -m signals.supervisor health` matches the committed lock.
2. `KIVOU_ACQUISITION_ENVIRONMENT` is explicit and environment-specific. Staging and production use separate databases, secrets, provider accounts/mailboxes, operator controls, and generic administrator credentials are forbidden.
3. H-A, H-B, and H-C are READY. H-D evidence is real, not inferred. H-E has configured budgets/caps/breakers/mailboxes/provider prerequisites and no critical incident. H-F joins structurally. H-G remains bounded by SPEC-029.
4. Kill switch and READ ONLY have been exercised in staging across Policy, campaign mutations, Step 2, learning application, reporting, and risk reduction.
5. Historical evaluation and SHADOW comparison are retained. Cost incompleteness, missing retention, or unconfigured threshold is a blocker, not zero.

## Promotion

Promotion requires an explicit operator/deployment approval and a new Policy control revision. SPEC-031 never auto-upgrades autonomy. Start at the approved lower mode; do not enable ADAPTIVE_SCALE merely because readiness says it could be safe. Global volume, country/mailbox/campaign caps, budgets, and allowlists cannot be broadened by Hermes.

## Verification

Run internal health/readiness, verify shallow public health exposes no details, inspect incidents/DLQ, and prove no existing campaign was changed. Perform no test send as part of this runbook.

## Rollback

Monotonically downgrade authority, activate runbook 02 where needed, stop the approved process, restore the prior application artifact, and preserve all database truth. Never auto-reactivate after rollback.
