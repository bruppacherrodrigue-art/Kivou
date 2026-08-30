# Card Presentation Staging Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy only the final merged and green `main` SHA to Kivou staging, verify and migrate PostgreSQL from `0027_signal_notes` to `0028_card_presentation`, publish backend and frontend atomically, backfill factual artifacts on one explicitly approved QA account, and collect desktop/mobile smoke evidence without touching production.

**Architecture:** Promotion is SHA-led and staging-only. A verified custom-format backup and scratch restore precede the additive migration. The existing versioned blue/green backend procedure publishes the same SHA used by an immutable frontend release and atomic symlink switch. Backfill is two explicit bounded invocations (`fr`, then `en`) and can produce only offline `FALLBACK/FACTUAL_FALLBACK` rows with null provider metadata. Application rollback switches both symlinks/releases back but deliberately retains additive migration 0028.

**Tech Stack:** GitHub CLI, SSH, systemd, PostgreSQL/pg_dump/pg_restore, SQLAlchemy/Alembic internal API, uv, npm/Vite, nginx, Playwright.

---

## Non-negotiable boundary

- Operate only through SSH alias `kivou-staging`, whose remote short hostname must equal `kivou-staging-01`.
- Do not open an SSH session, API session, DNS change, CI deploy or provider console for production.
- Do not run provider/model/prompt/QA-model workers. Do not read, copy or reuse Hermes credentials/configuration.
- Abort before the first mutation if the final `main` SHA, exact-main CI, staging hostname, current release, current database revision, backup unit, QA-account approval or versioned rollout procedure is not provable.

## Evidence directory

Create locally with `apply_patch` only when execution begins:

```text
artifacts/staging/card-presentation-$KIVOU_FINAL_SHORT/
  release-evidence.md
  github-ci.json
  database-evidence.txt
  backend-evidence.txt
  frontend-evidence.txt
  backfill-evidence.txt
  smoke-desktop/
  smoke-mobile/
  final-report.md
```

Never store cookies, passwords, environment-file contents, database URLs,
provider settings, customer payloads or raw source facts in this directory.

## Task 1: Pin final `main` and prove real exact-SHA CI

**Local resources:**

- Read: `.github/workflows/ci.yml`
- Read: final five merged PRs
- Create: evidence files above

- [ ] **Step 1: Resolve the immutable final SHA**

```bash
git fetch origin main
KIVOU_FINAL_SHA=$(git rev-parse origin/main)
KIVOU_FINAL_SHORT=$(git rev-parse --short=12 origin/main)
test "$(git rev-parse origin/main^{tree})" = "$(gh api repos/bruppacherrodrigue-art/Kivou/git/commits/$KIVOU_FINAL_SHA --jq .tree.sha)"
```

Record the five squash SHAs and confirm the fifth is an ancestor of this final
SHA. If `origin/main` advances during any later step, stop, reassess the delta
and require new exact-SHA CI; never silently deploy the older SHA.

- [ ] **Step 2: Resolve the successful push run**

```bash
KIVOU_CI_RUN_ID=$(gh run list --repo bruppacherrodrigue-art/Kivou --workflow CI --branch main --commit "$KIVOU_FINAL_SHA" --event push --status success --limit 1 --json databaseId,headSha,conclusion --jq '.[0].databaseId')
test -n "$KIVOU_CI_RUN_ID"
gh run view "$KIVOU_CI_RUN_ID" --repo bruppacherrodrigue-art/Kivou --json headSha,status,conclusion,jobs > artifacts/staging/card-presentation-$KIVOU_FINAL_SHORT/github-ci.json
```

- [ ] **Step 3: Validate actual Backend and Frontend steps**

Use `jq -e` to require exact `headSha`, overall success, exactly one Backend and
one Frontend job, job success, and a non-empty `steps` array. For Backend require
checkout, uv installation, dependency sync, Tests and Lint. For Frontend require
checkout, Node/npm setup, Tests, Chromium install, visual regression, Build,
Typecheck and Lint. A run like historical #328/#329/#330 with no allocated
runner and no executed steps is rejected even if a check name exists.

- [ ] **Step 4: Recheck remote main immediately before SSH**

