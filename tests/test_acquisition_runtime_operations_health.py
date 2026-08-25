from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from test_acquisition_runtime_health import _dependencies, capability

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeCycleStatus,
    RuntimeStageStatus,
)
from signals.acquisition_runtime.store import AcquisitionRuntimeStore
from signals.operations.contracts import HealthStatus, HermesRuntimeIdentity
from signals.operations.service import OperationsReadService
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.policy.contracts import (
    POLICY_VERSION,
    AutonomyMode,
    PolicyControlSnapshot,
)
from signals.policy.store import PolicyStore
from signals.supervisor.pin import load_hermes_pin

NOW = dt.datetime(2026, 8, 25, 15, tzinfo=dt.UTC)
OWNER = "runtime-health-owner"


def _engine(tmp_path, name: str):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")
    migrate_to_latest(engine)
    return engine


def _control(*, kill_switch: bool = False) -> PolicyControlSnapshot:
    return PolicyControlSnapshot(
        policy_snapshot_id="runtime-health-policy",
        control_revision=1,
        policy_version=POLICY_VERSION,
        autonomy_mode=AutonomyMode.SHADOW,
        shadow_target_mode=AutonomyMode.ASSISTED,
        read_only=True,
        kill_switch=kill_switch,
        allowed_commands=tuple(stage.command for stage in AcquisitionRuntimeStage),
        allowed_countries=("CH", "FR"),
        allowed_languages=("fr", "en"),
        allowed_wedges=("qa",),
        currency="CHF",
        daily_cost_cap=Decimal("1"),
        daily_volume_cap=1,
        effective_at=NOW - dt.timedelta(hours=1),
        expires_at=None,
        snapshot_fingerprint="1" * 64,
        created_at=NOW - dt.timedelta(hours=1),
        created_by_actor_type="HUMAN",
        created_by_actor_ref="operator-opaque-1",
        reason_codes=("QA_SHADOW_RUNTIME",),
    )


def _seed_runtime(
    engine,
    *,
    observed_at: dt.datetime = NOW - dt.timedelta(minutes=1),
    runtime_capability=None,
    cycle_status: RuntimeCycleStatus = RuntimeCycleStatus.SUCCEEDED,
) -> None:
    store = AcquisitionRuntimeStore(engine)
    lease = store.acquire_lease(
        OWNER,
        acquired_at=observed_at,
        lease_seconds=600,
    )
    assert lease.fencing_token is not None
    fence = {"owner_ref": OWNER, "fencing_token": lease.fencing_token}
    store.record_runtime_observation(
        OWNER,
        runtime_capability or capability(),
        fencing_token=lease.fencing_token,
        at=observed_at,
    )
    cycle = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("qa-opportunity-1",),
        config_fingerprint="2" * 64,
        at=observed_at,
    )
    cursor = observed_at
    if cycle_status is RuntimeCycleStatus.SUCCEEDED:
        for stage in AcquisitionRuntimeStage:
            cursor += dt.timedelta(milliseconds=1)
            store.begin_stage(cycle.cycle_ref, stage, **fence, at=cursor)
            cursor += dt.timedelta(milliseconds=1)
            store.finish_stage(
                cycle.cycle_ref,
                stage,
                RuntimeActionResult(status=RuntimeStageStatus.SUCCEEDED),
                **fence,
                at=cursor,
            )
        cursor += dt.timedelta(milliseconds=1)
        store.finish_cycle(
            cycle.cycle_ref,
            RuntimeCycleStatus.SUCCEEDED,
            **fence,
            at=cursor,
        )
    elif cycle_status is RuntimeCycleStatus.FAILED:
        cursor += dt.timedelta(milliseconds=1)
        store.finish_cycle(
            cycle.cycle_ref,
            RuntimeCycleStatus.FAILED,
            **fence,
            at=cursor,
            reason_code="CONTROLLED_FAILURE",
        )
    elif cycle_status is RuntimeCycleStatus.WAITING:
        cursor += dt.timedelta(milliseconds=1)
        store.finish_cycle(
            cycle.cycle_ref,
            RuntimeCycleStatus.WAITING,
            **fence,
            at=cursor,
            reason_code="APOLLO_PROVIDER_OUTCOME_AMBIGUOUS",
        )
    elif cycle_status is RuntimeCycleStatus.RUNNING:
        cursor += dt.timedelta(milliseconds=1)
        store.begin_stage(
            cycle.cycle_ref,
            AcquisitionRuntimeStage.SIGNAL_SEED,
            **fence,
            at=cursor,
        )
    elif cycle_status is RuntimeCycleStatus.WAITING:
        cursor += dt.timedelta(milliseconds=1)
        store.finish_cycle(
            cycle.cycle_ref,
            RuntimeCycleStatus.WAITING,
            **fence,
            at=cursor,
            reason_code="CONTROLLED_WAIT",
        )
    elif cycle_status is RuntimeCycleStatus.SUPPRESSED:
        cursor += dt.timedelta(milliseconds=1)
        store.begin_stage(
            cycle.cycle_ref,
            AcquisitionRuntimeStage.SIGNAL_SEED,
            **fence,
            at=cursor,
        )
        cursor += dt.timedelta(milliseconds=1)
        store.finish_stage(
            cycle.cycle_ref,
            AcquisitionRuntimeStage.SIGNAL_SEED,
            RuntimeActionResult(
                status=RuntimeStageStatus.SUPPRESSED,
                reason_codes=("CONTROLLED_SUPPRESSION",),
            ),
            **fence,
            at=cursor,
        )
    store.record_cycle_observation(
        OWNER,
        cycle.cycle_ref,
        fencing_token=lease.fencing_token,
        at=cursor,
    )
    store.release_lease(
        OWNER,
        fencing_token=lease.fencing_token,
        at=cursor,
    )


