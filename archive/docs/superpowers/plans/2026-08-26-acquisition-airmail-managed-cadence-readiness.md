# Acquisition AirMail Managed Cadence Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the staging-only QA Acquisition runtime accept an explicit protected cadence for verified managed AirMail accounts when Instantly omits `sending_gap`, without weakening the default send-readiness gate.

**Architecture:** Add one optional strict cadence to each existing protected mailbox binding. Preserve the provider's AirMail classification and actual key omission through the narrow Instantly adapter, then let the single readiness normalizer use the configured value only under the exact managed-AirMail proof. Pass the same account-scoped configuration to the runtime dependency probe and campaign boundary; keep the manual connectivity smoke unchanged.

**Tech Stack:** Python 3.12, Pydantic v2, httpx, pytest, Ruff, GitHub Actions.

---

## Scope and file map

Modify only these implementation surfaces:

- `src/signals/acquisition_connectivity/contracts.py`: protected binding field and validation.
- `src/signals/campaigns/instantly.py`: bounded provider facts, omission preservation, normalization and readiness source.
- `src/signals/acquisition_runtime/execution.py`: account map wiring and auditable fingerprints.
- `tests/test_acquisition_connectivity_config.py`: closed configuration contract.
- `tests/test_instantly_adapter.py`: provider boundary and normalization truth table.
- `tests/test_acquisition_connectivity_instantly.py`: connectivity-profile regression.
- `tests/test_acquisition_runtime_execution.py`: dependency and campaign composition wiring.
- `tests/test_acquisition_connectivity_architecture.py`: composition and redacted-example guardrails.
- `ops/examples/acquisition-shadow.json.example`: non-secret example cadence.
- `docs/runbooks/08-acquisition-shadow-provider-connectivity.md`: deployment order and rollback.
- `docs/superpowers/specs/2026-08-26-acquisition-airmail-managed-cadence-readiness-design.md`: approved status only.
- `docs/superpowers/plans/2026-08-26-acquisition-airmail-managed-cadence-readiness.md`: this executable TDD plan.

Do not add a migration, frontend change, provider write, retry, default cadence,
timer activation or production configuration.

### Task 1: Add the strict protected cadence contract

**Files:**

- Modify: `tests/test_acquisition_connectivity_config.py:15-176`
- Modify: `src/signals/acquisition_connectivity/contracts.py:63-65`

- [ ] **Step 1: Add the failing configuration tests**

Add this helper below `_deployment` and these tests below
`test_complete_configuration_is_strict_and_keeps_secrets_opaque`:

```python
def _deployment_with_airmail_gap(value: object) -> dict[str, object]:
    document = _deployment()
    mailboxes = list(document["mailboxes"])
    first = dict(mailboxes[0])
    first["managed_airmail_sending_gap_minutes"] = value
    mailboxes[0] = first
    document["mailboxes"] = mailboxes
    return document


@pytest.mark.parametrize("value", [1, 10, 1_440])
def test_managed_airmail_gap_accepts_only_bounded_strict_minutes(
    tmp_path: Path, value: int
) -> None:
    config = load_connectivity_config(
        _environment(tmp_path, _deployment_with_airmail_gap(value))
    )

    assert config.deployment.mailboxes[0].managed_airmail_sending_gap_minutes == value
    assert all(
        binding.managed_airmail_sending_gap_minutes is None
        for binding in config.deployment.mailboxes[1:]
    )


@pytest.mark.parametrize("value", [0, -1, 1_441, True, "10", 10.0])
def test_managed_airmail_gap_rejects_unsafe_or_coerced_values(
    tmp_path: Path, value: object
) -> None:
    with pytest.raises(ConnectivityFailure) as caught:
        load_connectivity_config(
            _environment(tmp_path, _deployment_with_airmail_gap(value))
        )

    assert caught.value.code is ConnectivityErrorCode.NOT_CONFIGURED
    assert "@" not in str(caught.value)


def test_existing_v1_document_without_airmail_gap_remains_fail_closed_compatible(
    tmp_path: Path,
) -> None:
    config = load_connectivity_config(_environment(tmp_path, _deployment()))

    assert config.deployment.schema_version == "acquisition-shadow-connectivity-v1"
    assert all(
        binding.managed_airmail_sending_gap_minutes is None
        for binding in config.deployment.mailboxes
    )
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
uv run pytest -q tests/test_acquisition_connectivity_config.py \
  -k 'managed_airmail_gap or existing_v1_document'
```

