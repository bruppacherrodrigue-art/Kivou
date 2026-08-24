from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from signals.acquisition_connectivity.config import validate_hermes_shadow_config
from signals.acquisition_connectivity.contracts import (
    AcquisitionConnectivityConfig,
    ConnectivityErrorCode,
    ConnectivityFailure,
    ShadowConnectivityDocument,
)
from signals.acquisition_connectivity.service import HermesConnectivityProbe
from signals.policy.contracts import AutonomyMode, PolicyControlSnapshot
from signals.supervisor.contracts import ProposedAction, SupervisorLimits, SupervisorPlan
from signals.supervisor.hermes import HermesSupervisorAdapter
from signals.supervisor.pin import load_hermes_pin
from signals.supervisor.profile import PROFILE_VERSION
from signals.supervisor.runtime import (
    HealthState,
    SupervisorHealth,
    SupervisorSettings,
    SupervisorTimeout,
    SupervisorValidationError,
)

NOW = dt.datetime(2026, 8, 24, 12, tzinfo=dt.UTC)
MODEL = "anthropic/claude-sonnet-4.6"
PIN = load_hermes_pin()


def _model_config(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "model": {"provider": "openrouter", "default": MODEL},
        "provider_routing": {
            "require_parameters": True,
            "data_collection": "deny",
        },
    }
    value.update(updates)
    return value


def _deployment() -> ShadowConnectivityDocument:
    return ShadowConnectivityDocument.model_validate(
        {
            "schema_version": "acquisition-shadow-connectivity-v1",
            "instantly_workspace_ref": "workspace-staging-ref",
            "mailboxes": [
                {"mailbox_ref": "mailbox-01", "provider_account_id": "one@example.com"},
                {"mailbox_ref": "mailbox-02", "provider_account_id": "two@example.com"},
                {"mailbox_ref": "mailbox-03", "provider_account_id": "three@example.com"},
            ],
        }
    )


def _config(tmp_path: Path, document: object | None = None) -> AcquisitionConnectivityConfig:
    home = tmp_path / "home"
    work = home / "work"
    home.mkdir(exist_ok=True)
    work.mkdir(exist_ok=True)
    python = tmp_path / "python"
    python.write_text("fixture", encoding="utf-8")
    if document is not None:
        (home / "config.yaml").write_text(json.dumps(document), encoding="utf-8")
    return AcquisitionConnectivityConfig(
        environment="STAGING",
        shadow_config_path=tmp_path / "shadow.json",
        apollo_api_key="synthetic-apollo",
        instantly_api_key="synthetic-instantly",
        hermes_python=python,
        hermes_home=home,
        hermes_cwd=work,
        deployment=_deployment(),
    )


def _control() -> PolicyControlSnapshot:
    return PolicyControlSnapshot.model_validate(
        {
            "policy_snapshot_id": "shadow-control",
            "control_revision": 7,
            "autonomy_mode": AutonomyMode.SHADOW,
            "shadow_target_mode": AutonomyMode.ASSISTED,
            "read_only": True,
            "kill_switch": True,
            "allowed_commands": ("evaluate_opportunity",),
            "currency": "CHF",
            "daily_cost_cap": "1",
            "daily_volume_cap": 0,
            "effective_at": NOW - dt.timedelta(minutes=1),
            "snapshot_fingerprint": "a" * 64,
            "created_at": NOW - dt.timedelta(minutes=1),
            "created_by_actor_type": "HUMAN",
            "created_by_actor_ref": "operator",
        }
    )


def _plan(
    *,
    actions: int = 0,
    estimated_cost: Decimal = Decimal("0"),
) -> SupervisorPlan:
    proposed = tuple(
        ProposedAction(
            command="evaluate_opportunity",
            target_ref=f"shadow-target-{index}",
            arguments={},
            reason_codes=("SHADOW_ONLY",),
            estimated_cost=estimated_cost / actions if actions else Decimal("0"),
        )
        for index in range(actions)
    )
    return SupervisorPlan(
        plan_id="shadow-plan",
        created_at=NOW,
        objective="Validate one bounded advisory cycle",
        priority=3,
        proposed_actions=proposed,
        reason_codes=("SHADOW_CONNECTIVITY",),
        confidence=Decimal("0.8"),
        estimated_cost=estimated_cost,
        next_review_at=NOW + dt.timedelta(hours=1),
        supervisor_version="hermes-agent-0.20.4",
        skill_version=PROFILE_VERSION,
    )


