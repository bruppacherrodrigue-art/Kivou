# Stendhal Electrical Assisted Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to execute this plan task by task.

**Goal:** Replace the exhausted timber targeting with the validated Stendhal/SPIE electrical opportunity, enrich SPIE, and materialize at most eight new site-sourced prospects in `pending_review` without sending anything.

**Architecture:** Keep the production acquisition runtime in `ASSISTED` mode and pin one mono-family opportunity (`electrical`). Add a preparation-level invariant that the named holder can never become its own prospect, including in strict holder-family mode. Deploy the tested code, atomically align the host-owned runtime configuration, enrich only SPIE, then run exactly one bounded preparation and verify the database and Founder API separately from any provider-delivery state.

**Tech Stack:** Python 3.12, SQLAlchemy, PostgreSQL, pytest, JSON runtime configuration, systemd, nginx, SSH.

---

## Non-negotiable safety envelope

- Never call `POST /api/founder/actions/prospection/send`.
- Never call any Instantly endpoint, including read-only diagnostics.
- Never change any existing `sent` row; record the count before and after.
- Never prepare more than once and never prepare more than eight targets.
- Keep every prepared target in `pending_review`, with `family_key='electrical'` and `email_source='site'`.
- Exclude holder SIREN `440055861` (SPIE BUILDING SOLUTIONS) from the target set.
- Keep the signal pinned to `opp_66e58fd25659ae991caefd864382366b8f7e` and reject any cycle whose materialized families are not exactly `['electrical']`.
- If holder enrichment still yields no website, phone, or published professional email, the queue may be prepared but the handoff must state: `ne pas envoyer tant que titulaire pauvre`.
- Abort before preparation if the `sent` baseline changes, the pinned opportunity no longer resolves to Stendhal/SPIE, or the prospective cycle is not mono-family electrical.

## Task 1: Lock holder self-exclusion with a regression test

**Files:**

- Modify: `tests/test_assisted_prospect_preparation.py`
- Modify: `src/signals/prospection_actions/preparation.py`

- [ ] Add a dedicated regression test after `test_strict_family_preparation_targets_the_promised_holder_family`:

```python
def test_strict_family_preparation_never_targets_the_named_holder(
    migrated_sqlite_engine,
) -> None:
    seed_directory(migrated_sqlite_engine, 20, eligible_department_count=20)
    holder_siren = "100000004"
    with migrated_sqlite_engine.begin() as connection:
        connection.execute(
            sa.update(supplier_directory)
            .where(supplier_directory.c.siren == holder_siren)
            .values(family_confirmation_status="confirmed")
        )

    result = ProspectPreparationService(
        migrated_sqlite_engine, link_issuer=Links(), clock=lambda: NOW
    ).prepare(
        signal(
            holder_siren=holder_siren,
            holder_family_required=True,
            target_holder_family=True,
            families=(("ready_mix_concrete", "Béton prêt à l'emploi"),),
        ),
        cycle_ref="cycle-strict-holder-exclusion",
    )

    assert result.prepared == 8
    with migrated_sqlite_engine.connect() as connection:
        queued_sirens = set(
            connection.execute(sa.select(prospect_target.c.siren)).scalars()
        )
    assert holder_siren not in queued_sirens
```

- [ ] Run the new test alone and confirm it fails because `100000004` is currently queued:

```bash
uv run pytest -q tests/test_assisted_prospect_preparation.py::test_strict_family_preparation_never_targets_the_named_holder
```

Expected: `1 failed`, on `assert holder_siren not in queued_sirens`.

- [ ] Add the minimal invariant inside the directory candidate loop, before email/history/family selection:

```python
if signal.holder_siren is not None and row["siren"] == signal.holder_siren:
    continue
```

- [ ] Re-run the focused test and the complete preparation suite:

```bash
uv run pytest -q tests/test_assisted_prospect_preparation.py::test_strict_family_preparation_never_targets_the_named_holder
uv run pytest -q tests/test_assisted_prospect_preparation.py
uv run ruff check src/signals/prospection_actions/preparation.py tests/test_assisted_prospect_preparation.py
```

Expected: all commands pass.

- [ ] Commit the isolated behavior change:

```bash
git add src/signals/prospection_actions/preparation.py tests/test_assisted_prospect_preparation.py
git commit -m "fix(acquisition): exclude awarded holder from prospects"
```

