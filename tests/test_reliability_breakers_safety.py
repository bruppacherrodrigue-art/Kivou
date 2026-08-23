from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from alembic import command
from test_policy_persistence import control

from signals.operations.circuit_breakers import (
    AcquisitionCircuitOpen,
    AcquisitionExecutionGuard,
    BounceObservation,
    CircuitBreakerService,
    DegradationObservation,
    LearningDegradationThresholds,
    ProviderFailureObservation,
)
from signals.operations.contracts import (
    BreakerScope,
    IncidentSeverity,
    IncidentState,
    IncidentType,
)
from signals.operations.safety_controller import SafetyController
from signals.operations.store import OperationsStore
from signals.persistence.database import alembic_config, create_database_engine
from signals.policy.contracts import AutonomyMode
from signals.policy.store import PolicyStore

NOW = dt.datetime(2026, 8, 23, 12, tzinfo=dt.UTC)


def _services(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'breakers.db'}")
    command.upgrade(alembic_config(engine), "head")
    store = OperationsStore(engine)
    return engine, store, CircuitBreakerService(store)


def test_bounce_breaker_uses_unique_step1_members_and_strictly_greater_than_five_percent(
    tmp_path,
) -> None:
    _, store, service = _services(tmp_path)
    members = tuple(f"member-{index:02d}" for index in range(20))

    exactly_five = service.observe_bounces(
        BounceObservation(
            scope=BreakerScope(scope_type="CAMPAIGN", scope_ref="campaign-1"),
            authoritative_step1_members=members,
            bounced_step1_members=(members[0],),
            source_state_ref="provider-window:one-bounce",
            observed_at=NOW,
            campaign_ref=None,
        )
    )
    assert exactly_five is None
    assert not store.has_open_breaker(
        BreakerScope(scope_type="CAMPAIGN", scope_ref="campaign-1")
    )

    opened = service.observe_bounces(
        BounceObservation(
            scope=BreakerScope(scope_type="CAMPAIGN", scope_ref="campaign-1"),
            authoritative_step1_members=members,
            bounced_step1_members=(members[0], members[1]),
            source_state_ref="provider-window:two-bounces",
            observed_at=NOW,
            campaign_ref=None,
        )
    )
    assert opened is not None
    assert opened.row["incident_type"] == IncidentType.BOUNCE_RATE
    assert opened.row["observed_value"] == Decimal("0.1")
    assert opened.row["threshold_value"] == Decimal("0.05")
    assert opened.row["state"] == IncidentState.OPEN

    restarted_guard = AcquisitionExecutionGuard(OperationsStore(store.engine))
    with pytest.raises(AcquisitionCircuitOpen):
        restarted_guard.require_allowed(
            BreakerScope(scope_type="CAMPAIGN", scope_ref="campaign-1")
        )


def test_complaint_opens_campaign_breaker_and_requires_pause_and_review(tmp_path) -> None:
    _, _, service = _services(tmp_path)
    outcome = service.observe_complaint(
        campaign_ref="campaign-complaint",
        response_evaluation_ref="response-evaluation-1",
        observed_at=NOW,
    )

    assert outcome.row["severity"] == IncidentSeverity.HIGH
    assert outcome.row["human_review_required"] is True
    assert outcome.row["pause_required"] is True
    assert outcome.row["state"] == IncidentState.OPEN
    assert service.observe_complaint(
        campaign_ref="campaign-complaint",
        response_evaluation_ref="response-evaluation-1",
        observed_at=NOW + dt.timedelta(minutes=1),
    ).replayed


def test_provider_failure_opens_after_three_qualifying_failures_but_not_rate_limit(
    tmp_path,
) -> None:
    _, _, service = _services(tmp_path)
    scope = BreakerScope(scope_type="MAILBOX", scope_ref="mailbox-1")
    assert (
        service.observe_provider_failures(
            ProviderFailureObservation(
                scope=scope,
                failure_refs=("op-1", "op-2"),
                failure_codes=("REMOTE_FAILURE", "REMOTE_FAILURE"),
                source_state_ref="provider-scan-1",
                observed_at=NOW,
            )
        )
        is None
    )
    assert (
        service.observe_provider_failures(
            ProviderFailureObservation(
                scope=scope,
                failure_refs=("op-1", "op-2", "op-rate"),
                failure_codes=("REMOTE_FAILURE", "REMOTE_FAILURE", "RATE_LIMITED"),
                source_state_ref="provider-scan-2",
                observed_at=NOW,
            )
        )
        is None
    )
    opened = service.observe_provider_failures(
        ProviderFailureObservation(
            scope=scope,
            failure_refs=("op-1", "op-2", "op-3"),
            failure_codes=("REMOTE_FAILURE", "RECONCILE_REQUIRED", "REMOTE_FAILURE"),
            source_state_ref="provider-scan-3",
            observed_at=NOW,
        )
    )
    assert opened is not None
    assert opened.row["incident_type"] == IncidentType.PROVIDER_FAILURE


