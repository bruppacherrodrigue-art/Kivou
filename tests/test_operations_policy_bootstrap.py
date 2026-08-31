from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa

from signals.operations.policy_bootstrap import (
    PolicyBootstrapError,
    bootstrap_policy_control,
)
from signals.persistence.schema import METADATA, acquisition_policy_snapshot
from signals.policy.contracts import AutonomyMode
from signals.policy.store import PolicyStore

NOW = dt.datetime(2026, 8, 31, 12, tzinfo=dt.UTC)


def _engine(tmp_path) -> sa.Engine:
    engine = sa.create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'policy.sqlite'}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    METADATA.create_all(engine, tables=[acquisition_policy_snapshot])
    return engine


def _bootstrap(engine):
    return bootstrap_policy_control(
        engine,
        at=NOW,
        actor_ref="operator:rodrigue",
        reason_code="ACQUISITION_PRODUCTION_SHADOW",
        daily_cost_cap=Decimal("30.00"),
        country="FR",
        language="fr",
        wedge="construction",
    )


def test_the_first_control_is_a_non_executable_shadow_authority(tmp_path) -> None:
    control = _bootstrap(_engine(tmp_path))
    assert control.control_revision == 1
    assert control.autonomy_mode is AutonomyMode.SHADOW
    assert control.shadow_target_mode is AutonomyMode.ASSISTED
    assert control.read_only is True
    assert control.kill_switch is True
    assert control.daily_volume_cap == 0
    assert control.currency == "CHF"
    assert control.daily_cost_cap == Decimal("30.00")
    assert control.created_by_actor_type == "HUMAN"


def test_the_scope_is_exact_so_a_cycle_can_compose(tmp_path) -> None:
    control = _bootstrap(_engine(tmp_path))
    assert control.allowed_countries == ("FR",)
    assert control.allowed_languages == ("fr",)
    assert control.allowed_wedges == ("construction",)
    assert control.allowed_commands != ()


def test_the_control_becomes_the_effective_one(tmp_path) -> None:
    engine = _engine(tmp_path)
    _bootstrap(engine)
    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1


def test_bootstrapping_twice_is_refused(tmp_path) -> None:
    engine = _engine(tmp_path)
    _bootstrap(engine)
    with pytest.raises(PolicyBootstrapError, match="CONTROL_ALREADY_EXISTS"):
        _bootstrap(engine)


def test_a_naive_timestamp_is_refused(tmp_path) -> None:
    with pytest.raises(PolicyBootstrapError, match="TIMESTAMP_NOT_AWARE"):
        bootstrap_policy_control(
            _engine(tmp_path),
            at=dt.datetime(2026, 8, 31, 12),  # noqa: DTZ001
            actor_ref="operator:rodrigue",
            reason_code="ACQUISITION_PRODUCTION_SHADOW",
            daily_cost_cap=Decimal("30.00"),
            country="FR",
            language="fr",
            wedge="construction",
        )