## Task 2: Pin the production runtime to Stendhal electrical

**Files:**

- Modify: `ops/host/acquisition-runtime.production.json`
- Modify: `tests/test_acquisition_runtime_config_production.py`

- [ ] Add a repository-configuration contract test that reads the committed production document and proves the exact targeting boundary:

```python
def test_committed_production_targeting_is_stendhal_electrical() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "ops"
        / "host"
        / "acquisition-runtime.production.json"
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    deployment = AcquisitionRuntimeDeployment.model_validate(document)

    assert deployment.mode.value == "ASSISTED"
    assert deployment.qa_scope.vertical == "technical_installation"
    assert deployment.selection is not None
    assert deployment.selection.vertical == "technical_installation"
    assert deployment.selection.family_key == "electrical"
    assert deployment.selection.email_source == "site"
    assert deployment.selection.pinned_opportunity_key == (
        "opp_66e58fd25659ae991caefd864382366b8f7e"
    )
```

- [ ] Run that test before editing the JSON and confirm it fails on the existing timber configuration:

```bash
uv run pytest -q tests/test_acquisition_runtime_config_production.py::test_committed_production_targeting_is_stendhal_electrical
```

Expected: `1 failed` because the committed family is `timber_carpentry`.

- [ ] Change only these production JSON values, keeping `ASSISTED`, region, `site`, limits, safety flags, and provider mode unchanged:

```json
"qa_scope": {
  "country": "FR",
  "language": "fr",
  "wedge": "general_building",
  "vertical": "technical_installation",
  "region": "Auvergne-Rhône-Alpes"
},
"selection": {
  "mode": "dynamic",
  "allowed_opportunity_keys": [],
  "vertical": "technical_installation",
  "region": "Auvergne-Rhône-Alpes",
  "family_key": "electrical",
  "email_source": "site",
  "pinned_opportunity_key": "opp_66e58fd25659ae991caefd864382366b8f7e",
  "window_days": 30,
  "minimum_amount": 50000.0,
  "require_named_holder": true,
  "require_nonempty_object": true,
  "require_model_fit": true
}
```

- [ ] Run the focused contract and production configuration suites:

```bash
uv run pytest -q tests/test_acquisition_runtime_config_production.py
uv run pytest -q tests/test_acquisition_runtime_contracts_production.py
uv run pytest -q tests/test_acquisition_runtime_selection.py
uv run ruff check tests/test_acquisition_runtime_config_production.py
```

Expected: all commands pass.

- [ ] Commit the runtime targeting change:

```bash
git add ops/host/acquisition-runtime.production.json tests/test_acquisition_runtime_config_production.py
git commit -m "chore(acquisition): target Stendhal electrical prospects"
```

## Task 3: Verify and publish the executable SHA

**Files:**

- Verify: all files changed since production SHA `06b8ab1ce97bd2c072915766721aadaa71b2be90`

- [ ] Inspect the complete delta and prove it contains no sending or Instantly changes:

```bash
git diff --check 06b8ab1ce97bd2c072915766721aadaa71b2be90..HEAD
git diff --stat 06b8ab1ce97bd2c072915766721aadaa71b2be90..HEAD
git diff 06b8ab1ce97bd2c072915766721aadaa71b2be90..HEAD -- \
  src/signals/prospection_actions/preparation.py \
  tests/test_assisted_prospect_preparation.py \
  ops/host/acquisition-runtime.production.json \
  tests/test_acquisition_runtime_config_production.py
rg -n "Instantly|/send|prospection/send" \
  src/signals/prospection_actions/preparation.py \
  ops/host/acquisition-runtime.production.json
```

Expected: clean diff; the final search returns no new send/provider code.

- [ ] Run the consolidated verification:

```bash
uv run pytest -q \
  tests/test_assisted_prospect_preparation.py \
  tests/test_acquisition_runtime_config_production.py \
  tests/test_acquisition_runtime_contracts_production.py \
  tests/test_acquisition_runtime_selection.py \
  tests/founder_api/test_prospection.py
uv run ruff check \
  src/signals/prospection_actions/preparation.py \
  tests/test_assisted_prospect_preparation.py \
  tests/test_acquisition_runtime_config_production.py
```

