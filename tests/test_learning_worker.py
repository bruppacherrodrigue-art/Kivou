from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from test_policy_persistence import control

from signals.learning.contracts import (
    AllocationCell,
    CandidateKind,
    LearningAllocationEnvelope,
    LearningCellKey,
    LearningCellMetrics,
    LearningSelection,
)
from signals.learning.policy import (
    GatewayLearningPolicyAuthorizer,
    LearningPolicyAuthorization,
)
from signals.learning.store import LearningStore
from signals.learning.worker import LearningLoopWorker, LearningWorkerStatus
from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import acquisition_allocation_proposal, policy_evaluation
from signals.policy.contracts import (
    AutonomyMode,
    BudgetUsage,
    OperationalReadiness,
)
from signals.policy.store import PolicyStore

NOW = dt.datetime(2026, 8, 22, 12, tzinfo=dt.UTC)


def _metric(wedge: str, mrr: int) -> LearningCellMetrics:
    return LearningCellMetrics(
        cell=LearningCellKey(country="CH", wedge=wedge),
        contacted_count=50,
        bounce_count=0,
        positive_reply_count=2,
        complaint_count=0,
        unsubscribe_count=0,
        click_count=2,
        signup_count=2,
        activation_count=2,
        paid_count=2,
        known_mrr_minor_units=mrr,
        retained_mrr_minor_units=mrr,
        currency="CHF",
        mrr_complete=True,
        m1_eligible_count=2,
        retained_m1_count=1,
        m2_eligible_count=0,
        retained_m2_count=0,
        churn_count=0,
        known_variable_cost_minor_units=1_000,
        cost_currency="CHF",
        cost_complete=True,
        missing_cost_reason_codes=(),
    )


class Metrics:
    def capture(self, *, window):
        return (_metric("weaker", 10_000), _metric("stronger", 30_000))


class SelectShift:
    def select(self, context):
        selected = next(
            item for item in context.candidates if item.kind is CandidateKind.SHIFT_ONE_UNIT
        )
        return LearningSelection(
            snapshot_ref=context.snapshot_ref,
            proposal_ref=selected.proposal_ref,
            reason_codes=("HERMES_SELECTED_HIGHER_VALUE",),
            confidence=Decimal("0.9"),
        )


class Authorization:
    def __init__(self, *, status: str, executable: bool, counterfactual: str | None = None):
        self.status = status
        self.executable = executable
        self.counterfactual = counterfactual
        self.calls = 0

    def authorize(self, proposal_ref: str, *, now: dt.datetime):
        self.calls += 1
        return LearningPolicyAuthorization(
            allowed=self.status == "APPROVED",
            executable=self.executable,
            policy_evaluation_id="e" * 64,
            policy_action_fingerprint="f" * 64,
            policy_status=self.status,
            policy_counterfactual_status=self.counterfactual,
        )


def _envelope() -> LearningAllocationEnvelope:
    return LearningAllocationEnvelope(
        valid_from=NOW - dt.timedelta(days=1),
        valid_until=NOW + dt.timedelta(days=30),
        total_daily_units=5,
        cells=(
            AllocationCell(
                cell=LearningCellKey(country="CH", wedge="weaker"),
                current_units=3,
                minimum_units=1,
                maximum_units=4,
            ),
            AllocationCell(
                cell=LearningCellKey(country="CH", wedge="stronger"),
                current_units=2,
                minimum_units=1,
                maximum_units=4,
            ),
        ),
    )


def _worker(tmp_path, authorization, *, envelope=True):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'worker.db'}")
    command.upgrade(alembic_config(engine), "head")
    return engine, LearningLoopWorker(
        store=LearningStore(engine),
        metrics_source=Metrics(),
        envelope_provider=(lambda at: _envelope()) if envelope else (lambda at: None),
        selector=SelectShift(),
        policy_authorizer=authorization,
    )


def test_unconfigured_envelope_is_a_durable_safe_noop(tmp_path) -> None:
    authorization = Authorization(status="APPROVED", executable=True)
    engine, worker = _worker(tmp_path, authorization, envelope=False)

    result = worker.run(window_end=NOW, captured_at=NOW)

    assert result.status is LearningWorkerStatus.UNCONFIGURED
    assert authorization.calls == 0
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_allocation_proposal)
            )
            == 0
        )


