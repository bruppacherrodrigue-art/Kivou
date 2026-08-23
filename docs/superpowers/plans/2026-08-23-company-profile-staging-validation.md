# Company Profile Staging Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove migration `0022`, the official-company backfill, authorization boundaries, and the real company-profile page against a restored staging PostgreSQL backup before making PR #59 ready for review.

**Architecture:** Restore the latest verified staging custom-format dump into an explicitly named disposable PostgreSQL database on `kivou-staging`. Execute the exact PR SHA from an isolated remote Git worktree, collect database and authorization evidence without changing the live staging database, then deploy that same SHA through the existing service layout and validate the protected UI with a synthetic staging account. Keep the PR draft until every gate passes.

**Tech Stack:** PostgreSQL 16, `pg_restore`, Alembic, SQLAlchemy Core, FastAPI TestClient, systemd, nginx, uv, Node/npm, Playwright CLI, GitHub CLI.

---

### Task 1: Pin the auditable PR SHA and staging baseline

**Files:**
- Modify: `docs/ROAD_TO_LIVE.md`
- Create: `docs/superpowers/plans/2026-08-23-company-profile-staging-validation.md`

- [ ] **Step 1: Record the required product state**

Keep these statements explicit in `docs/ROAD_TO_LIVE.md`:

```text
Fiche entreprise officielle : livrée en PR.
Enrichissement Apollo : différé jusqu’à obtention d’un accord contractuel écrit.
```

- [ ] **Step 2: Commit and push the documentation gate**

```bash
git add docs/ROAD_TO_LIVE.md \
  docs/superpowers/plans/2026-08-23-company-profile-staging-validation.md
git commit -m "docs(companies): define staging promotion gate"
git push origin feat/saas-company-profile-apollo
```

Expected: PR #59 remains draft and its `headRefOid` equals `git rev-parse HEAD`.

- [ ] **Step 3: Record the remote baseline without secrets**

```bash
ssh kivou-staging 'sudo -u kivou git -C /srv/kivou/app rev-parse HEAD'
ssh kivou-staging 'sudo -u postgres psql -Atqc \
  "select version_num from alembic_version" kivou_staging'
```

Expected before promotion: deployed SHA `48632e5cbb300fa070b9ce8c8d6dfa9de10f8bfe`; the database revision is recorded verbatim.

### Task 2: Restore the verified backup into a disposable PostgreSQL database

**Remote resources:**
- Read: `/srv/kivou/backups/kivou-20260822T064452Z.dump`
- Create temporarily: PostgreSQL database `kivou_profile_validation_pr59`

- [ ] **Step 1: Revalidate the archive and target absence**

```bash
ssh kivou-staging 'set -eu
  sudo -u kivou pg_restore --list \
    /srv/kivou/backups/kivou-20260822T064452Z.dump >/dev/null
  test "$(sudo -u postgres psql -Atqc \
    "select count(*) from pg_database where datname = '\''kivou_profile_validation_pr59'\''")" = 0'
```

Expected: archive readable and target count `0`. Stop instead of overwriting if it exists.

- [ ] **Step 2: Create and restore the disposable database**

```bash
ssh kivou-staging 'set -eu
  owner=$(sudo -u postgres psql -Atqc \
    "select pg_get_userbyid(datdba) from pg_database where datname = '\''kivou_staging'\''")
  sudo -u postgres createdb --template=template0 --owner="$owner" \
    kivou_profile_validation_pr59
  started=$(date +%s)
  sudo -u postgres pg_restore --exit-on-error --no-owner --no-privileges \
    --dbname=kivou_profile_validation_pr59 \
    /srv/kivou/backups/kivou-20260822T064452Z.dump
  finished=$(date +%s)
  echo "restore_seconds=$((finished-started))"'
```

Expected: restore exits `0`; only the explicitly named disposable database is created.

- [ ] **Step 3: Verify restored baseline integrity**

```bash
ssh kivou-staging 'sudo -u postgres psql -d kivou_profile_validation_pr59 \
  -Atqc "select version_num from alembic_version;
         select count(*) from materialized_signal;
         select count(*) from target_icp;
         select count(*) from account;"'
```

