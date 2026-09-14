# Controlled Company Catalogue Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Check off verified steps only.

**Goal:** Keep staging's real company catalogue aligned with production without copying private/customer data or connecting staging to the production database.

**Architecture:** A production-only, token-authenticated GET returns a bounded complete snapshot of explicitly permitted public company columns. A staging-only scheduled importer reconciles SIRENs transactionally, keeps ownership metadata, propagates withdrawals and preserves private/local-only data. No provider calls and no writes on the publishing side.

**Tech Stack:** Existing FastAPI configuration, Pydantic/SQLAlchemy, HTTPX TLS, PostgreSQL and systemd.

---

## Contract and files

- `src/signals/supplier_directory/catalogue_publication.py`: typed snapshot,
  public column allowlist, validation and deterministic SHA256 content digest.
  `build_snapshot(connection, *, now)` reads only supplier_directory. It publishes
  own-site-validated email via `published_email_evidence`, never raw model pages,
  private contacts, Apollo identifiers, model spend/call IDs, account data or jobs.
- `src/signals/api/routes_catalogue_publication.py`: GET
  `/internal/company-catalogue`, available only with acquisition_environment
  PRODUCTION and `KIVOU_CATALOGUE_PUBLICATION_TOKEN` at least32characters. Compare
  token in constant time; reject missing/wrong token before SQL; return no-store.
- `src/signals/supplier_directory/catalogue_mirror.py`: validate complete snapshot,
  digest, unique SIREN, bounded rows/size, timezone-aware timestamps and no unknown
  columns before transaction writes. `apply_snapshot(connection, snapshot,
  destination_environment="STAGING", now=...)` returns aggregate counts only.
- `src/signals/supplier_directory/catalogue_schema.py` and
  `0063_catalogue_mirror.py` after0062: per-SIREN source ownership and singleton
  snapshot timestamp/digest. A stale snapshot cannot overwrite a newer snapshot.
- `src/signals/supplier_directory/catalogue_worker.py`: HTTPS to exact
  `https://kivou.eu/api/internal/company-catalogue`, no redirects; limited download;
  validate actual target DB `kivou_staging` before writes. Environment/credentials
  are absent-by-default prerequisites; transport has a timeout and no provider I/O.
- `ops/systemd/kivou-catalogue-mirror.{service,timer}`: staging.env plus separate
  catalogue-mirror.env, run every15minutes with bounded execution and no overlapping
  instances. No production importer unit.

## Verification-first steps

- [ ] Add `tests/test_catalogue_publication.py` with actual SupplierDirectory rows
  and assertions that secrets/raw evidence/callID/private-email never appear.
  Unauthorized token and nonproduction instances must return404, with no DB reads.
- [ ] Add `tests/test_catalogue_mirror.py` for initial insertion, idempotence,
  source update, withdrawal/reappearance, local privacy suppression preserved,
  local-only rows/private columns preserved, stale/invalid/duplicate snapshots
  rejected atomically and production destination refused.
- [ ] Run `.venv/bin/pytest -n 0 tests/test_catalogue_publication.py
  tests/test_catalogue_mirror.py -q`; verify failures reflect absent implementation.
- [ ] Implement the contract above with explicit SQL column selection and closed
  errors. Do not reuse privileged company/account APIs for publication.
- [ ] Add tests for body limits/TLS/redirects/missing credentials, migration DDL and
  unit environment targeting; run focused GREEN and Ruff.
- [ ] Review specification compliance followed by quality before installation.

## Reconciliation rules

1. Only source-owned identities absent from a valid complete snapshot are withdrawn.
   Withdraw via recoverable suppression, never DELETE; record the exact suppression
   timestamp so reappearance cannot undo an independent local opt-out.
2. Imported fields never include local model journals/costs, lookup IDs or customer
   state. Preserve those columns on an existing staging record.
3. A locally suppressed row stays suppressed. Local-only rows are not withdrawn.
   Source updates may replace previously mirrored public fields, while newly
   discovered locally fresher facts are preserved where applicable.
4. Source email evidence is reduced to the accepted address and own-site URL;
   the destination records source `site` (publication provenance, not an assertion
   of personal-mailbox verification). Original model traces are never transferred.
5. Exactly audited fake rows990000001..990000030 namedEntreprise test01..30,
   cityBlois, created2026-09-11 11:01:05.975418UTC are quarantined separately after
   backup and manifest review. No fuzzy-name deletion or production fixture action.

## Rollout evidence

- [ ] Verify expected hosts, configure narrow credential without printing it.
- [ ] Publish only after candidate production service is deployed; first staging
  seed can use the identical reviewed serializer read-only against production via
  operator SSH so staging validation precedes live API activation.
- [ ] Initial seed/quarantine: before/after counts, exactSIRENs, protected/private
  baseline unchanged, replay makes no duplicate. Keep recoverable manifest.
- [ ] After production deployment enable timer, observe a successful run and
  matching shareable catalogue counts; report cadence honestly.
