# Signed recipe links

Goal: issue expiring production recipe links without acquisition side effects.
Architecture: separate `kqa1` HMAC domain and self-contained, strictly validated
payload. Existing `kat1` links remain unchanged. QA landings use only their own
unconfirmed provisional account; never bind commercial conversion attribution.
Stack: Python, Pydantic, SQLAlchemy, Alembic, FastAPI, systemd.

1. Add `tests/test_qa_attribution.py`; run against the previous runtime on staging
   using isolated SQLite fixtures, not the staging database. Observe RED.
2. Add `conversion/qa_token.py`, `conversion/mint_token.py`; extend
   `api/routes_attribution.py`, `accounts/schema.py`, `accounts/service.py`.
   Add migration `0043_qa_landing`. Mark the landing and every later product event
   as QA; exclude QA from `engagement/analytics.py` and founder quality queries.
3. Add the narrow attribution installer and EnvironmentFile to both API units.
   Copy only existing attribution key/version locally on each server. Do not
   enable the production Instantly webhook: its complete validation key group
   exceeds the authorized two-key scope.
4. Run new and legacy attribution regressions on staging in isolation. Push an
   identified SHA, deploy staging then production exclusively through the server
   deployment script, including backup and migration rehearsal. Check readiness.
5. Mint an actual seven-day production recipe link, prove its landing resolves
   the promised signal, and verify QA journal and unchanged acquisition counts.
   Return its URL and actual contract facts, without claiming an inferred trade
   is a verified execution requirement. No campaign/member/send or Hermes action.
