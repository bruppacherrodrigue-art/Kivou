from __future__ import annotations

import datetime as dt
import threading

import pytest
import sqlalchemy as sa
from alembic import command
from test_policy_persistence import control
from test_supplier_discovery_policy import _discovery_request

from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import supplier_discovery_run
from signals.policy.contracts import BudgetUsage
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore
from signals.supplier_discovery.contracts import (
    DiscoveryRunIdentityConflict,
    DiscoveryRunStart,
    DiscoveryRunStatus,
    SupplierTargetingConfig,
)
from signals.supplier_discovery.profile import build_supplier_search_profile
from signals.supplier_discovery.store import SupplierDiscoveryStore

NOW = dt.datetime(2026, 8, 20, 9, tzinfo=dt.UTC)


@pytest.fixture
def engine(tmp_path):
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'runs.db'}")
    command.upgrade(alembic_config(value), "head")
    PolicyStore(value).append_control(
        control(1, allowed_commands=("discover_suppliers",))
    )
    PolicyGateway(value).evaluate_and_record(
        _discovery_request(evaluation_id="discovery-eval-1", request_id="discovery-request-1"),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
    )
    return value


def start(run_id: str) -> DiscoveryRunStart:
    profile = build_supplier_search_profile(
        signal_ref="procurement-opportunity:public-1",
        representative_award_key="award-1",
        need_categories=("workforce_capacity",),
        targeting=SupplierTargetingConfig(),
    )
    return DiscoveryRunStart(
        discovery_run_id=run_id,
        policy_evaluation_id="discovery-eval-1",
        profile=profile,
        provider_request_fingerprint="b" * 64,
        started_at=NOW,
        correlation_id=run_id,
    )


def test_one_policy_evaluation_owns_at_most_one_provider_run(engine) -> None:
    store = SupplierDiscoveryStore(engine)
    first = store.start_run(start("run-1"))
    replay = store.start_run(start("run-2"))

    assert first.owned is True
    assert first.run.status is DiscoveryRunStatus.STARTED
    assert replay.owned is False
    assert replay.run.discovery_run_id == "run-1"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(supplier_discovery_run)) == 1


def test_concurrent_start_has_exactly_one_owner(engine, monkeypatch) -> None:
    store = SupplierDiscoveryStore(engine)
    original = store._insert_run_if_absent
    barrier = threading.Barrier(2)

    def synchronized_insert(connection, values):
        barrier.wait(timeout=5)
        return original(connection, values)

    monkeypatch.setattr(store, "_insert_run_if_absent", synchronized_insert)
    results = []
    errors = []

    def claim(run_id: str) -> None:
        try:
            results.append(store.start_run(start(run_id)))
        except (RuntimeError, sa.exc.SQLAlchemyError) as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=claim, args=(f"run-{index}",)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert sorted(result.owned for result in results) == [False, True]
    assert len({result.run.discovery_run_id for result in results}) == 1


def test_discovery_run_id_replay_with_same_semantics_returns_existing(engine) -> None:
    store = SupplierDiscoveryStore(engine)
    first = store.start_run(start("run-stable"))
    replay = store.start_run(start("run-stable"))

    assert first.owned is True
    assert replay.owned is False
    assert replay.run == first.run


def test_discovery_run_id_collision_with_other_policy_is_typed(engine) -> None:
    PolicyGateway(engine).evaluate_and_record(
        _discovery_request(
            evaluation_id="discovery-eval-2", request_id="discovery-request-2"
        ),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
    )
    store = SupplierDiscoveryStore(engine)
    store.start_run(start("run-collision"))
    other = start("run-collision").model_copy(
        update={"policy_evaluation_id": "discovery-eval-2"}
    )

    with pytest.raises(DiscoveryRunIdentityConflict, match="discovery_run_id"):
        store.start_run(other)

    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(supplier_discovery_run)
        ) == 1