def _ready_service(engine) -> OperationsReadService:
    PolicyStore(engine).append_control(_control())
    _seed_runtime(engine)
    return OperationsReadService(engine)


def test_constructor_injections_cannot_forge_runtime_readiness(tmp_path) -> None:
    engine = _engine(tmp_path, "injection.db")
    pin = load_hermes_pin()
    service = OperationsReadService(
        engine,
        observed_runtime=HermesRuntimeIdentity(
            repository=pin.repository,
            tag=pin.tag,
            commit=pin.commit,
            version=pin.version,
            python_contract=pin.python,
        ),
        supervisor_heartbeat_at=NOW - dt.timedelta(seconds=1),
        environment_identity="STAGING",
    )

    health = service.health(observed_at=NOW)
    readiness = service.readiness(evaluated_at=NOW)

    assert health.status is HealthStatus.NOT_READY
    assert health.hermes_runtime is HealthStatus.NOT_READY
    assert health.supervisor_loop is HealthStatus.NOT_READY
    assert "RUNTIME_OBSERVATION_UNAVAILABLE" in health.reason_codes
    assert readiness.h_a_runtime.status == "NOT_READY"
    assert readiness.highest_safe_mode is AutonomyMode.SHADOW


def test_fresh_durable_runtime_and_shadow_policy_are_the_only_runtime_authority(
    tmp_path,
) -> None:
    engine = _engine(tmp_path, "ready.db")
    service = _ready_service(engine)

    health = service.health(observed_at=NOW)
    readiness = service.readiness(evaluated_at=NOW)

    assert health.hermes_runtime is HealthStatus.READY
    assert health.supervisor_loop is HealthStatus.READY
    assert health.policy_control is HealthStatus.READY
    assert health.campaign_execution is HealthStatus.READY
    assert health.status is HealthStatus.READY
    assert readiness.h_a_runtime.status == "READY"
    assert readiness.h_c_policy.status == "READY"
    assert readiness.highest_safe_mode is AutonomyMode.SHADOW
    assert "QA_SHADOW_RUNTIME_ONLY" in readiness.blockers
    assert "acquisition-runtime-observation-v1" in readiness.evidence_refs


def test_timer_revalidates_a_completed_cycle_without_making_health_stale(
    tmp_path,
) -> None:
    engine = _engine(tmp_path, "timer-revalidation.db")
    service = _ready_service(engine)
    replayed_at = NOW + dt.timedelta(hours=2)
    store = AcquisitionRuntimeStore(engine)
    lease = store.acquire_lease(
        OWNER,
        acquired_at=replayed_at,
        lease_seconds=600,
    )
    assert lease.fencing_token is not None
    fence = {
        "owner_ref": OWNER,
        "fencing_token": lease.fencing_token,
    }
    store.record_runtime_observation(
        OWNER,
        capability(),
        fencing_token=lease.fencing_token,
        at=replayed_at,
    )
    cycle = store.resume_or_create_cycle(
        **fence,
        opportunity_keys=("qa-opportunity-1",),
        config_fingerprint="2" * 64,
        at=replayed_at,
    )
    assert cycle.status is RuntimeCycleStatus.SUCCEEDED
    store.record_cycle_observation(
        OWNER,
        cycle.cycle_ref,
        fencing_token=lease.fencing_token,
        at=replayed_at,
    )
    store.release_lease(
        OWNER,
        fencing_token=lease.fencing_token,
        at=replayed_at,
    )

    health = service.health(observed_at=replayed_at)

    assert health.status is HealthStatus.READY
    assert health.campaign_execution is HealthStatus.READY
    assert "RUNTIME_LAST_CYCLE_STALE" not in health.reason_codes


def test_stale_observation_fails_closed_even_when_policy_is_ready(tmp_path) -> None:
    engine = _engine(tmp_path, "stale.db")
    PolicyStore(engine).append_control(_control())
    _seed_runtime(engine, observed_at=NOW - dt.timedelta(hours=2))

    health = OperationsReadService(engine).health(observed_at=NOW)

    assert health.status is HealthStatus.NOT_READY
    assert health.supervisor_loop is HealthStatus.NOT_READY
    assert "RUNTIME_OBSERVATION_STALE" in health.reason_codes


