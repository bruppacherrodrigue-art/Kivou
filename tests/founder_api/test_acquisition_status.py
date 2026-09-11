from __future__ import annotations

import datetime as dt
import subprocess
from collections.abc import Callable
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from signals.founder_api.acquisition_status import (
    ACQUISITION_TIMER_UNIT,
    FounderAcquisitionActivity,
    FounderAcquisitionStatusReadService,
    SystemdAcquisitionActivityReader,
)
from signals.persistence.schema import (
    METADATA,
    acquisition_runtime_cycle,
    acquisition_runtime_observation,
)

NOW = dt.datetime(2026, 9, 11, 8, tzinfo=dt.UTC)


@pytest.fixture
def engine() -> sa.Engine:
    value = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    METADATA.create_all(
        value,
        tables=[acquisition_runtime_cycle, acquisition_runtime_observation],
    )
    return value


def _cycle_values(
    cycle_ref: str,
    *,
    reason_code: str,
    updated_at: dt.datetime,
) -> dict[str, object]:
    return {
        "cycle_ref": cycle_ref,
        "opportunity_key": f"opportunity-{cycle_ref}",
        "config_fingerprint": cycle_ref.ljust(64, "f"),
        "status": "SUPPRESSED",
        "next_stage": None,
        "spent_cost": Decimal("0"),
        "last_reason_code": reason_code,
        "started_at": updated_at - dt.timedelta(minutes=5),
        "updated_at": updated_at,
        "completed_at": updated_at,
    }


def _observation_values(
    *,
    environment: str = "PRODUCTION",
    mode: str = "SHADOW",
    last_cycle_ref: str | None = None,
    last_cycle_status: str | None = None,
    last_cycle_at: dt.datetime | None = None,
) -> dict[str, object]:
    return {
        "runtime_name": "acquisition-run-once",
        "capability_fingerprint": "f" * 64,
        "environment": environment,
        "mode": mode,
        "qa_only": environment == "STAGING",
        "hermes_repository": "kivou/hermes",
        "hermes_tag": "v1.0.0",
        "hermes_commit": "a" * 40,
        "hermes_version": "1.0.0",
        "hermes_python_contract": ">=3.11,<3.13",
        "registry_identity": "b" * 64,
        "native_tools": 0,
        "commands": ["signal_seed"],
        "dependencies": [],
        "observed_at": NOW - dt.timedelta(hours=3),
        "heartbeat_at": NOW,
        "last_cycle_ref": last_cycle_ref,
        "last_cycle_status": last_cycle_status,
        "last_cycle_at": last_cycle_at,
        "updated_at": NOW,
    }


def _systemctl_result(
    output: str,
    *,
    returncode: int = 0,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess([], returncode, stdout=output, stderr="")

    return run


def test_status_joins_runtime_observation_cycle_and_running_timer(
    engine: sa.Engine,
) -> None:
    observed_cycle_at = NOW - dt.timedelta(hours=1)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_runtime_cycle),
            [
                _cycle_values(
                    "cycle-1",
                    reason_code="NO_ELIGIBLE_OPPORTUNITY",
                    updated_at=observed_cycle_at,
                ),
                _cycle_values(
                    "cycle-newer",
                    reason_code="UNRELATED_NEWER_CYCLE",
                    updated_at=NOW,
                ),
            ],
        )
        connection.execute(
            sa.insert(acquisition_runtime_observation),
            _observation_values(
                last_cycle_ref="cycle-1",
                last_cycle_status="SUPPRESSED",
                last_cycle_at=observed_cycle_at,
            ),
        )

    status = FounderAcquisitionStatusReadService(
        engine,
        timer_reader=lambda _: FounderAcquisitionActivity(
            activity="RUNNING",
            activity_since=NOW - dt.timedelta(hours=2),
        ),
    ).read(now=NOW)

    assert status.mode == "SHADOW"
    assert status.activity == "RUNNING"
    assert status.activity_since == NOW - dt.timedelta(hours=2)
    assert status.last_cycle_ref == "cycle-1"
    assert status.last_cycle_at == observed_cycle_at
    assert status.last_cycle_status == "SUPPRESSED"
    assert status.last_cycle_reason_code == "NO_ELIGIBLE_OPPORTUNITY"


def test_status_replaces_an_invalid_persisted_cycle_reason(engine: sa.Engine) -> None:
    observed_cycle_at = NOW - dt.timedelta(hours=1)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_runtime_cycle),
            _cycle_values(
                "cycle-invalid-reason",
                reason_code="secret value",
                updated_at=observed_cycle_at,
            ),
        )
        connection.execute(
            sa.insert(acquisition_runtime_observation),
            _observation_values(
                last_cycle_ref="cycle-invalid-reason",
                last_cycle_status="SUPPRESSED",
                last_cycle_at=observed_cycle_at,
            ),
        )

    status = FounderAcquisitionStatusReadService(
        engine,
        timer_reader=lambda _: FounderAcquisitionActivity(activity="STOPPED"),
    ).read(now=NOW)

    assert status.last_cycle_reason_code == "RUNTIME_CYCLE_REASON_INVALID"