Expected: one Alembic revision and nonnegative baseline counts are recorded.

### Task 3: Execute PR migration and application backfill on the clone

**Remote resources:**
- Create temporarily: `/srv/kivou/validation/company-profile-pr59`
- Use: exact `headRefOid` from PR #59

- [ ] **Step 1: Prepare an isolated checkout of the exact PR SHA**

```bash
ssh kivou-staging 'set -eu
  sudo -u kivou git -C /srv/kivou/app fetch origin \
    feat/saas-company-profile-apollo
  sha=$(sudo -u kivou git -C /srv/kivou/app rev-parse FETCH_HEAD)
  sudo install -o kivou -g kivou -m 700 -d /srv/kivou/validation
  sudo -u kivou git -C /srv/kivou/app worktree add --detach \
    /srv/kivou/validation/company-profile-pr59 "$sha"
  sudo -u kivou git -C /srv/kivou/validation/company-profile-pr59 rev-parse HEAD'
```

Expected: printed SHA equals the PR `headRefOid`.

- [ ] **Step 2: Install locked runtime dependencies in the validation checkout**

```bash
ssh kivou-staging 'sudo -u kivou bash -lc \
  "cd /srv/kivou/validation/company-profile-pr59 &&
   uv sync --frozen --extra server --extra postgres"'
```

Expected: dependency synchronization exits `0` without changing the lockfile.

- [ ] **Step 3: Execute migration `0022` against only the disposable database**

Use Python URL parsing so credentials are never printed:

```bash
ssh kivou-staging 'sudo -u kivou bash -lc "
  set -a; source /etc/kivou/staging.env; set +a
  cd /srv/kivou/validation/company-profile-pr59
  export KIVOU_DATABASE_URL=\$(.venv/bin/python -c \
    '\''import os; from sqlalchemy.engine import make_url;
       print(make_url(os.environ[\"KIVOU_DATABASE_URL\"]).set(database=\"kivou_profile_validation_pr59\"))'\'')
  started=\$(date +%s)
  .venv/bin/alembic upgrade 0022_saas_company_profile
  finished=\$(date +%s)
  echo migration_seconds=\$((finished-started))
  .venv/bin/python -c \
    '\''from signals.persistence.database import create_database_engine, current_revision;
       import os; engine=create_database_engine(os.environ[\"KIVOU_DATABASE_URL\"]);
       print(current_revision(engine))'\''"'
```

Expected: revision `0022_saas_company_profile`; no secret appears in output.

- [ ] **Step 4: Execute and time the idempotent application backfill explicitly**

```bash
ssh kivou-staging 'sudo -u kivou bash -lc "
  set -a; source /etc/kivou/staging.env; set +a
  cd /srv/kivou/validation/company-profile-pr59
  export KIVOU_DATABASE_URL=\$(.venv/bin/python -c \
    '\''import os; from sqlalchemy.engine import make_url;
       print(make_url(os.environ[\"KIVOU_DATABASE_URL\"]).set(database=\"kivou_profile_validation_pr59\"))'\'')
  .venv/bin/python -c \
    '\''import os,time;
       from signals.companies.indexing import backfill_signal_company_identities;
       from signals.persistence.database import create_database_engine;
       engine=create_database_engine(os.environ[\"KIVOU_DATABASE_URL\"]);
       started=time.monotonic();
       with engine.begin() as connection: count=backfill_signal_company_identities(connection);
       print(f\"backfill_rows={count}\");
       print(f\"backfill_seconds={time.monotonic()-started:.3f}\")'\''"'
```

Expected: every persisted signal is revisited, the second pass is safe, and duration is recorded.

### Task 4: Validate data shape and authorization on PostgreSQL

**Files:**
- Create locally with `apply_patch`, then copy temporarily: `/home/jaybe/kivou-company-profile-postgres-validation.py`
- Copy temporarily to: `/srv/kivou/validation/company-profile-pr59/company-profile-postgres-validation.py`

- [ ] **Step 1: Measure identity coverage and duplicates**

Execute portable SQL against `kivou_profile_validation_pr59` and record:

