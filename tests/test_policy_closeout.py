from __future__ import annotations

import time

import pytest
import sqlalchemy as sa
from alembic import command
from test_policy_gateway import NOW, grant, request, snapshot
from test_policy_persistence import control

from signals.acquisition.store import AcquisitionStore
from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import acquisition_event, policy_evaluation
from signals.policy.contracts import (
    ApprovalPurpose,
    AutonomyMode,
    BudgetUsage,
    ComplianceState,
    OperationalReadiness,
    PolicyStatus,
)
from signals.policy.evaluator import evaluate_policy
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore


@pytest.mark.parametrize(
    ("mode", "command", "expected"),
    [
        (AutonomyMode.ASSISTED, "evaluate_opportunity", PolicyStatus.APPROVED),
        (AutonomyMode.ASSISTED, "schedule_campaign", PolicyStatus.APPROVAL_REQUIRED),
        (AutonomyMode.AUTONOMOUS_CAPPED, "schedule_campaign", PolicyStatus.APPROVED),
        (AutonomyMode.AUTONOMOUS_CAPPED, "reallocate_volume", PolicyStatus.DENIED),
        (AutonomyMode.ADAPTIVE_SCALE, "reallocate_volume", PolicyStatus.APPROVED),
    ],
)
def test_autonomy_matrix(mode: AutonomyMode, command: str, expected: PolicyStatus) -> None:
    global_command = command == "reallocate_volume"
    evidence = request().evidence
    if global_command:
        evidence = evidence.model_copy(
            update={
                "claims": (
                    *evidence.claims,
                    "LEARNING_SNAPSHOT",
                    "ALLOCATION_ENVELOPE",
                    "CONVERSION_RETENTION",
                )
            }
        )
    req = request(
        command,
        acquisition_opportunity_id=None if global_command else "opp-1",
        expected_opportunity_version=None if global_command else 1,
        evidence=evidence,
    )
    assert evaluate_policy(req, snapshot(autonomy_mode=mode), NOW).status is expected


def test_review_grant_does_not_satisfy_action_and_action_does_not_satisfy_review() -> None:
    snap = snapshot(autonomy_mode=AutonomyMode.ASSISTED)
    req = request(
        "schedule_campaign",
        compliance=request().compliance.model_copy(update={"state": ComplianceState.REVIEW_REQUIRED}),
    )
    review = grant(ApprovalPurpose.COMPLIANCE_REVIEW, req, snap)
    action = grant(ApprovalPurpose.ACTION, req, snap)
    review_only = evaluate_policy(req.model_copy(update={"approval_grants": (review,)}), snap, NOW)
    action_only = evaluate_policy(req.model_copy(update={"approval_grants": (action,)}), snap, NOW)
    assert "action_approval_required" in review_only.reason_codes
    assert "compliance_review_approval_required" in action_only.reason_codes
    assert [(item.approval_id, item.purpose) for item in review_only.approval_refs] == [
        (review.approval_id, ApprovalPurpose.COMPLIANCE_REVIEW)
    ]
    assert [(item.approval_id, item.purpose) for item in action_only.approval_refs] == [
        (action.approval_id, ApprovalPurpose.ACTION)
    ]


def test_pause_campaign_ignores_send_quota_but_requires_control_plane() -> None:
    req = request(
        "pause_campaign",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
        operational=OperationalReadiness(
            runtime_revision="runtime-1", provider_quota="EXHAUSTED", mailbox_quota="EXHAUSTED"
        ),
    )
    assert evaluate_policy(req, snapshot(kill_switch=True), NOW).status is PolicyStatus.APPROVED
    unavailable = req.model_copy(update={
        "operational": req.operational.model_copy(update={"provider_control_plane": "UNAVAILABLE"})
    })
    assert evaluate_policy(unavailable, snapshot(), NOW).status is PolicyStatus.RATE_LIMITED
    assert evaluate_policy(unavailable, snapshot(), NOW).retry_after is None


def test_external_text_is_data_but_secret_keys_are_rejected() -> None:
    safe = request(canonical_arguments='{"description":"password rotation tender"}')
    assert safe.canonical_arguments.endswith('"}')
    with pytest.raises(ValueError, match="prohibited"):
        request(canonical_arguments='{"privateKey":"value"}')


def test_pure_evaluator_is_deterministic_for_1000_invocations() -> None:
    req = request()
    snap = snapshot()
    started = time.perf_counter()
    decisions = [evaluate_policy(req, snap, NOW) for _ in range(1000)]
    elapsed = time.perf_counter() - started
    assert all(decision == decisions[0] for decision in decisions)
    assert elapsed >= 0


@pytest.fixture
def engine(tmp_path):
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'rollback.db'}")
    command.upgrade(alembic_config(value), "head")
    PolicyStore(value).append_control(control(1))
    return value


def test_event_failure_rolls_back_policy_row(engine, monkeypatch) -> None:
    acquisition = AcquisitionStore(engine)
    created = acquisition.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create-1"
    )
    req = request(
        acquisition_opportunity_id=created.projection.acquisition_opportunity_id,
        expected_opportunity_version=1,
    )
    monkeypatch.setattr(
        acquisition,
        "append_in_transaction",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("event write failed")),
    )
    with pytest.raises(RuntimeError, match="event write failed"):
        PolicyGateway(engine, acquisition_store=acquisition).evaluate_and_record(
            req, evaluated_at=NOW, budget_usage=BudgetUsage()
        )
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 0
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_event)) == 1


def test_policy_row_failure_never_appends_acquisition_event(engine, monkeypatch) -> None:
    acquisition = AcquisitionStore(engine)
    created = acquisition.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create-1"
    )
    req = request(
        acquisition_opportunity_id=created.projection.acquisition_opportunity_id,
        expected_opportunity_version=1,
    )
    import signals.policy.gateway as gateway_module

    original = gateway_module.decision_values

    def invalid_values(*args, **kwargs):
        values = original(*args, **kwargs)
        values["policy_snapshot_id"] = "missing-snapshot"
        return values

    monkeypatch.setattr(gateway_module, "decision_values", invalid_values)
    with pytest.raises(sa.exc.IntegrityError):
        PolicyGateway(engine, acquisition_store=acquisition).evaluate_and_record(
            req, evaluated_at=NOW, budget_usage=BudgetUsage()
        )
    assert len(acquisition.list_events(created.projection.acquisition_opportunity_id)) == 1


def test_policy_store_has_no_update_or_delete_control_api(engine) -> None:
    store = PolicyStore(engine)
    assert not hasattr(store, "update_control")
    assert not hasattr(store, "delete_control")
