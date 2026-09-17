# Founder Async Prospect Send Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Founder prospect sends return HTTP 202 immediately, process every target durably and idempotently in a worker, expose progress in the console, separate Instantly acceptance from webhook delivery, and safely resume the paused 16 September batch without reimporting any lead.

**Architecture:** PostgreSQL is the durable queue. The POST transaction reserves approved targets and creates one request plus one item per target; a systemd worker claims one due item at a time, performs at most one verification read, and persists the next state before returning. A GET endpoint and frontend polling expose progress, while webhook projection alone owns SMTP delivery state.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core, Alembic, PostgreSQL, httpx, pytest, React, TypeScript, Vitest, nginx, systemd.

---

### Task 1: Add the durable request/item schema and acceptance timestamp

**Files:**
- Create: `src/signals/persistence/migrations/versions/0065_async_prospect_send.py`
- Modify: `src/signals/persistence/schema.py`
- Modify: `tests/test_prospection_actions_migration.py`
- Modify: `tests/test_prospecting_migration.py`

- [ ] **Step 1: Write the failing migration test**

Extend `tests/test_prospection_actions_migration.py` to require:

```python
assert {
    "prospect_send_request",
    "prospect_send_item",
}.issubset(inspector.get_table_names())

target_columns = {column["name"] for column in inspector.get_columns("prospect_target")}
assert "instantly_accepted_at" in target_columns

request_columns = {
    column["name"] for column in inspector.get_columns("prospect_send_request")
}
assert {
    "processed_count",
    "failed_count",
    "provider_campaign_id",
    "next_attempt_at",
    "attempt_count",
    "claimed_by",
    "lease_id",
    "lease_expires_at",
    "started_at",
    "updated_at",
}.issubset(request_columns)

item_columns = {
    column["name"] for column in inspector.get_columns("prospect_send_item")
}
assert {
    "request_id",
    "target_id",
    "position",
    "expected_version",
    "status",
    "instantly_id",
    "verification_status",
    "error_code",
    "error_message",
    "next_attempt_at",
    "attempt_count",
    "created_at",
    "updated_at",
    "completed_at",
}.issubset(item_columns)
```

- [ ] **Step 2: Run the migration test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_prospection_actions_migration.py
```

Expected: FAIL because `prospect_send_item` and the new columns do not exist.

- [ ] **Step 3: Implement migration `0065_async_prospect_send` and schema metadata**

Use `down_revision = "0064_company_mail_merge"`. Add
`prospect_target.instantly_accepted_at`; expand `prospect_send_request`; create
`prospect_send_item` with a composite primary key and these constraints:

```python
sa.CheckConstraint(
    "status IN ('queued', 'running', 'verification_pending', 'sent', 'failed')",
    name="ck_prospect_send_item_status",
)
sa.CheckConstraint("position BETWEEN 0 AND 24", name="ck_prospect_send_item_position")
sa.CheckConstraint("attempt_count >= 0", name="ck_prospect_send_item_attempts")
```

Replace the request status constraint with:

```python
"status IN ('started', 'queued', 'running', 'waiting', 'completed', 'partial', 'failed')"
```

Backfill `instantly_accepted_at = sent_at` for existing `status='sent'` rows.
For delivery, rebuild each existing target from `prospect_delivery_event`: no
event means `delivery_status='not_sent'` and delivery timestamps stay null;
`email_sent` maps to `delivered`, followed by the latest higher-order event.
Grant the Founder write role SELECT/INSERT/UPDATE on `prospect_send_item` and
the new columns.

- [ ] **Step 4: Run migration/schema tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_prospection_actions_migration.py tests/test_prospecting_migration.py
```

Expected: PASS with one migration head, `0065_async_prospect_send`.

- [ ] **Step 5: Commit the schema slice**

```bash
git add src/signals/persistence/schema.py \
  src/signals/persistence/migrations/versions/0065_async_prospect_send.py \
  tests/test_prospection_actions_migration.py tests/test_prospecting_migration.py
git commit -m "feat(prospecting): add durable send queue schema"
```

