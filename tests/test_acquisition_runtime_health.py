from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from signals.acquisition_runtime import contracts
from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeCapabilityEvidence,
    RuntimeCycleStatus,
    RuntimeDependencyState,
    RuntimeHealthObservation,
    RuntimeHermesIdentityEvidence,
    RuntimeStageDependency,
    expected_runtime_registry_identity,
)
from signals.acquisition_runtime.registry import AcquisitionActionRegistry
from signals.acquisition_runtime.store import (
    AcquisitionRuntimeConflict,
    AcquisitionRuntimeStore,
)
from signals.persistence.schema import (
    METADATA,
    acquisition_runtime_cycle,
    acquisition_runtime_lease,
    acquisition_runtime_stage,
)
from signals.supervisor.pin import load_hermes_pin

NOW = dt.datetime(2026, 8, 25, 13, tzinfo=dt.UTC)


def test_runtime_health_contract_boundary_exists() -> None:
    assert {
        "RuntimeCapabilityEvidence",
        "RuntimeDependencyState",
        "RuntimeHealthObservation",
        "RuntimeHermesIdentityEvidence",
        "RuntimeStageDependency",
        "expected_runtime_registry_identity",
    } <= set(dir(contracts))


def _dependencies(
    *, missing: AcquisitionRuntimeStage | None = None
) -> tuple[RuntimeStageDependency, ...]:
    return tuple(
        RuntimeStageDependency(
            stage=stage,
            status=(
                RuntimeDependencyState.NOT_READY
                if stage is missing
                else RuntimeDependencyState.READY
            ),
            reason_codes=("DEPENDENCY_UNAVAILABLE",) if stage is missing else (),
        )
        for stage in AcquisitionRuntimeStage
    )


def capability(**updates: object) -> RuntimeCapabilityEvidence:
    pin = load_hermes_pin()
    values: dict[str, object] = {
        "environment": "STAGING",
        "mode": "SHADOW",
        "qa_only": True,
        "hermes": RuntimeHermesIdentityEvidence(
            repository=pin.repository,
            tag=pin.tag,
            commit=pin.commit,
            version=pin.version,
            python_contract=pin.python,
        ),
        "registry_identity": expected_runtime_registry_identity(),
        "native_tools": 0,
        "commands": tuple(stage.command for stage in AcquisitionRuntimeStage),
        "dependencies": _dependencies(),
    }
    values.update(updates)
    return RuntimeCapabilityEvidence.model_validate(values)


def test_registry_identity_matches_the_closed_executable_registry() -> None:
    def unused(_context):
        raise AssertionError("identity construction must not execute handlers")

    registry = AcquisitionActionRegistry(
        {stage: unused for stage in AcquisitionRuntimeStage}
    )

    assert expected_runtime_registry_identity() == registry.identity
    assert len(expected_runtime_registry_identity()) == 64


def test_capability_is_exactly_staging_qa_shadow_with_eleven_dependencies() -> None:
    observed = capability()

    assert observed.environment == "STAGING"
    assert observed.mode == "SHADOW"
    assert observed.qa_only is True
    assert observed.native_tools == 0
    assert observed.commands == tuple(
        stage.command for stage in AcquisitionRuntimeStage
    )
    assert tuple(item.stage for item in observed.dependencies) == tuple(
        AcquisitionRuntimeStage
    )
    assert all(item.status is RuntimeDependencyState.READY for item in observed.dependencies)
    assert len(observed.fingerprint) == 64