def test_wrong_hermes_pin_and_registry_identity_fail_closed(tmp_path) -> None:
    pin = load_hermes_pin()
    cases = (
        capability(
            hermes={
                "repository": pin.repository,
                "tag": pin.tag,
                "commit": "f" * 40,
                "version": pin.version,
                "python_contract": pin.python,
            }
        ),
        capability(registry_identity="f" * 64),
    )
    for index, runtime_capability in enumerate(cases):
        engine = _engine(tmp_path, f"identity-{index}.db")
        PolicyStore(engine).append_control(_control())
        _seed_runtime(engine, runtime_capability=runtime_capability)

        health = OperationsReadService(engine).health(observed_at=NOW)
        readiness = OperationsReadService(engine).readiness(evaluated_at=NOW)

        assert health.status is HealthStatus.NOT_READY
        assert readiness.h_a_runtime.status == "NOT_READY"
        assert readiness.highest_safe_mode is AutonomyMode.SHADOW


def test_missing_required_dependency_prevents_ready(tmp_path) -> None:
    engine = _engine(tmp_path, "dependency.db")
    PolicyStore(engine).append_control(_control())
    _seed_runtime(
        engine,
        runtime_capability=capability(
            dependencies=_dependencies(missing=AcquisitionRuntimeStage.COMPANY_RESEARCH)
        ),
    )

    health = OperationsReadService(engine).health(observed_at=NOW)
    readiness = OperationsReadService(engine).readiness(evaluated_at=NOW)

    assert health.campaign_execution is HealthStatus.NOT_READY
    assert "RUNTIME_DEPENDENCY_UNAVAILABLE" in health.reason_codes
    assert "DEPENDENCY_UNAVAILABLE" in health.reason_codes
    assert readiness.h_a_runtime.status == "NOT_READY"
    assert readiness.highest_safe_mode is AutonomyMode.SHADOW


def test_missing_policy_and_kill_switch_both_fail_closed(tmp_path) -> None:
    for suffix, control in (("missing", None), ("kill", _control(kill_switch=True))):
        engine = _engine(tmp_path, f"policy-{suffix}.db")
        if control is not None:
            PolicyStore(engine).append_control(control)
        _seed_runtime(engine)

        health = OperationsReadService(engine).health(observed_at=NOW)
        readiness = OperationsReadService(engine).readiness(evaluated_at=NOW)

        assert health.policy_control is HealthStatus.NOT_READY
        assert health.status is HealthStatus.NOT_READY
        assert readiness.h_c_policy.status == "NOT_READY"
        assert readiness.highest_safe_mode is AutonomyMode.SHADOW


def test_failed_last_cycle_prevents_ready_but_remains_bounded(tmp_path) -> None:
    engine = _engine(tmp_path, "failed-cycle.db")
    PolicyStore(engine).append_control(_control())
    _seed_runtime(engine, cycle_status=RuntimeCycleStatus.FAILED)

    health = OperationsReadService(engine).health(observed_at=NOW)

    assert health.campaign_execution is HealthStatus.NOT_READY
    assert "RUNTIME_LAST_CYCLE_FAILED" in health.reason_codes


def test_ambiguous_apollo_wait_is_visible_as_a_machine_reason_in_health(
    tmp_path,
) -> None:
    engine = _engine(tmp_path, "runtime-ambiguous-apollo.sqlite")
    PolicyStore(engine).append_control(_control())
    _seed_runtime(engine, cycle_status=RuntimeCycleStatus.WAITING)

    health = OperationsReadService(engine).health(observed_at=NOW)

    assert health.campaign_execution is HealthStatus.NOT_READY
    assert "RUNTIME_LAST_CYCLE_WAITING" in health.reason_codes
    assert "APOLLO_PROVIDER_OUTCOME_AMBIGUOUS" in health.reason_codes
    assert "CONTROLLED_FAILURE" not in health.model_dump_json()


@pytest.mark.parametrize(
    "cycle_status",
    (
        RuntimeCycleStatus.PENDING,
        RuntimeCycleStatus.RUNNING,
        RuntimeCycleStatus.WAITING,
        RuntimeCycleStatus.SUPPRESSED,
    ),
)
def test_only_a_successful_last_cycle_can_make_the_runtime_ready(
    tmp_path,
    cycle_status: RuntimeCycleStatus,
) -> None:
    engine = _engine(tmp_path, f"unfinished-{cycle_status.value.lower()}.db")
    PolicyStore(engine).append_control(_control())
    _seed_runtime(engine, cycle_status=cycle_status)

    health = OperationsReadService(engine).health(observed_at=NOW)

    assert health.status is HealthStatus.NOT_READY
    assert health.campaign_execution is HealthStatus.NOT_READY
    assert f"RUNTIME_LAST_CYCLE_{cycle_status.value}" in health.reason_codes


def test_runtime_health_outputs_contain_no_payload_recipient_or_secret(tmp_path) -> None:
    engine = _engine(tmp_path, "redaction.db")
    service = _ready_service(engine)

    serialized = (
        service.health(observed_at=NOW).model_dump_json()
        + service.readiness(evaluated_at=NOW).model_dump_json()
    )

    for marker in ("recipient", "email", "payload", "content", "secret", "token"):
        assert marker not in serialized.casefold()
