from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from alembic import command
from pydantic import ValidationError

from signals.operations.contracts import (
    DEFAULT_RETRY_POLICY,
    BreakerScope,
    DeadLetterExhaustion,
    DeadLetterStatus,
    GateEvidence,
    GateStatus,
    HealthEvidence,
    HealthStatus,
    HermesRuntimeIdentity,
    IncidentSeverity,
    IncidentState,
    IncidentTrigger,
    IncidentType,
    ReadinessEvidence,
    RetryDisposition,
    WorkType,
)
from signals.operations.health import evaluate_health, verify_hermes_runtime
from signals.operations.readiness import evaluate_readiness
from signals.operations.store import OperationsStore
from signals.persistence.database import alembic_config, create_database_engine
from signals.policy.contracts import AutonomyMode
from signals.supervisor.pin import load_hermes_pin

NOW = dt.datetime(2026, 8, 23, 12, tzinfo=dt.UTC)


def _store(tmp_path) -> OperationsStore:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'ops.db'}")
    command.upgrade(alembic_config(engine), "head")
    return OperationsStore(engine)


def _incident(**changes: object) -> IncidentTrigger:
    values: dict[str, object] = {
        "incident_type": IncidentType.COMPLAINT,
        "severity": IncidentSeverity.HIGH,
        "scope": BreakerScope(scope_type="CAMPAIGN", scope_ref="campaign-1"),
        "source_state_ref": "response-evaluation:synthetic",
        "triggered_at": NOW,
        "reason_codes": ("AUTHORITATIVE_COMPLAINT",),
        "campaign_ref": None,
        "human_review_required": True,
        "pause_required": True,
    }
    values.update(changes)
    return IncidentTrigger.model_validate(values)


def test_incident_replay_restart_and_explicit_resolution(tmp_path) -> None:
    store = _store(tmp_path)
    first = store.open_incident(_incident())
    replay = store.open_incident(_incident())

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.row["incident_ref"] == first.row["incident_ref"]
    assert store.has_open_breaker(BreakerScope(scope_type="CAMPAIGN", scope_ref="campaign-1"))

    restarted = OperationsStore(store.engine)
    assert restarted.get_incident(first.row["incident_ref"])["state"] == IncidentState.OPEN
    acknowledged = restarted.acknowledge_incident(first.row["incident_ref"], at=NOW)
    assert acknowledged["state"] == IncidentState.ACKNOWLEDGED
    assert restarted.has_open_breaker(
        BreakerScope(scope_type="CAMPAIGN", scope_ref="campaign-1")
    )
    resolved = restarted.resolve_incident(
        first.row["incident_ref"], at=NOW + dt.timedelta(minutes=1)
    )
    assert resolved["state"] == IncidentState.RESOLVED
    assert not restarted.has_open_breaker(
        BreakerScope(scope_type="CAMPAIGN", scope_ref="campaign-1")
    )


def test_warning_does_not_open_execution_breaker_but_global_critical_does(tmp_path) -> None:
    store = _store(tmp_path)
    store.open_incident(
        _incident(
            incident_type=IncidentType.COST_DRIFT,
            severity=IncidentSeverity.WARNING,
            scope=BreakerScope(scope_type="WEDGE", scope_ref="construction"),
        )
    )
    assert not store.has_open_breaker(
        BreakerScope(scope_type="WEDGE", scope_ref="construction")
    )

    store.open_incident(
        _incident(
            incident_type=IncidentType.UNEXPECTED_TRANSPORT_TRUTH,
            severity=IncidentSeverity.CRITICAL,
            scope=BreakerScope(scope_type="GLOBAL", scope_ref="acquisition"),
            reason_codes=("POST_STOP_SEND",),
        )
    )
    assert store.has_open_breaker(
        BreakerScope(scope_type="CAMPAIGN", scope_ref="any-campaign")
    )


def test_dead_letter_exhaustion_converges_and_survives_restart(tmp_path) -> None:
    store = _store(tmp_path)
    exhausted = DeadLetterExhaustion(
        work_type=WorkType.RESPONSE_RESOLUTION,
        work_ref="response-ref-1",
        scope=BreakerScope(scope_type="CAMPAIGN", scope_ref="campaign-1"),
        attempt_count=3,
        first_failed_at=NOW - dt.timedelta(minutes=10),
        last_failed_at=NOW,
        failure_code="RESPONSE_CONTENT_UNAVAILABLE",
        retry_policy_version="response-email-resolution-v1",
        source_component="responses",
        source_state_ref="evaluation-ref-1",
    )
    first = store.enqueue_dead_letter(exhausted, created_at=NOW)
    replay = store.enqueue_dead_letter(exhausted, created_at=NOW + dt.timedelta(minutes=1))

    assert not first.replayed
    assert replay.replayed
    assert replay.row["dead_letter_ref"] == first.row["dead_letter_ref"]
    restarted = OperationsStore(store.engine)
    row = restarted.get_dead_letter(first.row["dead_letter_ref"])
    assert row["status"] == DeadLetterStatus.OPEN
    requeued = restarted.mark_dead_letter_requeued(
        row["dead_letter_ref"], at=NOW + dt.timedelta(minutes=2)
    )
    assert requeued["status"] == DeadLetterStatus.REQUEUED
    resolved = restarted.resolve_dead_letter(
        row["dead_letter_ref"], at=NOW + dt.timedelta(minutes=3)
    )
    assert resolved["status"] == DeadLetterStatus.RESOLVED
    assert restarted.get_dead_letter(row["dead_letter_ref"])["status"] == "RESOLVED"