Expected: failure because `managed_airmail_sending_gap_minutes` is still an
extra forbidden property or absent from `ShadowMailboxBinding`.

- [ ] **Step 3: Add the minimal strict field**

Change `ShadowMailboxBinding` to:

```python
class ShadowMailboxBinding(_DeploymentModel):
    mailbox_ref: OpaqueRef
    provider_account_id: ProviderAccountEmail = Field(repr=False)
    managed_airmail_sending_gap_minutes: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        le=1_440,
    )
```

Do not change `SHADOW_CONNECTIVITY_SCHEMA_VERSION`.

- [ ] **Step 4: Run the contract tests and verify GREEN**

Run:

```bash
uv run pytest -q tests/test_acquisition_connectivity_config.py
uv run ruff check src/signals/acquisition_connectivity/contracts.py \
  tests/test_acquisition_connectivity_config.py
```

Expected: all configuration tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit the contract change**

```bash
git add src/signals/acquisition_connectivity/contracts.py \
  tests/test_acquisition_connectivity_config.py
git commit -m "feat(acquisition): add protected AirMail cadence binding"
```

### Task 2: Preserve AirMail proof and normalize the configured cadence

**Files:**

- Modify: `tests/test_instantly_adapter.py:1-20,520-579`
- Modify: `tests/test_acquisition_connectivity_instantly.py:100-150`
- Modify: `src/signals/campaigns/instantly.py:1-12,660-673,768-892`

- [ ] **Step 1: Add failing adapter and normalization tests**

Import `InstantlyMailboxReadinessSource` in
`tests/test_instantly_adapter.py`, then add:

```python
READINESS_NOW = dt.datetime(2026, 8, 26, 8, tzinfo=dt.UTC)


def _managed_airmail_account(**updates: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "status": 1,
        "warmup_status": 1,
        "setup_pending": False,
        "daily_limit": 20,
        "tracking_domain_status": "CTD_ACTIVE",
        "provider_code": 8,
        "is_managed_account": True,
    }
    raw.update(updates)
    return raw


def test_mailbox_readiness_adapter_preserves_airmail_facts_and_real_omission() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                **_managed_airmail_account(),
                "email": "private@example.invalid",
                "signature": "private-provider-value",
            },
        )

    result = _provider(handler).get_mailbox_readiness("sender@example.invalid")

    assert result == _managed_airmail_account()
    assert "sending_gap" not in result
    assert "email" not in result
    assert "signature" not in result


def test_strict_managed_airmail_uses_exact_protected_gap_when_provider_omits_it() -> None:
    result = normalize_mailbox_readiness(
        _managed_airmail_account(),
        observed_at=READINESS_NOW,
        managed_airmail_sending_gap_minutes=10,
    )

    assert result.state is MailboxReadinessState.READY
    assert result.sending_gap_seconds == 600


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_code": 7},
        {"provider_code": True},
        {"provider_code": "8"},
        {"provider_code": None},
        {"is_managed_account": False},
        {"is_managed_account": 1},
        {"is_managed_account": None},
        {"sending_gap": None},
        {"sending_gap": "10"},
        {"sending_gap": 20},
    ],
)
def test_managed_airmail_gap_fails_closed_without_exact_provider_proof(
    changes: dict[str, object],
) -> None:
    result = normalize_mailbox_readiness(
        _managed_airmail_account(**changes),
        observed_at=READINESS_NOW,
        managed_airmail_sending_gap_minutes=10,
    )

    assert result.state is MailboxReadinessState.UNKNOWN
    assert result.sending_gap_seconds == 0


def test_matching_provider_gap_remains_authoritative() -> None:
    result = normalize_mailbox_readiness(
        _managed_airmail_account(sending_gap=10),
        observed_at=READINESS_NOW,
        managed_airmail_sending_gap_minutes=10,
    )

    assert result.state is MailboxReadinessState.READY
    assert result.sending_gap_seconds == 600
```