def test_status_fails_closed_without_observation_or_stable_systemd_state(
    engine: sa.Engine,
) -> None:
    status = FounderAcquisitionStatusReadService(
        engine,
        timer_reader=lambda _: FounderAcquisitionActivity(activity="UNKNOWN"),
    ).read(now=NOW)

    assert status.mode is None
    assert status.activity == "UNKNOWN"
    assert status.activity_since is None
    assert status.last_cycle_ref is None
    assert status.last_cycle_at is None
    assert status.last_cycle_status is None
    assert status.last_cycle_reason_code is None


def test_status_ignores_a_non_production_runtime_observation(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_runtime_observation),
            _observation_values(environment="STAGING"),
        )

    status = FounderAcquisitionStatusReadService(
        engine,
        timer_reader=lambda _: FounderAcquisitionActivity(activity="STOPPED"),
    ).read(now=NOW)

    assert status.mode is None
    assert status.last_cycle_ref is None


def test_systemd_reader_uses_active_and_inactive_enter_timestamps() -> None:
    running = SystemdAcquisitionActivityReader(
        run=_systemctl_result(
            "LoadState=loaded\n"
            "ActiveState=active\n"
            "ActiveEnterTimestamp=Fri 2026-09-11 06:00:00 UTC\n"
            "InactiveEnterTimestamp=Thu 2026-09-10 07:48:16 UTC\n"
            "LastTriggerUSec=Fri 2026-09-11 05:55:00 UTC\n"
        )
    )(NOW)
    stopped = SystemdAcquisitionActivityReader(
        run=_systemctl_result(
            "LoadState=loaded\n"
            "ActiveState=inactive\n"
            "ActiveEnterTimestamp=Thu 2026-09-10 06:00:00 UTC\n"
            "InactiveEnterTimestamp=Thu 2026-09-10 07:48:16 UTC\n"
            "LastTriggerUSec=Thu 2026-09-10 07:34:23 UTC\n"
        )
    )(NOW)

    assert running.activity == "RUNNING"
    assert running.activity_since == dt.datetime(2026, 9, 11, 6, tzinfo=dt.UTC)
    assert stopped.activity == "STOPPED"
    assert stopped.activity_since == dt.datetime(2026, 9, 10, 7, 48, 16, tzinfo=dt.UTC)


def test_systemd_reader_parses_the_numeric_timestamp_without_weekday_locale() -> None:
    activity = SystemdAcquisitionActivityReader(
        run=_systemctl_result(
            "LoadState=loaded\n"
            "ActiveState=active\n"
            "ActiveEnterTimestamp=Jour 2026-09-11 06:00:00 UTC\n"
        )
    )(NOW)

    assert activity.activity == "RUNNING"
    assert activity.activity_since == dt.datetime(2026, 9, 11, 6, tzinfo=dt.UTC)


def test_systemd_reader_bounds_the_command_properties_environment_and_timeout() -> None:
    call: dict[str, object] = {}

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        call["args"] = args
        call["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            [],
            0,
            stdout="LoadState=loaded\nActiveState=inactive\nInactiveEnterTimestamp=n/a\n",
            stderr="",
        )

    SystemdAcquisitionActivityReader(run=run)(NOW)

    args = call["args"]
    kwargs = call["kwargs"]
    assert isinstance(args, tuple)
    assert isinstance(args[0], tuple)
    assert args[0][:4] == ("systemctl", "show", ACQUISITION_TIMER_UNIT, "--no-pager")
    assert set(args[0][4:]) == {
        "--property=LoadState",
        "--property=ActiveState",
        "--property=ActiveEnterTimestamp",
        "--property=InactiveEnterTimestamp",
    }
    assert "--property=LastTriggerUSec" not in args[0]
    assert isinstance(kwargs, dict)
    assert kwargs["timeout"] == 2
    assert kwargs["env"]["LANG"] == "C"  # type: ignore[index]
    assert kwargs["env"]["LC_ALL"] == "C"  # type: ignore[index]
    assert kwargs["env"]["TZ"] == "UTC"  # type: ignore[index]


@pytest.mark.parametrize("active_state", ("failed", "activating", "deactivating"))
def test_systemd_reader_fails_closed_for_failed_or_transitional_states(
    active_state: str,
) -> None:
    activity = SystemdAcquisitionActivityReader(
        run=_systemctl_result(
            f"LoadState=loaded\nActiveState={active_state}\n"
            "ActiveEnterTimestamp=Fri 2026-09-11 06:00:00 UTC\n"
            "InactiveEnterTimestamp=Thu 2026-09-10 07:48:16 UTC\n"
        )
    )(NOW)

    assert activity.activity == "UNKNOWN"
    assert activity.activity_since is None


@pytest.mark.parametrize(
    "error",
    (OSError("systemd unavailable"), subprocess.TimeoutExpired("systemctl", timeout=2)),
)
def test_systemd_reader_fails_closed_on_command_errors(error: Exception) -> None:
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        raise error

    activity = SystemdAcquisitionActivityReader(run=run)(NOW)

    assert activity.activity == "UNKNOWN"
    assert activity.activity_since is None


def test_systemd_reader_fails_closed_on_unsuccessful_command() -> None:
    activity = SystemdAcquisitionActivityReader(
        run=_systemctl_result("ActiveState=inactive\n", returncode=1)
    )(NOW)

    assert activity.activity == "UNKNOWN"
    assert activity.activity_since is None
