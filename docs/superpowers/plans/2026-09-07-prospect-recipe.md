# Prospect recipe implementation plan

Goal: deliver the approved provisional prospect experience without sending mail.
Architecture: reuse the existing shell, account landing journal, profile matching and persistent sentence. A shared public-fact eligibility rule applies to minting, materialization and current acquisition decisions. Historical audits remain unchanged.

1. Regressions: `tests/test_prospect_recipe.py`, `frontend/src/signals/prospect.test.tsx`; reproduce false provisional state, missing shell, wrong fallback, title and date labels before implementation.
2. State: `accounts/service.py`, `api/routes_auth.py`, `api/routes_signals.py`, frontend `api/types.ts` and `layouts/AppShell.tsx`; expose one stored provisional-state predicate and use it for shell and banner.
3. Eligibility: new `domain/prospect.py`, `conversion/mint_token.py`, decision input/contracts/evaluator plus decision and personalization services; require a named holder, usable object and an effective award/notification/publication date at most 30 days old. Feed the refusal reasons into current decisions, retaining archived decisions.
4. Landing: `ingestion/backfill.py`, `api/routes_attribution.py`, `accounts/service.py`; materialize the promised opportunity and at most four eligible matching neighbours, bounded candidate scan, no provider call. Limit the landing grant to five total.
5. Presentation: `personalization/for_you.py`, `for_you_store.py`, `feed/view.py`, `SignalDrawer.tsx`, translations and associated tests; one fact-based fallback, short title, full object only when different, award/notification label distinct from publication.
6. Validate pure tests locally; database regressions on the staging server only. Measure fresh and replayed QA entry with Playwright. Preserve screenshots and timings in private output artifacts.
7. Deploy through the server script to staging, validate, then production. Do not enable acquisition or send any mail. Mint and verify a fresh eligible production token, deliver the URL privately.

Baseline: production QA replay at 1440 px, click-to-drawer 770 ms (landing 161 ms); this is not a first-account measurement. Screenshot: `output/playwright/prospect-before/desktop.png`.
