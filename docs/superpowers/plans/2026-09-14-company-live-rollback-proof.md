# Company live rollback proof implementation plan

> **For agentic workers:** Execute the root-approved bounded component with TDD;
> root owns independent review, Git integration and every remote/copy operation.

**Goal:** Prove actual old-artifact API rollback and candidate recovery on an
operator-created, already-migrated PostgreSQL copy, preserving private state.

**Architecture:** One private loopback nginx sidecar proxies an owned Unix socket.
The operator starts the exact candidate, seeds only synthetic copy rows through
existing private-contract helpers and authenticated local HTTP, closes the exact
versioned V11 guard, switches to the exact legacy API, validates auth/billing
reads and unchanged private business state, then returns to the candidate before
reopening writes. No frontend bundles, production QA seeder or live links.

**Tech stack:** Python stdlib, existing SQLAlchemy/private-baseline helpers,
uvicorn, nginx; offline pytest including a real candidate API contract check.

## Approved boundaries

- Both physical code roots and both full 40-character SHAs are explicit and
  verified against Git/import paths. Source environment is STAGING or PRODUCTION.
- Copy URL/name rules match `company-live-rehearsal.py`; default DB must be the
  same copy. Ambient libpq/provider configuration is not inherited by children.
- Require the candidate Alembic head already present; never migrate, downgrade,
  create/drop a database, invoke providers, or touch global units/release links.
- Use `exercise_private_contracts` unchanged. Preserve original and newly
  exercised private rows with bounded private baselines; report aggregate
  booleans/counts only. Synthetic session tokens remain in memory.
- Cleanup only the owned subprocesses and files inside a newly created private
  directory. The operator leaves copy deletion to root's OID-checked procedure.

## Tasks

- [x] Create `tests/test_company_live_rollback_rehearsal.py`: first assert the
  versioned tool exists; run and observe the missing implementation failure.
- [x] Add configuration/child-environment/report tests: malformed SHA, live name,
  mismatched URL, libpq query override, physical/import mismatch, closed errors,
  atomic 0600 report with 0700 parent, same accepted copy rules as sibling checker.
- [x] Add sequence tests: guard closed before legacy, actual legacy GETs and
  rejected writes, candidate read verified before opening, cleanup on every failure.
- [x] Implement `docs/reports/prospecting-v11/company-live-rollback-rehearsal.py`
  with explicit execute/serve modes, root/SHA verification, bounded own-process
  startup, candidate-only helper loading, copy fencing and private reporting.
- [x] Add a real candidate TestClient integration on disposable SQLite proving
  local synthetic note/contact CAS and tombstones; no network/provider is used.
- [x] Run focused pytest, Ruff and compile checks. Hand off exact evidence and
  any unavailable runtime prerequisite; do not claim a PostgreSQL/legacy/nginx
  execution until root performs the operator-created-copy rehearsal.

Concrete production source artifact supplied by root is
`4c3bc6373e7bc2c1b24c413b6c7db523a44e15ba`; staging's full `7f2…` SHA is supplied
by the operator. Neither value is inferred or baked into runtime authorization.

## Operator invocation and lifecycle

The reviewed script may be copied to a private operator directory; it does not
need to exist in the candidate or legacy release. Use the candidate interpreter
to run it, and supply both physical roots, both full SHAs, the source environment
and an absolute report path under an operator-owned 0700 directory. The existing
four `KIVOU_V11_*`/`KIVOU_DATABASE_URL` copy variables are its only database inputs.
The source copy must already have the candidate head verified by the companion
`company-live-rehearsal.py` checker. `--nginx` optionally names the executable.

Git checks use a fixed environment, disable ambient global/system Git config,
verify the repository top-level and confirm that the candidate baseline helper
is tracked. The API import path is checked again inside each served artifact.
Reports are atomically replaced as 0600 files and both contents/parent directory
are fsynced; exceptions expose closed codes, never SQL, tokens or credentials.

Each API/nginx child owns a newly created session/process group. Handled SIGTERM,
SIGINT and the 240-second deadline perform bounded TERM/KILL escalation and
verify that each recorded group disappeared, including descendants after the
leader exits. Temporary nginx files/socket are in a newly created 0700 `/tmp`
directory (short Unix-socket path); baseline fingerprints and the report remain
in the private operator evidence location.

Forced SIGKILL of the operator bypasses Python cleanup and does not itself kill
those separate child sessions. Root's external launch wrapper must allow the
handled-signal grace period and retain its independent no-open-copy-connections
check before any copy disposal. No claim of resilience to unhandleable SIGKILL
or proof of a remotely served old artifact is made by the offline test suite.

The focused tests include a real candidate API on disposable SQLite, a real
local nginx closed/open cycle when `KIVOU_TEST_NGINX` is provided, the copy/Git
fences, private report failures and a forked-descendant cleanup regression. No
provider or PostgreSQL connection is made during these tests.

## Verification evidence

Final focused run: **22 passed in 8.53 seconds** with
`PYTEST_DEBUG_TEMPROOT=/tmp` and `KIVOU_TEST_NGINX` pointing to the existing
disposable local nginx binary. Ruff check, Ruff formatting, `py_compile` and
`git diff --check` passed. Initial missing-operator cases and subsequent real API,
nginx temporary-directory, Git-environment, report durability, descendant cleanup
and exit-race regressions were each observed failing before their corrections.

Independent reviewer confirmed the core sequence, copy/private-data scope and
real API composition, then requested isolated Git checks and descendant cleanup.
Both corrections are implemented and the final version is frozen for targeted
re-review. Root remains responsible for Git integration and the actual old-release
PostgreSQL-copy round-trip; that remote proof has not been executed by this agent.