Add this local provider and source-isolation tests:

```python
class _ReadinessProvider:
    def get_mailbox_readiness(self, _provider_account_id: str) -> dict[str, object]:
        return _managed_airmail_account()


def test_readiness_source_binds_cadence_to_one_casefolded_account() -> None:
    source = InstantlyMailboxReadinessSource(
        _ReadinessProvider(),
        managed_airmail_sending_gaps={"SENDER-ONE@EXAMPLE.INVALID": 10},
    )

    matching = source.get("sender-one@example.invalid", observed_at=READINESS_NOW)
    other = source.get("sender-two@example.invalid", observed_at=READINESS_NOW)

    assert matching.state is MailboxReadinessState.READY
    assert matching.sending_gap_seconds == 600
    assert other.state is MailboxReadinessState.UNKNOWN


def test_readiness_source_rejects_cadence_map_for_connectivity_opt_out() -> None:
    with pytest.raises(ValueError, match="strict send-readiness"):
        InstantlyMailboxReadinessSource(
            _ReadinessProvider(),
            require_sending_gap=False,
            managed_airmail_sending_gaps={"sender@example.invalid": 10},
        )
```

The existing
`test_probe_accepts_exact_configured_staging_account_shape` and
`test_probe_reuses_provider_and_normalizer_for_four_official_gets` tests remain
unchanged as the connectivity-only omission and request-count regressions.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest -q \
  tests/test_instantly_adapter.py \
  tests/test_acquisition_connectivity_instantly.py \
  -k 'airmail or mailbox_readiness or optional_gap'
```

Expected: failures from missing allowlisted facts and unsupported configured
cadence arguments.

- [ ] **Step 3: Preserve only present allowlisted provider facts**

Change `HttpInstantlyProvider.get_mailbox_readiness` to use this allowlist and
presence-preserving projection:

```python
allowed = {
    "status",
    "warmup_status",
    "setup_pending",
    "daily_limit",
    "sending_gap",
    "tracking_domain_status",
    "provider_code",
    "is_managed_account",
}
return {key: value[key] for key in allowed if key in value}
```

- [ ] **Step 4: Add one effective-gap helper and keep the normalizer fail-closed**

Add this private helper immediately before `normalize_mailbox_readiness`:

```python
def _strict_bounded_int(value: object, *, minimum: int, maximum: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )


def _effective_sending_gap_minutes(
    raw: dict[str, object],
    *,
    require_sending_gap: bool,
    managed_airmail_sending_gap_minutes: int | None,
) -> int | None:
    provider_gap_present = "sending_gap" in raw
    provider_gap = raw.get("sending_gap")
    provider_gap_valid = _strict_bounded_int(
        provider_gap,
        minimum=0,
        maximum=1_440,
    )
    configured_gap_valid = (
        managed_airmail_sending_gap_minutes is None
        or _strict_bounded_int(
            managed_airmail_sending_gap_minutes,
            minimum=1,
            maximum=1_440,
        )
    )
    if not configured_gap_valid:
        return None
    if managed_airmail_sending_gap_minutes is None:
        if provider_gap_present:
            return int(provider_gap) if provider_gap_valid else None
        return None if require_sending_gap else 0
    if not require_sending_gap:
        return None
    provider_code = raw.get("provider_code")
    managed_airmail = (
        isinstance(provider_code, int)
        and not isinstance(provider_code, bool)
        and provider_code == 8
        and raw.get("is_managed_account") is True
    )
    if not managed_airmail:
        return None
    if not provider_gap_present:
        return managed_airmail_sending_gap_minutes
    if not provider_gap_valid or provider_gap != managed_airmail_sending_gap_minutes:
        return None
    return int(provider_gap)
