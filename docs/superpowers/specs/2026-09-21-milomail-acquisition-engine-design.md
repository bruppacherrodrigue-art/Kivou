# Milo Mail acquisition program — design

Date: 2026-09-21. Base: `origin/main` at `b4373d0814bfc90e0b82d865148e8437b17ca3b5`.
Status: implementation design; no outbound authorization or deployment.

## Existing boundaries and reuse

| Need | Existing Kivou component | Change |
| --- | --- | --- |
| Durable orchestration | `signals.acquisition` event store and `signals.acquisition_runtime` | Add a versioned program identity and a bounded program-specific stage adapter. Preserve procurement stages. |
| Organization discovery | `signals.supplier_discovery.apollo`, supplier store | Map a configured service-sector search to the existing Apollo adapter; never infer send permission from Apollo. |
| Person and company facts | `signals.contact_discovery.apollo`, `signals.company_research.apollo` | Reuse the adapters and durable supplier/contact/company identities. Keep source, observed time, and uncertainty. |
| Authorization and suppression | `signals.policy.gateway`, `signals.compliance` | Add a distinct Milo Mail FR B2B ruleset and a program-scoped suppression predicate. The gateway remains the final execution authority. |
| Campaigns | `signals.campaigns`, `ShadowInstantlyProvider` | Render a versioned French draft; use a distinct workspace/sender configuration. SHADOW never calls provider mutations. |
| Outcomes | `signals.acquisition` events and `signals.conversion` token pattern | Bind opaque tokens to program prospects; ingest only signed minimal milestone events into Kivou's event store. |

SPEC-014 is SaaS alerts/analytics; SPEC-015 is frontend; SPEC-016 is ingestion runtime; SPEC-017 is advisory Hermes; SPEC-018 is the acquisition event store; SPEC-019 is Policy Gateway; SPEC-020 is procurement-seeded Apollo supplier discovery. Their code is present, but none supplies a multi-product program contract. Current migration head is `0067_acceptance_error_cleanup`.

## Decision model

`AcquisitionProgramConfig` owns targeting, score weights and thresholds, copy version, policy version, budgets, sender allowlist, and landing requirements. Milo Mail is one configured instance. Missing configuration is a negative gate. Provider detection reads DNS MX only. `@gmail.com` is classified consumer even when professionally published; the pilot allows only confirmed Google Workspace on a company domain. A business-domain address becomes confirmed professional only with a matching active company domain, decision-maker role, verified address, and dated professional source. Unknown or stale facts produce HOLD; personal/minor, unsupported provider, suppression, or excluded segment produce NO_SEND.

The Milo Mail ruleset emits SEND/HOLD/NO_SEND as a **theoretical** eligibility result. It is separate from SPEC-025's Kivou purpose and records score, policy version, reason codes, and evidence IDs. A SEND result cannot schedule or export a lead: the program's fixed SHADOW execution boundary rejects every Instantly mutation. The existing SPEC-019 Policy Gateway denies executable operations in SHADOW and has no Milo Mail provider command. The Apollo program pipeline therefore accepts only `httpx.MockTransport` during this mission. A future real preparatory provider command must be reviewed and registered in that gateway. This separation permits representative SEND tests without external delivery.

The French B2B ruleset requires verified professional relevance, source and collection time, sender identity, privacy and source notice, simple free opposition, and a current suppression check. It is based on [CNIL's B2B guidance](https://www.cnil.fr/fr/communication-electronique-quelles-regles), [CPCE L34-5](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000042155961/), and [GDPR Articles 6, 14, 21](https://eur-lex.europa.eu/eli/reg/2016/679/oj?locale=fr). This is a conservative program rule, not an assertion of external legal approval. Future activation still needs a separate operational/legal review.

Google's [official Workspace MX guidance](https://knowledge.workspace.google.com/admin/domains/set-up-mx-records-for-google-workspace) documents `smtp.google.com` and legacy `aspmx` records. The detector accepts only exact documented Google host patterns; mixed-provider MX, DNS failure, and missing MX stay UNKNOWN.

## Product and data boundary

Milo Mail is the product; Milo is its in-product AI agent. Kivou stores only acquisition facts and minimal signed conversion events. Milo Mail receives no prospect, Apollo, Instantly, score, or suppression data. Kivou receives no Gmail content, OAuth token, mailbox category, or detailed audit result. The free audit is described as read-only; Milo Clean alone is available. Milo Pro and Milo Agent are coming soon.

No French landing URL, exact sender legal identity, or authorized secondary sender domain is supplied. The program is committed disabled in SHADOW with zero contact and cost limits. Tests use synthetic readiness and do not prove real infrastructure. No live sender credentials, provider mutation, production migration, or outbound mail are part of this implementation.

## Rollout and proof

Implement in L1–L5 with one reversible commit per lot. Tests use synthetic companies, a fake DNS resolver, fake Apollo responses, and an Instantly mutation spy. Migration upgrade/downgrade runs on disposable SQLite; PostgreSQL DDL parity uses the repository's existing test conventions. A future activation requires a French landing, privacy/opt-out routes, independent Milo Mail sender domain and mailboxes, SPF/DKIM/DMARC, warm-up, verified webhooks, and an explicit operator order.
