"""Single acquisition-status projection for the Founder Console."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
from collections.abc import Callable, Mapping
from typing import Literal

import sqlalchemy as sa
from pydantic import field_validator
from sqlalchemy.engine import Engine

from signals.acquisition_runtime.store import (
    RUNTIME_OBSERVATION_NAME,
    AcquisitionRuntimeStore,
)
from signals.founder_api.contracts import FounderContract
from signals.persistence.schema import acquisition_runtime_observation

ACQUISITION_TIMER_UNIT = "kivou-acquisition-production.timer"


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


class FounderAcquisitionActivity(FounderContract):
    activity: Literal["RUNNING", "STOPPED", "UNKNOWN"]
    activity_since: dt.datetime | None = None

    _activity_since = field_validator("activity_since")(
        lambda value: _aware(value) if value is not None else None
    )


class FounderAcquisitionStatus(FounderContract):
    mode: str | None = None
    activity: Literal["RUNNING", "STOPPED", "UNKNOWN"]
    activity_since: dt.datetime | None = None
    last_cycle_ref: str | None = None
    last_cycle_at: dt.datetime | None = None
    last_cycle_status: str | None = None
    last_cycle_reason_code: str | None = None

    _times = field_validator("activity_since", "last_cycle_at")(
        lambda value: _aware(value) if value is not None else None
    )


AcquisitionActivityReader = Callable[[dt.datetime], FounderAcquisitionActivity]
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class SystemdAcquisitionActivityReader:
    _PROPERTIES = (
        "LoadState",
        "ActiveState",
        "ActiveEnterTimestamp",
        "InactiveEnterTimestamp",
    )

    def __init__(self, *, run: CommandRunner = subprocess.run) -> None:
        self._run = run

    def __call__(self, _: dt.datetime) -> FounderAcquisitionActivity:
        try:
            completed = self._run(
                (
                    "systemctl",
                    "show",
                    ACQUISITION_TIMER_UNIT,
                    "--no-pager",
                    *(f"--property={key}" for key in self._PROPERTIES),
                ),
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
                env={**os.environ, "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            )
        except (OSError, subprocess.TimeoutExpired):
            return FounderAcquisitionActivity(activity="UNKNOWN")
        values = _systemd_properties(
            completed.stdout,
            allowed=frozenset(self._PROPERTIES),
        )
        if completed.returncode != 0 or values.get("LoadState") != "loaded":
            return FounderAcquisitionActivity(activity="UNKNOWN")
        active_state = values.get("ActiveState")
        if active_state == "active":
            return FounderAcquisitionActivity(
                activity="RUNNING",
                activity_since=_systemd_time(values.get("ActiveEnterTimestamp")),
            )
        if active_state == "inactive":
            return FounderAcquisitionActivity(
                activity="STOPPED",
                activity_since=_systemd_time(values.get("InactiveEnterTimestamp")),
            )
        return FounderAcquisitionActivity(activity="UNKNOWN")


class FounderAcquisitionStatusReadService:
    def __init__(
        self,
        engine: Engine,
        *,
        timer_reader: AcquisitionActivityReader | None = None,
    ) -> None:
        self._engine = engine
        self._runtime_store = AcquisitionRuntimeStore(engine)
        self._timer_reader = timer_reader or SystemdAcquisitionActivityReader()

    def read(self, *, now: dt.datetime) -> FounderAcquisitionStatus:
        activity = self._timer_reader(_aware(now))
        with self._engine.connect() as connection:
            observation = (
                connection.execute(
                    sa.select(acquisition_runtime_observation).where(
                        acquisition_runtime_observation.c.runtime_name
                        == RUNTIME_OBSERVATION_NAME,
                        acquisition_runtime_observation.c.environment == "PRODUCTION",
                    )
                )
                .mappings()
                .one_or_none()
            )
        cycle_ref = None if observation is None else observation["last_cycle_ref"]
        cycle_reason_code = (
            self._runtime_store.read_cycle_reason_code(str(cycle_ref))
            if cycle_ref is not None
            else None
        )
        return _status_from_rows(
            activity=activity,
            observation=observation,
            cycle_reason_code=cycle_reason_code,
        )


def _status_from_rows(
    *,
    activity: FounderAcquisitionActivity,
    observation: Mapping[str, object] | None,
    cycle_reason_code: str | None,
) -> FounderAcquisitionStatus:
    if observation is None:
        return FounderAcquisitionStatus(
            activity=activity.activity,
            activity_since=activity.activity_since,
        )
    last_cycle_at = observation["last_cycle_at"]
    return FounderAcquisitionStatus(
        mode=str(observation["mode"]),
        activity=activity.activity,
        activity_since=activity.activity_since,
        last_cycle_ref=(
            str(observation["last_cycle_ref"])
            if observation["last_cycle_ref"] is not None
            else None
        ),
        last_cycle_at=(last_cycle_at if isinstance(last_cycle_at, dt.datetime) else None),
        last_cycle_status=(
            str(observation["last_cycle_status"])
            if observation["last_cycle_status"] is not None
            else None
        ),
        last_cycle_reason_code=cycle_reason_code,
    )


def _systemd_properties(output: str, *, allowed: frozenset[str]) -> dict[str, str]:
    return {
        key: value
        for line in output.splitlines()
        if "=" in line
        for key, value in (line.split("=", 1),)
        if key in allowed
    }


def _systemd_time(value: str | None) -> dt.datetime | None:
    if not value or value == "n/a":
        return None
    try:
        _, numeric_time = value.split(maxsplit=1)
        return dt.datetime.strptime(numeric_time, "%Y-%m-%d %H:%M:%S UTC").replace(
            tzinfo=dt.UTC
        )
    except ValueError:
        return None


__all__ = [
    "ACQUISITION_TIMER_UNIT",
    "AcquisitionActivityReader",
    "CommandRunner",
    "FounderAcquisitionActivity",
    "FounderAcquisitionStatus",
    "FounderAcquisitionStatusReadService",
    "SystemdAcquisitionActivityReader",
]
