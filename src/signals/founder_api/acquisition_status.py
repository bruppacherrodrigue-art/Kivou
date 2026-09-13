"""Single acquisition-status projection for the Founder Console."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
from collections.abc import Callable, Mapping
from typing import Literal

import sqlalchemy as sa
from pydantic import Field, field_validator
from sqlalchemy.engine import Engine

from signals.acquisition_runtime.store import (
    RUNTIME_OBSERVATION_NAME,
    AcquisitionRuntimeStore,
)
from signals.founder_api.contracts import FounderContract
from signals.persistence.schema import acquisition_runtime_observation, prospect_target
from signals.prospection_actions.day import prospection_day_bounds
from signals.prospection_actions.preparation import DAILY_PENDING_CAP

ACQUISITION_SERVICE_UNIT = "kivou-acquisition-production.service"
ACQUISITION_TIMER_UNIT = "kivou-acquisition-production.timer"


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


class FounderAcquisitionActivity(FounderContract):
    activity: Literal["RUNNING", "STOPPED", "UNKNOWN"]
    activity_since: dt.datetime | None = None
    next_run_at: dt.datetime | None = None

    _activity_times = field_validator("activity_since", "next_run_at")(
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
    prepared_today_count: int = Field(default=0, ge=0, le=DAILY_PENDING_CAP)
    daily_pending_cap: int = Field(default=DAILY_PENDING_CAP, ge=DAILY_PENDING_CAP, le=DAILY_PENDING_CAP)
    next_run_at: dt.datetime | None = None

    _times = field_validator("activity_since", "last_cycle_at", "next_run_at")(
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
        "ExecMainStartTimestamp",
        "NextElapseUSecRealtime",
        "Id",
    )

    def __init__(self, *, run: CommandRunner = subprocess.run) -> None:
        self._run = run

    def __call__(self, _: dt.datetime) -> FounderAcquisitionActivity:
        try:
            completed = self._run(
                (
                    "systemctl",
                    "show",
                    ACQUISITION_SERVICE_UNIT,
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
        records = _systemd_records(
            completed.stdout,
            allowed=frozenset(self._PROPERTIES),
        )
        service = records.get(ACQUISITION_SERVICE_UNIT)
        timer = records.get(ACQUISITION_TIMER_UNIT, {})
        if service is None and len(records) == 1:
            service = next(iter(records.values()))
        if completed.returncode != 0 or service is None or service.get("LoadState") != "loaded":
            return FounderAcquisitionActivity(activity="UNKNOWN")
        next_run_at = (
            _systemd_time(timer.get("NextElapseUSecRealtime"))
            if timer.get("LoadState") == "loaded" and timer.get("ActiveState") == "active"
            else None
        )
        active_state = service.get("ActiveState")
        if active_state in {"active", "activating"}:
            return FounderAcquisitionActivity(
                activity="RUNNING",
                activity_since=_systemd_time(
                    service.get("ExecMainStartTimestamp")
                    or service.get("ActiveEnterTimestamp")
                ),
                next_run_at=next_run_at,
            )
        if active_state == "inactive":
            return FounderAcquisitionActivity(
                activity="STOPPED",
                activity_since=_systemd_time(service.get("InactiveEnterTimestamp")),
                next_run_at=next_run_at,
            )
        return FounderAcquisitionActivity(activity="UNKNOWN", next_run_at=next_run_at)


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
            day_start, day_end = prospection_day_bounds(now)
            prepared_today = int(
                connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(prospect_target)
                    .where(
                        prospect_target.c.created_at >= day_start,
                        prospect_target.c.created_at < day_end,
                    )
                )
                or 0
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
            prepared_today_count=min(prepared_today, DAILY_PENDING_CAP),
        )


def _status_from_rows(
    *,
    activity: FounderAcquisitionActivity,
    observation: Mapping[str, object] | None,
    cycle_reason_code: str | None,
    prepared_today_count: int,
) -> FounderAcquisitionStatus:
    if observation is None:
        return FounderAcquisitionStatus(
            activity=activity.activity,
            activity_since=activity.activity_since,
            prepared_today_count=prepared_today_count,
            next_run_at=activity.next_run_at,
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
        prepared_today_count=prepared_today_count,
        next_run_at=activity.next_run_at,
    )


def _systemd_properties(output: str, *, allowed: frozenset[str]) -> dict[str, str]:
    return {
        key: value
        for line in output.splitlines()
        if "=" in line
        for key, value in (line.split("=", 1),)
        if key in allowed
    }


def _systemd_records(
    output: str,
    *,
    allowed: frozenset[str],
) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}
    anonymous = 0
    for line in (*output.splitlines(), ""):
        if not line:
            if current:
                key = current.get("Id") or f"anonymous-{anonymous}"
                records[key] = current
                current = {}
                anonymous += 1
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in allowed:
            current[key] = value
    return records


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
    "ACQUISITION_SERVICE_UNIT",
    "ACQUISITION_TIMER_UNIT",
    "AcquisitionActivityReader",
    "CommandRunner",
    "FounderAcquisitionActivity",
    "FounderAcquisitionStatus",
    "FounderAcquisitionStatusReadService",
    "SystemdAcquisitionActivityReader",
]