Expected: all tests and Ruff pass.

- [ ] Push the current branch and record the full immutable SHA:

```bash
git status --short
git push origin HEAD:main
git rev-parse HEAD
```

Expected: clean worktree and one 40-character SHA available to deployment.

## Task 4: Snapshot production and deploy without preparing

**Files:**

- Read: `/etc/kivou/production.env`
- Read/modify atomically: `/etc/kivou/acquisition-production.json`
- Deploy: immutable Git SHA from Task 3

- [ ] Read-only snapshot the active SHA, current runtime selection, Stendhal opportunity, current queue counts, and `sent` baseline. Do not print secret environment values:

```bash
ssh kivou-production 'readlink -f /srv/kivou/app; sudo python3 - <<"PY"
import json
from pathlib import Path
p = Path("/etc/kivou/acquisition-production.json")
d = json.loads(p.read_text())
print(json.dumps({"mode": d["mode"], "qa_scope": d["qa_scope"], "selection": d["selection"]}, ensure_ascii=False, indent=2))
PY'
```

Then use a short SQLAlchemy read-only script under the production environment to print only:

- total `sent` count;
- counts by active queue status;
- opportunity key/title/holder SIREN/holder name/family keys for `opp_66e58fd25659ae991caefd864382366b8f7e`;
- current SPIE `website_url`, `phone`, `professional_email`, and evidence/source fields.

Expected preconditions: sent baseline is recorded (previously 22), queue has no row that would collide with the requested preparation, and the pinned opportunity is Stendhal/SPIE with materialized family keys exactly `['electrical']`. Abort if any precondition differs materially.

- [ ] Record whether `kivou-acquisition-production.timer` is active, then stop that timer for the short config/deploy/prepare window. Do not stop or invoke any send service:

```bash
ssh kivou-production 'systemctl is-active kivou-acquisition-production.timer || true'
ssh -tt kivou-production "sudo systemctl stop kivou-acquisition-production.timer"
```

This prevents an hourly preparation from racing the one authorized preparation. Restore the timer only if the first command reported `active`.

- [ ] Fetch the SHA on production, then deploy it with the standard backup/migration/readiness script:

```bash
KIVOU_STENDHAL_SHA=$(git rev-parse HEAD)
test "${#KIVOU_STENDHAL_SHA}" -eq 40
ssh -tt kivou-production "sudo bash -lc 'set -a; source /etc/kivou/production.env; set +a; git -c safe.directory=/srv/kivou/source -C /srv/kivou/source fetch origin main; /srv/kivou/source/ops/bin/kivou-deploy.sh production $KIVOU_STENDHAL_SHA'"
```

Expected: backup succeeds, migration rehearsal succeeds, services are healthy, and the release reports the value of `KIVOU_STENDHAL_SHA` active.

- [ ] Atomically align the host-owned runtime configuration with the deployed, tested file, preserving a timestamped rollback copy:

```bash
ssh -tt kivou-production "sudo bash -lc 'set -Eeuo pipefail; stamp=20260918-stendhal-electrical; cp -a /etc/kivou/acquisition-production.json /etc/kivou/acquisition-production.json.\$stamp.bak; install -o root -g kivou -m 0640 /srv/kivou/app/ops/host/acquisition-runtime.production.json /etc/kivou/acquisition-production.json; python3 -m json.tool /etc/kivou/acquisition-production.json >/dev/null'"
```

Do not start a service manually. The preparation itself remains Task 6 and must run exactly once.

- [ ] Re-read the installed host JSON and assert, without displaying secrets:

```text
mode=ASSISTED
qa_scope.vertical=technical_installation
selection.vertical=technical_installation
selection.family_key=electrical
selection.email_source=site
selection.pinned_opportunity_key=opp_66e58fd25659ae991caefd864382366b8f7e
```

## Task 5: Enrich only the SPIE holder and evaluate landing readiness

**Files:**

- Execute: `src/signals/company_research/replay.py`
- Read: production `supplier_directory` row for SIREN `440055861`

- [ ] Run one forced, single-worker, single-SIREN enrichment under the production application identity:

```bash
ssh -tt kivou-production "sudo bash -lc 'set -a; source /etc/kivou/production.env; source /etc/kivou/acquisition-production.env; set +a; cd /srv/kivou/app; runuser -u kivou --preserve-environment -- /srv/kivou/app/.venv/bin/python -m signals.company_research.replay --siren 440055861 --force --workers 1 --limit 1 --batch-id stendhal-spie-20260918'"
```