### Task 2: Reserve sends idempotently and expose a durable request view

**Files:**
- Create: `src/signals/prospection_actions/queue.py`
- Create: `tests/test_prospection_send_queue.py`
- Modify: `src/signals/prospection_actions/contracts.py`
- Modify: `src/signals/prospection_actions/service.py`

- [ ] **Step 1: Write failing queue tests**

Build the fixture with `seed`, `approve`, `MxVerifier`, `LinkIssuer` and the
recording `Delivery` double already exported by
`tests/test_prospection_actions_send.py`, then cover these behaviors:

```python
def test_enqueue_reserves_without_calling_provider(async_sending):
    actions, provider, engine = async_sending
    result = actions.enqueue_send(command(), actor="rodrigue@kivou.eu")
    assert result.status == "queued"
    assert result.total_count == 1
    assert result.sent_count == result.processed_count == result.failed_count == 0
    assert provider.calls == []


def test_same_request_and_payload_replays_without_new_rows(async_sending):
    actions, provider, engine = async_sending
    first = actions.enqueue_send(command(), actor="rodrigue@kivou.eu")
    replay = actions.enqueue_send(command(), actor="rodrigue@kivou.eu")
    assert replay == first
    assert provider.calls == []
    assert row_count(engine, prospect_send_request) == 1
    assert row_count(engine, prospect_send_item) == 1


def test_same_request_with_other_payload_is_a_conflict(async_sending):
    actions, provider, _ = async_sending
    actions.enqueue_send(command(), actor="rodrigue@kivou.eu")
    with pytest.raises(ProspectionActionError) as caught:
        actions.enqueue_send(other_payload_same_request_id(), actor="rodrigue@kivou.eu")
    assert caught.value.code == "SEND_REQUEST_IDEMPOTENCY_CONFLICT"
    assert provider.calls == []


def test_enqueue_never_reserves_a_sent_target(async_sending):
    actions, provider, engine = async_sending
    mark_target_sent(engine)
    with pytest.raises(ProspectionActionError) as caught:
        actions.enqueue_send(command(), actor="rodrigue@kivou.eu")
    assert caught.value.code == "INVALID_TARGET_STATUS"
    assert provider.calls == []
```

- [ ] **Step 2: Run the new tests and verify RED**

```bash
.venv/bin/pytest -q tests/test_prospection_send_queue.py
```

Expected: FAIL because `enqueue_send` and `prospect_send_item` orchestration do
not exist.

- [ ] **Step 3: Implement queue contracts and transaction**

Add frozen Pydantic contracts:

```python
class SendItemProgress(_Contract):
    target_id: UUID
    email_address: EmailStr
    status: Literal["queued", "running", "verification_pending", "sent", "failed"]
    instantly_id: str | None = None
    verification_status: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class SendRequestProgress(_Contract):
    request_id: UUID
    status: Literal["queued", "running", "waiting", "completed", "partial", "failed"]
    total_count: int = Field(ge=1, le=25)
    processed_count: int = Field(ge=0, le=25)
    sent_count: int = Field(ge=0, le=25)
    failed_count: int = Field(ge=0, le=25)
    items: tuple[SendItemProgress, ...]
```

Move the current validation/reservation half of `ProspectionActions.send` into
`enqueue_send`. Insert request and item rows in the same transaction, set
`prospect_target.send_request_id`, and return `send_progress(request_id)`. Do
not construct `DeliveryTarget` and do not call the provider from this method.

- [ ] **Step 4: Run queue and legacy action tests**

```bash
.venv/bin/pytest -q tests/test_prospection_send_queue.py \
  tests/test_prospection_actions_service.py
```

Expected: queue and non-send service tests PASS. The legacy synchronous send
tests remain unchanged until their worker conversion in Task 3.

- [ ] **Step 5: Commit the durable reservation slice**

```bash
git add src/signals/prospection_actions/contracts.py \
  src/signals/prospection_actions/queue.py \
  src/signals/prospection_actions/service.py \
  tests/test_prospection_send_queue.py
git commit -m "feat(prospecting): enqueue idempotent send requests"
```

