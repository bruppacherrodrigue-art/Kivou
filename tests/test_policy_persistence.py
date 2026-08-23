from __future__ import annotations

import datetime as dt
import threading
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from test_policy_gateway import NOW, grant, request, snapshot

from signals.acquisition.contracts import EventType, OpportunityConcurrencyConflict
from signals.acquisition.store import AcquisitionStore
from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import acquisition_event, policy_evaluation
from signals.policy.contracts import (
    POLICY_VERSION,
    ApprovalPurpose,
    AutonomyMode,
    BudgetUsage,
    ComplianceState,
    OperationalReadiness,
    PolicyControlSnapshot,
    PolicyControlUnavailable,
    PolicyEvaluationIdempotencyConflict,
)
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore

PREVIOUS = "0007_acquisition_event_store"
HEAD = "0008_policy_gateway"
CURRENT_HEAD = "0021_reliability_operations"


def control(revision: int, **overrides: object) -> PolicyControlSnapshot:
    values: dict[str, object] = {
        "policy_snapshot_id": f"snapshot-{revision}",
        "control_revision": revision,
        "policy_version": POLICY_VERSION,
        "autonomy_mode": AutonomyMode.AUTONOMOUS_CAPPED,
        "read_only": False,
        "kill_switch": False,
        "allowed_commands": ("evaluate_opportunity", "generate_weekly_report"),
        "allowed_countries": ("CH",),
        "allowed_languages": ("fr",),
        "allowed_wedges": ("construction",),
        "currency": "CHF",
        "daily_cost_cap": Decimal("100"),
        "daily_volume_cap": 100,
        "effective_at": NOW - dt.timedelta(hours=1),
        "expires_at": None,
        "snapshot_fingerprint": f"{revision:064x}",
        "created_at": NOW - dt.timedelta(hours=1),
        "created_by_actor_type": "HUMAN",
        "created_by_actor_ref": "operator-1",
        "reason_codes": ("configured",),
    }
    values.update(overrides)
    return PolicyControlSnapshot.model_validate(values)


@pytest.fixture
def engine(tmp_path):
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'policy.db'}")
    command.upgrade(alembic_config(value), "head")
    return value


def test_migration_is_linear_and_adds_exactly_two_tables(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'migration.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())
    command.upgrade(config, HEAD)
    assert set(sa.inspect(engine).get_table_names()) - before == {
        "acquisition_policy_snapshot",
        "policy_evaluation",
    }
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(HEAD).down_revision == PREVIOUS
    assert len(HEAD) <= 32
    assert current_revision(engine) == HEAD


def test_postgresql_offline_migration_contains_only_policy_tables(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option(
        "sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou"
    )
    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    sql = capsys.readouterr().out
    assert "CREATE TABLE acquisition_policy_snapshot" in sql
    assert "CREATE TABLE policy_evaluation" in sql
    assert sql.count("CREATE TABLE") == 2
    assert "NUMERIC(18, 6)" in sql
    assert "ON DELETE RESTRICT" in sql


def test_migrated_policy_tables_match_core_schema(engine) -> None:
    from signals.persistence.schema import acquisition_policy_snapshot

    inspector = sa.inspect(engine)
    for table in (acquisition_policy_snapshot, policy_evaluation):
        assert {column["name"] for column in inspector.get_columns(table.name)} == {
            column.name for column in table.columns
        }
    evaluation_columns = {
        column["name"] for column in inspector.get_columns(policy_evaluation.name)
    }
    assert "approval_refs" in evaluation_columns
    assert "approval_ids" not in evaluation_columns


def test_snapshot_selection_uses_highest_eligible_revision_and_survives_restart(engine) -> None:
    store = PolicyStore(engine)
    store.append_control(control(1))
    store.append_control(control(2, expires_at=NOW - dt.timedelta(seconds=1)))
    store.append_control(control(3, effective_at=NOW + dt.timedelta(hours=1)))
    store.append_control(control(4, kill_switch=True))
    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 4
    assert PolicyStore(engine).get_effective_control(NOW).kill_switch is True


def test_snapshot_append_is_monotonic_and_missing_control_fails_closed(engine) -> None:
    with pytest.raises(PolicyControlUnavailable):
        PolicyStore(engine).get_effective_control(NOW)
    store = PolicyStore(engine)
    store.append_control(control(2))
    with pytest.raises(ValueError, match="greater"):
        store.append_control(control(1))


def test_global_evaluation_is_durable_and_retry_idempotent(engine) -> None:
    store = PolicyStore(engine)
    store.append_control(control(1))
    gateway = PolicyGateway(engine)
    req = request(
        "generate_weekly_report",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
    )
    first = gateway.evaluate_and_record(req, evaluated_at=NOW, budget_usage=BudgetUsage())
    second = gateway.evaluate_and_record(req, evaluated_at=NOW, budget_usage=BudgetUsage())
    assert first == second
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 1
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_event)) == 0
        assert connection.execute(sa.select(policy_evaluation.c.approval_refs)).scalar_one() == []
    with pytest.raises(PolicyEvaluationIdempotencyConflict):
        gateway.evaluate_and_record(
            req.model_copy(update={"target_ref": "changed"}),
            evaluated_at=NOW,
            budget_usage=BudgetUsage(),
        )


