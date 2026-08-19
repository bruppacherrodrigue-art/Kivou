from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from test_policy_gateway import NOW, request

from signals.acquisition.contracts import EventType, OpportunityConcurrencyConflict
from signals.acquisition.store import AcquisitionStore
from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import acquisition_event, policy_evaluation
from signals.policy.contracts import (
    POLICY_VERSION,
    AutonomyMode,
    BudgetUsage,
    PolicyControlSnapshot,
    PolicyControlUnavailable,
    PolicyEvaluationIdempotencyConflict,
)
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore

PREVIOUS = "0007_acquisition_event_store"
HEAD = "0008_policy_gateway"


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
    assert script.get_heads() == [HEAD]
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
    with pytest.raises(PolicyEvaluationIdempotencyConflict):
        gateway.evaluate_and_record(
            req.model_copy(update={"target_ref": "changed"}),
            evaluated_at=NOW,
            budget_usage=BudgetUsage(),
        )


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


def test_same_attempt_retry_returns_original_audit_after_control_changes(engine) -> None:
    store = PolicyStore(engine)
    store.append_control(control(1))
    gateway = PolicyGateway(engine)
    req = request(
        "generate_weekly_report",
        acquisition_opportunity_id=None,
        expected_opportunity_version=None,
    )
    original = gateway.evaluate_and_record(
        req, evaluated_at=NOW, budget_usage=BudgetUsage()
    )
    store.append_control(control(2, kill_switch=True))

    retried = gateway.evaluate_and_record(
        req, evaluated_at=NOW, budget_usage=BudgetUsage()
    )
    fresh = gateway.evaluate_and_record(
        req.model_copy(update={"evaluation_id": "eval-fresh"}),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
    )

    assert retried == original
    assert fresh.control_revision == 2
    assert fresh.evaluation_id == "eval-fresh"


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