### Task 3: Implement the one-read, one-item worker state machine

**Files:**
- Create: `src/signals/prospection_actions/worker.py`
- Create: `tests/test_prospection_send_worker.py`
- Modify: `src/signals/prospection_actions/delivery.py`
- Modify: `src/signals/founder_api/actions_composition.py`
- Modify: `tests/test_assisted_instantly_delivery.py`
- Modify: `tests/test_prospection_actions_send.py`

- [ ] **Step 1: Write failing state-machine tests**

Add tests proving:

```python
def test_worker_reads_pending_verification_once_and_reschedules(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=12)
    outcome = worker.run_once(worker_ref="worker-a", now=NOW)
    assert outcome.status == "waiting"
    assert provider.get_lead_calls == ["lead-1"]
    assert provider.sleep_calls == []
    item = send_item(engine)
    assert item["status"] == "verification_pending"
    assert item["next_attempt_at"] == NOW + dt.timedelta(minutes=1)


def test_worker_reuses_existing_lead_without_import(worker_fixture):
    worker, provider, engine = worker_fixture(
        instantly_id="existing-lead", provider_campaign_id="existing-campaign",
        verification_status=1,
    )
    worker.run_once(worker_ref="worker-a", now=NOW)
    assert provider.create_campaign_calls == []
    assert provider.create_lead_calls == []
    assert provider.get_lead_calls == ["existing-lead"]


def test_acceptance_does_not_claim_smtp_delivery(worker_fixture):
    worker, provider, engine = worker_fixture(verification_status=1)
    worker.run_once(worker_ref="worker-a", now=NOW)
    target = target_row(engine)
    assert target["status"] == "sent"
    assert target["instantly_accepted_at"] == NOW
    assert target["delivery_status"] == "not_sent"
    assert target["sent_at"] is None


@pytest.mark.parametrize(
    ("verification_status", "error_code"),
    [(-1, "instantly_email_invalid"), (-2, "instantly_email_risky"),
     (-3, "instantly_email_catch_all"), (-4, "instantly_email_job_change")],
)
def test_terminal_verification_failure_is_visible_and_releases_target(
    worker_fixture, verification_status, error_code
):
    worker, _, engine = worker_fixture(verification_status=verification_status)
    worker.run_once(worker_ref="worker-a", now=NOW)
    assert send_item(engine)["error_code"] == error_code
    target = target_row(engine)
    assert target["status"] == "approved"
    assert target["send_request_id"] is None
```

Add a PostgreSQL concurrency test showing `SKIP LOCKED` gives a single claimant,
plus a lease-expiry test showing an interrupted item can be reclaimed once.

- [ ] **Step 2: Run worker tests and verify RED**

```bash
.venv/bin/pytest -q tests/test_prospection_send_worker.py tests/test_assisted_instantly_delivery.py
```

Expected: FAIL because the worker and incremental delivery operations are absent.

- [ ] **Step 3: Replace polling delivery with incremental provider operations**

Expose narrow operations from `delivery.py`:

```python
class AssistedInstantlyDelivery:
    def ensure_campaign(self, request, *, at): ...
    def import_target(self, campaign_id, target): ...
    def verification(self, instantly_id): ...
    def activate(self, campaign_id): ...
```

`verification()` performs exactly one `get_lead`. It returns one of
`accepted`, `pending`, or `failed` with a public error code. Remove the 15-pass
loop and every `time.sleep` import from this module.

Implement `ProspectSendWorker.run_once`: claim one due item with a lease,
re-check the kill switch, reuse stored remote identifiers, persist the outcome,
recompute request counts, and activate the campaign exactly once when every
item is terminal and at least one item is sent. The update predicate must
include the current `lease_id` so an expired worker cannot overwrite a newer
claim.

- [ ] **Step 4: Verify GREEN and no sleeping path**