def test_concurrent_identical_evaluation_id_reloads_one_durable_decision(
    engine, monkeypatch
) -> None:
    PolicyStore(engine).append_control(control(1))
    req = request(
        "generate_weekly_report",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
    )
    original = PolicyStore.evaluation_row
    barrier = threading.Barrier(2)
    call_counts: dict[int, int] = {}
    counts_lock = threading.Lock()

    def synchronized_read(connection, evaluation_id):
        row = original(connection, evaluation_id)
        thread_id = threading.get_ident()
        with counts_lock:
            call_counts[thread_id] = call_counts.get(thread_id, 0) + 1
            call_number = call_counts[thread_id]
        if row is None and call_number <= 2:
            barrier.wait(timeout=5)
        return row

    monkeypatch.setattr(PolicyStore, "evaluation_row", staticmethod(synchronized_read))
    decisions = []
    errors = []

    def evaluate() -> None:
        try:
            decisions.append(
                PolicyGateway(engine).evaluate_and_record(
                    req, evaluated_at=NOW, budget_usage=BudgetUsage()
                )
            )
        except sa.exc.SQLAlchemyError as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=evaluate) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert len(decisions) == 2
    assert decisions[0] == decisions[1]
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 1


def test_fresh_evaluation_id_creates_a_fresh_audit(engine) -> None:
    PolicyStore(engine).append_control(control(1))
    gateway = PolicyGateway(engine)
    req = request(
        "generate_weekly_report", acquisition_opportunity_id=None, expected_opportunity_version=None
    )
    gateway.evaluate_and_record(req, evaluated_at=NOW, budget_usage=BudgetUsage())
    gateway.evaluate_and_record(
        req.model_copy(update={"evaluation_id": "eval-2"}),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
    )
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 2


def test_same_evaluation_id_conflicts_when_control_revision_changes(engine) -> None:
    store = PolicyStore(engine)
    store.append_control(control(1))
    gateway = PolicyGateway(engine)
    req = request(
        "generate_weekly_report",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
    )
    gateway.evaluate_and_record(req, evaluated_at=NOW, budget_usage=BudgetUsage())
    store.append_control(control(2))

    with pytest.raises(PolicyEvaluationIdempotencyConflict):
        gateway.evaluate_and_record(req, evaluated_at=NOW, budget_usage=BudgetUsage())
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 1
    fresh = gateway.evaluate_and_record(
        req.model_copy(update={"evaluation_id": "eval-fresh"}),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
    )
    assert fresh.control_revision == 2
    assert fresh.evaluation_id == "eval-fresh"


def test_same_evaluation_id_conflicts_when_kill_switch_changes(engine) -> None:
    store = PolicyStore(engine)
    store.append_control(control(1))
    gateway = PolicyGateway(engine)
    req = request(
        "generate_weekly_report",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
    )
    gateway.evaluate_and_record(req, evaluated_at=NOW, budget_usage=BudgetUsage())
    store.append_control(control(2, kill_switch=True))

    with pytest.raises(PolicyEvaluationIdempotencyConflict):
        gateway.evaluate_and_record(req, evaluated_at=NOW, budget_usage=BudgetUsage())
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 1


@pytest.mark.parametrize(
    ("request_update", "usage"),
    [
        (
            {
                "compliance": request().compliance.model_copy(
                    update={"state": ComplianceState.BLOCKED}
                )
            },
            BudgetUsage(),
        ),
        (
            {
                "operational": OperationalReadiness(
                    runtime_revision="runtime-1", provider_quota="EXHAUSTED"
                )
            },
            BudgetUsage(),
        ),
        ({}, BudgetUsage(cost_used=Decimal("1"))),
    ],
    ids=("compliance", "provider-quota", "budget-usage"),
)
def test_same_evaluation_id_conflicts_when_authoritative_state_changes(
    engine, request_update, usage
) -> None:
    PolicyStore(engine).append_control(control(1))
    gateway = PolicyGateway(engine)
    req = request(
        "generate_weekly_report",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
    )
    gateway.evaluate_and_record(req, evaluated_at=NOW, budget_usage=BudgetUsage())

    with pytest.raises(PolicyEvaluationIdempotencyConflict):
        gateway.evaluate_and_record(
            req.model_copy(update=request_update), evaluated_at=NOW, budget_usage=usage
        )
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 1