```

Extend `normalize_mailbox_readiness` with:

```python
managed_airmail_sending_gap_minutes: int | None = None,
```

Replace its direct `sending_gap` validation with:

```python
normalized_sending_gap = _effective_sending_gap_minutes(
    raw,
    require_sending_gap=require_sending_gap,
    managed_airmail_sending_gap_minutes=managed_airmail_sending_gap_minutes,
)
```

Treat `normalized_sending_gap is None` as the existing `UNKNOWN` branch and
otherwise use the returned integer directly. Keep all existing status, warmup,
setup, daily-limit, tracking and five-minute freshness checks unchanged.

- [ ] **Step 5: Add the immutable account-scoped source configuration**

Import `Mapping` from `collections.abc` and `MappingProxyType` from `types`, then
replace the source constructor and `get` implementation with:

```python
def __init__(
    self,
    provider: InstantlyProvider,
    *,
    require_sending_gap: bool = True,
    managed_airmail_sending_gaps: Mapping[str, int] | None = None,
) -> None:
    source = managed_airmail_sending_gaps or {}
    normalized: dict[str, int] = {}
    for account, gap in source.items():
        if not isinstance(account, str) or not account.strip() or len(account.strip()) > 320:
            raise ValueError("managed AirMail account binding is invalid")
        if not _strict_bounded_int(gap, minimum=1, maximum=1_440):
            raise ValueError("managed AirMail cadence is invalid")
        key = account.strip().casefold()
        if key in normalized:
            raise ValueError("managed AirMail account binding is duplicated")
        normalized[key] = gap
    if normalized and not require_sending_gap:
        raise ValueError("managed AirMail cadence requires strict send-readiness")
    self._provider = provider
    self._require_sending_gap = require_sending_gap
    self._managed_airmail_sending_gaps = MappingProxyType(normalized)


def get(self, provider_account_id: str, *, observed_at: dt.datetime) -> MailboxReadiness:
    account_key = provider_account_id.strip().casefold()
    return normalize_mailbox_readiness(
        self._provider.get_mailbox_readiness(provider_account_id),
        observed_at=observed_at,
        require_sending_gap=self._require_sending_gap,
        managed_airmail_sending_gap_minutes=(
            self._managed_airmail_sending_gaps.get(account_key)
        ),
    )
```

- [ ] **Step 6: Run the adapter and normalization suites and verify GREEN**

Run:

```bash
uv run pytest -q tests/test_instantly_adapter.py \
  tests/test_acquisition_connectivity_instantly.py
uv run ruff check src/signals/campaigns/instantly.py \
  tests/test_instantly_adapter.py \
  tests/test_acquisition_connectivity_instantly.py
```

Expected: all tests pass; no real network request is made.

- [ ] **Step 7: Commit the provider-boundary change**

```bash
git add src/signals/campaigns/instantly.py \
  tests/test_instantly_adapter.py \
  tests/test_acquisition_connectivity_instantly.py
git commit -m "fix(acquisition): normalize managed AirMail cadence"
```

### Task 3: Wire the strict cadence through runtime readiness and campaigns

**Files:**

- Modify: `tests/test_acquisition_runtime_execution.py:100-115,214-233,320-416`
- Modify: `src/signals/acquisition_runtime/execution.py:165-181,322-370,605-617`

- [ ] **Step 1: Make the dependency fixture reproduce the staging omission**

Change `ProbeInstantlyProvider.get_mailbox_readiness` so it returns the exact
bounded managed-AirMail facts without `sending_gap`:

```python
def get_mailbox_readiness(self, _provider_account_email):
    return {
        "status": 1 if self.mailbox_ready else -1,
        "warmup_status": 1,
        "setup_pending": False,
        "daily_limit": 3,
        "tracking_domain_status": "active",
        "provider_code": 8,
        "is_managed_account": True,
    }
