from __future__ import annotations

import datetime as dt
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
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
from signals.operations.safety_controller import (
    MAX_CONTROL_APPEND_ATTEMPTS,
    SAFETY_CONTROLLER_REF,
    SafetyControlConflict,
    SafetyController,
)
from signals.operations.service import OperationsReadService
from signals.persistence.database import create_database_engine
from signals.persistence.schema import (
    METADATA,
    contract_award,
    opportunity_representation,
    source_event,
)
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
    _seed_public_opportunity(engine)
    return engine


def _seed_public_opportunity(
    engine,
    *,
    opportunity_key: str = "opportunity-qa-001",
    country: str = "CH",
) -> None:
    event_key = f"simap:{opportunity_key}:1"
    award_key = f"award-{opportunity_key}"
    with engine.begin() as connection:
        connection.execute(
            sa.insert(source_event).values(
                event_key=event_key,
                source_system="simap",
                source_notice_id=opportunity_key,
                notice_version="1",
                source_country=country,
                event_type="AWARD",
                procedure_buyers=[],
                created_at=NOW - dt.timedelta(days=1),
            )
        )
        connection.execute(
            sa.insert(contract_award).values(
                award_key=award_key,
                event_key=event_key,
                cpv_additional=[],
                winner_status="NAMED",
                awardee_parties=[],
                contract_signatories=[],
                created_at=NOW - dt.timedelta(days=1),
            )
        )
        connection.execute(
            sa.insert(opportunity_representation).values(
                award_key=award_key,
                opportunity_key=opportunity_key,
                created_at=NOW - dt.timedelta(days=1),
            )
        )


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


def _inject_critical_stop_after_stale_effective_read(
    monkeypatch,
    engine,
) -> None:
    original = PolicyStore.get_effective_control
    injected = False

    def interleaved(store, at):
        nonlocal injected
        stale = original(store, at)
        if not injected:
            injected = True
            SafetyController(engine).critical_stop(
                at=at,
                reason_codes=("OPERATOR_QA_STOP",),
            )
        return stale

    monkeypatch.setattr(PolicyStore, "get_effective_control", interleaved)


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


