# Milo Mail SHADOW census — design and implementation plan

Status: implementation plan. The program remains disabled and in SHADOW. This
work neither sends email nor creates an Instantly campaign.

## Existing components and the census gap

| Need | Existing Kivou component | Census change |
| --- | --- | --- |
| Apollo organization search | `supplier_discovery.apollo.ApolloOrganizationSearchClient` | Deterministic, bounded partition profiles and durable page checkpoints. |
| Company/contact facts | `company_research.apollo`, `contact_discovery.apollo` | Reuse behind a durable credit reservation; no personal email, phone or waterfall. |
| MX and qualification | `acquisition_programs.mail_provider`, `qualification` | Persist the minimum provider evidence and final program eligibility reference. |
| Decision and suppression | `ProgramDiscoveryPipeline`, `MilomailShadowRuntime` | Reuse the Milo Mail ruleset and Kivou suppression store. No census policy fork. |
| Attribution and sending | Existing program attribution and `ShadowInstantlyProvider` | No attribution token, export or Instantly call is needed for a census. |

The existing discovery pipeline deliberately accepts only mocked Apollo
transports. It has no durable page cursor or credit ledger. The census adds a
separate preparatory orchestrator, not a second acquisition engine. It calls
the existing candidate assessor only after its own budget gate and uses the
existing policy decision. The first implementation must leave the old mock-only
`run()` boundary intact.

## Partition and coverage rules

`plan` builds a stable cross product of configured sectors and disjoint employee
intervals covering 1–10. Each partition uses only Apollo Organization Search
filters supported by the existing adapter: France, employee range and sector
keyword tags. The signature includes filter version and canonical JSON.
Keywords may overlap between sectors; occurrences are recorded and candidates
are globally deduplicated by Apollo organization ID and normalized domain.
An Apollo total at or above its 50,000-result display limit is flagged as a
coverage hole. A page or budget cap reached before the reported last page also
remains an incomplete partition. The census never subdivides solely to evade
that API limit. Plan counts are unknown until Apollo returns them.

## Durable and conservative cost model

One additive migration stores a run, partition checkpoints, candidate
identities, partition occurrences and API call reservations. Before each
potentially billed request, a transaction reserves its worst-case credit cost
against the run limits. A completed response and its page/candidate checkpoint
are committed together. An interrupted reservation is `REVIEW_REQUIRED` on
resume: the request is not silently replayed or refunded. A confirmed rate
limit may be retried only within an explicit bounded retry limit and remaining
budget. No missing limit means unlimited; all default limits are zero.

Organization Search is budgeted at one credit per page, Organization
Enrichment at one per organization, and People Enrichment at a conservative
nine-credit maximum per person. People Search is counted as an API call but is
budgeted at zero credits. The ledger reports *reserved upper bound* separately
from actual consumption. Actual credits and CHF cost remain unknown until
provider usage is reconciled; no estimate is labelled as a measured cost.

## Execution and resume

`plan` writes no provider calls. `run` and `resume` require an explicit census
enable flag, nonzero limits, a CHF-per-credit ceiling, an authorization
reference, a dedicated Apollo credential and SHADOW program configuration.
Tests inject mocked adapters and never use a real key. Page checkpoints and
candidate stages make a second pass idempotent. A failed or ambiguous billed
call stops for review, preserving reserved credits. `status` and `report` read
only persisted data and redact email addresses and secrets.

Candidate processing validates the public company domain, checks MX, then
performs bounded company/contact enrichment only for Google Workspace
candidates. Other providers are ruled out for this Gmail-specific campaign;
UNKNOWN is held pending evidence. Eligible candidates use the existing
company/contact assessment, suppression, score and Milo Mail policy. The
program's SHADOW guard continues to block Instantly exports, including a
theoretical `SEND`.

## Verification order

1. Add failing tests for deterministic partitions, zero defaults, budgets,
   deduplication, checkpoint/resume, coverage gaps and synthetic funnel.
2. Add the schema and reversible migration, then persistence and orchestration.
3. Add a CLI with `plan`, `run`, `resume`, `status`, `report`; keep paid calls
   unavailable without explicit configuration.
4. Test the mocked Apollo/MX/policy path, rate limits, no Instantly mutation,
   upgrade/downgrade, lint, types and complete relevant CI.
5. Document the runbook and open a dedicated PR. Do not merge or deploy it.
