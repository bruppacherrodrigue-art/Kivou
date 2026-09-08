# Verified prospect email implementation plan

**Goal:** Addressed prospect links create unverified real identities; only verified recipients receive alerts.
**Architecture:** Signed opaque recipient reference, server-side address binding, independent email proof, shared delivery gate. Existing accounts receive public signal details and a login invitation, never an authenticated session.
**Stack:** SQLAlchemy/Alembic, FastAPI, React, existing SMTP gateway.

## Identity and proof
- Create `src/signals/accounts/email_verification.py`, `src/signals/accounts/verification_delivery.py`, `src/signals/api/routes_email.py`.
- Create migration `0044_email_verification.py`: additive identity and recipient tables, no inferred verification of existing users.
- Wire `src/signals/api/app.py`, `src/signals/api/asgi.py`, migration metadata imports.
- Add `tests/test_email_verification.py`: unverified defaults, proof expiry/replay, recipient changes, collisions, session revocation, visible SMTP failure, origin enforcement.
- Run targeted tests against the old endpoints, implement, then rerun.

## Addressed tokens
- Modify `conversion/mint_token.py`, `api/routes_attribution.py`, actual campaign issuance boundary; create `conversion/recipient_records.py`.
- Require recipient binding before issuance; no address in signed payload or logs.
- Test public existing-account fallback, no synthetic identity creation, no account takeover, no commercial QA records.

## Frontend
- Add email API adapter, verification page and public preview route; update confirmation, account settings, first-confirmed Today title.
- Reuse existing headings, fields and drawer language. Verification requires an explicit button, never a mail scanner GET.
- Test prefill/edit, visible validation/transport failure, public preview without authentication and first-visit title.

## Delivery and Checkout
- Gate notification preparation and pre-send on exact verified recipient, including pending address changes and stale batches.
- Add Checkout `locale=fr`, preserve tax ID collection and customer updates.
- Prepare three approved Stripe descriptions only; Rodrigue validates them in Dashboard.

## Validation and rollout
- Targeted backend/frontend tests, existing affected suites, build and CI before deployment.
- Deploy with server-side `ops/bin/kivou-deploy.sh` only, disposable migration rehearsal and readiness on staging then production.
- Mint one production QA link for the user-approved mailbox; verify profile flow without accessing that mailbox.
- Send its verification message through normal runtime. Wait for Rodrigue's verification click before a scoped weekly alert. No acquisition activation, no automated mailbox access, no merge.