@pytest.mark.parametrize(
    ("authorization", "expected_state", "expected_status"),
    [
        (
            Authorization(status="DENIED", executable=False, counterfactual="APPROVED"),
            "SHADOW_ONLY",
            LearningWorkerStatus.SHADOW_ONLY,
        ),
        (
            Authorization(status="DENIED", executable=False),
            "POLICY_DENIED",
            LearningWorkerStatus.POLICY_DENIED,
        ),
        (
            Authorization(status="APPROVED", executable=True),
            "APPLIED",
            LearningWorkerStatus.APPLIED,
        ),
    ],
)
def test_worker_persists_shadow_denial_or_applies_only_executable_policy(
    tmp_path, authorization, expected_state, expected_status
) -> None:
    engine, worker = _worker(tmp_path, authorization)

    result = worker.run(window_end=NOW, captured_at=NOW)

    assert result.status is expected_status
    with engine.connect() as connection:
        selected = (
            connection.execute(
                sa.select(acquisition_allocation_proposal).where(
                    acquisition_allocation_proposal.c.selection_source == "HERMES"
                )
            )
            .mappings()
            .one()
        )
    assert selected["state"] == expected_state
    assert sum(item["units"] for item in selected["proposed_allocation"]) == 5


def test_repeated_worker_window_converges_without_second_application(tmp_path) -> None:
    authorization = Authorization(status="APPROVED", executable=True)
    engine, worker = _worker(tmp_path, authorization)

    first = worker.run(window_end=NOW, captured_at=NOW)
    second = worker.run(window_end=NOW, captured_at=NOW)

    assert first.status is LearningWorkerStatus.APPLIED
    assert second.status in {LearningWorkerStatus.NO_CHANGE, LearningWorkerStatus.APPLIED}
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(acquisition_allocation_proposal)
                .where(acquisition_allocation_proposal.c.state == "APPLIED")
            )
            == 1
        )


def test_gateway_policy_is_durable_and_exact_adaptive_control_can_apply(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'gateway-worker.db'}")
    command.upgrade(alembic_config(engine), "head")
    PolicyStore(engine).append_control(
        control(
            1,
            autonomy_mode=AutonomyMode.ADAPTIVE_SCALE,
            allowed_commands=("reallocate_volume",),
        )
    )
    authorizer = GatewayLearningPolicyAuthorizer(
        engine,
        operational_provider=lambda proposal_ref, now: OperationalReadiness(
            runtime_revision="learning-runtime-v1"
        ),
        budget_usage_provider=lambda proposal_ref, now: BudgetUsage(),
        currency="CHF",
    )
    worker = LearningLoopWorker(
        store=LearningStore(engine),
        metrics_source=Metrics(),
        envelope_provider=lambda at: _envelope(),
        selector=SelectShift(),
        policy_authorizer=authorizer,
    )

    result = worker.run(window_end=NOW, captured_at=NOW)

    assert result.status is LearningWorkerStatus.APPLIED
    with engine.connect() as connection:
        decision = connection.execute(sa.select(policy_evaluation)).mappings().one()
    assert decision["command"] == "reallocate_volume"
    assert decision["status"] == "APPROVED"
    assert decision["proposed_volume"] == 0
    assert decision["estimated_cost"] == 0


def test_restart_after_policy_before_application_resumes_without_second_outcome(
    tmp_path, monkeypatch
) -> None:
    authorization = Authorization(status="APPROVED", executable=True)
    engine, worker = _worker(tmp_path, authorization)
    durable_apply = worker.store.apply

    def crash_after_policy(*args, **kwargs):
        raise RuntimeError("synthetic crash after durable Policy decision")

    monkeypatch.setattr(worker.store, "apply", crash_after_policy)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        worker.run(window_end=NOW, captured_at=NOW)
    monkeypatch.setattr(worker.store, "apply", durable_apply)

    resumed = worker.run(window_end=NOW, captured_at=NOW + dt.timedelta(minutes=1))

    assert resumed.status is LearningWorkerStatus.APPLIED
    assert authorization.calls == 1
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(acquisition_allocation_proposal)
                .where(acquisition_allocation_proposal.c.state == "APPLIED")
            )
            == 1
        )