```sql
SELECT count(*) FROM materialized_signal;
SELECT count(*) FROM materialized_signal
 WHERE company_identity_fingerprint IS NOT NULL;
SELECT count(DISTINCT company_identity_fingerprint)
 FROM materialized_signal
 WHERE company_identity_fingerprint IS NOT NULL;
SELECT count(*) FROM (
  SELECT identity_fingerprint FROM saas_company
  GROUP BY identity_fingerprint HAVING count(*) > 1
) duplicates;
SELECT count(*) FROM saas_company;
```

Expected: duplicate count `0`; null and non-null coverage are reported honestly.

- [ ] **Step 2: Exercise one paid and one Discovery authorization path**

Copy the locally linted one-shot validator, then execute it with both `src` and
`tests` on the import path. The script refuses every backend/database except
PostgreSQL database `kivou_profile_validation_pr59` before it writes anything.

```bash
scp /home/jaybe/kivou-company-profile-postgres-validation.py \
  kivou-staging:/tmp/kivou-company-profile-postgres-validation.py
ssh kivou-staging 'set -eu
  sudo install -o kivou -g kivou -m 700 \
    /tmp/kivou-company-profile-postgres-validation.py \
    /srv/kivou/validation/company-profile-pr59/company-profile-postgres-validation.py
  sudo -u kivou bash -lc "
    set -a; source /etc/kivou/staging.env; set +a
    cd /srv/kivou/validation/company-profile-pr59
    export KIVOU_VALIDATION_DATABASE_URL=\$(.venv/bin/python -c \
      '\''import os; from sqlalchemy.engine import make_url;
         print(make_url(os.environ[\"KIVOU_DATABASE_URL\"]).set(database=\"kivou_profile_validation_pr59\"))'\'')
    PYTHONPATH=src:tests .venv/bin/python company-profile-postgres-validation.py"'
```

The script creates only synthetic `@example.test` accounts in the disposable
clone. It materializes four bundled public-notice fixtures, grants one Scale
subscription through the existing synchronization helper, grants one
permanent Discovery signal through `discovery.grant_up_to_limit`, then resolves
both profiles through `billing.feedable_target_icps`, `feed_access`,
`query.feed_page`, `ensure_company_for_unlocked_signal`, and
`company_profile_for_account`. Every related signal is rechecked through
`query.owned_signal` and `access.is_unlocked`; output contains only opaque keys
and aggregates.

Expected: `paid_profile_access=pass` and `discovery_profile_access=pass`.

- [ ] **Step 3: Exercise HTTP 404 non-disclosure**

The same script opens application sessions only for its synthetic clone
accounts and builds the real FastAPI app on PostgreSQL. It asserts the exact
same `company_not_found` envelope for an unknown opaque key, another account's
company, a locked-only company, an invalidated signal, and an old ICP revision.
It additionally asserts that no Apollo, website, official-identity, or related-
signal field occurs in those error responses.

Expected for all five checks: HTTP `404`, code `company_not_found`, identical public envelope, no company name, official identifier, website, signal fact, or Apollo field.

- [ ] **Step 4: Record company creation and association metrics after access**

```sql
SELECT count(*) AS companies_created FROM saas_company;
SELECT count(*) AS duplicate_company_fingerprints FROM (
  SELECT identity_fingerprint FROM saas_company
  GROUP BY identity_fingerprint HAVING count(*) > 1
) duplicates;
SELECT count(*) AS indexed_signals
 FROM materialized_signal
 WHERE company_identity_fingerprint IS NOT NULL;
SELECT count(*) AS orphan_company_origins
 FROM saas_company c
 LEFT JOIN materialized_signal s ON s.signal_key = c.origin_signal_key
 WHERE s.signal_key IS NULL;
```

Expected: at least one company from each exercised access path, zero duplicates, zero orphan origins.

### Task 5: Test supported downgrade on the disposable database

**Remote resource:** `kivou_profile_validation_pr59` only.

- [ ] **Step 1: Confirm downgrade is declared and isolated**

The repository migration defines `downgrade()` for `0022`; therefore test it only on the clone after all forward evidence is recorded.

- [ ] **Step 2: Downgrade to `0021_reliability_operations`**