```bash
.venv/bin/pytest -q tests/test_prospection_send_worker.py \
  tests/test_assisted_instantly_delivery.py tests/test_prospection_actions_send.py
! rg -n "time\.sleep|for poll in range\(15\)" src/signals/prospection_actions
```

Expected: all tests PASS and `rg` finds no synchronous polling loop.

- [ ] **Step 5: Commit the worker slice**

```bash
git add src/signals/prospection_actions/worker.py \
  src/signals/prospection_actions/delivery.py \
  src/signals/founder_api/actions_composition.py \
  tests/test_prospection_send_worker.py \
  tests/test_assisted_instantly_delivery.py \
  tests/test_prospection_actions_send.py
git commit -m "feat(prospecting): process sends one target at a time"
```

### Task 4: Return HTTP 202 and add the progress endpoint

**Files:**
- Modify: `src/signals/founder_api/prospection_actions.py`
- Modify: `tests/founder_api/test_prospection_actions_api.py`

- [ ] **Step 1: Write failing API tests**

Add a provider that raises if touched and assert:

```python
response = client.post(
    "/api/founder/actions/prospection/send",
    headers=founder_headers,
    json=command_payload,
)
assert response.status_code == 202
assert response.json() == {
    "version": "founder-prospection-send-v2",
    "request_id": command_payload["request_id"],
    "status": "queued",
    "total_count": 2,
    "processed_count": 0,
    "sent_count": 0,
    "failed_count": 0,
    "status_url": f"/api/founder/actions/prospection/send/{command_payload['request_id']}",
    "items": expected_items,
}

progress = client.get(
    response.json()["status_url"], headers=founder_headers
)
assert progress.status_code == 200
assert progress.json()["request_id"] == command_payload["request_id"]
```

Also assert replay returns 202 with the existing progress and a fingerprint
conflict returns 409 without changing row counts.

- [ ] **Step 2: Run API tests and verify RED**

```bash
.venv/bin/pytest -q tests/founder_api/test_prospection_actions_api.py
```

Expected: FAIL because POST is synchronous/200 and GET does not exist.

- [ ] **Step 3: Implement the route contract**

Change the route to:

```python
@router.post("/send", status_code=202)
def send(command: SendCommand, identity: FounderIdentityDependency):
    return _send_response(service.enqueue_send(command, actor=identity.email))


@router.get("/send/{request_id}")
def send_progress(request_id: UUID, identity: FounderIdentityDependency):
    del identity
    return _send_response(service.send_progress(str(request_id)))
```

Return 404 `SEND_REQUEST_NOT_FOUND` for an unknown identifier. Keep all error
messages structured through `_error`.

- [ ] **Step 4: Run API tests and verify GREEN**

```bash
.venv/bin/pytest -q tests/founder_api/test_prospection_actions_api.py
```

Expected: PASS.

- [ ] **Step 5: Commit the HTTP slice**

```bash
git add src/signals/founder_api/prospection_actions.py \
  tests/founder_api/test_prospection_actions_api.py
git commit -m "feat(founder): return 202 for prospect sends"
```

### Task 5: Make webhook delivery strictly independent from acceptance

**Files:**
- Modify: `src/signals/prospection_actions/contracts.py`
- Modify: `src/signals/prospection_actions/webhook.py`
- Modify: `tests/test_assisted_prospect_webhooks.py`
- Modify: `tests/test_prospect_attribution.py`

- [ ] **Step 1: Write failing separation tests**

```python
def test_email_sent_webhook_sets_delivery_without_changing_acceptance(engine):
    row = accepted_target(engine, instantly_accepted_at=NOW)
    ingest("email_sent", row["email_address"])
    target = target_row(engine)
    assert target["status"] == "sent"
    assert target["instantly_accepted_at"] == NOW
    assert target["delivery_status"] == "delivered"
    assert target["sent_at"] == NOW + dt.timedelta(minutes=5)


def test_open_without_prior_sent_still_proves_delivery(engine):
    row = accepted_target(engine, instantly_accepted_at=NOW)
    ingest("email_opened", row["email_address"])
    target = target_row(engine)
    assert target["delivery_status"] == "opened"
    assert target["opened_at"] is not None
```