def test_policy_control_cas_requires_the_exact_durable_head_and_next_revision(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    store = PolicyStore(engine)

    assert not store.append_control_if_latest(
        control(2, effective_at=NOW),
        expected_latest_revision=0,
    )
    assert not store.append_control_if_latest(
        control(3, effective_at=NOW),
        expected_latest_revision=1,
    )
    assert store.get_latest_control().control_revision == 1


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
    assert opened.qa_signal_ref == "procurement-opportunity:opportunity-qa-001"
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


def test_open_window_requires_the_one_allowlisted_public_opportunity_to_exist(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)

    with pytest.raises(_error_type()):
        _open(
            _controller(engine),
            runtime_config=_runtime_config(opportunity_keys=("missing-opportunity",)),
        )

    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1


def test_open_window_requires_the_public_country_to_match_the_exact_qa_scope(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)

    with pytest.raises(_error_type()):
        _open(
            _controller(engine),
            runtime_config=_runtime_config(
                scope=RuntimeQaScope(
                    country="FR",
                    language="fr",
                    wedge="construction",
                )
            ),
        )

    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1


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


def test_expired_window_can_be_reopened_with_the_next_persisted_revision(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    controller = _controller(engine)
    runtime_config = _runtime_config()
    first = controller.open(
        at=NOW,
        expires_at=NOW + dt.timedelta(minutes=1),
        actor_ref="operator-qa-001",
        reason_code="AUDIT_80_QA_CYCLE",
        runtime_config=runtime_config,
    )

    reopened = controller.open(
        at=NOW + dt.timedelta(minutes=2),
        expires_at=NOW + dt.timedelta(minutes=12),
        actor_ref="operator-qa-001",
        reason_code="AUDIT_80_QA_CYCLE_REOPEN",
        runtime_config=runtime_config,
    )

    assert first.control_revision == 2
    assert reopened.control_revision == 3
    assert reopened.qa_signal_ref == "procurement-opportunity:opportunity-qa-001"


def test_reopen_refuses_an_unrelated_expired_durable_head(tmp_path) -> None:
    engine = _engine(tmp_path)
    PolicyStore(engine).append_control(
        control(
            2,
            autonomy_mode=AutonomyMode.ASSISTED,
            read_only=False,
            kill_switch=False,
            effective_at=NOW - dt.timedelta(minutes=2),
            expires_at=NOW - dt.timedelta(minutes=1),
        )
    )

    with pytest.raises(_error_type()):
        _open(_controller(engine))

    assert PolicyStore(engine).get_latest_control().control_revision == 2


def test_open_cannot_clear_a_critical_stop_inserted_after_its_head_read(
    tmp_path,
    monkeypatch,
) -> None:
    engine = _engine(tmp_path)
    controller = _controller(engine)
    runtime_config = _runtime_config()
    _open(controller, runtime_config=runtime_config)
    controller.close(
        at=NOW + dt.timedelta(minutes=1),
        actor_ref="operator-qa-001",
        reason_code="AUDIT_80_QA_CYCLE_COMPLETE",
        runtime_config=runtime_config,
    )
    _inject_critical_stop_after_stale_effective_read(monkeypatch, engine)

    with pytest.raises(_error_type()):
        controller.open(
            at=NOW + dt.timedelta(minutes=2),
            expires_at=NOW + dt.timedelta(minutes=12),
            actor_ref="operator-qa-001",
            reason_code="AUDIT_80_QA_CYCLE_REOPEN",
            runtime_config=runtime_config,
        )

    winner = PolicyStore(engine).get_effective_control(NOW + dt.timedelta(minutes=2))
    assert winner.autonomy_mode is AutonomyMode.SHADOW
    assert winner.read_only is True
    assert winner.kill_switch is True
    assert winner.created_by_actor_ref == SAFETY_CONTROLLER_REF


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
    assert closed.qa_signal_ref == "procurement-opportunity:opportunity-qa-001"
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


def test_close_remains_available_if_public_seed_data_disappears_after_open(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    controller = _controller(engine)
    runtime_config = _runtime_config()
    _open(controller, runtime_config=runtime_config)
    with engine.begin() as connection:
        connection.execute(sa.delete(opportunity_representation))

    closed = controller.close(
        at=NOW + dt.timedelta(minutes=1),
        actor_ref="operator-qa-001",
        reason_code="AUDIT_80_QA_CYCLE_COMPLETE",
        runtime_config=runtime_config,
    )

    assert closed.autonomy_mode is AutonomyMode.SHADOW
    assert closed.read_only is True
    assert closed.kill_switch is False


def test_close_refuses_the_audited_baseline_hard_stop_without_an_open_window(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)

    with pytest.raises(_error_type()):
        _controller(engine).close(
            at=NOW,
            actor_ref="operator-qa-001",
            reason_code="AUDIT_80_QA_RECOVER_SAFE_SHADOW",
            runtime_config=_runtime_config(),
        )

    current = PolicyStore(engine).get_effective_control(NOW)
    assert current.control_revision == 1
    assert current.kill_switch is True


def test_close_refuses_to_clear_a_kill_switch_raised_before_the_window_was_closed(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    controller = _controller(engine)
    runtime_config = _runtime_config()
    _open(controller, runtime_config=runtime_config)
    stopped = SafetyController(engine).critical_stop(
        at=NOW + dt.timedelta(minutes=1),
        reason_codes=("OPERATOR_QA_STOP",),
    )

    with pytest.raises(_error_type()):
        controller.close(
            at=NOW + dt.timedelta(minutes=2),
            actor_ref="operator-qa-001",
            reason_code="AUDIT_80_QA_RECOVER_SAFE_SHADOW",
            runtime_config=runtime_config,
        )

    current = PolicyStore(engine).get_effective_control(NOW + dt.timedelta(minutes=2))
    assert current == stopped
    assert current.kill_switch is True


def test_close_cannot_clear_a_critical_stop_inserted_after_its_head_read(
    tmp_path,
    monkeypatch,
) -> None:
    engine = _engine(tmp_path)
    controller = _controller(engine)
    runtime_config = _runtime_config()
    _open(controller, runtime_config=runtime_config)
    _inject_critical_stop_after_stale_effective_read(monkeypatch, engine)

    with pytest.raises(_error_type()):
        controller.close(
            at=NOW + dt.timedelta(minutes=1),
            actor_ref="operator-qa-001",
            reason_code="AUDIT_80_QA_CYCLE_COMPLETE",
            runtime_config=runtime_config,
        )

    winner = PolicyStore(engine).get_effective_control(NOW + dt.timedelta(minutes=1))
    assert winner.autonomy_mode is AutonomyMode.SHADOW
    assert winner.read_only is True
    assert winner.kill_switch is True
    assert winner.created_by_actor_ref == SAFETY_CONTROLLER_REF


def test_downgrade_cannot_clear_a_critical_stop_inserted_after_its_head_read(
    tmp_path,
    monkeypatch,
) -> None:
    engine = _engine(tmp_path)
    _open(_controller(engine))
    _inject_critical_stop_after_stale_effective_read(monkeypatch, engine)

    result = SafetyController(engine).downgrade(
        at=NOW + dt.timedelta(minutes=1),
        reason_codes=("OPERATIONS_INCIDENT",),
    )

    winner = PolicyStore(engine).get_effective_control(NOW + dt.timedelta(minutes=1))
    assert result == winner
    assert winner.autonomy_mode is AutonomyMode.SHADOW
    assert winner.read_only is True
    assert winner.kill_switch is True
    assert winner.created_by_actor_ref == SAFETY_CONTROLLER_REF


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
    assert stopped.created_by_actor_ref == SAFETY_CONTROLLER_REF
    assert stopped.reason_codes == ("OPERATOR_QA_STOP",)
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


def test_critical_stop_wins_a_concurrent_close_with_exact_hard_stop_authority(
    tmp_path,
    monkeypatch,
) -> None:
    engine = _engine(tmp_path)
    controller = _controller(engine)
    runtime_config = _runtime_config()
    _open(controller, runtime_config=runtime_config)
    original = PolicyStore.append_control_if_latest
    barrier = threading.Barrier(2)
    calls: dict[int, int] = {}
    lock = threading.Lock()

    def synchronized_append(store, snapshot, *, expected_latest_revision):
        thread_id = threading.get_ident()
        with lock:
            calls[thread_id] = calls.get(thread_id, 0) + 1
            first_attempt = calls[thread_id] == 1
        if first_attempt:
            barrier.wait(timeout=5)
        return original(
            store,
            snapshot,
            expected_latest_revision=expected_latest_revision,
        )

    monkeypatch.setattr(
        PolicyStore,
        "append_control_if_latest",
        synchronized_append,
    )
    at = NOW + dt.timedelta(minutes=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        close_future = pool.submit(
            controller.close,
            at=at,
            actor_ref="operator-qa-001",
            reason_code="AUDIT_80_QA_CYCLE_COMPLETE",
            runtime_config=runtime_config,
        )
        stop_future = pool.submit(
            SafetyController(engine).critical_stop,
            at=at,
            reason_codes=("OPERATOR_QA_STOP",),
        )
        stopped = stop_future.result(timeout=10)
        try:
            close_future.result(timeout=10)
        except _error_type():
            pass

    winner = PolicyStore(engine).get_effective_control(at)
    assert winner == stopped
    assert winner.autonomy_mode is AutonomyMode.SHADOW
    assert winner.read_only is True
    assert winner.kill_switch is True
    assert winner.created_by_actor_ref == SAFETY_CONTROLLER_REF
    assert winner.reason_codes == ("OPERATOR_QA_STOP",)


def test_critical_stop_fails_closed_after_a_bounded_number_of_cas_losses(
    tmp_path,
    monkeypatch,
) -> None:
    engine = _engine(tmp_path)
    controller = _controller(engine)
    runtime_config = _runtime_config()
    _open(controller, runtime_config=runtime_config)
    controller.close(
        at=NOW + dt.timedelta(minutes=1),
        actor_ref="operator-qa-001",
        reason_code="AUDIT_80_QA_CYCLE_COMPLETE",
        runtime_config=runtime_config,
    )
    attempts = 0

    def lose_every_cas(_store, _snapshot, *, expected_latest_revision):
        nonlocal attempts
        del expected_latest_revision
        attempts += 1
        return False

    monkeypatch.setattr(
        PolicyStore,
        "append_control_if_latest",
        lose_every_cas,
    )

    with pytest.raises(SafetyControlConflict):
        SafetyController(engine).critical_stop(
            at=NOW + dt.timedelta(minutes=2),
            reason_codes=("OPERATOR_QA_STOP",),
        )

    assert attempts == MAX_CONTROL_APPEND_ATTEMPTS
    current = PolicyStore(engine).get_effective_control(NOW + dt.timedelta(minutes=2))
    assert current.kill_switch is False


def test_cli_opens_and_closes_without_printing_actor_or_reason(
    tmp_path, monkeypatch, capsys
) -> None:
    engine = _engine(tmp_path)
    url = str(engine.url)
    monkeypatch.setenv("KIVOU_DATABASE_URL", url)
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "STAGING")
    runtime_config = _configure_cli(monkeypatch)

    opened = main(
        [
            "open-runtime-qa-policy-window",
            "--duration-seconds",
            "1800",
            "--actor-ref",
            "operator-qa-001",
            "--reason-code",
            "AUDIT_80_QA_CYCLE",
        ],
        clock=lambda: NOW,
    )
    open_output = capsys.readouterr()
    closed = main(
        [
            "close-runtime-qa-policy-window",
            "--actor-ref",
            "operator-qa-001",
            "--reason-code",
            "AUDIT_80_QA_CYCLE_COMPLETE",
        ],
        clock=lambda: NOW + dt.timedelta(minutes=1),
    )
    close_output = capsys.readouterr()

    assert opened == closed == 0
    assert open_output.err == close_output.err == ""
    assert open_output.out == (
        "runtime_qa_policy_window status=OPEN control_revision=2 "
        "autonomy=ASSISTED read_only=false kill_switch=false\n"
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
    monkeypatch.setenv("KIVOU_DATABASE_URL", str(engine.url))
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "STAGING")
    _configure_cli(monkeypatch)

    result = main(
        [
            "open-runtime-qa-policy-window",
            "--duration-seconds",
            "1800",
            "--actor-ref",
            actor_ref,
            "--reason-code",
            reason_code,
        ],
        clock=lambda: NOW,
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
    monkeypatch.setenv("KIVOU_DATABASE_URL", str(engine.url))
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", environment)
    _configure_cli(monkeypatch)

    result = main(
        [
            "open-runtime-qa-policy-window",
            "--duration-seconds",
            "1800",
            "--actor-ref",
            marker,
            "--reason-code",
            "AUDIT_80_QA_CYCLE",
        ],
        clock=lambda: NOW,
    )

    assert result == 2
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "runtime_qa_policy_window_invalid\n"
    assert marker not in streams.err
    assert environment not in streams.err
    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1


@pytest.mark.parametrize("duration", ("0", "1801", "not-a-duration"))
def test_cli_rejects_an_unbounded_window_duration_without_reflection(
    tmp_path,
    monkeypatch,
    capsys,
    duration,
) -> None:
    engine = _engine(tmp_path, f"qa-policy-cli-duration-{duration}.db")
    monkeypatch.setenv("KIVOU_DATABASE_URL", str(engine.url))
    _configure_cli(monkeypatch)

    result = main(
        [
            "open-runtime-qa-policy-window",
            "--duration-seconds",
            duration,
            "--actor-ref",
            "operator-qa-001",
            "--reason-code",
            "AUDIT_80_QA_CYCLE",
        ],
        clock=lambda: NOW,
    )

    assert result == 2
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "runtime_qa_policy_window_invalid\n"
    assert duration not in streams.err
    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1


@pytest.mark.parametrize(
    "forbidden_arguments",
    (
        ("--database-url", "sqlite+pysqlite:///private-marker.db"),
        ("--now", "2026-08-25T16:00:00+00:00"),
    ),
)
def test_mutating_qa_commands_refuse_operator_database_and_clock_authority(
    tmp_path,
    monkeypatch,
    capsys,
    forbidden_arguments,
) -> None:
    engine = _engine(tmp_path, "qa-policy-cli-authority.db")
    monkeypatch.setenv("KIVOU_DATABASE_URL", str(engine.url))
    _configure_cli(monkeypatch)

    result = main(
        [
            *forbidden_arguments,
            "open-runtime-qa-policy-window",
            "--duration-seconds",
            "1800",
            "--actor-ref",
            "operator-qa-001",
            "--reason-code",
            "AUDIT_80_QA_CYCLE",
        ],
        clock=lambda: NOW,
    )

    assert result == 2
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "runtime_qa_policy_window_invalid\n"
    assert "private-marker" not in streams.err
    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1


def test_mutating_qa_command_redacts_forbidden_authority_after_the_subcommand(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    engine = _engine(tmp_path, "qa-policy-cli-authority-order.db")
    marker = "private-database-marker"
    monkeypatch.setenv("KIVOU_DATABASE_URL", str(engine.url))
    _configure_cli(monkeypatch)

    result = main(
        [
            "open-runtime-qa-policy-window",
            "--database-url",
            f"sqlite+pysqlite:///{marker}.db",
            "--duration-seconds",
            "1800",
            "--actor-ref",
            "operator-qa-001",
            "--reason-code",
            "AUDIT_80_QA_CYCLE",
        ],
        clock=lambda: NOW,
    )

    assert result == 2
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "runtime_qa_policy_window_invalid\n"
    assert marker not in streams.err


def test_mutating_qa_parser_never_reflects_an_unknown_private_option(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    engine = _engine(tmp_path, "qa-policy-cli-private-option.db")
    marker = "private-email@example.test"
    monkeypatch.setenv("KIVOU_DATABASE_URL", str(engine.url))
    _configure_cli(monkeypatch)

    result = main(
        [
            "open-runtime-qa-policy-window",
            "--private-note",
            marker,
            "--duration-seconds",
            "1800",
            "--actor-ref",
            "operator-qa-001",
            "--reason-code",
            "AUDIT_80_QA_CYCLE",
        ],
        clock=lambda: NOW,
    )

    assert result == 2
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "runtime_qa_policy_window_invalid\n"
    assert marker not in streams.err


@pytest.mark.parametrize("failure", ("clock", "engine", "config"))
def test_mutating_qa_boundary_redacts_clock_engine_and_config_failures(
    tmp_path,
    monkeypatch,
    capsys,
    failure,
) -> None:
    marker = "private-failure-marker"
    engine = _engine(tmp_path, f"qa-policy-cli-boundary-{failure}.db")
    monkeypatch.setenv("KIVOU_DATABASE_URL", str(engine.url))
    _configure_cli(monkeypatch)
    clock = lambda: NOW
    if failure == "clock":

        def clock():
            raise RuntimeError(marker)

    elif failure == "engine":
        monkeypatch.setenv("KIVOU_DATABASE_URL", f"{marker}://invalid")
    else:
        monkeypatch.setattr(
            "signals.operations.cli.load_runtime_config",
            lambda: (_ for _ in ()).throw(RuntimeError(marker)),
        )

    result = main(
        [
            "open-runtime-qa-policy-window",
            "--duration-seconds",
            "1800",
            "--actor-ref",
            "operator-qa-001",
            "--reason-code",
            "AUDIT_80_QA_CYCLE",
        ],
        clock=clock,
    )

    assert result == 2
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "runtime_qa_policy_window_invalid\n"
    assert marker not in streams.err