```

Change the helper signature and binding construction to:

```python
def _connectivity_config(
    tmp_path,
    *,
    managed_gap: int | None = 10,
) -> AcquisitionConnectivityConfig:
    return AcquisitionConnectivityConfig(
        environment="STAGING",
        shadow_config_path=tmp_path / "shadow.json",
        apollo_api_key=SecretStr("synthetic-apollo-key"),
        instantly_api_key=SecretStr("synthetic-instantly-key"),
        hermes_python=tmp_path / "hermes-python",
        hermes_home=tmp_path / "hermes-home",
        hermes_cwd=tmp_path / "hermes-cwd",
        deployment=ShadowConnectivityDocument(
            instantly_workspace_ref="workspace-qa",
            mailboxes=tuple(
                ShadowMailboxBinding(
                    mailbox_ref=f"mailbox-qa-{index}",
                    provider_account_id=f"sender-{index}@example.com",
                    managed_airmail_sending_gap_minutes=managed_gap,
                )
                for index in range(1, 4)
            ),
        ),
    )
```

- [ ] **Step 2: Add failing runtime wiring and fingerprint tests**

Keep `test_production_dependency_probe_reports_real_bounded_component_readiness`
unchanged after the fixture update; it now proves the dependency probe consumes
the protected cadence. Add:

```python
def test_runtime_campaign_source_uses_the_same_managed_airmail_binding(tmp_path) -> None:
    engine = _engine()
    provider = ProbeInstantlyProvider()
    apollo = ApolloComponents(
        organization_search=NoNetworkProvider(),
        contact_discovery=NoNetworkProvider(),
        company_research=NoNetworkProvider(),
        identity=NoNetworkProvider(),
    )
    composition = build_runtime_execution_composition(
        engine=engine,
        runtime_config=_runtime_config(),
        connectivity_config=_connectivity_config(tmp_path),
        links=_links(),
        webhook_configuration=_webhook_configuration(),
        apollo=apollo,
        instantly_provider=provider,
        hermes_runtime=ClosedFakeHermes(),
        dependency_probe=ReadyDependencyProbe(),
        clock=lambda: NOW,
    )

    readiness = composition.domain.campaign_service._mailbox_readiness.get(
        "SENDER-1@EXAMPLE.COM",
        observed_at=NOW,
    )

    assert readiness.state is MailboxReadinessState.READY
    assert readiness.sending_gap_seconds == 600
    engine.dispose()
```

Import `MailboxReadinessState` from `signals.campaigns.contracts` for this test.
Add the fail-closed compatibility and fingerprint tests:

```python
def test_dependency_probe_keeps_missing_managed_gap_not_ready(tmp_path) -> None:
    probe = ProductionRuntimeDependencyProbe(
        apollo=SimpleNamespace(identity=ProbeApolloIdentity()),
        instantly_provider=ProbeInstantlyProvider(),
        connectivity=_connectivity_config(tmp_path, managed_gap=None),
        hermes_runtime=ClosedFakeHermes(),
        webhook_configuration=_webhook_configuration(),
    )

    dependencies = {item.stage: item for item in probe.check(observed_at=NOW)}

    assert dependencies[AcquisitionRuntimeStage.CAMPAIGN].reason_codes == (
        "MAILBOX_DEPENDENCY_NOT_READY",
    )


def test_managed_airmail_cadence_changes_runtime_and_mailbox_fingerprints(
    tmp_path,
) -> None:
    engine = _engine()
    provider = NoNetworkProvider()
    apollo = ApolloComponents(
        organization_search=provider,
        contact_discovery=provider,
        company_research=provider,
        identity=provider,
    )
    common = {
        "engine": engine,
        "runtime_config": _runtime_config(),
        "links": _links(),
        "webhook_configuration": _webhook_configuration(),
        "apollo": apollo,
        "instantly_provider": provider,
        "hermes_runtime": ClosedFakeHermes(),
        "dependency_probe": ReadyDependencyProbe(),
        "clock": lambda: NOW,
    }
    before = build_runtime_execution_composition(
        **common,
        connectivity_config=_connectivity_config(tmp_path, managed_gap=10),
    )
    after = build_runtime_execution_composition(
        **common,
        connectivity_config=_connectivity_config(tmp_path, managed_gap=20),
    )
    before_mailbox = (
        before.domain.campaign_service._deployment.mailbox_catalog.entries[0]
    )
    after_mailbox = after.domain.campaign_service._deployment.mailbox_catalog.entries[0]

    assert before.config_fingerprint != after.config_fingerprint
    assert before_mailbox.config_fingerprint != after_mailbox.config_fingerprint
    engine.dispose()
