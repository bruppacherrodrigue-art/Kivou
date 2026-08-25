from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr
from test_policy_persistence import control

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeConfig,
    AcquisitionRuntimeDeployment,
    AcquisitionRuntimeLimits,
    AcquisitionRuntimeStage,
    RuntimeQaScope,
)
from signals.operations.cli import main
from signals.operations.contracts import HealthStatus
from signals.operations.safety_controller import SafetyController
from signals.operations.service import OperationsReadService
from signals.persistence.database import create_database_engine
from signals.persistence.schema import METADATA
from signals.policy.contracts import AutonomyMode
from signals.policy.store import PolicyStore

NOW = dt.datetime(2026, 8, 25, 16, tzinfo=dt.UTC)
RUNTIME_COMMANDS = tuple(stage.command for stage in AcquisitionRuntimeStage)


@pytest.fixture(autouse=True)
def _staging_environment(monkeypatch) -> None:
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "STAGING")


def _controller(engine):
    from signals.operations.qa_policy_window import RuntimeQaPolicyWindowController

    return RuntimeQaPolicyWindowController(engine)


def _error_type():
    from signals.operations.qa_policy_window import RuntimeQaPolicyWindowError

    return RuntimeQaPolicyWindowError


def _engine(tmp_path, name: str = "qa-policy.db"):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")
    METADATA.create_all(engine)
    PolicyStore(engine).append_control(
        control(
            1,
            autonomy_mode=AutonomyMode.SHADOW,
            shadow_target_mode=AutonomyMode.ASSISTED,
            read_only=True,
            kill_switch=True,
            allowed_commands=(),
            allowed_countries=(),
            allowed_languages=(),
            allowed_wedges=(),
            currency="CHF",
            daily_cost_cap=Decimal("0"),
            daily_volume_cap=0,
            effective_at=NOW - dt.timedelta(hours=1),
        )
    )
    return engine


def _runtime_config(
    *,
    opportunity_keys: tuple[str, ...] = ("opportunity-qa-001",),
    scope: RuntimeQaScope | None = None,
    maximum_cycle_cost: Decimal = Decimal("5"),
) -> AcquisitionRuntimeConfig:
    return AcquisitionRuntimeConfig(
        environment="STAGING",
        deployment_path=Path("/etc/kivou/acquisition-runtime.json"),
        deployment=AcquisitionRuntimeDeployment(
            mode="SHADOW",
            qa_only=True,
            allowed_opportunity_keys=opportunity_keys,
            qa_scope=scope
            or RuntimeQaScope(
                country="CH",
                language="fr",
                wedge="construction",
            ),
            qa_recipient_identity_hmac="0" * 64,
            qa_recipient_key_version="qa-recipient-key-v1",
            qa_provider_mutations_capable=True,
            limits=AcquisitionRuntimeLimits(
                maximum_cycle_cost=maximum_cycle_cost,
                maximum_suppliers=1,
                maximum_contacts=1,
                maximum_provider_operations=3,
                maximum_wall_seconds=900,
                lease_seconds=1200,
            ),
        ),
        qa_recipient=SecretStr("qa-controlled@example.test"),
        qa_recipient_hmac_key=SecretStr("private-qa-hmac-marker"),
    )


def _open(
    controller,
    *,
    expires_at: dt.datetime | None = None,
    runtime_config: AcquisitionRuntimeConfig | None = None,
):
    return controller.open(
        at=NOW,
        expires_at=expires_at or NOW + dt.timedelta(minutes=30),
        actor_ref="operator-qa-001",
        reason_code="AUDIT_80_QA_CYCLE",
        runtime_config=runtime_config or _runtime_config(),
    )


def _configure_cli(
    monkeypatch,
    runtime_config: AcquisitionRuntimeConfig | None = None,
) -> AcquisitionRuntimeConfig:
    configured = runtime_config or _runtime_config()
    monkeypatch.setattr(
        "signals.operations.cli.load_runtime_config",
        lambda: configured,
    )
    return configured