def test_same_evaluation_id_conflicts_when_approval_set_or_purpose_changes(engine) -> None:
    PolicyStore(engine).append_control(control(1))
    gateway = PolicyGateway(engine)
    req = request(
        "generate_weekly_report",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
    )
    snap = snapshot(
        policy_snapshot_id="snapshot-1",
        control_revision=1,
        autonomy_mode=AutonomyMode.AUTONOMOUS_CAPPED,
    )
    action = grant(ApprovalPurpose.ACTION, req, snap)
    first = req.model_copy(update={"approval_grants": (action,)})
    gateway.evaluate_and_record(first, evaluated_at=NOW, budget_usage=BudgetUsage())
    review = action.model_copy(update={"purpose": ApprovalPurpose.COMPLIANCE_REVIEW})

    with pytest.raises(PolicyEvaluationIdempotencyConflict):
        gateway.evaluate_and_record(
            req.model_copy(update={"approval_grants": (review,)}),
            evaluated_at=NOW,
            budget_usage=BudgetUsage(),
        )
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 1


def test_both_used_approval_refs_are_persisted_in_both_audit_surfaces(engine) -> None:
    PolicyStore(engine).append_control(
        control(
            1,
            autonomy_mode=AutonomyMode.ASSISTED,
            allowed_commands=("schedule_campaign",),
        )
    )
    acquisition = AcquisitionStore(engine)
    created = acquisition.create_opportunity(
        identity_key="approval-audit", signal_ref="signal-approval", idempotency_key="create"
    )
    req = request(
        "schedule_campaign",
        acquisition_opportunity_id=created.projection.acquisition_opportunity_id,
        expected_opportunity_version=created.projection.stream_version,
        compliance=request().compliance.model_copy(
            update={"state": ComplianceState.REVIEW_REQUIRED}
        ),
    )
    snap = snapshot(
        policy_snapshot_id="snapshot-1",
        control_revision=1,
        autonomy_mode=AutonomyMode.ASSISTED,
    )
    approvals = (
        grant(ApprovalPurpose.ACTION, req, snap),
        grant(ApprovalPurpose.COMPLIANCE_REVIEW, req, snap),
    )
    req = req.model_copy(update={"approval_grants": approvals})

    decision = PolicyGateway(engine, acquisition_store=acquisition).evaluate_and_record(
        req, evaluated_at=NOW, budget_usage=BudgetUsage()
    )
    with engine.connect() as connection:
        row = connection.execute(sa.select(policy_evaluation)).mappings().one()
    event = acquisition.list_events(created.projection.acquisition_opportunity_id)[-1]

    expected = [item.model_dump(mode="json") for item in decision.approval_refs]
    assert len(expected) == 2
    assert {item["purpose"] for item in expected} == {"ACTION", "COMPLIANCE_REVIEW"}
    assert row["approval_refs"] == expected
    assert event.payload["approval_refs"] == expected

    replayed = PolicyGateway(engine, acquisition_store=acquisition).evaluate_and_record(
        req.model_copy(update={"approval_grants": tuple(reversed(approvals))}),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
    )
    assert replayed == decision
    assert (
        acquisition.get_opportunity(created.projection.acquisition_opportunity_id).stream_version
        == created.projection.stream_version + 1
    )


def test_opportunity_audit_is_atomic_state_neutral_and_retry_safe(engine) -> None:
    PolicyStore(engine).append_control(control(1))
    acquisition = AcquisitionStore(engine)
    created = acquisition.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create-1"
    )
    req = request(
        acquisition_opportunity_id=created.projection.acquisition_opportunity_id,
        expected_opportunity_version=created.projection.stream_version,
    )
    gateway = PolicyGateway(engine, acquisition_store=acquisition)
    first = gateway.evaluate_and_record(req, evaluated_at=NOW, budget_usage=BudgetUsage())
    current = acquisition.get_opportunity(created.projection.acquisition_opportunity_id)
    assert first.executable
    assert current.state == created.projection.state
    assert current.decision == created.projection.decision
    assert current.stream_version == created.projection.stream_version + 1
    events = acquisition.list_events(current.acquisition_opportunity_id)
    assert events[-1].event_type is EventType.POLICY_EVALUATED
    gateway.evaluate_and_record(req, evaluated_at=NOW, budget_usage=BudgetUsage())
    assert (
        acquisition.get_opportunity(current.acquisition_opportunity_id).stream_version
        == current.stream_version
    )


def test_concurrency_failure_writes_neither_audit_surface(engine) -> None:
    PolicyStore(engine).append_control(control(1))
    acquisition = AcquisitionStore(engine)
    created = acquisition.create_opportunity(
        identity_key="identity-1", signal_ref="signal-1", idempotency_key="create-1"
    )
    req = request(
        acquisition_opportunity_id=created.projection.acquisition_opportunity_id,
        expected_opportunity_version=99,
    )
    with pytest.raises(OpportunityConcurrencyConflict):
        PolicyGateway(engine, acquisition_store=acquisition).evaluate_and_record(
            req, evaluated_at=NOW, budget_usage=BudgetUsage()
        )
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 0
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_event)) == 1