Run: `test "$(gh api repos/bruppacherrodrigue-art/Kivou/commits/main --jq .sha)" = "$KIVOU_FINAL_SHA"`

Expected: PASS. Freeze this SHA in the evidence report.

## Task 2: Preflight staging and capture both rollback targets

**Remote read-only resources:**

- `/srv/kivou/app`
- `/srv/kivou/frontend`
- `/etc/kivou/staging.env` metadata only
- `kivou-api.service`, `nginx`, backup timer/unit

- [ ] **Step 1: Prove the host and service boundary**

```bash
ssh kivou-staging 'set -eu
  test "$(hostname -s)" = kivou-staging-01
  test -L /srv/kivou/app
  test -L /srv/kivou/frontend
  test "$(stat -c "%U:%G:%a" /etc/kivou/staging.env)" = root:kivou:600
  systemctl is-active --quiet kivou-api.service
  systemctl is-active --quiet nginx
  systemctl is-enabled --quiet kivou-backup.timer
  curl --silent --show-error --fail --connect-timeout 3 --max-time 5 http://127.0.0.1:8000/openapi.json >/dev/null'
```

Do not source or print `staging.env` during this check.

- [ ] **Step 2: Capture explicit rollback targets**

Resolve `/srv/kivou/app` and `/srv/kivou/frontend` with `readlink -f`. Accept
only paths matching `/srv/kivou/releases/backend-*` and
`/srv/kivou/releases/frontend-*`. Record their basename and backend Git SHA,
then verify both directories exist and are not writable by non-owner users.

- [ ] **Step 3: Prove the current migration revision through the running release**

Run an isolated `systemd-run --wait --collect --pipe` as user/group `kivou`,
with `/etc/kivou/staging.env` as `EnvironmentFile`, invoking:

```python
from signals.persistence.database import create_database_engine, current_revision
engine = create_database_engine()
revision = current_revision(engine)
assert revision == "0027_signal_notes", revision
print(revision)
```

Expected: exactly `0027_signal_notes`; no URL or exception payload is printed.
Any other revision stops the rollout for review.

- [ ] **Step 4: Confirm the versioned procedure contains the atomic frontend switch**

At the final SHA, read all of
`docs/runbooks/11-staging-card-presentation-rollout.md`. Require immutable
`frontend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT`, temporary symlink,
`mv -Tf`, public HTTP verification and explicit reverse switch to the captured
previous frontend target. If this exact operator sequence is absent or differs
from the proven staging topology, stop for owner validation before mutation.

## Task 3: Create, hash, list and scratch-restore a fresh PostgreSQL backup

**Remote mutation:** one backup file and one explicitly named temporary database.

- [ ] **Step 1: Trigger a fresh backup**

Capture UTC start time, start `kivou-backup.service`, require its result to be
`success`, and resolve exactly one new `/srv/kivou/backups/kivou-*.dump` created
after the captured time. Refuse zero or multiple matches.

- [ ] **Step 2: Verify archive permissions, size, hash and table of contents**

Require owner `kivou`, mode `600`, size at least the configured minimum, then
run as `kivou`:

```bash
sha256sum "$KIVOU_BACKUP_FILE"
pg_restore --list "$KIVOU_BACKUP_FILE"
```

Store only filename, byte count, SHA-256, TOC line count and exit codes in
evidence. Do not copy the dump into the repository.

- [ ] **Step 3: Restore into a unique scratch database**

Set `KIVOU_RESTORE_DB=kivou_card_restore_$KIVOU_FINAL_SHORT`. Validate it with
`case "$KIVOU_RESTORE_DB" in kivou_card_restore_[0-9a-f][0-9a-f]*) ;; *) exit 64 ;; esac`
and prove it does not exist. Resolve the live database owner without displaying
credentials, create it from `template0`, then run:

```bash
sudo -u postgres pg_restore --exit-on-error --no-owner --no-privileges --dbname="$KIVOU_RESTORE_DB" "$KIVOU_BACKUP_FILE"
```

- [ ] **Step 4: Verify the restored database**

Query only aggregate evidence: revision must be `0027_signal_notes`; core tables
`account`, `target_icp`, `materialized_signal`, `contract_award` and
`alembic_version` exist; their counts are nonnegative; database size is
positive. Run `ANALYZE` only on the scratch database if needed.

