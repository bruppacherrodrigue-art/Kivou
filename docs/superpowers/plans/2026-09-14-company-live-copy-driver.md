# Company live copy driver implementation plan

> **For agentic workers:** Execute the root-approved bounded task with TDD.
> Root owns independent review, commits and every remote execution.

**Goal:** Create an isolated, verified database restoration for the versioned
company checker, retaining the backup and private evidence on every outcome.

**Architecture:** A self-contained operator script validates explicit local
source/admin DSNs and source/candidate artifacts before any mutation. It invokes
the candidate's tracked backup/checker scripts with minimal environments, owns
one unpredictable copy name/OID, and reaps each owned child group before cleanup.

**Tech stack:** Python stdlib, psycopg, SQLAlchemy URL parsing; offline pytest.

## Approved interface and boundaries

`company-live-copy-driver.py --environment STAGING|PRODUCTION --sha SHA40
--source-sha SHA40 --source-root /srv/kivou/releases/exact-active-release
--candidate-root /absolute/release [--execute] [--keep-copy]`.

Without `--execute`, only configuration/artifact/source read-only/disk checks
run. Source/admin DSNs arrive through protected `KIVOU_DATABASE_URL` and
`KIVOU_MIGRATION_ADMIN_URL`. Both require literal `127.0.0.1`, port 5432
(omission means PostgreSQL's default and is normalized explicitly), no query
options, and exact database names (`kivou_staging`/`kivou`, `postgres`).

The explicit source root accommodates real timestamped production release names;
it must be an immediate physical child of `/srv/kivou/releases`, equal the active
backend symlink, and carry the exact clean full source SHA. Both artifacts must
equal their Git top-level directory; a nested directory of another checkout is
not an artifact.

The driver may be a separately reviewed operator file. The candidate's checker
and backup must be tracked, clean and belong to the exact requested SHA. Active
`/srv/kivou/app` is read only and must match the explicit source artifact.

Every execution gets a fresh 0700 `/var/tmp` directory and atomic 0600 report.
Verified backups remain there on success and failure; no global retention is
touched. `--keep-copy` preserves the owned OID on either outcome. Otherwise only
the recorded OID can be dropped after confirmed child cleanup. Report states
distinguish `retained_intentionally`, `dropped` and `cleanup_refused`.

## TDD sequence

- [x] Create `tests/test_company_live_copy_driver.py`; observe missing-script
  assertion RED before implementation.
- [x] Add pure boundary cases: URL host/port/database/query rejection, decoded
  passwords only in PG environment, provider/PG ambient variables absent in
  checker environment, exact SHA/root/active artifact checks, disk floor.
- [x] Implement those guards in
  `docs/reports/prospecting-v11/company-live-copy-driver.py`; run focused GREEN.
- [x] Add evidence/process tests: actual private atomic files; no symlink
  traversal; timeout, failed leader, orphaned group and bounded TERM/KILL cleanup
  using synthetic process boundaries (never signal a real unrelated PID).
- [x] Add orchestration tests with fake PostgreSQL connection boundaries and
  real temporary evidence files: source READ ONLY, no CREATE on preflight or
  collision, restore failure cleanup, OID mismatch refusal, retained backup,
  intentional copy retention, evidence I/O failure still attempts safe cleanup,
  closed child JSON and no secret exception forwarding.
- [x] Run `PYTEST_DEBUG_TEMPROOT=/tmp .venv/bin/pytest -o addopts= -q -n0
  tests/test_company_live_copy_driver.py`, Ruff and compilation checks. Request
  independent review and freeze these three files; no Git or remote action.

Local evidence: initial 32 missing-driver failures; targeted cleanup regressions
observed RED before corrections; the initial final 45/45 offline cases passed.
The omitted-default-port regression was then reproduced before normalization.
PostgreSQL
source/admin/CREATE/DROP boundaries are simulated; two owned local subprocess
cases exercise real process/output cleanup without network access. No remote
backup, restoration or release activation is implied by these tests.

Production/staging heads remain explicit in the checker contract, not inferred
from stale documentation. No QA seeder, BOAMP, provider, activation, systemd,
nginx, backup deletion or global database cleanup belongs in this driver.