- [ ] **Step 2: Run webhook tests and verify RED**

```bash
.venv/bin/pytest -q tests/test_assisted_prospect_webhooks.py tests/test_prospect_attribution.py
```

Expected: FAIL because `email_sent` currently writes the ambiguous value `sent`
and synchronous acceptance pre-populates delivery.

- [ ] **Step 3: Update delivery contracts and projector**

Use:

```python
class DeliveryStatus(StrEnum):
    NOT_SENT = "not_sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    UNSUBSCRIBED = "unsubscribed"
```

Map `ProviderEventType.EMAIL_SENT` to `delivered`. Never assign
`prospect_target.status` or `instantly_accepted_at` from the webhook. Preserve
the existing idempotent event fingerprint and bounce/suppression behavior.

- [ ] **Step 4: Run webhook/conversion tests and verify GREEN**

```bash
.venv/bin/pytest -q tests/test_assisted_prospect_webhooks.py \
  tests/test_prospect_attribution.py tests/test_conversion_tracking_migration.py
```

Expected: PASS.

- [ ] **Step 5: Commit the delivery semantics slice**

```bash
git add src/signals/prospection_actions/contracts.py \
  src/signals/prospection_actions/webhook.py \
  tests/test_assisted_prospect_webhooks.py \
  tests/test_prospect_attribution.py
git commit -m "fix(prospecting): separate acceptance from delivery"
```

### Task 6: Poll and render durable progress in the Founder Console

**Files:**
- Modify: `frontend/founder/src/types.ts`
- Modify: `frontend/founder/src/api.ts`
- Modify: `frontend/founder/src/ProspectionPage.tsx`
- Modify: `frontend/founder/src/ProspectionActions.test.tsx`

- [ ] **Step 1: Write failing frontend tests**

Add Vitest cases proving:

```typescript
expect(await screen.findByText('0/21 envoyées')).toBeInTheDocument()
resolveProgress({ status: 'running', processed_count: 7, sent_count: 7, failed_count: 0 })
expect(await screen.findByText('7/21 envoyées')).toBeInTheDocument()

resolveProgress({
  status: 'partial', processed_count: 21, sent_count: 18, failed_count: 3,
  items: [{ email_address: 'invalid@example.fr', status: 'failed',
    error_message: 'Adresse invalide' }],
})
expect(await screen.findByText('18/21 envoyées · 3 en échec')).toBeInTheDocument()
expect(screen.getByText('invalid@example.fr — Adresse invalide')).toBeInTheDocument()
```

Add a reload test that seeds `sessionStorage` with the request ID and proves the
page resumes GET polling without issuing a second POST. Assert the acceptance
column and delivery column have separate labels and values.

- [ ] **Step 2: Run the focused frontend test and verify RED**

```bash
npm --prefix frontend/founder test -- --run src/ProspectionActions.test.tsx
```

Expected: FAIL because the client expects the synchronous v1 response.

- [ ] **Step 3: Implement API types, polling and rendering**

Define `FounderProspectionSendProgress` matching v2. Make
`sendFounderProspects` accept HTTP 202, add `loadFounderProspectSend(requestId)`,
and poll every two seconds until `completed`, `partial`, or `failed`. Store only
the opaque request ID in session storage. Clear it after terminal rendering.

Remove the optimistic transition that marks every row `sent` before the POST
returns. Update rows only from terminal/progress item states. Render public
messages from `error_message`, never raw provider bodies.

- [ ] **Step 4: Run frontend tests and verify GREEN**

```bash
npm --prefix frontend/founder test -- --run src/ProspectionActions.test.tsx
npm --prefix frontend/founder run typecheck
npm --prefix frontend/founder run lint
```

Expected: all commands PASS.

- [ ] **Step 5: Commit the console slice**

```bash
git add frontend/founder/src/types.ts frontend/founder/src/api.ts \
  frontend/founder/src/ProspectionPage.tsx \
  frontend/founder/src/ProspectionActions.test.tsx
git commit -m "feat(founder): show asynchronous send progress"
```

