# Instantly campaign and winner requeue design

## Objective

Make assisted Instantly campaign creation conform to the current API v2 contract, and make holder-family enrichment requeue a terminal winner job as a fresh pending attempt without relaxing the lifecycle constraint.

## Campaign contract

The assisted campaign keeps one sequence and one email step. The schedule uses `Europe/Belgrade` because Instantly's current v2 timezone enum contains none of `Europe/Zurich`, `Europe/Berlin`, `Europe/Rome`, or `Europe/Madrid`; Belgrade observes the same CET/CEST clock as Zurich. The single step carries `delay: 0`, required by the v2 schema even though there is no following step.

Validation uses a real empty campaign: create it with the production key and configured sender, verify the provider response, then delete it. No lead is attached during contract validation.

## Winner enrichment lifecycle

The database constraint correctly defines `pending` as an unstarted attempt: `attempt_count=0`, `started_at IS NULL`, and `finished_at IS NULL`. Requeueing a `partial`, `completed`, or `failed` job therefore resets those lifecycle fields, clears its claim and error, and sets a fresh queue timestamp. The constraint remains unchanged.

## Isolated delivery test

After deployment, create a separate diagnostic campaign containing only `rodrigue.bruppacher@gmail.com`, import that one fictitious lead, wait for verification, activate only if accepted, and confirm provider state. No `prospect_target` row and none of the 21 approved targets is read or mutated by this test flow.