def test_default_retry_policy_is_bounded_and_reconcile_first() -> None:
    assert DEFAULT_RETRY_POLICY.maximum_attempts == 5
    assert DEFAULT_RETRY_POLICY.delays_seconds == (60, 120, 240, 480, 960)
    assert DEFAULT_RETRY_POLICY.decide(1, failed_at=NOW).retry_at == NOW + dt.timedelta(
        minutes=1
    )
    assert DEFAULT_RETRY_POLICY.decide(5, failed_at=NOW).disposition is RetryDisposition.DLQ
    assert (
        DEFAULT_RETRY_POLICY.decide(1, failed_at=NOW, external_outcome_unknown=True).disposition
        is RetryDisposition.RECONCILE_FIRST
    )


def test_pinned_runtime_health_and_conservative_default_readiness() -> None:
    pin = load_hermes_pin()
    observed = HermesRuntimeIdentity(
        repository=pin.repository,
        tag=pin.tag,
        commit=pin.commit,
        version=pin.version,
        python_contract=pin.python,
    )
    assert verify_hermes_runtime(observed, pin=pin).status is HealthStatus.READY
    mismatch = observed.model_copy(update={"commit": "0" * 40})
    assert verify_hermes_runtime(mismatch, pin=pin).status is HealthStatus.NOT_READY

    health = evaluate_health(
        HealthEvidence(
            observed_at=NOW,
            api=HealthStatus.READY,
            database=HealthStatus.READY,
            hermes_runtime=HealthStatus.NOT_READY,
            supervisor_loop=HealthStatus.DEGRADED,
            policy_control=HealthStatus.READY,
            campaign_execution=HealthStatus.READY,
            dlq=HealthStatus.READY,
            circuit_breakers=HealthStatus.READY,
            reason_codes=("HERMES_RUNTIME_UNCONFIGURED",),
        )
    )
    assert health.status is HealthStatus.NOT_READY
    assert "HERMES_RUNTIME_UNCONFIGURED" in health.reason_codes

    readiness = evaluate_readiness(ReadinessEvidence.repository_default(evaluated_at=NOW))
    assert readiness.h_a_runtime.status is GateStatus.NOT_READY
    assert readiness.h_d_shadow.status is GateStatus.INSUFFICIENT_EVIDENCE
    assert readiness.h_e_capped.status is GateStatus.NOT_READY
    assert readiness.highest_safe_mode is AutonomyMode.SHADOW


def test_all_explicit_synthetic_gates_can_report_adaptive_without_changing_policy() -> None:
    ready = GateEvidence(status=GateStatus.READY, reason_codes=("SYNTHETIC_GATE_READY",))
    evidence = ReadinessEvidence(
        evaluated_at=NOW,
        h_a_runtime=ready,
        h_b_state=ready,
        h_c_policy=ready,
        h_d_shadow=ready,
        h_e_capped=ready,
        h_f_closed_loop=ready,
        h_g_scale=ready,
    )
    result = evaluate_readiness(evidence)
    assert result.highest_safe_mode is AutonomyMode.ADAPTIVE_SCALE
    assert result.blockers == ()


def test_incident_and_dead_letter_contracts_reject_pii_sized_or_free_form_values() -> None:
    # Bounded contracts accept only enum vocabularies and short safe codes/refs.
    trigger = _incident(observed_value=Decimal("0.10"), threshold_value=Decimal("0.05"))
    assert trigger.observed_value == Decimal("0.10")
    exhaustion = DeadLetterExhaustion(
        work_type=WorkType.LEARNING_CYCLE,
        work_ref="learning:cycle:1",
        scope=BreakerScope(scope_type="GLOBAL", scope_ref="acquisition"),
        attempt_count=5,
        first_failed_at=NOW,
        last_failed_at=NOW,
        failure_code="POLICY_UNAVAILABLE",
        retry_policy_version="acquisition-retry-policy-v1",
        source_component="learning",
        source_state_ref="snapshot-ref",
    )
    serialized = str(exhaustion.model_dump(mode="json")) + str(
        trigger.model_dump(mode="json")
    )
    for marker in ("lead@example.invalid", "sk_live_secret", "response body marker"):
        assert marker not in serialized
    with pytest.raises(ValidationError):
        _incident(source_state_ref="lead-marker@example.invalid")
    with pytest.raises(ValidationError):
        DeadLetterExhaustion(
            work_type=WorkType.CAMPAIGN_PROVIDER_OPERATION,
            work_ref="https://provider.invalid/raw-object",
            scope=BreakerScope(scope_type="CAMPAIGN", scope_ref="campaign-ref"),
            attempt_count=3,
            first_failed_at=NOW,
            last_failed_at=NOW,
            failure_code="REMOTE_UNKNOWN",
            retry_policy_version="provider-operation-v1",
            source_component="campaigns",
            source_state_ref="operation-ref",
        )