Expected: cohort 1, processed 1, no error. A budget/provider failure does not authorize broadening the cohort or changing providers; record it and continue only with the existing holder facts.

- [ ] Query the single SPIE row and record these non-secret fields:

```text
siren, legal_name, family_keys, family_confirmation_status,
website_url, domain, domain_validation_method,
phone, phone_source,
professional_email, email_source, email_evidence_url,
enrichment_observed_at
```

- [ ] Set the final landing-readiness verdict:

  - ready for review if at least one of `website_url`, `phone`, or a published professional email is populated;
  - otherwise preserve the queue workflow but attach the exact warning `ne pas envoyer tant que titulaire pauvre`.

## Task 6: Run exactly one bounded preparation

**Files:**

- Execute: `python -m signals.acquisition_runtime prepare-queue --max-signals 1`

- [ ] Immediately before the mutation, recheck that the `sent` count equals Task 4's baseline and that no new queue was created concurrently. Abort on drift.

- [ ] Execute one preparation under the production lock:

```bash
ssh -tt kivou-production "sudo bash -lc 'set -a; source /etc/kivou/production.env; source /etc/kivou/acquisition-production.env; set +a; cd /srv/kivou/app; runuser -u kivou --preserve-environment -- /usr/bin/flock --verbose --nonblock --conflict-exit-code 75 /run/kivou/acquisition.lock /srv/kivou/app/.venv/bin/python -m signals.acquisition_runtime prepare-queue --max-signals 1'"
```

Expected: one Stendhal cycle is prepared or a precise no-target reason is reported. Do not retry on failure without a new diagnosis and user authorization.

- [ ] Confirm no timer or worker performed a send during the operation. This is a database/service-log check only; do not query Instantly.

- [ ] If `kivou-acquisition-production.timer` was active before Task 4, restore it without triggering the service immediately:

```bash
ssh -tt kivou-production "sudo systemctl start kivou-acquisition-production.timer"
```

## Task 7: Prove the acceptance recipe and report two non-sent previews

**Files:**

- Read: PostgreSQL production state
- Read: local Founder API `GET /api/founder/prospection`

- [ ] Query the new cycle and assert all of the following:

```text
targeting.family_keys == ['electrical']
signal.opportunity_key == opp_66e58fd25659ae991caefd864382366b8f7e
signal title describes Stendhal electricity (courants forts / courants faibles)
0 <= pending_review_count <= 8
approved_count == 0 for the new cycle
sent_count == the recorded baseline
every target family_key == electrical
every target email_source == site
no target siren == 440055861
```

If fewer than three rows exist, stop and report the honest fresh-site count; do not widen family, source, geography, or signal.

- [ ] For every pending row, prove the unique kat1 identity and link consistency:

```text
attribution_url is nonempty
attribution_url occurs in mail_text
attribution_url occurs in mail_html
one target has one attribution token
```

- [ ] Read the Founder API locally using `/etc/kivou/founder.env` and the configured founder headers. Confirm the API agrees with the database on family, signal, statuses, and count. Do not print header secrets.

- [ ] Inspect two preview rows, returning company name, subject, redacted body excerpt, and their non-sent kat1 URLs. Assert case-insensitively that neither preview contains:

```text
charpente, bardage, tzen, vestiaire, toiture, échafaudage, scaffolding, roofing
```

Both previews must refer to Stendhal and electrical work (`électricité`, `courants forts`, or `courants faibles`).

- [ ] Run a final immutable-state check:

```text
active release SHA == Task 3 SHA
sent total == Task 4 baseline
new sent rows == 0
new approved rows == 0
all new rows == pending_review
```

- [ ] Deliver the outcome in French with:

  - retained family: `electrical`;
  - retained notice and holder: Stendhal / SPIE, with opportunity key;
  - holder enrichment result and landing-readiness warning if necessary;
  - exact `N` pending rows (`N <= 8`), all `site` and electrical;
  - two non-sent kat1 URLs when `N >= 2`;
  - `sent` before/after;
  - deployed SHA;
  - explicit confirmation: no `/send` and no Instantly call.