@pytest.mark.parametrize(
    "updates",
    (
        {"environment": "UNCONFIGURED"},
        {"mode": "ASSISTED"},
        {"native_tools": 1},
        {"commands": tuple(stage.command for stage in AcquisitionRuntimeStage)[:-1]},
        {
            "commands": (
                *tuple(stage.command for stage in AcquisitionRuntimeStage)[:-1],
                "run_shell",
            )
        },
        {"dependencies": _dependencies()[:-1]},
        {"dependencies": (*_dependencies()[:-1], _dependencies()[0])},
    ),
)
def test_capability_rejects_environment_registry_and_dependency_drift(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        capability(**updates)


def test_production_capability_evidence_is_now_representable() -> None:
    observed = capability(environment="PRODUCTION", qa_only=False)

    assert observed.environment == "PRODUCTION"
    assert observed.qa_only is False
    assert observed.mode == "SHADOW"
    assert observed.native_tools == 0
    assert observed.commands == tuple(
        stage.command for stage in AcquisitionRuntimeStage
    )
    assert tuple(item.stage for item in observed.dependencies) == tuple(
        AcquisitionRuntimeStage
    )
    assert all(item.status is RuntimeDependencyState.READY for item in observed.dependencies)
    assert len(observed.fingerprint) == 64


def test_dependency_status_is_closed_and_requires_a_bounded_failure_reason() -> None:
    with pytest.raises(ValidationError):
        RuntimeStageDependency(
            stage=AcquisitionRuntimeStage.COMPANY_RESEARCH,
            status=RuntimeDependencyState.NOT_READY,
        )
    with pytest.raises(ValidationError):
        RuntimeStageDependency(
            stage=AcquisitionRuntimeStage.COMPANY_RESEARCH,
            status=RuntimeDependencyState.READY,
            reason_codes=("SHOULD_NOT_BE_PRESENT",),
        )


def test_health_observation_binds_heartbeat_and_last_durable_cycle() -> None:
    observation = RuntimeHealthObservation(
        capability=capability(),
        observed_at=NOW,
        heartbeat_at=NOW + dt.timedelta(minutes=1),
        last_cycle_ref="cycle-qa-001",
        last_cycle_status=RuntimeCycleStatus.SUCCEEDED,
        last_cycle_at=NOW + dt.timedelta(seconds=30),
    )

    assert observation.last_cycle_status is RuntimeCycleStatus.SUCCEEDED
    assert observation.heartbeat_at > observation.last_cycle_at


@pytest.mark.parametrize(
    "updates",
    (
        {"observed_at": NOW.replace(tzinfo=None)},
        {"heartbeat_at": NOW - dt.timedelta(seconds=1)},
        {"last_cycle_ref": "cycle-qa-001"},
        {
            "last_cycle_ref": "cycle-qa-001",
            "last_cycle_status": RuntimeCycleStatus.SUCCEEDED,
            "last_cycle_at": NOW + dt.timedelta(seconds=1),
        },
    ),
)
def test_health_observation_rejects_incomplete_or_incoherent_time_binding(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RuntimeHealthObservation.model_validate(
            {
                "capability": capability(),
                "observed_at": NOW,
                "heartbeat_at": NOW,
                **updates,
            }
        )


def test_health_contract_contains_no_runtime_payload_or_recipient() -> None:
    serialized = RuntimeHealthObservation(
        capability=capability(
            dependencies=_dependencies(
                missing=AcquisitionRuntimeStage.COMPANY_RESEARCH
            )
        ),
        observed_at=NOW,
        heartbeat_at=NOW,
    ).model_dump_json()

    for forbidden in (
        "recipient",
        "email",
        "payload",
        "content",
        "secret",
        "api_key",
        "token",
    ):
        assert forbidden not in serialized.casefold()


def _engine(tmp_path, name: str = "runtime-health.db") -> sa.Engine:
    engine = sa.create_engine(
        f"sqlite+pysqlite:///{tmp_path / name}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    tables = [
        acquisition_runtime_lease,
        acquisition_runtime_cycle,
        acquisition_runtime_stage,
    ]
    observation = METADATA.tables.get("acquisition_runtime_observation")
    if observation is not None:
        tables.append(observation)
    METADATA.create_all(engine, tables=tables)
    return engine


def test_missing_durable_runtime_observation_reads_as_absent(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))

    assert store.read_runtime_observation() is None


def test_owned_runtime_observation_survives_lease_release(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    lease = store.acquire_lease(
        "owner-qa-001", acquired_at=NOW, lease_seconds=120
    )
    assert lease.fencing_token is not None

    recorded = store.record_runtime_observation(
        "owner-qa-001",
        capability(),
        fencing_token=lease.fencing_token,
        at=NOW,
    )
    store.release_lease(
        "owner-qa-001",
        fencing_token=lease.fencing_token,
        at=NOW + dt.timedelta(seconds=1),
    )
    persisted = AcquisitionRuntimeStore(store.engine).read_runtime_observation()

    assert persisted == recorded
    assert persisted is not None
    assert persisted.heartbeat_at == NOW
    assert persisted.last_cycle_ref is None
    with store.engine.connect() as connection:
        lease = connection.execute(sa.select(acquisition_runtime_lease)).mappings().one()
    assert lease["owner_ref"] is None


def test_only_the_current_lease_owner_can_advance_runtime_health(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    lease = store.acquire_lease(
        "owner-qa-001", acquired_at=NOW, lease_seconds=120
    )
    assert lease.fencing_token is not None

    with pytest.raises(AcquisitionRuntimeConflict):
        store.record_runtime_observation(
            "owner-qa-other",
            capability(),
            fencing_token=lease.fencing_token,
            at=NOW,
        )
    with pytest.raises(AcquisitionRuntimeConflict):
        store.record_runtime_observation(
            "owner-qa-001",
            capability(),
            fencing_token=lease.fencing_token,
            at=NOW + dt.timedelta(seconds=120),
        )


def test_cycle_heartbeat_uses_the_durable_cycle_status_and_timestamp(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    lease = store.acquire_lease(
        "owner-qa-001", acquired_at=NOW, lease_seconds=120
    )
    assert lease.fencing_token is not None
    store.record_runtime_observation(
        "owner-qa-001",
        capability(),
        fencing_token=lease.fencing_token,
        at=NOW,
    )
    cycle = store.resume_or_create_cycle(
        owner_ref="owner-qa-001",
        fencing_token=lease.fencing_token,
        opportunity_keys=("signal-qa-001",),
        config_fingerprint="f" * 64,
        at=NOW + dt.timedelta(seconds=1),
    )
    store.begin_stage(
        cycle.cycle_ref,
        AcquisitionRuntimeStage.SIGNAL_SEED,
        owner_ref="owner-qa-001",
        fencing_token=lease.fencing_token,
        at=NOW + dt.timedelta(seconds=2),
    )

    observed = store.record_cycle_observation(
        "owner-qa-001",
        cycle.cycle_ref,
        fencing_token=lease.fencing_token,
        at=NOW + dt.timedelta(seconds=2),
    )
    store.release_lease(
        "owner-qa-001",
        fencing_token=lease.fencing_token,
        at=NOW + dt.timedelta(seconds=3),
    )

    assert observed.heartbeat_at == NOW + dt.timedelta(seconds=2)
    assert observed.last_cycle_ref == cycle.cycle_ref
    assert observed.last_cycle_status is RuntimeCycleStatus.RUNNING
    assert observed.last_cycle_at == NOW + dt.timedelta(seconds=2)
    assert store.read_runtime_observation() == observed


def test_observation_time_cannot_move_backwards(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    lease = store.acquire_lease(
        "owner-qa-001", acquired_at=NOW, lease_seconds=120
    )
    assert lease.fencing_token is not None
    store.record_runtime_observation(
        "owner-qa-001",
        capability(),
        fencing_token=lease.fencing_token,
        at=NOW + dt.timedelta(seconds=2),
    )

    with pytest.raises(AcquisitionRuntimeConflict):
        store.record_runtime_observation(
            "owner-qa-001",
            capability(),
            fencing_token=lease.fencing_token,
            at=NOW + dt.timedelta(seconds=1),
        )


def test_new_run_clears_the_previous_cycle_until_current_cycle_is_bound(
    tmp_path,
) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    lease = store.acquire_lease(
        "owner-qa-001", acquired_at=NOW, lease_seconds=120
    )
    assert lease.fencing_token is not None
    store.record_runtime_observation(
        "owner-qa-001",
        capability(),
        fencing_token=lease.fencing_token,
        at=NOW,
    )
    cycle = store.resume_or_create_cycle(
        owner_ref="owner-qa-001",
        fencing_token=lease.fencing_token,
        opportunity_keys=("signal-qa-001",),
        config_fingerprint="f" * 64,
        at=NOW,
    )
    store.record_cycle_observation(
        "owner-qa-001",
        cycle.cycle_ref,
        fencing_token=lease.fencing_token,
        at=NOW,
    )
    store.release_lease(
        "owner-qa-001", fencing_token=lease.fencing_token, at=NOW
    )

    next_run_at = NOW + dt.timedelta(minutes=1)
    next_lease = store.acquire_lease(
        "owner-qa-002",
        acquired_at=next_run_at,
        lease_seconds=120,
    )
    assert next_lease.fencing_token is not None
    refreshed = store.record_runtime_observation(
        "owner-qa-002",
        capability(),
        fencing_token=next_lease.fencing_token,
        at=next_run_at,
    )
    store.release_lease(
        "owner-qa-002",
        fencing_token=next_lease.fencing_token,
        at=next_run_at,
    )

    assert refreshed.last_cycle_ref is None
    assert refreshed.last_cycle_status is None
    assert refreshed.last_cycle_at is None


def test_tampered_capability_fingerprint_fails_closed_on_read(tmp_path) -> None:
    store = AcquisitionRuntimeStore(_engine(tmp_path))
    lease = store.acquire_lease(
        "owner-qa-001", acquired_at=NOW, lease_seconds=120
    )
    assert lease.fencing_token is not None
    store.record_runtime_observation(
        "owner-qa-001",
        capability(),
        fencing_token=lease.fencing_token,
        at=NOW,
    )
    with store.engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE acquisition_runtime_observation "
                "SET capability_fingerprint = :fingerprint"
            ),
            {"fingerprint": "0" * 64},
        )

    with pytest.raises(AcquisitionRuntimeConflict):
        store.read_runtime_observation()


def test_runtime_observation_table_is_single_bounded_expurgated_state(tmp_path) -> None:
    engine = _engine(tmp_path)
    columns = {
        item["name"]
        for item in sa.inspect(engine).get_columns("acquisition_runtime_observation")
    }
    assert columns == {
        "runtime_name",
        "capability_fingerprint",
        "environment",
        "mode",
        "qa_only",
        "hermes_repository",
        "hermes_tag",
        "hermes_commit",
        "hermes_version",
        "hermes_python_contract",
        "registry_identity",
        "native_tools",
        "commands",
        "dependencies",
        "observed_at",
        "heartbeat_at",
        "last_cycle_ref",
        "last_cycle_status",
        "last_cycle_at",
        "updated_at",
    }
    forbidden = ("email", "recipient", "payload", "content", "secret", "token")
    assert not any(marker in column for marker in forbidden for column in columns)
