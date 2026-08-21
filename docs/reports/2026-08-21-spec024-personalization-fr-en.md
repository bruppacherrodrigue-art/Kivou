# SPEC-024 — deterministic FR/EN personalization

Implementation base: `4241f7ac96943cafd4f2736035307727a8b82f66`.
The approved design was merged as that same main commit. The executable commit
is `148a90d072c9663726c5f25e8a2e765a9bae05bf`; executable CI run
`32452770971` succeeded.

## Contract

`PersonalizationService` accepts only a current `SEND` opportunity whose next
action is `prepare_campaign`. It owns one timezone-aware clock capture, rebuilds
the current public Decision Engine input with `decision-policy-v1`, and proceeds
only when the fresh pure result is `SEND`. Thus day 60 remains eligible and the
same historical SEND is rejected at day 61. It never records a second
`DECISION_RECORDED`.

Current public Contract Understanding and Need Graph are rebuilt from the
representative public award. The selected grounding is exactly `needs[0]`; no
needs raises `PersonalizationGroundingInsufficient` before Policy.

The renderer is offline deterministic templates only, with `fr` and `en` as the
only languages. It uses the existing recency claim doctrine, controlled Need
labels, one calibrated inference and one CTA. No LLM, provider, crawler,
campaign, or email is used.

`PersonalizationInput`, proposal, artifact, and Policy action fingerprints are
separate. Input snapshots contain no raw first name or email. A safe first name
may appear only inside a READY greeting; its semantic binding is a
domain-separated contact-personalization fingerprint.

## Persistence and workflow

Migration `0013_personalization` adds exactly one table,
`acquisition_personalization_artifact`. READY records hold bounded rendered
content and a `NEXT_ACTION_SET` event reference; POLICY_BLOCKED records hold
only PII-minimized identity/provenance and NULL rendered content. Policy
evaluation ownership is unique and artifacts are append-only.

An executable final transaction locks and revalidates the opportunity,
supplier, contact, company profile, public context, eligibility, Need Graph,
input and proposal before atomically appending
`NEXT_ACTION_SET(assess_campaign_compliance)` and persisting READY. State stays
`SEND`; `acquisition-state-v1` and existing EventTypes remain unchanged.

Completed replay occurs before any clock access. It reconstructs the original
Policy budget context from the immutable policy snapshot and stored remaining
budget, so unrelated later BudgetUsage does not invalidate replay. A policy
audit without an artifact requires a fresh evaluation ID. SHADOW/non-executable
Policy creates POLICY_BLOCKED without copy or workflow mutation.

## Validation

- Backend: 3325 passed, 0 skipped (local); Ruff and `git diff --check` passed.
- Frontend: 150 passed; build, typecheck and lint passed.
- Executable CI `32452770971`: backend and frontend SUCCESS.
- Offline EVAL corpus: `tests/fixtures/personalization_catalog_eval_v1.json`.

No live Apollo, Instantly, SMTP, LLM/provider, campaign, email, deployment, or
staging/production migration was performed.