### Task 7: Add production worker units and Founder timeout override

**Files:**
- Create: `ops/systemd/kivou-prospect-send.service`
- Create: `ops/systemd/kivou-prospect-send.timer`
- Modify: `ops/nginx/kivou-founder-control.conf`
- Modify: `tests/test_ops_nginx_routes.py`
- Create: `tests/test_prospect_send_systemd.py`
- Modify: `ops/production/README.md`

- [ ] **Step 1: Write failing ops tests**

Require the Founder server/location to contain:

```python
assert "proxy_read_timeout 120s;" in founder_server.body
```

Require systemd units to use the production environment and bounded worker:

```python
service = (ROOT / "ops/systemd/kivou-prospect-send.service").read_text()
timer = (ROOT / "ops/systemd/kivou-prospect-send.timer").read_text()
assert "EnvironmentFile=/etc/kivou/founder.env" in service
assert "EnvironmentFile=/etc/kivou/production.env" in service
assert "EnvironmentFile=/etc/kivou/acquisition-production.env" in service
assert "python -m signals.prospection_actions.worker --limit 25" in service
assert "TimeoutStartSec=20min" in service
assert "OnUnitInactiveSec=5s" in timer
```

- [ ] **Step 2: Run ops tests and verify RED**

```bash
.venv/bin/pytest -q tests/test_ops_nginx_routes.py tests/test_prospect_send_systemd.py
```

Expected: FAIL because the units and 120-second override are absent.

- [ ] **Step 3: Add CLI composition, service, timer and nginx override**

Give `worker.py` a `main()` that loads the production connectivity, Founder
write engine and httpx client, prints one JSON summary, and exits nonzero only
for an operational failure. The service must use `flock`, `NoNewPrivileges`,
read-only application paths and the same network restrictions as the Founder
API. Add `proxy_read_timeout 120s;` inside the Founder server so it overrides
the common 30-second include only for Founder routes.

- [ ] **Step 4: Verify ops configuration**

```bash
.venv/bin/pytest -q tests/test_ops_nginx_routes.py tests/test_prospect_send_systemd.py
```

Expected: syntax assertions and unit-file tests PASS. Production `nginx -t` is
performed before installation in Task 9.

- [ ] **Step 5: Commit the runtime slice**

```bash
git add ops/systemd/kivou-prospect-send.service \
  ops/systemd/kivou-prospect-send.timer \
  ops/nginx/kivou-founder-control.conf ops/production/README.md \
  tests/test_ops_nginx_routes.py tests/test_prospect_send_systemd.py \
  src/signals/prospection_actions/worker.py
git commit -m "ops(prospecting): run durable send worker"
```

### Task 8: Build and prove the incident recovery path

**Files:**
- Create: `src/signals/prospection_actions/recovery.py`
- Create: `tests/test_prospect_send_recovery.py`
- Modify: `src/signals/prospection_actions/worker.py`
- Modify: `ops/production/README.md`

- [ ] **Step 1: Write failing recovery tests from the 21-target shape**

Seed one sent target and twenty approved targets, all with existing campaign and
lead IDs; set 17 remote statuses to `1` and three to `-1`. Assert:

```python
preview = recover_request(engine, request_id=REQUEST_ID, dry_run=True)
assert preview == RecoveryPreview(
    request_id=REQUEST_ID,
    approved_count=20,
    already_sent_count=1,
    existing_lead_count=20,
    create_lead_count=0,
)
assert provider.calls == []

recover_request(engine, request_id=REQUEST_ID, dry_run=False)
run_until_terminal(worker)
assert provider.create_campaign_calls == []
assert provider.create_lead_calls == []
assert sent_target_count(engine) == 18
assert failure_codes(engine) == {
    "contact@ambitionthd.com": "instantly_email_invalid",
    "contact@malosse-sa.fr": "instantly_email_invalid",
    "contact@bourguignon-dalalu.fr": "instantly_email_invalid",
}
```

- [ ] **Step 2: Run recovery tests and verify RED**

