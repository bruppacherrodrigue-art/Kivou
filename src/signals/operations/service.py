"""Local read-only operational health/readiness service."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.engine import Engine, RowMapping

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

SUPERVISOR_HEARTBEAT_MAX_AGE = dt.timedelta(minutes=15)


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
        self._policy = PolicyStore(engine)
        self._runtime = observed_runtime
        self._heartbeat = supervisor_heartbeat_at
        self._environment = environment_identity

    def health(self, *, observed_at: dt.datetime) -> AcquisitionOperationalHealth:
        reasons: list[str] = []
        try:
            with self._engine.connect() as connection:
                connection.scalar(sa.select(sa.literal(1)))
            database = HealthStatus.READY
        except sa.exc.SQLAlchemyError:
            database = HealthStatus.NOT_READY
            reasons.append("DATABASE_UNAVAILABLE")

        runtime = verify_hermes_runtime(self._runtime)
        reasons.extend(runtime.reason_codes)
        heartbeat = self._heartbeat
        if heartbeat is None:
            supervisor = HealthStatus.NOT_READY
            reasons.append("SUPERVISOR_LOOP_UNOBSERVED")
        else:
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=dt.UTC)
            age = observed_at.astimezone(dt.UTC) - heartbeat.astimezone(dt.UTC)
            supervisor = (
                HealthStatus.READY
                if dt.timedelta(0) <= age <= SUPERVISOR_HEARTBEAT_MAX_AGE
                else HealthStatus.NOT_READY
            )
            if supervisor is HealthStatus.NOT_READY:
                reasons.append("SUPERVISOR_LOOP_STALE")

        try:
            self._policy.get_effective_control(observed_at)
            policy = HealthStatus.READY
        except Exception:  # noqa: BLE001 - boundary emits a bounded reason, never exception text
            policy = HealthStatus.NOT_READY
            reasons.append("POLICY_CONTROL_UNAVAILABLE")

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
        campaign = (
            HealthStatus.NOT_READY
            if breakers is HealthStatus.NOT_READY
            else HealthStatus.DEGRADED
            if breakers is HealthStatus.DEGRADED
            else HealthStatus.READY
        )
        return evaluate_health(
            HealthEvidence(
                observed_at=observed_at,
                api=HealthStatus.READY,
                database=database,
                hermes_runtime=runtime.status,
                supervisor_loop=supervisor,
                policy_control=policy,
                campaign_execution=campaign,
                dlq=dlq,
                circuit_breakers=breakers,
                reason_codes=tuple(sorted(set(reasons))),
            )
        )

    def readiness(self, *, evaluated_at: dt.datetime) -> AutonomousReadiness:
        base = ReadinessEvidence.repository_default(evaluated_at=evaluated_at)
        health = self.health(observed_at=evaluated_at)
        runtime_ready = (
            health.hermes_runtime is HealthStatus.READY
            and health.supervisor_loop is HealthStatus.READY
            and health.database is HealthStatus.READY
            and self._environment in {"STAGING", "PRODUCTION"}
        )
        h_a = GateEvidence(
            status=GateStatus.READY if runtime_ready else GateStatus.NOT_READY,
            reason_codes=(
                ("PINNED_RUNTIME_OBSERVED",)
                if runtime_ready
                else tuple(
                    sorted(
                        {
                            *(
                                ("ENVIRONMENT_UNCONFIGURED",)
                                if self._environment == "UNCONFIGURED"
                                else ()
                            ),
                            *(
                                ("HERMES_RUNTIME_UNAVAILABLE",)
                                if health.hermes_runtime is not HealthStatus.READY
                                else ()
                            ),
                            *(
                                ("SUPERVISOR_LOOP_UNHEALTHY",)
                                if health.supervisor_loop is not HealthStatus.READY
                                else ()
                            ),
                        }
                    )
                )
            ),
            evidence_refs=("hermes-runtime-pin:v2026.8.18",) if runtime_ready else (),
        )
        h_e = base.h_e_capped
        if health.circuit_breakers is HealthStatus.NOT_READY:
            h_e = h_e.model_copy(
                update={
                    "reason_codes": tuple(
                        sorted({*h_e.reason_codes, "CRITICAL_BREAKER_OPEN"})
                    )
                }
            )
        return evaluate_readiness(base.model_copy(update={"h_a_runtime": h_a, "h_e_capped": h_e}))

    def incidents(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        return tuple(self._safe_row(row) for row in self._store.list_incidents(limit=limit))

    def dead_letters(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        return tuple(self._safe_row(row) for row in self._store.list_dead_letters(limit=limit))

    @staticmethod
    def _safe_row(row: RowMapping) -> dict[str, object]:
        return dict(row)