- [ ] **Step 5: Remove only the validated scratch database**

After successful proof, revalidate the exact name and use
`sudo -u postgres dropdb "$KIVOU_RESTORE_DB"`. Confirm it no longer exists.
The verified backup remains available for recovery.

## Task 4: Prepare the immutable backend release and apply 0028

**Remote resources:**

- Create: `/srv/kivou/releases/backend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT`
- Read: versioned backend release section in `ops/README.md`

- [ ] **Step 1: Build the release from remote `main`, never a branch ref**

Execute the exact GitHub-known-host, deploy-key isolation and immutable release
preparation in `ops/README.md`. Set `KIVOU_RELEASE_SHA` to the frozen final SHA,
verify `ls-remote refs/heads/main` equals it, fetch into a detached release,
run `uv sync --frozen --extra server --extra postgres`, and prove Git status is
clean. Do not reuse `/srv/kivou/app` as a build directory.

- [ ] **Step 2: Recheck code/database migration pair**

From the new release, assert Alembic has one head
`0028_card_presentation`, the live database is still `0027_signal_notes`, and
the migration file has `down_revision = "0027_signal_notes"`.

- [ ] **Step 3: Apply migration with the internal API in an isolated unit**

Use a unique unit `kivou-card-migrate-$KIVOU_FINAL_SHORT`, user/group `kivou`,
working directory equal to the immutable backend release and protected
`EnvironmentFile`. Invoke the new release Python with:

```python
from signals.persistence.database import create_database_engine, current_revision, migrate_to_latest
engine = create_database_engine()
before = current_revision(engine)
assert before == "0027_signal_notes", before
migrate_to_latest(engine)
after = current_revision(engine)
assert after == "0028_card_presentation", after
print(f"migration={before}->{after}")
```

Expected: unit success and only the revision transition in stdout.

- [ ] **Step 4: Verify additive schema and empty publication state**

Read-only SQL must prove one `card_presentation_artifact` table, all expected
constraints/indexes, zero rows for the approved QA account before backfill, and
the prior tables/counts unchanged. Never run `alembic downgrade` automatically.

## Task 5: Publish backend blue/green from the exact final SHA

**Remote procedure:** `ops/README.md`, section `Reverse proxy public de staging (#84)`.

- [ ] **Step 1: Capture the rollout state and render the isolated nginx candidate**

Execute the versioned candidate/evidence blocks exactly. Require the captured
previous backend release to equal Task 2 and `nginx -t` on the isolated
candidate to succeed.

- [ ] **Step 2: Start and prove green on port 8001**

Start `kivou-api-green.service` from the new release. Require versioned readiness,
`/openapi.json=200`, `/me=401`, active unit and no startup traceback. Confirm the
runtime sees revision `0028_card_presentation`.

- [ ] **Step 3: Execute the monitored atomic backend switch**

Run the documented public status monitor, safe nginx bundle publication,
single reload to green, atomic `/srv/kivou/app` symlink `mv -Tf`, versioned
service install/restart on 8000 and proxy return. Require every monitor row to
be `200 401` and stop the green unit only after normal readiness succeeds.

- [ ] **Step 4: Prove exact backend deployment**

Require `/srv/kivou/app` to resolve to the new immutable release, its `HEAD` to
equal `KIVOU_FINAL_SHA`, clean Git status, API active, public `/=200`, public
`/me=401`, internal migration head 0028 and no new error journal entries.

## Task 6: Build and atomically publish the frontend from the same SHA

**Remote resources:**

- Temporary: `/srv/kivou/releases/.frontend-build-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT`
- Immutable: `/srv/kivou/releases/frontend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT`
- Atomic link: `/srv/kivou/frontend`

- [ ] **Step 1: Validate paths and create an isolated source tree**

Construct both paths from the same `KIVOU_RELEASE_UTC` and
`KIVOU_RELEASE_SHORT`. Validate them with explicit `case` patterns, prove they
do not exist, and create them owned by `kivou`. Export the exact final source
using `git archive "$KIVOU_FINAL_SHA" frontend` from the immutable backend
release; do not build in `/home/ubuntu` or the live symlink.

