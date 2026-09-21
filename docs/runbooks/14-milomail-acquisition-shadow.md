# Milo Mail acquisition — SHADOW runbook

Status: implementation for review only. Milo Mail is the product; Milo is the in-product agent. Kivou owns all prospecting decisions and data. No real campaign has been created or sent.

## Architecture and reuse

| Need | Kivou source of truth | Program addition |
| --- | --- | --- |
| Discovery and identity | `supplier_discovery.apollo`, `SupplierDiscoveryStore`, `AcquisitionStore` | Configured France/service search; program-scoped opportunity identity. The program pipeline runs only with mocked Apollo transports in this lot. |
| Contact and company facts | `contact_discovery.apollo`, `company_research.apollo`, existing contact/supplier tables | Bound Apollo organization/person evidence plus a separately supplied dated active-company proof. Apollo facts never authorize SEND alone. |
| Provider and qualification | `acquisition_programs.mail_provider`, `qualification` | Public DNS MX, professional-capacity classification, scored public business proxies. |
| Compliance and suppression | `compliance.rules` remains SPEC-025 Kivou; `compliance.milomail_rules`; existing `acquisition_contact_suppression` | Distinct Milo Mail B2B FR ruleset and HMAC-separated Milo Mail suppression scope. |
| Provider operation | Existing `ShadowInstantlyProvider`, Instantly normalization | Two-step preview and authenticated one-prospect webhook simulation only. No provider mutation route. |
| Attribution | `AcquisitionStore` event journal | Program token binding and minimal replay receipt. Product events append to the existing journal. |

SPEC-014–020 are present: 014 analytics, 015 frontend, 016 ingestion, 017 Hermes, 018 event store, 019 gateway, 020 procurement-seeded supplier discovery. SPEC-020's `SupplierSearchProfile` requires a procurement seed, so Milo Mail uses a configured organization profile with the same Apollo adapter. The existing Policy Gateway's SHADOW mode denies executable commands. A future live Apollo stage needs a reviewed generic program command; this lot permits only `httpx.MockTransport` in the program pipeline.

Migrations `0068_acquisition_program`, `0069_milomail_suppression_scope`, and `0070_program_conversion_receipt` add immutable program versions, eligibility facts, token bindings, a new scope in the **existing** suppression table, and a minimal global replay index. Existing Kivou historical rows have no invented Milo Mail defaults. The `0069` downgrade needs Milo Mail suppression rows removed from a disposable/test database; never use that downgrade to erase production objections.

## Decision matrix

`MILOMAIL_GMAIL_AUDIT_B2B` is an allowed `ComplianceInput.acquisition_purpose` value but is explicitly rejected by the frozen Kivou SPEC-025 evaluator. `compliance.milomail_rules` version `milomail-fr-b2b-v1` decides:

| Decision | Conditions |
| --- | --- |
| SEND, theoretical | FR company, active proof, 1–10 people, listed service sector, relevant offer, verified founder/owner/CEO/director address on company domain, fresh professional source, confirmed Google Workspace MX, score ≥ configured review threshold, source/collection time, suppression clear, legal sender identity and notices, French landing and healthy authorized sender, available configured budget. SHADOW still blocks export. |
| HOLD | Temporarily missing or stale DNS, active-company proof, role, verified email, professional source, policy disclosure, landing/sender readiness, budget, or a low score caused by unresolved core facts. |
| NO_SEND | Known personal/minor, suppressed recipient, non-FR company, inactive or excluded company, Microsoft/other/consumer Gmail pilot provider, or a known score below the review threshold once core facts are resolved. |

Every stored assessment contains provider MX/source/time/version, capacity reasons/source/time, score breakdown/version, decision/reason codes/policy country/version/evidence IDs/time. `UNKNOWN` and `LIKELY_PROFESSIONAL` cannot yield SEND. `@gmail.com` can be confirmed professional only with explicit professional publication and company/role proof, but remains NO_SEND in this Google Workspace-only pilot.

