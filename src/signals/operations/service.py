"""Local read-only operational health/readiness service."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Engine, RowMapping

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeCycleStatus,
    RuntimeDependencyState,
    expected_runtime_registry_identity,
)
from signals.acquisition_runtime.store import AcquisitionRuntimeStore
from signals.operations.contracts import (
    AcquisitionOperationalHealth,
    AutonomousReadiness,
    GateEvidence,
    GateStatus,
    HealthEvidence,
    HealthStatus,
    HermesRuntimeIdentity,
    ReadinessEvidence,
)
from signals.operations.health import evaluate_health, verify_hermes_runtime
from signals.operations.readiness import evaluate_readiness
from signals.operations.store import OperationsStore
from signals.policy.store import PolicyStore

RUNTIME_OBSERVATION_MAX_AGE = dt.timedelta(minutes=90)


@dataclass(frozen=True)
class _RuntimeEvidenceState:
    hermes: HealthStatus
    supervisor: HealthStatus
    execution: HealthStatus
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class _PolicyEvidenceState:
    status: HealthStatus
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]


class OperationsReadService:
    """Inspect local durable state only; construction and reads perform no network I/O."""

    def __init__(
        self,
        engine: Engine,
        *,
        observed_runtime: HermesRuntimeIdentity | None = None,
        supervisor_heartbeat_at: dt.datetime | None = None,
        environment_identity: str = "UNCONFIGURED",
    ) -> None:
        if environment_identity not in {"UNCONFIGURED", "STAGING", "PRODUCTION"}:
            raise ValueError("invalid acquisition environment identity")
        self._engine = engine
        self._store = OperationsStore(engine)
        self._runtime_store = AcquisitionRuntimeStore(engine)
        self._policy = PolicyStore(engine)
        # Compatibility-only constructor parameters cannot authorize readiness.
        # The single authority is the observation written by the leased runtime.
        del observed_runtime, supervisor_heartbeat_at, environment_identity

    def health(self, *, observed_at: dt.datetime) -> AcquisitionOperationalHealth:
        health, _, _ = self._health_evidence(observed_at=observed_at)
        return health

    def _health_evidence(
        self, *, observed_at: dt.datetime
    ) -> tuple[
        AcquisitionOperationalHealth,
        _RuntimeEvidenceState,
        _PolicyEvidenceState,
    ]:
        observed_at = self._aware(observed_at)
        reasons: list[str] = []
        try:
            with self._engine.connect() as connection:
                connection.scalar(sa.select(sa.literal(1)))
            database = HealthStatus.READY
        except sa.exc.SQLAlchemyError:
            database = HealthStatus.NOT_READY
            reasons.append("DATABASE_UNAVAILABLE")

        runtime = self._runtime_evidence(observed_at=observed_at)
        policy = self._policy_evidence(observed_at=observed_at)
        reasons.extend(runtime.reason_codes)
        reasons.extend(policy.reason_codes)

        unresolved = self._store.list_incidents(unresolved_only=True, limit=500)
        if any(row["severity"] == "CRITICAL" for row in unresolved):
            breakers = HealthStatus.NOT_READY
            reasons.append("CRITICAL_BREAKER_OPEN")
        elif any(row["severity"] == "HIGH" for row in unresolved):
            breakers = HealthStatus.DEGRADED
            reasons.append("EXECUTION_BREAKER_OPEN")
        else:
            breakers = HealthStatus.READY
        dead_letters = self._store.list_dead_letters(limit=500)
        if any(row["status"] == "OPEN" for row in dead_letters):
            dlq = HealthStatus.DEGRADED
            reasons.append("DEAD_LETTER_BACKLOG")
        else:
            dlq = HealthStatus.READY
        campaign = self._least_ready(runtime.execution, breakers)
        health = evaluate_health(
            HealthEvidence(
                observed_at=observed_at,
                api=HealthStatus.READY,
                database=database,
                hermes_runtime=runtime.hermes,
                supervisor_loop=runtime.supervisor,
                policy_control=policy.status,
                campaign_execution=campaign,
                dlq=dlq,
                circuit_breakers=breakers,
                reason_codes=tuple(sorted(set(reasons))),
            )
        )
        return health, runtime, policy

    def readiness(self, *, evaluated_at: dt.datetime) -> AutonomousReadiness:
        evaluated_at = self._aware(evaluated_at)
        base = ReadinessEvidence.repository_default(evaluated_at=evaluated_at)
        health, runtime, policy = self._health_evidence(observed_at=evaluated_at)
        runtime_ready = (
            health.hermes_runtime is HealthStatus.READY
            and health.supervisor_loop is HealthStatus.READY
            and health.database is HealthStatus.READY
            and health.campaign_execution is HealthStatus.READY
        )
        h_a = GateEvidence(
            status=GateStatus.READY if runtime_ready else GateStatus.NOT_READY,
            reason_codes=(
                ("DURABLE_RUNTIME_OBSERVED",)
                if runtime_ready
                else tuple(
                    sorted(
                        {
                            *runtime.reason_codes,
                            *(
                                ("DATABASE_UNAVAILABLE",)
                                if health.database is not HealthStatus.READY
                                else ()
                            ),
                            *(
                                ("CAMPAIGN_EXECUTION_UNHEALTHY",)
                                if health.campaign_execution is not HealthStatus.READY
                                else ()
                            ),
                        }
                    )
                )
            ),
            evidence_refs=runtime.evidence_refs if runtime_ready else (),
        )
        h_c = GateEvidence(
            status=(
                GateStatus.READY if policy.status is HealthStatus.READY else GateStatus.NOT_READY
            ),
            reason_codes=(
                ("DURABLE_SHADOW_POLICY_OBSERVED",)
                if policy.status is HealthStatus.READY
                else policy.reason_codes
            ),
            evidence_refs=policy.evidence_refs,
        )
        h_e = base.h_e_capped
        if health.circuit_breakers is HealthStatus.NOT_READY:
            h_e = h_e.model_copy(
                update={"reason_codes": tuple(sorted({*h_e.reason_codes, "CRITICAL_BREAKER_OPEN"}))}
            )
        return evaluate_readiness(
            base.model_copy(
                update={
                    "h_a_runtime": h_a,
                    "h_c_policy": h_c,
                    "h_e_capped": h_e,
                }
            )
        )

    def _runtime_evidence(self, *, observed_at: dt.datetime) -> _RuntimeEvidenceState:
        try:
            observation = self._runtime_store.read_runtime_observation()
        except Exception:  # noqa: BLE001 - fail closed without leaking row contents
            return _RuntimeEvidenceState(
                hermes=HealthStatus.NOT_READY,
                supervisor=HealthStatus.NOT_READY,
                execution=HealthStatus.NOT_READY,
                reason_codes=("RUNTIME_OBSERVATION_INVALID",),
                evidence_refs=(),
            )
        if observation is None:
            return _RuntimeEvidenceState(
                hermes=HealthStatus.NOT_READY,
                supervisor=HealthStatus.NOT_READY,
                execution=HealthStatus.NOT_READY,
                reason_codes=("RUNTIME_OBSERVATION_UNAVAILABLE",),
                evidence_refs=(),
            )

        reasons: list[str] = []
        observed_runtime = HermesRuntimeIdentity(
            repository=observation.capability.hermes.repository,
            tag=observation.capability.hermes.tag,
            commit=observation.capability.hermes.commit,
            version=observation.capability.hermes.version,
            python_contract=observation.capability.hermes.python_contract,
        )
        hermes = verify_hermes_runtime(observed_runtime)
        reasons.extend(hermes.reason_codes)
        if observation.capability.registry_identity != expected_runtime_registry_identity():
            reasons.append("RUNTIME_REGISTRY_IDENTITY_MISMATCH")

        fresh = self._fresh(observation.observed_at, at=observed_at) and self._fresh(
            observation.heartbeat_at,
            at=observed_at,
        )
        supervisor = HealthStatus.READY if fresh else HealthStatus.NOT_READY
        if not fresh:
            reasons.append("RUNTIME_OBSERVATION_STALE")

        execution = HealthStatus.READY
        if any(
            item.status is RuntimeDependencyState.NOT_READY
            for item in observation.capability.dependencies
        ):
            execution = HealthStatus.NOT_READY
            reasons.append("RUNTIME_DEPENDENCY_UNAVAILABLE")
        if observation.last_cycle_at is None:
            execution = HealthStatus.NOT_READY
            reasons.append("RUNTIME_LAST_CYCLE_UNOBSERVED")
        elif not self._fresh(observation.last_cycle_at, at=observed_at):
            execution = HealthStatus.NOT_READY
            reasons.append("RUNTIME_LAST_CYCLE_STALE")
        elif observation.last_cycle_status is not RuntimeCycleStatus.SUCCEEDED:
            execution = HealthStatus.NOT_READY
            reasons.append(f"RUNTIME_LAST_CYCLE_{observation.last_cycle_status.value}")
        if hermes.status is not HealthStatus.READY or (
            observation.capability.registry_identity != expected_runtime_registry_identity()
        ):
            execution = HealthStatus.NOT_READY

        return _RuntimeEvidenceState(
            hermes=hermes.status,
            supervisor=supervisor,
            execution=execution,
            reason_codes=tuple(sorted(set(reasons))),
            evidence_refs=("acquisition-runtime-observation-v1",),
        )

    def _policy_evidence(self, *, observed_at: dt.datetime) -> _PolicyEvidenceState:
        try:
            control = self._policy.get_effective_control(observed_at)
        except Exception:  # noqa: BLE001 - fail closed without leaking policy contents
            return _PolicyEvidenceState(
                status=HealthStatus.NOT_READY,
                reason_codes=("POLICY_CONTROL_UNAVAILABLE",),
                evidence_refs=(),
            )
        reasons: list[str] = []
        if control.kill_switch:
            reasons.append("KILL_SWITCH_ACTIVE")
        if control.autonomy_mode.value != "SHADOW":
            reasons.append("POLICY_MODE_NOT_SHADOW")
        if not control.read_only:
            reasons.append("POLICY_WRITE_MODE_ENABLED")
        required_commands = {stage.command for stage in AcquisitionRuntimeStage}
        if not required_commands.issubset(set(control.allowed_commands)):
            reasons.append("POLICY_COMMANDS_INCOMPLETE")
        return _PolicyEvidenceState(
            status=(HealthStatus.NOT_READY if reasons else HealthStatus.READY),
            reason_codes=tuple(sorted(set(reasons))),
            evidence_refs=("acquisition-policy-v1",),
        )

    @staticmethod
    def _fresh(value: dt.datetime, *, at: dt.datetime) -> bool:
        age = at - value.astimezone(dt.UTC)
        return dt.timedelta(0) <= age <= RUNTIME_OBSERVATION_MAX_AGE

    @staticmethod
    def _aware(value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("operational observation timestamp must be timezone-aware")
        return value.astimezone(dt.UTC)

    @staticmethod
    def _least_ready(*statuses: HealthStatus) -> HealthStatus:
        if HealthStatus.NOT_READY in statuses:
            return HealthStatus.NOT_READY
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        return HealthStatus.READY

    def incidents(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        return tuple(self._safe_row(row) for row in self._store.list_incidents(limit=limit))

    def dead_letters(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        return tuple(self._safe_row(row) for row in self._store.list_dead_letters(limit=limit))

    @staticmethod
    def _safe_row(row: RowMapping) -> dict[str, object]:
        return dict(row)
