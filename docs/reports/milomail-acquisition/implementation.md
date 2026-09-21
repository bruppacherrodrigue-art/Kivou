# Milo Mail acquisition — implementation record

Date: 2026-09-21. Review state: SHADOW implementation under validation; no production mutation, merge, deployment or outbound send.

## L0 repository audit

- Repository: `/home/jaybe/projects/Kivou`; isolated worktree `/home/jaybe/projects/Kivou/.worktrees/milomail-acquisition-engine`.
- Authorized base: `origin/main` at `b4373d0814bfc90e0b82d865148e8437b17ca3b5`. Branch: `feat/milomail-acquisition-engine`. Base migration head: `0067_acceptance_error_cleanup`.
- Original local `main` was ahead by two, behind `origin/main` by 229, and had four user changes; it was not modified. Remote state was fetched before branch creation. No applicable `AGENTS.md` existed inside Kivou; the session-provided AGENTS instructions were read. Milo Mail's repository instructions were inspected read-only.
- Tools at audit: Python 3.12.3, uv 0.11.7, SQLAlchemy 2.0.52, Alembic 1.19.1, dnspython 2.8, Ruff 0.16.5. Baseline: 46 relevant Kivou acquisition/compliance/campaign tests passed.
- SPEC-014–020 are present but not a multi-product program runtime: 014 alerts, 015 frontend, 016 ingestion, 017 Hermes, 018 acquisition event stream, 019 Policy Gateway, 020 procurement-seeded Apollo supplier search. Later SPEC-025 is a frozen Kivou compliance ruleset; it is preserved and rejects the Milo Mail purpose.

| Milo Mail need | Observed Kivou component | Change in this branch |
| --- | --- | --- |
| Program identity and configuration | `AcquisitionStore`, SQLAlchemy Core schema, Alembic | Versioned `AcquisitionProgramConfig`, immutable registration, program eligibility/token/receipt tables. |
| Account/contact discovery | Apollo organization/people/company adapters; supplier/contact stores | Configured search/profile mapper, bounded mock-only SHADOW pipeline, existing stores and event stream. |
| Gmail provider | dnspython already installed, no existing dedicated detector | Strict DNS MX detector, cache, timestamps, unknown handling. |
| Recipient and fit | Contact role ranking; company research; decision engine | Professional source classification, versioned fit/public proxy score. |
| Compliance and suppression | SPEC-025 and one suppression table | Separate FR B2B purpose/ruleset, scoped HMAC identities on the same table. |
| Campaign and delivery | `ShadowInstantlyProvider`, Instantly parser | Versioned French draft, provider-shaped simulation, no mutation call. |
| Attribution | Acquisition event journal, Kivou conversion token pattern | Program-bound opaque token, minimal signed Milo Mail events, global replay index. |

## Implemented boundaries

Milo Mail is the product; Milo is its agent. The program is generic/versioned in Kivou and configured as `milomail`, disabled, SHADOW, zero caps. Kivou continues to own supplier/contact/prospect research, score, policy, suppression, attribution and metrics. Apollo remains a source adapter; Instantly remains an execution/feedback adapter. The code exposes no Apollo/Instantly path to Milo Mail, and product conversion ingress accepts no Gmail message content, OAuth token, audit detail or email address.

The theoretical ruleset may return SEND for a complete synthetic French B2B case. The execution boundary remains SHADOW; `ShadowInstantlyProvider` rejects provider creation, activation and lead import, and the campaign preview has daily limit zero/no sending account. Real Apollo discovery is also disabled in this lot because SPEC-019 denies executable commands in SHADOW and SPEC-020 is procurement-seeded; the pipeline accepts `httpx.MockTransport` only. This is the main architecture difference from the prompt's assumed multi-program runtime. A generic preparatory Policy Gateway command is required before real discovery, not before this mock-based implementation.

The existing suppression table now has separate Kivou and Milo Mail scopes and domain-separated HMACs. Same-brand Milo Mail objections block token issuance and all SHADOW previews; the simulated Instantly opt-out is authenticated, bound to workspace/campaign/recipient, and idempotent. There is no cross-brand suppression propagation.

Read-only review exposed five defects that were corrected before delivery: the SHADOW Instantly facade now delegates only named reads; token issuance binds to the selected contact and the email HMAC captured in the actual SEND assessment, and checks suppression at issuance time even when `issued_at` is backdated; repeated mock discovery reuses the existing opportunity while appending a fresh eligibility assessment; target roles require an unambiguous whole current title; and a complete score below the review threshold is NO_SEND. Provider and conversion telemetry no longer replace the actual policy version on the opportunity projection. Regression tests reproduce each original failure.

Migrations `0068`, `0069`, `0070` are additive on upgrade. The `0069` downgrade cannot safely remove a scope if production Milo Mail objections exist; production has not been migrated. Fresh database upgrade/downgrade is tested.

## Rollout limits

The example config intentionally lacks a real French landing, authorized Milo Mail secondary domain/mailboxes, legal sender identity/address, privacy and opt-out routes, workspace and secrets. The active-company verifier is injected and tested with a synthetic public proof; no live registry credential or company lookup was used. The actual Instantly and Milo Mail product webhook routes, grouped campaign lead binding, durable retry/dead-letter, provider cost observation, complete retention job and alert wiring are future activation work. These do not block theoretical SEND or local SHADOW tests. They block any real campaign.

The long-term 0.10–0.20 CHF/contact target is configuration only; no measured acquisition cost exists. External provider cost incurred by this implementation: 0 CHF. No secret or production credential was used. No campaign was created, no email was sent, and no production database was migrated.

## Validation and review record

Draft PR: [#277](https://github.com/bruppacherrodrigue-art/Kivou/pull/277). Executable change set through `5a2b8105` is on the PR branch; a later documentation/test-only commit may advance the head. The [SHADOW runbook](../../runbooks/14-milomail-acquisition-shadow.md) records the decision model, event contract, data boundary, emergency stop and future activation gates.

Focused post-review Milo Mail tests: 49 passed. The acquisition-program, acquisition-runtime, campaign-worker and SHADOW guard suite: 553 passed, 13 SQLAlchemy/SQLite deprecation warnings, after the review fixes. Four attribution/metrics/provider corpus files passed again (8 tests) after freezing their synthetic clock. `uv run ruff check .`, `git diff --check`, compileall and mypy on six changed program/compliance modules passed. SQLite migration upgrade/downgrade and schema checks passed before the review fixes; no migration was changed by those fixes. CI results are tracked at the PR checks and must be reported by exact final SHA, not inferred from local success.

The broad repository suite previously exposed four failures reproduced on a disposable clean `origin/main` checkout at `b4373d08`: two assertions in `tests/test_ops_production_runtime.py` about release-one shell structure and two `tests/test_prospection_provider_bindings.py` corrected-payload cases. They are outside the Milo Mail component changes. That baseline comparison is evidence of pre-existing failures, not a waiver of CI: the final PR checks remain part of the review record. A previous local full run produced 6848 passed, 50 failed, 61 skipped and 1 xfailed, but it was invalid for change-set verification because the program JSON changed while xdist workers had imported the earlier model; 44 failures came from that inconsistent in-process state, two from test registries since corrected, and four were the clean-base failures above. No test failure is hidden or counted as a pass.