This is a conservative internal rule for [CNIL B2B electronic prospecting](https://www.cnil.fr/fr/communication-electronique-quelles-regles), [CPCE L34-5](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000042155961/) and [GDPR articles 6, 14 and 21](https://eur-lex.europa.eu/eli/reg/2016/679/oj?locale=fr). It does not extend policy to other EU countries. An additional legal review may be tracked without blocking SHADOW tests; activation requires a separate review.

## MX and professional evidence

`MailProviderDetector` accepts bare validated domains only, makes bounded MX DNS queries with a mocked resolver option, caches observation and configurable expiry, and never connects to SMTP or Gmail. The exact [Google Workspace MX hosts](https://knowledge.workspace.google.com/admin/domains/set-up-mx-records-for-google-workspace) include current `smtp.google.com` and legacy `aspmx.l.google.com`/`alt1`–`alt4` variants. Microsoft protection MX maps to `MICROSOFT_365`; mixed records, timeout or no DNS map to `UNKNOWN`. `@gmail.com` maps to `GMAIL_CONSUMER`, not Workspace.

An Apollo verified business email, a matching active company domain, an unambiguous whole current director title, a professional source URL/type and fresh observation are all required to confirm recipient capacity. Titles such as “Assistant to CEO” and “Former Founder” do not qualify. Active-company status must come from a separately dated public/company-registry proof; Apollo listing does not imply an active company. Public activity and service type contribute only documented score proxies. No Gmail content, inbox volume, OAuth token, private metadata, sensitive category, or invented pain statistic enters Kivou.

## Configuration and SHADOW procedure

The reviewed template is [`ops/examples/milomail-acquisition.json.example`](../../ops/examples/milomail-acquisition.json.example). It contains `program_key=milomail`, product `Milo Mail`, offer `gmail_free_audit`, `milo_clean` available and `milo_pro`/`milo_agent` coming soon, FR/fr-FR, 1–10 people, the three service sectors, Google Workspace, SHADOW, `enabled=false`, and zero contact/cost caps. Landing, sender domain, legal identity, workspace, privacy and opt-out destinations are absent. Do not replace them with invented production values.

Environment controls use `MILOMAIL_ACQUISITION_ENABLED=false`, `MILOMAIL_CAMPAIGN_MODE=SHADOW`, `MILOMAIL_ALLOWED_COUNTRIES=FR`, `MILOMAIL_ALLOWED_PROVIDERS=GOOGLE_WORKSPACE`, `MILOMAIL_MAX_DAILY_CONTACTS=0`, `MILOMAIL_MAX_MONTHLY_CONTACTS=0`, `MILOMAIL_MAX_COST_CHF=0` by default. A non-SHADOW mode is rejected by `runtime_flags`. Enabling evaluation requires an explicit SHADOW mode. The campaign factory creates a local, versioned preview with two steps; its Instantly-shaped payload has daily limit zero and no sending account. `ShadowInstantlyProvider` forwards only explicit read operations; all known and future mutations are denied by default.

Run local proof with `uv run pytest -q -n 0 tests/test_milomail_*.py`; inspect program metrics with `read_program_metrics(engine, program_id=...)` on a disposable database. The synthetic pipeline accepts only `httpx.MockTransport`, and test fixtures use fictitious companies, addresses, keys and domains. Do not supply production credentials to these tests. No Milo Mail frontend connection to Apollo or Instantly exists.

## Sequence and attribution contract

The French initial message and one follow-up are versioned in the program JSON. They state that the audit is free, does not modify or delete email, leaves the prospect in control, and that only Milo Clean is available; the other plans remain coming soon. The optional personalized fact must have a Kivou evidence ID and public source; removing it leaves the base message exact. Every step includes the configured exact legal sender identity, postal address, source notice, privacy route and simple free opt-out. Links contain a 43-character opaque token, never an email address.

`ProgramAttributionService` issues a program/campaign/opportunity-bound HMAC token only after a theoretical SEND assessment, a match against the selected contact **and** the assessed recipient identity, and a current suppression check. An address change requires a new assessment; a caller cannot backdate issuance to bypass an opt-out. The database retains the token hash and a separate HMAC of the intended recipient. The product may send only this minimal JSON event to Kivou: `event_id`, `event_type`, `attribution_token`, `occurred_at`, and optional `mrr_chf` on paid/retention events. Allowed product event types: `landing_clicked`, `audit_started`, `google_oauth_completed`, `audit_completed`, `milo_clean_checkout_started`, `milo_clean_paid`, `m1_retained`, `m2_retained`. `mrr_chf` is never inferred from a click. The event is signed with a **distinct** Milo Mail webhook secret: HMAC-SHA256 over `milomail-conversion-v1\0` + ASCII Unix timestamp + `\0` + exact raw JSON bytes. Headers: `X-MiloMail-Timestamp`, `X-MiloMail-Signature` (lowercase hex). Reception permits ±300 seconds, limits body to 4096 bytes, validates the exact closed schema, checks token binding/validity, and deduplicates opaque event IDs globally per program. No Gmail/OAuth content, audit detail, user email or mailbox category is accepted.

Instantly simulation accepts existing normalized webhook fields with a separate Milo Mail shared secret and exact workspace/campaign/recipient HMAC binding. It records sent/bounced/replied/unsubscribed facts in the Kivou event journal, discards reply content, and writes opt-outs in `MILOMAIL_ACQUISITION_EMAIL`. One synthetic campaign binds one prospect. Grouped real campaigns and an authenticated production route are deliberately outside this SHADOW lot; activation is blocked until lead identity, replay and retry/dead-letter behavior are reviewed end to end.

## Metrics, costs and alerts

`read_program_metrics` reports latest assessment counts by program/wedge/campaign, provider and UNKNOWN rate, decision/reason counts, conversion milestones, and available Instantly reply/bounce counters. MRR is known only if paid events provide `mrr_chf`. Cost per studied/contacted stays **unknown** without observed provider costs; the configured 0.10–0.20 CHF/contact is a target, not measured performance. No external costs or sends were incurred in this local SHADOW implementation.

Future alert thresholds are configurable starting guards, not observations: bounce ≥2%, complaint near 0.1%, suppression failure, invalid webhook signature, cost overrun, abnormal UNKNOWN growth, and any export outside the country/domain allowlist. SHADOW export attempts should be counted as blocked. Existing event records and reason codes are the audit trail; never log raw provider payloads, personal addresses, tokens or secrets.

## Stop and future activation

Emergency stop: keep `MILOMAIL_ACQUISITION_ENABLED=false`, `MILOMAIL_CAMPAIGN_MODE=SHADOW`, all caps zero; revoke any Milo Mail sender/webhook credentials in the existing secret manager if ever provisioned. Record opt-outs immediately through `SuppressionStore(scope=MILOMAIL_SUPPRESSION_SCOPE)`; the HMAC domain is separate from Kivou and applies across Milo Mail campaigns. Verify with `EmailSuppressionChecker` before any future export and each follow-up. Do not silently propagate Milo Mail suppression across brands without policy review. Existing suppression retention is at least three calendar years; evidence and token TTLs are configured/bounded, while a full deletion/retention job remains an activation prerequisite.

Future activation requires, in order: (1) a validated French landing, exact legal sender identity, privacy and opt-out routes; (2) a separately authorized sender domain and mailboxes with SPF/DKIM/DMARC, warm-up and delivery caps; (3) reviewed FR B2B legal policy and source retention; (4) a generic Policy Gateway command for actual Apollo preparatory calls and separate Milo Mail secrets; (5) real grouped-campaign recipient binding and authenticated Instantly route, retry/dead-letter, suppression recheck before every initial/follow-up export; (6) signed product conversion route and attribution tests; (7) budget/cost observation and alert wiring; (8) explicit operational approval and a separate activation change. This PR performs none of these activation steps.

Milo Mail never receives Kivou prospects, campaigns, scores, research, suppressions or supplier identifiers. Kivou never receives Gmail content, Google OAuth tokens or detailed audit results. No production migration, campaign, merge or deployment is part of this runbook execution.
