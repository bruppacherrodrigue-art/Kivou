# Instantly SHADOW Connectivity Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the manual SHADOW connectivity smoke accept the exact positive Instantly account shape observed on STAGING while preserving strict send-readiness behavior for every `CampaignWorker` consumer.

**Architecture:** Extend the existing mailbox normalizer and source with one default-strict `require_sending_gap` parameter. Only the acquisition connectivity composition opts out because the official Account schema makes the gap optional; outbound consumers retain the default and continue to fail closed. Recognize only the observed positive `CTD_ACTIVE` tracking token in addition to the existing closed vocabulary.

**Tech Stack:** Python 3.12, Pydantic contracts, httpx mock transport, pytest, Ruff, GitHub CLI.

---

### Task 1: Preserve strict send readiness and add the explicit connectivity profile

**Files:**
- Modify: `tests/test_instantly_adapter.py:510-544`
- Modify: `src/signals/campaigns/instantly.py:768-864`

- [ ] **Step 1: Run the existing adapter tests as the clean baseline**

Run:

```bash
uv run pytest -q tests/test_instantly_adapter.py
```

Expected: all existing Instantly adapter tests pass before the regression test is added.

- [ ] **Step 2: Add regression tests for the exact provider response and default-strict isolation**

Add the exact observed positive tracking token to the existing mapper table in
`tests/test_instantly_adapter.py`:

```python
        ({"tracking_domain_status": "CTD_ACTIVE"}, MailboxReadinessState.READY),
```

Then add these tests below `test_mailbox_readiness_mapper_is_typed_and_fail_closed`:

```python
def test_missing_optional_gap_remains_unknown_for_send_readiness() -> None:
    raw = {
        "status": 1,
        "warmup_status": 1,
        "setup_pending": False,
        "daily_limit": 20,
        "tracking_domain_status": "CTD_ACTIVE",
    }

    result = normalize_mailbox_readiness(
        raw, observed_at=dt.datetime(2026, 8, 24, 13, tzinfo=dt.UTC)
    )

    assert result.state is MailboxReadinessState.UNKNOWN
    assert result.sending_gap_seconds == 0


def test_connectivity_profile_accepts_openapi_optional_missing_gap() -> None:
    raw = {
        "status": 1,
        "warmup_status": 1,
        "setup_pending": False,
        "daily_limit": 20,
        "tracking_domain_status": "CTD_ACTIVE",
    }

    result = normalize_mailbox_readiness(
        raw,
        observed_at=dt.datetime(2026, 8, 24, 13, tzinfo=dt.UTC),
        require_sending_gap=False,
    )

    assert result.state is MailboxReadinessState.READY
    assert result.provider_daily_limit == 20
    assert result.sending_gap_seconds == 0
```

- [ ] **Step 3: Run the new tests and verify the RED state**

Run:

```bash
uv run pytest -q \
  tests/test_instantly_adapter.py::test_mailbox_readiness_mapper_is_typed_and_fail_closed \
  tests/test_instantly_adapter.py::test_missing_optional_gap_remains_unknown_for_send_readiness \
  tests/test_instantly_adapter.py::test_connectivity_profile_accepts_openapi_optional_missing_gap
```

Expected: the `CTD_ACTIVE` case is not `READY`, and the connectivity-profile test fails with `TypeError: normalize_mailbox_readiness() got an unexpected keyword argument 'require_sending_gap'`.

- [ ] **Step 4: Implement the minimal default-strict normalizer option**

Change the normalizer signature and validation in
`src/signals/campaigns/instantly.py` to this behavior:

```python
def normalize_mailbox_readiness(
    raw: object,
    *,
    observed_at: dt.datetime,
    require_sending_gap: bool = True,
) -> MailboxReadiness:
    """Map only bounded V2 account facts and fail closed on incomplete state."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("mailbox readiness observation must be timezone-aware")
    if not isinstance(raw, dict):
        return MailboxReadiness(
            state=MailboxReadinessState.UNKNOWN,
            provider_daily_limit=0,
            sending_gap_seconds=0,
            observed_at=observed_at,
        )
    official_status = {
        1: "active",
        2: "paused",
        3: "maintenance",
        -1: "connection_error",
        -2: "soft_bounce_error",
        -3: "sending_error",
    }.get(raw.get("status"), raw.get("status", ""))
    official_warmup = {
        0: "paused",
        1: "active",
        -1: "banned",
        -2: "spam_folder_unknown",
        -3: "permanent_suspension",
    }.get(raw.get("warmup_status"), raw.get("warmup_status", ""))
    status = str(official_status).strip().casefold().replace(" ", "_")
    warmup = str(official_warmup).strip().casefold().replace(" ", "_")
    tracking = (
        str(raw.get("tracking_domain_status", ""))
        .strip()
        .casefold()
        .replace(" ", "_")
    )
    setup_pending = raw.get("setup_pending")
    daily_limit = raw.get("daily_limit")
    sending_gap = raw.get("sending_gap")
    valid_daily_limit = (
        isinstance(daily_limit, int)
        and not isinstance(daily_limit, bool)
        and 0 <= daily_limit <= 100_000
    )
    valid_sending_gap = (
        isinstance(sending_gap, int)
        and not isinstance(sending_gap, bool)
        and 0 <= sending_gap <= 1_440
    )
    if (
        not isinstance(setup_pending, bool)
        or not valid_daily_limit
        or (require_sending_gap and not valid_sending_gap)
        or (sending_gap is not None and not valid_sending_gap)
    ):
        state = MailboxReadinessState.UNKNOWN
        normalized_daily_limit = 0
        normalized_sending_gap = 0
    else:
        normalized_daily_limit = daily_limit
        normalized_sending_gap = sending_gap if valid_sending_gap else 0
        if status in {
            "connection_error",
            "soft_bounce_error",
            "sending_error",
            "banned",
        } or warmup in {
            "banned",
            "suspended",
            "error",
            "spam_folder_unknown",
            "permanent_suspension",
        } or tracking in {"invalid", "error", "failed"}:
            state = MailboxReadinessState.UNHEALTHY
        elif (
            status in {"paused", "maintenance"}
            or warmup in {"paused", "maintenance"}
            or normalized_daily_limit == 0
        ):
            state = MailboxReadinessState.TEMPORARILY_UNAVAILABLE
        elif (
            status == "active"
            and setup_pending is False
            and warmup in {"active", "completed", "enabled"}
            and tracking
            in {"active", "verified", "connected", "not_required", "ctd_active"}
        ):
            state = MailboxReadinessState.READY
        else:
            state = MailboxReadinessState.UNKNOWN
    return MailboxReadiness(
        state=state,
        provider_daily_limit=normalized_daily_limit,
        sending_gap_seconds=normalized_sending_gap * 60,
        observed_at=observed_at,
        valid_until=(
            observed_at + dt.timedelta(minutes=5)
            if state is MailboxReadinessState.READY
            else None
        ),
    )
```

Extend the existing source without changing its default:

```python
class InstantlyMailboxReadinessSource:
    """Explicit network-backed source; construction and imports perform no I/O."""

    def __init__(
        self,
        provider: InstantlyProvider,
        *,
        require_sending_gap: bool = True,
    ) -> None:
        self._provider = provider
        self._require_sending_gap = require_sending_gap

    def get(
        self, provider_account_id: str, *, observed_at: dt.datetime
    ) -> MailboxReadiness:
        return normalize_mailbox_readiness(
            self._provider.get_mailbox_readiness(provider_account_id),
            observed_at=observed_at,
            require_sending_gap=self._require_sending_gap,
        )
```

- [ ] **Step 5: Run the adapter tests and verify GREEN**

Run:

```bash
uv run pytest -q tests/test_instantly_adapter.py
```

Expected: all adapter tests pass, including the default-strict and connectivity-profile regressions.

- [ ] **Step 6: Commit the normalizer behavior**

```bash
git add src/signals/campaigns/instantly.py tests/test_instantly_adapter.py
git commit -m "fix(acquisition): distinguish Instantly connectivity readiness"
```

### Task 2: Wire the opt-out only into the manual SHADOW composition

**Files:**
- Modify: `tests/test_acquisition_connectivity_instantly.py:42-78`
- Modify: `tests/test_acquisition_connectivity_architecture.py:1-70`
- Modify: `src/signals/acquisition_connectivity/cli.py:52-66`

- [ ] **Step 1: Add the captured response-shape smoke regression**

Change the test probe helper in
`tests/test_acquisition_connectivity_instantly.py`:

```python
    return InstantlyConnectivityProbe(
        provider=provider,
        mailbox_readiness=InstantlyMailboxReadinessSource(
            provider, require_sending_gap=False
        ),
    )
```

Add this test after `test_probe_reuses_provider_and_normalizer_for_four_official_gets`:

```python
def test_probe_accepts_exact_configured_staging_account_shape() -> None:
    account = _ready_account(tracking_domain_status="CTD_ACTIVE")
    account.pop("sending_gap")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/workspaces/current"):
            return httpx.Response(200, json={"id": "workspace-staging-ref"})
        return httpx.Response(200, json=account)

    evidence = _probe(handler).check(_document(), observed_at=NOW)

    assert evidence.workspace == "BOUND"
    assert evidence.mailboxes_ready == 3
    assert evidence.mailboxes_total == 3
```

Add this architectural ownership test to
`tests/test_acquisition_connectivity_architecture.py`:

```python
def test_optional_gap_profile_is_owned_only_by_manual_connectivity_composition() -> None:
    opt_out_callers = [
        path
        for path in Path("src/signals").rglob("*.py")
        if "require_sending_gap=False" in path.read_text(encoding="utf-8")
    ]

    assert opt_out_callers == [Path("src/signals/acquisition_connectivity/cli.py")]
```

- [ ] **Step 2: Run the connectivity regressions and verify the RED state**

Run:

```bash
uv run pytest -q \
  tests/test_acquisition_connectivity_instantly.py::test_probe_accepts_exact_configured_staging_account_shape \
  tests/test_acquisition_connectivity_architecture.py::test_optional_gap_profile_is_owned_only_by_manual_connectivity_composition
```

Expected: the response-shape test passes through the test-only explicit profile, while the architectural test fails because production composition has not opted in yet.

- [ ] **Step 3: Wire the existing source in the production composition root**

Change only the Instantly source construction in
`src/signals/acquisition_connectivity/cli.py`:

```python
    instantly = InstantlyConnectivityProbe(
        provider=instantly_provider,
        mailbox_readiness=InstantlyMailboxReadinessSource(
            instantly_provider,
            require_sending_gap=False,
        ),
    )
```

- [ ] **Step 4: Run all connectivity wiring tests and verify GREEN**

Run:

```bash
uv run pytest -q \
  tests/test_acquisition_connectivity_instantly.py \
  tests/test_acquisition_connectivity_cli.py \
  tests/test_acquisition_connectivity_architecture.py
```

Expected: all tests pass; the exact response shape yields three ready mailboxes, while negative and unknown states still fail closed.

- [ ] **Step 5: Commit the composition wiring**

```bash
git add \
  src/signals/acquisition_connectivity/cli.py \
  tests/test_acquisition_connectivity_instantly.py \
  tests/test_acquisition_connectivity_architecture.py
git commit -m "fix(acquisition): wire optional Instantly gap for shadow smoke"
```

### Task 3: Verify the complete delta and open the review PR

**Files:**
- Verify: `src/signals/campaigns/instantly.py`
- Verify: `src/signals/acquisition_connectivity/cli.py`
- Verify: `tests/test_instantly_adapter.py`
- Verify: `tests/test_acquisition_connectivity_instantly.py`
- Verify: `tests/test_acquisition_connectivity_cli.py`
- Verify: `tests/test_acquisition_connectivity_architecture.py`
- Verify: `docs/superpowers/specs/2026-08-24-instantly-shadow-connectivity-hotfix-design.md`
- Verify: `docs/superpowers/plans/2026-08-24-instantly-shadow-connectivity-hotfix.md`

- [ ] **Step 1: Run the targeted regression suite**

```bash
uv run pytest -q \
  tests/test_instantly_adapter.py \
  tests/test_acquisition_connectivity_instantly.py \
  tests/test_acquisition_connectivity_cli.py \
  tests/test_acquisition_connectivity_architecture.py
```

Expected: all targeted tests pass with no provider network access.

- [ ] **Step 2: Run Ruff and whitespace checks**

```bash
uv run ruff check .
git diff --check origin/main...HEAD
```

Expected: Ruff emits no findings and `git diff --check` emits no output.

- [ ] **Step 3: Run the complete backend suite**

```bash
uv run pytest -q
```

Expected: the complete backend suite passes. Frontend tests are not required because no frontend or shared client contract is modified.

- [ ] **Step 4: Inspect the bounded diff and prove no deployment or secret file changed**

```bash
git status --short
git diff --stat origin/main...HEAD
git diff --name-only origin/main...HEAD
git diff origin/main...HEAD -- \
  src/signals/campaigns/instantly.py \
  src/signals/acquisition_connectivity/cli.py \
  tests/test_instantly_adapter.py \
  tests/test_acquisition_connectivity_instantly.py \
  tests/test_acquisition_connectivity_architecture.py
```

Expected: the worktree is clean; only the two documentation files, two Python source files, and three test files belong to the branch. No `.env`, example configuration, systemd unit, provider secret, mailbox address, migration, frontend file, worker, policy, or store changes.

- [ ] **Step 5: Push the branch and open a PR without merging**

```bash
git push -u origin fix/acquisition-shadow-instantly-connectivity
gh pr create \
  --base main \
  --head fix/acquisition-shadow-instantly-connectivity \
  --title "fix(acquisition): accept optional Instantly gap in shadow connectivity" \
  --body "$(printf '%s\n' \
    '## Summary' \
    '- preserve strict Instantly send readiness for CampaignWorker' \
    '- accept the official optional sending_gap only in the manual SHADOW connectivity composition' \
    '- recognize the observed positive CTD_ACTIVE token through the existing normalizer' \
    '' \
    '## Safety' \
    '- GET-only provider path unchanged' \
    '- no provider mutation, campaign, lead, email, worker, scheduler, timer, policy, store, secret, or VPS configuration change' \
    '- unknown states remain fail-closed and the outbound default still requires sending_gap' \
    '' \
    '## Validation' \
    '- targeted pytest: PASS' \
    '- Ruff: PASS' \
    '- git diff --check: PASS' \
    '- complete backend pytest: PASS' \
    '' \
    'Official contract: https://api.instantly.ai/openapi/api_v2.json')"
```

Expected: GitHub returns the new PR URL. Do not merge or deploy the hotfix until its exact head SHA and CI result have been reviewed.