def test_conversion_retention_breakers_are_operator_configured_and_default_unconfigured(
    tmp_path,
) -> None:
    _, _, service = _services(tmp_path)
    observation = DegradationObservation(
        incident_type=IncidentType.RETENTION_DEGRADATION,
        scope=BreakerScope(scope_type="WEDGE", scope_ref="construction"),
        authoritative_sample_count=50,
        observed_rate=Decimal("0.20"),
        source_state_ref="learning-snapshot-ref",
        observed_at=NOW,
    )
    assert service.observe_degradation(
        observation, thresholds=LearningDegradationThresholds()
    ) is None

    opened = service.observe_degradation(
        observation,
        thresholds=LearningDegradationThresholds(
            version="operator-degradation-thresholds-v1",
            minimum_sample=20,
            minimum_retention_rate=Decimal("0.30"),
        ),
    )
    assert opened is not None
    assert opened.row["incident_type"] == IncidentType.RETENTION_DEGRADATION
    assert opened.row["threshold_value"] == Decimal("0.30")


def test_critical_transport_preserves_evidence_and_opens_global_hard_stop(tmp_path) -> None:
    _, store, service = _services(tmp_path)
    opened = service.observe_critical_transport(
        campaign_ref="campaign-stopped",
        provider_event_ref="authoritative-sent-event",
        incident_code="UNEXPECTED_EMAIL_SENT_AFTER_STOP",
        observed_at=NOW,
    )
    assert opened.row["severity"] == IncidentSeverity.CRITICAL
    assert opened.row["incident_type"] == IncidentType.UNEXPECTED_TRANSPORT_TRUTH
    assert "authoritative-sent-event" not in opened.row["reason_codes"]
    assert store.has_open_breaker(
        BreakerScope(scope_type="CAMPAIGN", scope_ref="campaign-stopped")
    )


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (AutonomyMode.ADAPTIVE_SCALE, AutonomyMode.AUTONOMOUS_CAPPED),
        (AutonomyMode.AUTONOMOUS_CAPPED, AutonomyMode.ASSISTED),
        (AutonomyMode.ASSISTED, AutonomyMode.SHADOW),
        (AutonomyMode.SHADOW, AutonomyMode.SHADOW),
    ],
)
def test_autonomy_downgrade_is_monotonic_append_only_and_idempotent(
    tmp_path, start, expected
) -> None:
    engine, _, _ = _services(tmp_path)
    PolicyStore(engine).append_control(
        control(
            1,
            autonomy_mode=start,
            shadow_target_mode=(AutonomyMode.ASSISTED if start is AutonomyMode.SHADOW else None),
            allowed_commands=("schedule_campaign", "pause_campaign", "generate_weekly_report"),
            effective_at=NOW - dt.timedelta(minutes=1),
        )
    )
    safety = SafetyController(engine)

    changed = safety.downgrade(at=NOW, reason_codes=("OPERATIONS_INCIDENT",))
    replay = safety.downgrade(at=NOW, reason_codes=("OPERATIONS_INCIDENT",))

    assert changed.autonomy_mode is expected
    assert replay.policy_snapshot_id == changed.policy_snapshot_id
    assert replay.autonomy_mode is expected
    assert replay.control_revision == changed.control_revision


def test_critical_downgrade_sets_shadow_kill_switch_read_only_and_keeps_history(tmp_path) -> None:
    engine, _, _ = _services(tmp_path)
    PolicyStore(engine).append_control(
        control(
            1,
            autonomy_mode=AutonomyMode.ADAPTIVE_SCALE,
            allowed_commands=(
                "schedule_campaign",
                "reallocate_volume",
                "pause_campaign",
                "generate_weekly_report",
            ),
            effective_at=NOW - dt.timedelta(minutes=1),
        )
    )
    safety = SafetyController(engine)

    result = safety.critical_stop(at=NOW, reason_codes=("POST_STOP_SEND",))

    assert result.autonomy_mode is AutonomyMode.SHADOW
    assert result.shadow_target_mode is AutonomyMode.ASSISTED
    assert result.kill_switch is True
    assert result.read_only is True
    assert result.control_revision == 2
    first = PolicyStore(engine).get_control("snapshot-1")
    assert first.autonomy_mode is AutonomyMode.ADAPTIVE_SCALE
    assert safety.critical_stop(
        at=NOW + dt.timedelta(minutes=1), reason_codes=("POST_STOP_SEND",)
    ).policy_snapshot_id == result.policy_snapshot_id
