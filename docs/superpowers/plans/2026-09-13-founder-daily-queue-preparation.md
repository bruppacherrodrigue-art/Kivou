# Founder Daily Queue Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the founder start one bounded assisted acquisition cycle from the Prospection queue, observe live `N/25` progress, and keep production scheduled hourly from 06:00 Europe/Zurich without any automatic send.

**Architecture:** A Founder-only launcher acquires the same OS file lock as the production timer and hands that lock to a detached `run-once` child. The existing durable runtime lease remains the second concurrency barrier. The Founder read model combines the acquisition service state, timer next occurrence, and Zurich-day target count; the React queue card polls that projection until the cycle is terminal and then reloads its action rows.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, `fcntl`/`subprocess`, React 19, TypeScript, Vitest/Testing Library, systemd, nginx, pytest.

---

### Task 1: Share Europe/Zurich day boundaries with the preparation cap

**Files:**
- Create: `src/signals/prospection_actions/day.py`
- Modify: `src/signals/prospection_actions/preparation.py`
- Test: `tests/test_assisted_prospect_preparation.py`

- [ ] **Step 1: Write the failing midnight-boundary test**

Add a test that prepares 25 targets at `2026-09-13T21:30:00Z`, advances the
clock to `2026-09-13T22:30:00Z` (00:30 Zurich on the next day), and verifies a
new signal can prepare targets. Before the change, the UTC-day query keeps the
old 25 rows and the assertion fails.

```python
def test_daily_preparation_cap_resets_at_zurich_midnight(migrated_sqlite_engine) -> None:
    seed_directory(migrated_sqlite_engine, 50, eligible_department_count=50)
    clock = [dt.datetime(2026, 9, 13, 21, 30, tzinfo=dt.UTC)]
    service = ProspectPreparationService(
        migrated_sqlite_engine,
        link_issuer=Links(),
        clock=lambda: clock[0],
    )
    assert service.prepare(signal(), cycle_ref="cycle-before-midnight").prepared == 25
    clock[0] = dt.datetime(2026, 9, 13, 22, 30, tzinfo=dt.UTC)
    result = service.prepare(
        signal(
            opportunity_key="boamp-next-zurich-day",
            acquisition_opportunity_id="z" * 64,
            procedure_key="boamp-next-zurich-day",
            decision_date=dt.date(2026, 9, 14),
        ),
        cycle_ref="cycle-after-midnight",
    )
    assert result.prepared == 25
```

- [ ] **Step 2: Run the test and observe the expected RED**

Run:
`pytest -q tests/test_assisted_prospect_preparation.py::test_daily_preparation_cap_resets_at_zurich_midnight`

Expected: `prepared == 0`, proving the existing cap is still UTC-based.

- [ ] **Step 3: Add one shared day-boundary function and use it**

```python
# src/signals/prospection_actions/day.py
import datetime as dt
from zoneinfo import ZoneInfo

PROSPECTION_TIMEZONE = "Europe/Zurich"
_ZONE = ZoneInfo(PROSPECTION_TIMEZONE)

def prospection_day_bounds(value: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("prospection clock must be timezone-aware")
    local = value.astimezone(_ZONE)
    local_start = dt.datetime.combine(local.date(), dt.time(), tzinfo=_ZONE)
    return local_start.astimezone(dt.UTC), (local_start + dt.timedelta(days=1)).astimezone(dt.UTC)
```

Replace the UTC `day_start`/`day_end` calculation in
`ProspectPreparationService.prepare` with `prospection_day_bounds(now)` and use
the Zurich local date for the attribution-window check and advisory-lock key.

- [ ] **Step 4: Run the preparation tests GREEN**

Run: `pytest -q tests/test_assisted_prospect_preparation.py`