```bash
.venv/bin/alembic downgrade 0021_reliability_operations
```

Expected: `saas_company` is absent, `company_identity_fingerprint` is absent, all pre-existing signal/account/ICP counts equal the restored baseline, and revision is `0021_reliability_operations`.

- [ ] **Step 3: Re-upgrade to `0022_saas_company_profile`**

```bash
.venv/bin/alembic upgrade 0022_saas_company_profile
```

Expected: revision restored to `0022_saas_company_profile`, backfill coverage restored, duplicate count `0`.

### Task 6: Deploy the exact PR SHA to staging

**Remote live paths:**
- Modify: `/srv/kivou/app` checkout and generated environments/assets
- Restart: `kivou-api.service`
- Do not modify: production, Stripe LIVE, acquisition autonomy, provider configuration

- [ ] **Step 1: Take a fresh verified backup before deployment**

After fetching the PR SHA, run the versioned `ops/bin/kivou-backup.sh` with `/etc/kivou/staging.env` and verify the resulting archive with `pg_restore --list`. Record filename and size; never print the database URL.

- [ ] **Step 2: Record rollback artifact**

```text
previous_sha=48632e5cbb300fa070b9ce8c8d6dfa9de10f8bfe
rollback_application=checkout previous_sha, restore locked dependencies/assets, restart kivou-api
rollback_database=not required because 0022 is additive and old code ignores it
```

- [ ] **Step 3: Build exact PR SHA before changing the running process**

```bash
sha=$(git rev-parse origin/feat/saas-company-profile-apollo)
git checkout --detach "$sha"
uv sync --frozen --extra server --extra postgres
cd frontend && npm ci && npm run build
```

Expected: checked-out SHA equals PR head, lockfiles remain clean, build exits `0`.

- [ ] **Step 4: Migrate live staging exactly once and restart API**

```bash
uv run alembic upgrade 0022_saas_company_profile
sudo systemctl restart kivou-api.service
```

Expected: service active, shallow health succeeds, served frontend assets come from the exact checkout, current revision is `0022_saas_company_profile`.

### Task 7: Validate the real staging page and release the draft gate

**Tool:** Playwright CLI wrapper `/home/jaybe/.codex/skills/playwright/scripts/playwright_cli.sh`

- [ ] **Step 1: Create a synthetic staging account through the real UI**

Use an `@example.test` address unique to this validation. Complete signup and onboarding through the public staging origin; do not use a real customer's credentials or copy protected facts into browser storage.

- [ ] **Step 2: Validate the protected path**

Open one unlocked signal, follow `Voir la fiche entreprise`, and verify:

```text
URL contains only an opaque /app/companies/cmp_ route segment;
official company name and public source are visible;
at least one accessible related signal is visible;
no locked signal or personal contact appears;
back navigation works;
sessionStorage contains no company facts;
no browser console error occurs.
```

- [ ] **Step 3: Recheck responsive and keyboard behavior**

At 1440, 1024, 768, 390, and 320 px verify one `h1`, one `main`, no horizontal overflow, visible focus, reachable actions, and safe external-link attributes.

- [ ] **Step 4: Make PR #59 ready only after every prior gate passes**

```bash
gh pr ready 59
gh pr view 59 --json isDraft,headRefOid,state,statusCheckRollup
```

Expected: `isDraft=false`, exact deployed SHA equals `headRefOid`, CI green. Do not merge the PR.

### Task 8: Cleanup and evidence report

- [ ] **Step 1: Remove only disposable validation resources**

After evidence is captured and staging validation passes:

```bash
sudo -u postgres dropdb kivou_profile_validation_pr59
git -C /srv/kivou/app worktree remove /srv/kivou/validation/company-profile-pr59
```

Resolve both targets explicitly before removal. Do not remove backups, staging data, user work, or the deployed checkout.

- [ ] **Step 2: Deliver the evidence**

Report backup filename/size, restored baseline revision/counts, migration and backfill durations, companies created, duplicates, indexed/null signals, orphan associations, paid/Discovery results, four 404 results, downgrade/re-upgrade results, deployed SHA, service/health status, browser results, PR ready state, cleanup status, and every remaining production limitation.
