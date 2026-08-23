"""Pure operational health and local Hermes pin verification."""

from __future__ import annotations

from signals.operations.contracts import (
    AcquisitionOperationalHealth,
    HealthComponent,
    HealthEvidence,
    HealthStatus,
    HermesRuntimeIdentity,
)
from signals.supervisor.pin import HermesPin, load_hermes_pin


def verify_hermes_runtime(
    observed: HermesRuntimeIdentity | None, *, pin: HermesPin | None = None
) -> HealthComponent:
    expected = pin or load_hermes_pin()
    if observed is None:
        return HealthComponent(
            status=HealthStatus.NOT_READY,
            reason_codes=("HERMES_RUNTIME_UNCONFIGURED",),
        )
    actual = (
        observed.repository,
        observed.tag,
        observed.commit,
        observed.version,
        observed.python_contract,
    )
    wanted = (expected.repository, expected.tag, expected.commit, expected.version, expected.python)
    if actual != wanted:
        return HealthComponent(
            status=HealthStatus.NOT_READY,
            reason_codes=("HERMES_RUNTIME_IDENTITY_MISMATCH",),
        )
    return HealthComponent(status=HealthStatus.READY)


def evaluate_health(evidence: HealthEvidence) -> AcquisitionOperationalHealth:
    values = (
        evidence.api,
        evidence.database,
        evidence.hermes_runtime,
        evidence.supervisor_loop,
        evidence.policy_control,
        evidence.campaign_execution,
        evidence.dlq,
        evidence.circuit_breakers,
    )
    if HealthStatus.NOT_READY in values:
        aggregate = HealthStatus.NOT_READY
    elif HealthStatus.DEGRADED in values:
        aggregate = HealthStatus.DEGRADED
    else:
        aggregate = HealthStatus.READY
    return AcquisitionOperationalHealth(
        observed_at=evidence.observed_at,
        api=evidence.api,
        database=evidence.database,
        hermes_runtime=evidence.hermes_runtime,
        supervisor_loop=evidence.supervisor_loop,
        policy_control=evidence.policy_control,
        campaign_execution=evidence.campaign_execution,
        dlq=evidence.dlq,
        circuit_breakers=evidence.circuit_breakers,
        status=aggregate,
        reason_codes=tuple(sorted(set(evidence.reason_codes))),
    )