class FakeAdapter:
    def __init__(
        self,
        settings: SupervisorSettings,
        *,
        health: SupervisorHealth | None = None,
        plan: SupervisorPlan | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.settings = settings
        self._health = health or SupervisorHealth(
            state=HealthState.AVAILABLE,
            hermes_version=PIN.version,
            source_commit=PIN.commit,
            executable_tools=(),
        )
        self._plan = plan or _plan()
        self.failure = failure
        self.contexts = []

    def health(self) -> SupervisorHealth:
        return self._health

    def plan(self, context):
        self.contexts.append(context)
        if self.failure:
            raise self.failure
        return self._plan


class RecordingTransport:
    def __init__(self, response: str) -> None:
        self._response = response
        self.requests: list[dict[str, object]] = []

    def invoke(self, request):
        self.requests.append(request)
        value = {
            "ok": True,
            "protocol_version": 1,
            "hermes_version": PIN.version,
            "source_commit": PIN.commit,
            "executable_tools": [],
        }
        if request["operation"] == "plan":
            value.update(
                {
                    "response": self._response,
                    "provider": "openrouter",
                    "model": MODEL,
                    "automatic_retries": 0,
                    "fallbacks": False,
                }
            )
        return value


def _settings(config: AcquisitionConnectivityConfig, **limits: object) -> SupervisorSettings:
    return SupervisorSettings(
        config.hermes_python,
        config.hermes_home,
        config.hermes_cwd,
        SupervisorLimits(**limits),
    )


def test_immutable_existing_hermes_pin_is_reused_exactly() -> None:
    assert PIN.repository == "https://github.com/NousResearch/hermes-agent.git"
    assert PIN.tag == "v2026.8.18"
    assert PIN.commit == "e624e9fde561e1add9388384012b295fde669ade"
    assert PIN.version == "0.20.4"
    assert PIN.python == ">=3.11,<3.14"


def test_exact_json_compatible_yaml_model_configuration_is_required(tmp_path: Path) -> None:
    config = _config(tmp_path, _model_config())

    validate_hermes_shadow_config(config)


@pytest.mark.parametrize(
    "document",
    [
        None,
        {},
        {**_model_config(), "fallback_model": "other/model"},
        _model_config(model={"provider": "openrouter", "default": "other/model"}),
        _model_config(model={"provider": "other", "default": MODEL}),
        _model_config(
            provider_routing={"require_parameters": False, "data_collection": "deny"}
        ),
        _model_config(
            provider_routing={"require_parameters": True, "data_collection": "allow"}
        ),
        {**_model_config(), "tools": ["terminal"]},
    ],
)
def test_missing_fallback_or_extended_hermes_configuration_fails_closed(
    tmp_path: Path, document: object | None
) -> None:
    config = _config(tmp_path, document)

    with pytest.raises(ConnectivityFailure) as caught:
        validate_hermes_shadow_config(config)

    assert caught.value.code is ConnectivityErrorCode.NOT_CONFIGURED


def test_probe_reuses_adapter_with_exact_limits_and_advisory_context(tmp_path: Path) -> None:
    config = _config(tmp_path, _model_config())
    adapter = FakeAdapter(_settings(config))

    hermes, plan = HermesConnectivityProbe(config=config, adapter=adapter).check(
        _control(), observed_at=NOW
    )

    assert hermes.state == "AVAILABLE"
    assert hermes.version == "0.20.4"
    assert hermes.executable_tools == 0
    assert hermes.model == MODEL
    assert hermes.tag == "v2026.8.18"
    assert hermes.commit == "e624e9fde561e1add9388384012b295fde669ade"
    assert plan.status == "advisory"
    assert plan.plan_id == "shadow-plan"
    assert plan.next_review_at == NOW + dt.timedelta(hours=1)
    assert plan.actions == 0
    context = adapter.contexts[0]
    assert context.runtime_mode == "SHADOW"
    assert context.policy_version == "acquisition-policy-v1"
    assert context.budget.currency == "CHF"
    assert context.budget.maximum_cycle_cost == Decimal("1")
    assert len(context.available_commands) > 0
    assert context.opportunities == ()
    assert context.recent_outcomes == ()


def test_probe_passes_exact_plan_schema_through_existing_adapter(tmp_path: Path) -> None:
    config = _config(tmp_path, _model_config())
    transport = RecordingTransport(_plan().model_dump_json())
    adapter = HermesSupervisorAdapter(_settings(config), transport=transport)

    hermes, plan = HermesConnectivityProbe(config=config, adapter=adapter).check(
        _control(), observed_at=NOW
    )

    request = transport.requests[1]
    assert request["operation"] == "plan"
    assert request["response_schema"] == SupervisorPlan.model_json_schema()
    assert "tools" not in request
    assert hermes.executable_tools == 0
    assert plan.status == "advisory"


@pytest.mark.parametrize(
    "limits",
    [
        {"invocation_timeout_seconds": 31},
        {"max_output_tokens": 2049},
        {"max_planned_actions": 11},
    ],
)
def test_limits_cannot_exceed_kivou_shadow_envelope(
    tmp_path: Path, limits: dict[str, object]
) -> None:
    config = _config(tmp_path, _model_config())
    adapter = FakeAdapter(_settings(config, **limits))

    with pytest.raises(ConnectivityFailure) as caught:
        HermesConnectivityProbe(config=config, adapter=adapter).check(
            _control(), observed_at=NOW
        )

    assert caught.value.code is ConnectivityErrorCode.HERMES_PLAN_INVALID
    assert adapter.contexts == []


@pytest.mark.parametrize(
    ("health", "code"),
    [
        (SupervisorHealth(state=HealthState.NOT_CONFIGURED), ConnectivityErrorCode.NOT_CONFIGURED),
        (
            SupervisorHealth(state=HealthState.VERSION_MISMATCH),
            ConnectivityErrorCode.HERMES_VERSION_MISMATCH,
        ),
        (SupervisorHealth(state=HealthState.UNAVAILABLE), ConnectivityErrorCode.NETWORK),
        (
            SupervisorHealth(
                state=HealthState.AVAILABLE,
                hermes_version=PIN.version,
                source_commit=PIN.commit,
                executable_tools=("terminal",),
            ),
            ConnectivityErrorCode.HERMES_TOOLS_EXPOSED,
        ),
        (
            SupervisorHealth(
                state=HealthState.AVAILABLE,
                hermes_version="0.20.3",
                source_commit=PIN.commit,
            ),
            ConnectivityErrorCode.HERMES_VERSION_MISMATCH,
        ),
    ],
)
def test_health_identity_and_zero_tools_fail_closed(
    tmp_path: Path,
    health: SupervisorHealth,
    code: ConnectivityErrorCode,
) -> None:
    config = _config(tmp_path, _model_config())
    adapter = FakeAdapter(_settings(config), health=health)

    with pytest.raises(ConnectivityFailure) as caught:
        HermesConnectivityProbe(config=config, adapter=adapter).check(
            _control(), observed_at=NOW
        )

    assert caught.value.code is code
    assert adapter.contexts == []


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (SupervisorTimeout("sensitive runtime detail"), ConnectivityErrorCode.TIMEOUT),
        (
            SupervisorValidationError("sensitive raw plan"),
            ConnectivityErrorCode.HERMES_PLAN_INVALID,
        ),
    ],
)
def test_adapter_failures_are_redacted_and_closed(
    tmp_path: Path, failure: Exception, code: ConnectivityErrorCode
) -> None:
    config = _config(tmp_path, _model_config())
    adapter = FakeAdapter(_settings(config), failure=failure)

    with pytest.raises(ConnectivityFailure) as caught:
        HermesConnectivityProbe(config=config, adapter=adapter).check(
            _control(), observed_at=NOW
        )

    assert caught.value.code is code
    assert "sensitive" not in str(caught.value)


@pytest.mark.parametrize(
    "plan",
    [
        _plan(actions=11),
        _plan(actions=1, estimated_cost=Decimal("1.01")),
    ],
)
def test_returned_plan_is_defensively_bounded(
    tmp_path: Path, plan: SupervisorPlan
) -> None:
    config = _config(tmp_path, _model_config())
    adapter = FakeAdapter(_settings(config), plan=plan)

    with pytest.raises(ConnectivityFailure) as caught:
        HermesConnectivityProbe(config=config, adapter=adapter).check(
            _control(), observed_at=NOW
        )

    assert caught.value.code is ConnectivityErrorCode.HERMES_PLAN_INVALID