- [ ] **Step 2: Build with a closed `kivou` environment**

As `kivou`, set `HOME=/srv/kivou`, an explicit `PATH`, and accessible working
directory. Run `npm ci`, `npm run build`, `npm run typecheck` and
`npm run lint`. Require `frontend/dist/index.html` and its referenced hashed
assets to exist. Write a root-owned release marker containing only the final
SHA into the immutable release after installing the built `dist` tree.

- [ ] **Step 3: Verify the immutable frontend before switching**

Serve the candidate temporarily on localhost or validate with the existing
nginx filesystem mapping. Request `/`, `/app/dashboard`, `/app/companies` and
`/app/signals`; verify SPA index and all referenced assets return 200. Confirm
the release marker equals the final SHA and target directory is not writable by
group/other.

- [ ] **Step 4: Switch the live frontend atomically**

Capture again that current `/srv/kivou/frontend` equals Task 2. Create a
temporary symlink in an explicit `/srv/kivou/.kivou-frontend-next.*` directory,
verify its resolved target, then execute
`sudo mv -Tf "$KIVOU_FRONTEND_NEXT" /srv/kivou/frontend`.
Immediately require public `/`, a hashed asset and each SPA deep route to return
200 without changing nginx or backend.

- [ ] **Step 5: Clean only the validated temporary build tree**

After success, validate the path starts exactly with
`/srv/kivou/releases/.frontend-build-` and remove it with a depth-first `find`
that names that resolved path explicitly. Retain both immutable old/new frontend
releases for rollback.

## Task 7: Approve one QA account and run separate factual FR/EN backfills

**Protected operator input:** `/etc/kivou/card-presentation-qa.env`.

- [ ] **Step 1: Require explicit owner-approved QA binding**

The file must already exist, be `root:kivou 640`, and contain exactly one
assignment whose key is `KIVOU_CARD_QA_ACCOUNT_ID` and whose value passes the
account-ID contract. Its creation is an owner approval gate,
not part of this rollout. If absent, malformed or pointing to a non-staging QA
account, stop and request validation. Never infer an account from email domains,
recent activity or a customer-like name.

- [ ] **Step 2: Verify account scope read-only**

Through a names/IDs-redacted check, prove exactly one active account matches,
it owns an active current ICP, has at least one currently accessible unlocked
signal, and the protected browser session used in Task 8 reports the same
`account_id`. Record only the opaque account ID fingerprint and aggregate counts.

- [ ] **Step 3: Run exactly one bounded FR page**

Use a transient `systemd-run --wait --collect --pipe` as `kivou` from the final
backend release with both protected environment files and execute:

```text
python -m signals.card_intelligence backfill-fallbacks --account-id "$KIVOU_CARD_QA_ACCOUNT_ID" --as-of "$KIVOU_BACKFILL_AS_OF" --language fr --limit 50 --offset 0
```

Do not follow `next_offset` automatically. Require exit 0, `scanned<=50`,
`published<=50`, zero item failures and no content/credentials in the journal.

- [ ] **Step 4: Run exactly one bounded EN page separately**

Run a new transient unit with the same bounds and `--language en`. Do not reuse
the FR process/transaction and do not loop.

- [ ] **Step 5: Verify publication truthfulness in SQL**

For only the approved account, require languages exactly `fr` and `en`, every
published row `qa_status='FALLBACK'`, every variant
`FACTUAL_FALLBACK`, every claim has non-empty evidence, and `provider`,
`model_id`, `prompt_version`, `qa_provider`, `qa_model_id` are all `NULL`.
Require no `PASS/FULL`, no row for another account, no duplicate active key and
no malformed public payload. This is the explicit AI activation proof: disabled.

## Task 8: Run authenticated desktop and mobile staging smoke tests

**Local browser evidence:** Playwright using an existing protected staging QA
storage state whose account matches Task 7. Never print or commit it.

- [ ] **Step 1: Establish browser failure collectors**

At 1440×900 and 390×844, collect `pageerror`, unexpected console errors,
request failures and HTTP 5xx. Fail the smoke on any finding. Verify the first
authenticated `/me` response account ID equals the approved QA binding without
recording email or cookie values.