```

- [ ] **Step 3: Run the runtime tests and verify RED**

Run:

```bash
uv run pytest -q tests/test_acquisition_runtime_execution.py \
  -k 'production_dependency_probe_reports or managed_airmail_binding or cadence_fingerprint'
```

Expected: readiness remains `NOT_READY` or `UNKNOWN` because neither runtime
composition passes the configured account map yet; the mailbox fingerprint is
also unchanged.

- [ ] **Step 4: Add one map builder and wire both strict consumers**

Add near `_mailbox_fingerprint`:

```python
def _managed_airmail_sending_gaps(
    connectivity: AcquisitionConnectivityConfig,
) -> dict[str, int]:
    return {
        str(binding.provider_account_id).casefold(): gap
        for binding in connectivity.deployment.mailboxes
        if (gap := binding.managed_airmail_sending_gap_minutes) is not None
    }
```

Construct the dependency source with:

```python
InstantlyMailboxReadinessSource(
    instantly_provider,
    managed_airmail_sending_gaps=_managed_airmail_sending_gaps(connectivity),
)
```

Construct the campaign source with:

```python
InstantlyMailboxReadinessSource(
    provider,
    managed_airmail_sending_gaps=(
        _managed_airmail_sending_gaps(connectivity_config)
    ),
)
```

Do not alter the manual connectivity composition in
`src/signals/acquisition_connectivity/cli.py`.

- [ ] **Step 5: Bind the cadence into the mailbox fingerprint**

Add this item to the dictionary passed to `_mailbox_fingerprint`:

```python
"managed_airmail_sending_gap_minutes": (
    binding.managed_airmail_sending_gap_minutes
),
```

The global runtime fingerprint already includes the entire connectivity
deployment; do not add a second global fingerprint mechanism.

- [ ] **Step 6: Run runtime and architecture tests and verify GREEN**

Run:

```bash
uv run pytest -q \
  tests/test_acquisition_runtime_execution.py \
  tests/test_acquisition_connectivity_architecture.py
uv run ruff check src/signals/acquisition_runtime/execution.py \
  tests/test_acquisition_runtime_execution.py
```

Expected: all tests pass; dependency readiness and campaign readiness both use
600 seconds for the configured staging fixture.

- [ ] **Step 7: Commit the runtime wiring**

```bash
git add src/signals/acquisition_runtime/execution.py \
  tests/test_acquisition_runtime_execution.py
git commit -m "fix(acquisition): wire AirMail cadence into runtime readiness"
```

### Task 4: Version the redacted example and rollback procedure

**Files:**

- Modify: `tests/test_acquisition_connectivity_architecture.py:119-150`
- Modify: `ops/examples/acquisition-shadow.json.example:1-20`
- Modify: `docs/runbooks/08-acquisition-shadow-provider-connectivity.md:90-150`

- [ ] **Step 1: Add the failing example-contract assertion**

After parsing `OPS_JSON` in
`test_redacted_deployment_examples_are_strict_and_secret_free`, add:

```python
assert {
    binding.managed_airmail_sending_gap_minutes
    for binding in deployment.mailboxes
} == {10}
```

- [ ] **Step 2: Run the architecture test and verify RED**

Run:

```bash
uv run pytest -q tests/test_acquisition_connectivity_architecture.py \
  -k redacted_deployment_examples