```bash
.venv/bin/pytest -q tests/test_prospect_send_recovery.py
```

Expected: FAIL because the recovery command does not exist.

- [ ] **Step 3: Implement dry-run and apply modes**

The CLI accepts only a UUID request ID plus either `--dry-run` or `--apply`.
`--dry-run` opens no write transaction and never constructs a mutating provider.
`--apply` refuses any approved target without both existing remote identifiers
for this incident, creates item rows only for approved targets, records the
already-sent target as completed, and resets the legacy request to `queued`.

Print a bounded JSON document containing counts and target IDs, but no mail
body, attribution token or API response body.

- [ ] **Step 4: Run recovery tests and verify GREEN**

```bash
.venv/bin/pytest -q tests/test_prospect_send_recovery.py
```

Expected: PASS with zero create/import calls.

- [ ] **Step 5: Commit the recovery slice**

```bash
git add src/signals/prospection_actions/recovery.py \
  src/signals/prospection_actions/worker.py \
  tests/test_prospect_send_recovery.py ops/production/README.md
git commit -m "feat(prospecting): recover interrupted send batches"
```

### Task 9: Full verification, deploy, and resume exactly the approved remainder

**Files:**
- No planned source edits; this task verifies and deploys the committed slices.

- [ ] **Step 1: Run the full focused backend suite**

```bash
.venv/bin/pytest -q \
  tests/test_prospection_actions_migration.py \
  tests/test_prospection_send_queue.py \
  tests/test_prospection_send_worker.py \
  tests/test_assisted_instantly_delivery.py \
  tests/test_prospection_actions_send.py \
  tests/founder_api/test_prospection_actions_api.py \
  tests/test_assisted_prospect_webhooks.py \
  tests/test_prospect_attribution.py \
  tests/test_prospect_send_recovery.py \
  tests/test_ops_nginx_routes.py \
  tests/test_prospect_send_systemd.py
.venv/bin/ruff check src tests
```

Expected: all tests PASS and Ruff reports no errors.

- [ ] **Step 2: Run the Founder frontend suite**

```bash
npm --prefix frontend/founder test -- --run
npm --prefix frontend/founder run typecheck
npm --prefix frontend/founder run lint
```

Expected: all commands PASS.

- [ ] **Step 3: Verify migration and repository state**

```bash
.venv/bin/pytest -q tests/test_prospecting_migration.py
git diff --check
git status --short
```

Expected: one migration head, clean diff checks, and only intended commits.

- [ ] **Step 4: Deploy code, migration and runtime configuration**

Follow `ops/production/README.md`: install the release, run the Alembic upgrade,
install/reload nginx after `nginx -t`, install and enable
`kivou-prospect-send.timer`, restart the Founder API, and verify both services.
Do not unpause the campaign in this step.

- [ ] **Step 5: Prove the POST is asynchronous in production**

Use a non-sending fixture request or a route-level timing probe that performs no
provider mutation. Verify HTTP 202 in less than one second, then GET the same
request twice and confirm the same identity and counts.

- [ ] **Step 6: Dry-run the paused incident recovery**

```bash
sudo -u kivou /srv/kivou/app/.venv/bin/python -m \
  signals.prospection_actions.recovery \
  f593879c-1e4d-4e81-9619-8a2addf773e5 --dry-run
```

Required output: `approved_count=20`, `already_sent_count=1`,
`existing_lead_count=20`, `create_lead_count=0`. Stop if any value differs.

- [ ] **Step 7: Apply recovery and observe the worker to terminal state**

Run the same command with `--apply`, start the worker, and poll the GET status.
Required terminal state: 18 accepted in total, three failed with
`instantly_email_invalid`, zero lead imports, and the original sent target never
claimed by the worker.

- [ ] **Step 8: Reactivate only the existing campaign after convergence**

Allow the worker's guarded activation to resume the existing paused campaign.
Verify its provider ID is unchanged and Instantly still contains exactly 21
leads. Record SMTP/webhook outcomes separately from the 18 acceptance states.