def test_open_window_is_staging_only_and_never_changes_policy_elsewhere(
    tmp_path, monkeypatch
) -> None:
    for environment in ("UNCONFIGURED", "PRODUCTION"):
        engine = _engine(tmp_path, f"qa-policy-{environment}.db")
        monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", environment)

        with pytest.raises(_error_type()):
            _open(_controller(engine))

        assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1


def test_controller_cannot_forge_staging_identity_over_the_process_environment(
    tmp_path, monkeypatch
) -> None:
    engine = _engine(tmp_path)
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "PRODUCTION")

    with pytest.raises(_error_type()):
        _open(_controller(engine))

    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1


@pytest.mark.parametrize(
    "expires_at",
    (
        NOW,
        NOW - dt.timedelta(seconds=1),
        NOW + dt.timedelta(minutes=30, seconds=1),
    ),
)
def test_open_window_requires_a_positive_expiry_of_at_most_thirty_minutes(
    tmp_path, expires_at
) -> None:
    engine = _engine(tmp_path)

    with pytest.raises(_error_type()):
        _open(_controller(engine), expires_at=expires_at)

    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1


def test_open_window_installs_exact_qa_scope_fixed_caps_and_runtime_commands(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    before = PolicyStore(engine).get_effective_control(NOW)

    opened = _open(_controller(engine))

    assert opened.control_revision == 2
    assert opened.autonomy_mode is AutonomyMode.ASSISTED
    assert opened.shadow_target_mode is None
    assert opened.read_only is False
    assert opened.kill_switch is False
    assert opened.allowed_commands == RUNTIME_COMMANDS
    assert before.allowed_countries == before.allowed_languages == before.allowed_wedges == ()
    assert opened.allowed_countries == ("CH",)
    assert opened.allowed_languages == ("fr",)
    assert opened.allowed_wedges == ("construction",)
    assert opened.currency == before.currency == "CHF"
    assert opened.daily_cost_cap == Decimal("5")
    assert opened.daily_volume_cap == 1
    assert opened.effective_at == NOW
    assert opened.expires_at == NOW + dt.timedelta(minutes=30)
    assert opened.created_by_actor_type == "HUMAN"
    assert opened.created_by_actor_ref == "operator-qa-001"
    assert "AUDIT_80_QA_CYCLE" in opened.reason_codes


def test_open_window_uses_the_lower_configured_cycle_cost_but_never_zero_base_caps(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)

    opened = _open(
        _controller(engine),
        runtime_config=_runtime_config(maximum_cycle_cost=Decimal("2.5")),
    )

    assert opened.daily_cost_cap == Decimal("2.5")
    assert opened.daily_volume_cap == 1


def test_open_window_rejects_more_than_one_allowed_opportunity(tmp_path) -> None:
    engine = _engine(tmp_path)

    with pytest.raises(_error_type()):
        _open(
            _controller(engine),
            runtime_config=_runtime_config(
                opportunity_keys=("opportunity-qa-001", "opportunity-qa-002")
            ),
        )

    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1


def test_open_is_idempotent_for_the_same_active_window(tmp_path) -> None:
    engine = _engine(tmp_path)
    controller = _controller(engine)
    runtime_config = _runtime_config()

    first = _open(controller, runtime_config=runtime_config)
    replay = controller.open(
        at=NOW + dt.timedelta(minutes=1),
        expires_at=NOW + dt.timedelta(minutes=30),
        actor_ref="operator-qa-001",
        reason_code="AUDIT_80_QA_CYCLE",
        runtime_config=runtime_config,
    )

    assert replay == first
    assert replay.control_revision == 2


def test_open_rejects_a_different_scope_while_a_window_is_already_active(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    controller = _controller(engine)
    _open(controller)

    with pytest.raises(_error_type()):
        _open(
            controller,
            runtime_config=_runtime_config(
                scope=RuntimeQaScope(
                    country="FR",
                    language="en",
                    wedge="it-services",
                )
            ),
        )

    current = PolicyStore(engine).get_effective_control(NOW)
    assert current.control_revision == 2
    assert current.allowed_countries == ("CH",)


def test_open_is_the_only_bounded_assisted_step_that_temporarily_clears_hard_stop(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)

    opened = _open(_controller(engine))

    assert opened.autonomy_mode is AutonomyMode.ASSISTED
    assert opened.read_only is False
    assert opened.kill_switch is False
    assert opened.expires_at == NOW + dt.timedelta(minutes=30)


def test_unclosed_window_expires_back_to_the_previous_hard_stop(tmp_path) -> None:
    engine = _engine(tmp_path)
    _open(_controller(engine))

    restored = PolicyStore(engine).get_effective_control(NOW + dt.timedelta(minutes=31))

    assert restored.control_revision == 1
    assert restored.autonomy_mode is AutonomyMode.SHADOW
    assert restored.read_only is True
    assert restored.kill_switch is True


def test_close_appends_safe_shadow_authority_and_is_idempotent(tmp_path) -> None:
    engine = _engine(tmp_path)
    controller = _controller(engine)
    runtime_config = _runtime_config()
    opened = _open(controller, runtime_config=runtime_config)

    closed = controller.close(
        at=NOW + dt.timedelta(minutes=1),
        actor_ref="operator-qa-001",
        reason_code="AUDIT_80_QA_CYCLE_COMPLETE",
        runtime_config=runtime_config,
    )
    replay = controller.close(
        at=NOW + dt.timedelta(minutes=1),
        actor_ref="operator-qa-001",
        reason_code="AUDIT_80_QA_CYCLE_COMPLETE",
        runtime_config=runtime_config,
    )

    assert closed.control_revision == opened.control_revision + 1
    assert closed.autonomy_mode is AutonomyMode.SHADOW
    assert closed.shadow_target_mode is AutonomyMode.ASSISTED
    assert closed.read_only is True
    assert closed.kill_switch is False
    assert closed.allowed_commands == RUNTIME_COMMANDS
    assert closed.allowed_countries == ("CH",)
    assert closed.allowed_languages == ("fr",)
    assert closed.allowed_wedges == ("construction",)
    assert closed.currency == "CHF"
    assert closed.daily_cost_cap == Decimal("5")
    assert closed.daily_volume_cap == 1
    assert closed.expires_at is None
    assert closed.created_by_actor_type == "HUMAN"
    assert closed.created_by_actor_ref == "operator-qa-001"
    assert "AUDIT_80_QA_CYCLE_COMPLETE" in closed.reason_codes
    assert replay == closed


def test_kill_switch_can_be_tested_then_explicitly_recovered_to_ready_shadow(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    controller = _controller(engine)
    runtime_config = _runtime_config()
    _open(controller, runtime_config=runtime_config)
    first_close = controller.close(
        at=NOW + dt.timedelta(minutes=1),
        actor_ref="operator-qa-001",
        reason_code="AUDIT_80_QA_CYCLE_COMPLETE",
        runtime_config=runtime_config,
    )
    assert (
        OperationsReadService(engine)
        .health(observed_at=NOW + dt.timedelta(minutes=1))
        .policy_control
        is HealthStatus.READY
    )

    stopped = SafetyController(engine).critical_stop(
        at=NOW + dt.timedelta(minutes=2),
        reason_codes=("OPERATOR_QA_STOP",),
    )
    assert stopped.control_revision == first_close.control_revision + 1
    assert stopped.kill_switch is True
    assert (
        OperationsReadService(engine)
        .health(observed_at=NOW + dt.timedelta(minutes=2))
        .policy_control
        is HealthStatus.NOT_READY
    )

    recovered = controller.close(
        at=NOW + dt.timedelta(minutes=3),
        actor_ref="operator-qa-001",
        reason_code="AUDIT_80_QA_RECOVER_SAFE_SHADOW",
        runtime_config=runtime_config,
    )

    assert recovered.control_revision == stopped.control_revision + 1
    assert recovered.autonomy_mode is AutonomyMode.SHADOW
    assert recovered.read_only is True
    assert recovered.kill_switch is False
    assert (
        OperationsReadService(engine)
        .health(observed_at=NOW + dt.timedelta(minutes=3))
        .policy_control
        is HealthStatus.READY
    )


def test_cli_opens_and_closes_without_printing_actor_or_reason(
    tmp_path, monkeypatch, capsys
) -> None:
    engine = _engine(tmp_path)
    url = str(engine.url)
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "STAGING")
    runtime_config = _configure_cli(monkeypatch)

    opened = main(
        [
            "--database-url",
            url,
            "--now",
            NOW.isoformat(),
            "open-runtime-qa-policy-window",
            "--expires-at",
            (NOW + dt.timedelta(minutes=30)).isoformat(),
            "--actor-ref",
            "operator-qa-001",
            "--reason-code",
            "AUDIT_80_QA_CYCLE",
        ]
    )
    open_output = capsys.readouterr()
    closed = main(
        [
            "--database-url",
            url,
            "--now",
            (NOW + dt.timedelta(minutes=1)).isoformat(),
            "close-runtime-qa-policy-window",
            "--actor-ref",
            "operator-qa-001",
            "--reason-code",
            "AUDIT_80_QA_CYCLE_COMPLETE",
        ]
    )
    close_output = capsys.readouterr()

    assert opened == closed == 0
    assert open_output.err == close_output.err == ""
    assert open_output.out == (
        "runtime_qa_policy_window status=OPEN control_revision=2 "
        "expires_at=2026-08-25T16:30:00+00:00\n"
    )
    assert close_output.out == (
        "runtime_qa_policy_window status=CLOSED control_revision=3 "
        "autonomy=SHADOW read_only=true kill_switch=false\n"
    )
    combined = open_output.out + close_output.out
    assert "operator-qa-001" not in combined
    assert "AUDIT_80" not in combined
    assert runtime_config.qa_recipient.get_secret_value() not in combined
    assert runtime_config.qa_recipient_hmac_key.get_secret_value() not in combined


@pytest.mark.parametrize(
    ("actor_ref", "reason_code", "private_marker"),
    (
        ("private@example.test", "AUDIT_80_QA_CYCLE", "private@example.test"),
        ("operator-qa-001", "private reason marker", "private reason marker"),
    ),
)
def test_cli_rejects_non_opaque_actor_or_non_machine_reason_without_reflection(
    tmp_path,
    monkeypatch,
    capsys,
    actor_ref,
    reason_code,
    private_marker,
) -> None:
    engine = _engine(tmp_path, "qa-policy-cli-invalid-input.db")
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "STAGING")
    _configure_cli(monkeypatch)

    result = main(
        [
            "--database-url",
            str(engine.url),
            "--now",
            NOW.isoformat(),
            "open-runtime-qa-policy-window",
            "--expires-at",
            (NOW + dt.timedelta(minutes=30)).isoformat(),
            "--actor-ref",
            actor_ref,
            "--reason-code",
            reason_code,
        ]
    )

    assert result == 2
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "runtime_qa_policy_window_invalid\n"
    assert private_marker not in streams.err
    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1


@pytest.mark.parametrize(
    "environment",
    ("UNCONFIGURED", "PRODUCTION", "private-invalid-environment-marker"),
)
def test_cli_rejects_non_staging_without_reflecting_private_inputs(
    tmp_path, monkeypatch, capsys, environment
) -> None:
    engine = _engine(tmp_path, f"qa-policy-cli-{environment}.db")
    marker = "private@example.test"
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", environment)
    _configure_cli(monkeypatch)

    result = main(
        [
            "--database-url",
            str(engine.url),
            "--now",
            NOW.isoformat(),
            "open-runtime-qa-policy-window",
            "--expires-at",
            (NOW + dt.timedelta(minutes=30)).isoformat(),
            "--actor-ref",
            marker,
            "--reason-code",
            "AUDIT_80_QA_CYCLE",
        ]
    )

    assert result == 2
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "runtime_qa_policy_window_invalid\n"
    assert marker not in streams.err
    assert environment not in streams.err
    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1