- [ ] **Step 2: Smoke C001 Dashboard**

Open `/app/dashboard`; verify heading, factual published summaries, maximum six
cards, qualified dates, explicit buyer/awardee, missing values, one CTA deep
link carrying an artifact ID and no administrative title used as a headline.
Capture desktop and mobile screenshots.

- [ ] **Step 3: Smoke C002 Companies**

Open `/app/companies`; verify award rows, no browser fan-out to
`/signals/:id`, desktop independent list/detail scrolling, selection URL
`/app/companies/:companyKey?signal=:signalId`, direct reload, browser Back and
Forward, focus restoration, mobile list→detail, `Retour aux entreprises`,
selected profile facts and canonical Signals link. Capture both viewports.

- [ ] **Step 4: Smoke C003 Signals**

Open `/app/signals`; verify list/detail exact artifact ID/version, feed
selection, direct deep link/reload, historical lookup behavior, browser Back
and Forward, desktop independent scroll, mobile `Retour aux signaux`, focus
restoration, note field loading without mutation, canonical Company link and
no raw-title headline. Verify all displayed staging artifacts are factual
fallbacks.

- [ ] **Step 5: Smoke locked teasers and privacy**

Using an approved account state with a locked item, inspect the network JSON and
DOM: locked item has no `presentation` or `company_key`, no company/awardee
identity, no detail/note request, and routes to the real billing capability.
Do not unlock or purchase anything.

- [ ] **Step 6: Verify final public/runtime state after browser load**

Recheck frontend symlink marker, backend SHA, migration 0028, service/nginx
health, public statuses and journals since the rollout cursor. Require no
provider call, generation worker, unhandled exception or browser console error.

## Task 9: Prepare and, only if needed, execute application rollback

- [ ] **Step 1: Validate both captured previous releases**

Recheck the exact Task 2 backend/frontend targets still exist, match the allowed
path patterns, and have not changed. Prepare temporary rollback symlinks but do
not switch them during a healthy rollout.

- [ ] **Step 2: Define rollback trigger**

Rollback on API readiness loss, repeated 5xx, wrong served SHA, migration
incompatibility, broken SPA/assets, artifact mismatch, privacy leak, browser
console/request failure or an unfixable smoke regression. A missing approved QA
account before backfill is a stop, not a reason to mutate production or enable AI.

- [ ] **Step 3: Roll back frontend and backend applications atomically**

Frontend: validate a temporary symlink to the exact previous frontend release,
`mv -Tf` it onto `/srv/kivou/frontend`, then verify public routes/assets.
Backend: use the versioned application recovery sequence and exact prior backend
release, green readiness and public monitor before switching `/srv/kivou/app`.

- [ ] **Step 4: Retain migration 0028**

Do not automatically execute `alembic downgrade`. The migration is additive and
the previous application must tolerate the extra table. Preserve factual rows
for diagnosis. A schema downgrade requires a separate owner-approved incident
procedure.

- [ ] **Step 5: Verify rollback state**

Require previous frontend/backend release targets, healthy public/API routes,
database still at `0028_card_presentation`, no production change and recorded
incident evidence.

## Task 10: Produce the final evidence-backed report

Create `final-report.md` with these exact sections:

1. Replacement PRs and drafts closed;
2. five squash SHAs and final `main` SHA;
3. PR and final-main GitHub Actions run IDs, job/step conclusions;
4. local and staging desktop/mobile captures inspected;
5. backup filename/hash/restore verification and migration transition;
6. backend and frontend staging releases plus deployed SHA;
7. FR and EN bounded backfill counts;
8. Dashboard/Companies/Signals smoke matrix;
9. deep-link, Back/Forward, focus, scroll, locked teaser and console results;
10. rollback targets and whether rollback was executed;
11. remaining limitations;
12. explicit AI status.

The final AI line must be:

```text
Activation IA : DÉSACTIVÉE — aucun provider, modèle, prompt, QA provider ou worker live approuvé ; staging limité à l’architecture et aux FALLBACK/FACTUAL_FALLBACK factuels hors GET.
```

State explicitly: `Production : aucun déploiement, aucune mutation.`