Expected: all preparation tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/signals/prospection_actions/day.py src/signals/prospection_actions/preparation.py tests/test_assisted_prospect_preparation.py
git commit -m "fix(prospection): apply daily cap in Zurich time"
```

### Task 2: Add the bounded Founder acquisition launcher

**Files:**
- Create: `src/signals/founder_api/acquisition_actions.py`
- Modify: `src/signals/founder_api/actions_composition.py`
- Modify: `src/signals/founder_api/prospection_actions.py`
- Modify: `src/signals/founder_api/app.py`
- Modify: `src/signals/founder_api/asgi.py`
- Test: `tests/founder_api/test_acquisition_prepare_action.py`
- Test: `tests/founder_api/test_prospection_actions_api.py`

- [ ] **Step 1: Write launcher tests for accepted, locked, capped, and disabled states**

Use a temporary lock path, disabled path, SQLite engine with `prospect_target`,
and an injected `popen` function. Assert:

```python
result = launcher.prepare()
assert result.accepted is True
assert result.prepared_today_count == 0
command, options = launched[0]
assert command[-3:] == ("-m", "signals.acquisition_runtime", "run-once")
assert len(options["pass_fds"]) == 1
```

Hold a real non-blocking `flock` in the test and assert
`FounderAcquisitionLaunchError(code="ACQUISITION_ALREADY_RUNNING", status_code=409)`.
Seed 25 Zurich-day `prospect_target` rows and assert the `429` cap error. Create
the disabled file and assert the `423` kill-switch error. A small real child
fixture must verify that the duplicated descriptor retains the lock after the
launcher closes its parent copy and releases it when the child exits.

- [ ] **Step 2: Run the launcher tests RED**

Run: `pytest -q tests/founder_api/test_acquisition_prepare_action.py`

Expected: import failure for the new module.

- [ ] **Step 3: Implement the launcher**

Create immutable `FounderAcquisitionLaunch` and
`FounderAcquisitionLaunchError` contracts. `FounderAcquisitionLauncher.prepare`
must execute in this exact order: count Zurich-day rows; reject at 25; reject an
existing disabled path; open the lock file; attempt `fcntl.flock(fd,
LOCK_EX|LOCK_NB)`; duplicate the descriptor for the child; start

```python
(
    sys.executable,
    "-m",
    "signals.acquisition_runtime",
    "run-once",
)
```

with `pass_fds=(child_fd,)`, `start_new_session=True`, and inherited production
environment. Close parent descriptors on every success/failure path. Start one
daemon reaper thread calling `process.wait`. Never include environment values,
provider errors, or child output in the HTTP contract.

`build_founder_acquisition_launcher(engine)` in `actions_composition.py` binds
the production paths and command. `asgi.py` builds it from the Founder write
engine and passes it to `create_founder_app`.

- [ ] **Step 4: Add the route test RED**

Build the Founder app with a fake launcher. POST an empty JSON object to
`/api/founder/actions/prospection/prepare` and assert `202` plus:

```json
{
  "version": "founder-prospection-prepare-v1",
  "status": "accepted",
  "prepared_today_count": 0,
  "daily_pending_cap": 25
}
```

Parametrize launcher errors and assert the exact `409`, `423`, and `429`
Founder error envelopes and French phrases from the spec.

- [ ] **Step 5: Implement the POST boundary GREEN**

Extend `build_prospection_actions_router` with an optional launcher and add the
route only when it exists. Map `FounderAcquisitionLaunchError` to the existing
Founder detail envelope. Add the launcher dependency to `create_founder_app`
without changing the existing approve/correct/reject/send contracts.

- [ ] **Step 6: Run backend action tests GREEN and commit**

Run:
`pytest -q tests/founder_api/test_acquisition_prepare_action.py tests/founder_api/test_prospection_actions_api.py`

Then:

```bash
git add src/signals/founder_api tests/founder_api
git commit -m "feat(founder): launch assisted queue preparation"
```

### Task 3: Project service progress, Zurich count, and next run

**Files:**
- Modify: `src/signals/founder_api/acquisition_status.py`
- Modify: `tests/founder_api/test_acquisition_status.py`
- Modify: `tests/founder_api/test_prospection.py`
- Modify: `tests/founder_api/test_read_models.py`

- [ ] **Step 1: Write failing projection tests**

Add tests with two mocked `systemctl show` responses. The service response uses
`ActiveState=activating`; the timer response uses `ActiveState=active` and
`NextElapseUSecRealtime=Mon 2026-09-14 04:00:00 UTC`. Assert:

```python
assert status.activity == "RUNNING"
assert status.next_run_at == dt.datetime(2026, 9, 14, 4, tzinfo=dt.UTC)
assert status.prepared_today_count == 7
assert status.daily_pending_cap == 25
```

Add the inverse case: service inactive plus timer active must return `STOPPED`,
not `RUNNING`. Seed rows around Zurich midnight and assert only the current
Zurich day is counted.

- [ ] **Step 2: Run the status tests RED**

Run: `pytest -q tests/founder_api/test_acquisition_status.py`

Expected: missing fields and the old timer-based activity interpretation.

- [ ] **Step 3: Split service and timer reads**

Replace `ACQUISITION_TIMER_UNIT` with service and timer constants. Extend
`FounderAcquisitionActivity` and `FounderAcquisitionStatus` with
`next_run_at`. Query both units in one sanitized `systemctl show` invocation,
parse records by `Id`, and derive activity only from the service record.

In `FounderAcquisitionStatusReadService.read`, use
`prospection_day_bounds(now)` to count current-day `prospect_target` rows and
populate `prepared_today_count` plus `daily_pending_cap=25`.

- [ ] **Step 4: Update existing fixture contracts and run GREEN**

Update all Founder acquisition status fixtures with the four new values where
required. Run:

`pytest -q tests/founder_api/test_acquisition_status.py tests/founder_api/test_prospection.py tests/founder_api/test_read_models.py`

- [ ] **Step 5: Commit**

```bash
git add src/signals/founder_api/acquisition_status.py tests/founder_api
git commit -m "feat(founder): expose acquisition preparation progress"
```

### Task 4: Add the button and live queue polling

**Files:**
- Modify: `frontend/founder/src/types.ts`
- Modify: `frontend/founder/src/api.ts`
- Modify: `frontend/founder/src/FounderApp.tsx`
- Modify: `frontend/founder/src/ProspectionPage.tsx`
- Modify: `frontend/founder/src/ProspectionPage.test.tsx`
- Modify: `frontend/founder/src/index.css`

- [ ] **Step 1: Write failing API/UI tests**

Extend the fetch mock with the prepare endpoint. With fake timers, click
« Préparer la file du jour », assert the POST, then assert
« Préparation en cours · 3/25 ». Advance two seconds, return a projection with
a changed `last_cycle_at`, `activity=STOPPED`, and one pending target, and assert
the row appears without `window.location.reload`.

Add tests for permanent display of last cycle/result/next pass/button, local
double-click disabling, exact 409/423/429 messages, and the 25-minute polling
timeout.

- [ ] **Step 2: Run the component tests RED**

Run:
`npm test -- --run src/ProspectionPage.test.tsx`
from `frontend/founder`.

Expected: missing button and missing prepare API function.

- [ ] **Step 3: Implement the typed API and refresh callback**

Add `FounderProspectionPrepareResponse` and the four status fields to the TypeScript
contracts. Add:

```typescript
export function prepareFounderProspection(): Promise<FounderProspectionPrepareResponse> {
  return requestActionJson(
    '/api/founder/actions/prospection/prepare',
    {},
    'La préparation de la file a échoué.',
  )
}
```

Pass `onRefresh={() => setRefreshKey((value) => value + 1)}` from `FounderApp`
to `ProspectionPage` and `QueueSection`.

- [ ] **Step 4: Implement the card state machine**

Track `idle | requesting | polling`, baseline cycle time, start time, and
notice/error. Poll every 2 seconds while `polling`; stop on changed cycle,
observed running-then-stopped, count 25, or 25-minute timeout. Let the existing
`data.generated_at` effect reload action rows after every parent refresh.

Render last cycle plus translated result, next passage in Europe/Zurich,
`prepared_today_count/25`, and the button in a compact status strip above the
empty state/table. While requesting or polling, render exactly
`Préparation en cours · N/25` and disable the button.

- [ ] **Step 5: Run frontend tests GREEN and commit**

Run from `frontend/founder`:

```bash
npm test -- --run src/ProspectionPage.test.tsx src/FounderApp.test.tsx
npm run typecheck
npm run lint
```

Then commit:

```bash
git add frontend/founder/src
git commit -m "feat(founder): prepare and refresh the daily queue"
```

### Task 5: Schedule assisted production safely

**Files:**
- Modify: `ops/systemd/kivou-acquisition-production.service`
- Modify: `ops/systemd/kivou-acquisition-production.timer`
- Modify: `ops/systemd/kivou-founder-api.service`
- Modify: `ops/nginx/kivou-founder-control.conf`
- Modify: `tests/test_acquisition_runtime_units.py`
- Modify: `tests/test_ops_nginx_routes.py`
- Modify: `tests/test_card_presentation_runbook.py`
- Modify: `docs/runbooks/12-acquisition-production-shadow.md`

- [ ] **Step 1: Write failing architecture tests**

Assert the timer contains
`OnCalendar=*-*-* 06..23:00:00 Europe/Zurich`, `Persistent=true`, and no random
delay. Assert service flock conflict code `75`, both units share
`/run/kivou/acquisition.lock`, Founder API declares the same
`RuntimeDirectory=kivou`, and nginx permits POST only on the exact `/prepare`
route.

- [ ] **Step 2: Run architecture tests RED**

Run:
`pytest -q tests/test_acquisition_runtime_units.py tests/test_ops_nginx_routes.py tests/test_card_presentation_runbook.py`

- [ ] **Step 3: Modify units, nginx, and runbook**

Change the timer schedule, keep `AccuracySec=60`, remove jitter, set flock's
conflict exit code to 75, add the Founder API runtime directory, and add an
exact nginx POST location mirroring the existing assisted-action proxy headers.
Document that production mode must be `ASSISTED`, the button never sends, and
the timer continues to enforce all caps and the disabled-file condition.

- [ ] **Step 4: Run architecture tests GREEN and validate units**

```bash
pytest -q tests/test_acquisition_runtime_units.py tests/test_ops_nginx_routes.py tests/test_card_presentation_runbook.py
systemd-analyze verify ops/systemd/kivou-acquisition-production.service ops/systemd/kivou-acquisition-production.timer ops/systemd/kivou-founder-api.service
```

- [ ] **Step 5: Commit**

```bash
git add ops tests docs/runbooks/12-acquisition-production-shadow.md
git commit -m "ops(acquisition): schedule assisted queue preparation"
```

### Task 6: Verify, review, deploy, and capture proof

**Files:**
- Create: `docs/reports/2026-09-13-founder-queue-preparation.md`
- Create: `docs/reports/2026-09-13-founder-queue-preparation/queue-filled.png`

- [ ] **Step 1: Run the complete verification suite**

Run backend tests, Ruff, frontend tests, typecheck, lint, build, migration-head
check, and `git diff --check`. Record exact counts and exit codes.

- [ ] **Step 2: Push a PR and require green CI**

Push the feature branch, create the PR, wait for every required GitHub Actions
check, and merge only if the merge SHA is based on current `main`.

- [ ] **Step 3: Deploy the merged main atomically**

Deploy the exact merge SHA using `ops/bin/kivou-deploy.sh production <sha>`.
Verify Founder/API health, the deployed SHA, Alembic head, unit hardening, nginx
syntax, and that the production acquisition document reports mode `ASSISTED`.
Enable `kivou-acquisition-production.timer` only after these checks.

- [ ] **Step 4: Execute the approved production recipe**

Read current queue count and send count, click the Founder button once, observe
the running state and `N/25`, wait for the terminal cycle, verify at least one
pending-review row appears, and prove the send count is unchanged. If the queue
is already at 25, preserve that factual result and capture the explicit cap
refusal instead of bypassing the cap.

- [ ] **Step 5: Capture and document**

Use Playwright against `control.kivou.eu/prospection` to capture the filled queue
with button, last result, next passage, and at least one prepared row visible.
Write the report with exact before/after counts, cycle reference, status, timer
schedule, and unchanged send count. Commit and merge the evidence through a
docs-only PR.