```

Expected: failure because the example bindings still have no managed AirMail
cadence.

- [ ] **Step 3: Update the example and runbook**

Add this property to each of the three synthetic mailbox objects in
`ops/examples/acquisition-shadow.json.example`:

```json
"managed_airmail_sending_gap_minutes": 10
```

Add a runbook subsection immediately after protected JSON provisioning that
states all of the following operational facts:

```text
Install code containing the optional field before changing the protected JSON.
Use the field only for an account whose fresh GET response proves provider_code
8, is_managed_account true and actual omission of sending_gap. A provider value,
null, mismatch or different classification blocks readiness. The value is a
Kivou operator cadence, not an Instantly observation. Restore the protected JSON
backup before rolling back to code that predates the field.
```

Keep example identities synthetic and include no provider key, real mailbox or
secret.

- [ ] **Step 4: Run documentation guardrails and verify GREEN**

Run:

```bash
uv run pytest -q tests/test_acquisition_connectivity_architecture.py
uv run ruff check tests/test_acquisition_connectivity_architecture.py
git diff --check
```

Expected: all architecture tests and checks pass.

- [ ] **Step 5: Commit the documentation**

```bash
git add ops/examples/acquisition-shadow.json.example \
  docs/runbooks/08-acquisition-shadow-provider-connectivity.md \
  tests/test_acquisition_connectivity_architecture.py \
  docs/superpowers/specs/2026-08-26-acquisition-airmail-managed-cadence-readiness-design.md \
  docs/superpowers/plans/2026-08-26-acquisition-airmail-managed-cadence-readiness.md
git commit -m "docs(acquisition): document managed AirMail cadence rollout"
```

### Task 5: Final verification and GitHub delivery

**Files:**

- Verify every file listed in the scope map; create no additional file.

- [ ] **Step 1: Run the complete targeted regression set**

```bash
uv run pytest -q \
  tests/test_acquisition_connectivity_config.py \
  tests/test_acquisition_connectivity_instantly.py \
  tests/test_acquisition_connectivity_architecture.py \
  tests/test_instantly_adapter.py \
  tests/test_acquisition_runtime_execution.py
```

Expected: zero failed tests and zero real network requests.

- [ ] **Step 2: Run the complete backend validation once on the final local HEAD**

```bash
uv run ruff check .
uv run pytest
git diff --check origin/main...HEAD
git status --short
```

Expected: Ruff and pytest exit zero; the diff check is clean; `git status
--short` is empty.

- [ ] **Step 3: Review the exact scope and forbidden surfaces**

```bash
git diff --name-only origin/main...HEAD
git diff --stat origin/main...HEAD
git diff --name-only origin/main...HEAD | rg \
  '^(frontend/|src/signals/(acquisition/|supplier_discovery/|company_research/|contact_discovery/|personalization/|compliance/)|src/signals/persistence/migrations/)'
```

Expected: the first two commands list only the files in this plan. The final
command returns exit code 1 with no output, proving no forbidden engine module,
frontend or migration changed.

- [ ] **Step 4: Synchronize by a normal merge and re-run final validation if main moved**

```bash
git fetch origin
git merge --no-edit origin/main
```

If the merge creates a commit, repeat Steps 1-3 on that merged HEAD. Do not
rebase and do not force-push.

- [ ] **Step 5: Push once and open the focused PR**

Rename the local branch before the first push:

```bash
git branch -m fix/acquisition-airmail-readiness
git push -u origin fix/acquisition-airmail-readiness
```

Open a PR titled:

```text
fix(acquisition): support managed AirMail cadence readiness
```

The PR body must reference issue #83 and contain: confirmed cause, minimal
correction, no-migration statement, risks, protected-JSON-first rollback order,
executed test commands, no real network/provider mutation, and exact closure
criteria. Do not include provider payloads, mailbox identities or secrets.

- [ ] **Step 6: Inspect the single CI run for the final PR HEAD**

Run:

```bash
gh pr checks --watch
gh run list --branch fix/acquisition-airmail-readiness --limit 5
```

Use `gh run view <run-id> --log-failed` only when a check fails. Diagnose and
correct the cause before pushing a new commit; do not rerun a red job merely to
obtain green. Do not merge until every required check is green.

The merged deployment and controlled staging proof are the next operational
phase of audit #80. They are not evidence produced by this offline TDD plan.
