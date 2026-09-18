"""Single acquisition-status projection for the Founder Console."""

from __future__ import annotations

import datetime as dt
import fcntl
import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

import sqlalchemy as sa
from pydantic import Field, field_validator
from sqlalchemy.engine import Engine

from signals.acquisition_runtime.store import (
    RUNTIME_OBSERVATION_NAME,
    AcquisitionRuntimeStore,
)
from signals.founder_api.contracts import FounderContract
from signals.persistence.schema import (
    acquisition_runtime_cycle,
    acquisition_runtime_observation,
    prospect_target,
)
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

    def __init__(
        self,
        *,
        run: CommandRunner = subprocess.run,
        lock_path: Path = Path("/run/kivou/acquisition.lock"),
    ) -> None:
        self._run = run
        self._lock_path = lock_path

    def __call__(self, now: dt.datetime) -> FounderAcquisitionActivity:
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
        if self._lock_is_held():
            return FounderAcquisitionActivity(
                activity="RUNNING",
                activity_since=now,
                next_run_at=next_run_at,
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

    def _lock_is_held(self) -> bool:
        try:
            lock_fd = os.open(self._lock_path, os.O_RDWR)
        except OSError:
            return False
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            return False
        finally:
            os.close(lock_fd)
        return False


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
            active_queue_count = int(
                connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(prospect_target)
                    .where(
                        prospect_target.c.status.in_(("pending_review", "approved")),
                    )
                )
                or 0
            )
            catalog_cycle = (
                connection.execute(
                    sa.select(acquisition_runtime_cycle)
                    .where(
                        acquisition_runtime_cycle.c.last_reason_code.in_(
                            (
                                "ASSISTED_CATALOG_PENDING_REVIEW",
                                "ASSISTED_CATALOG_EMPTY",
                            )
                        )
                    )
                    .order_by(
                        acquisition_runtime_cycle.c.updated_at.desc(),
                        acquisition_runtime_cycle.c.cycle_ref,
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        visible_catalog_cycle = _newer_catalog_cycle(
            observation=observation,
            catalog_cycle=catalog_cycle,
        )
        cycle_ref = (
            visible_catalog_cycle["cycle_ref"]
            if visible_catalog_cycle is not None
            else None if observation is None else observation["last_cycle_ref"]
        )
        cycle_reason_code = (
            self._runtime_store.read_cycle_reason_code(str(cycle_ref))
            if cycle_ref is not None
            else None
        )
        return _status_from_rows(
            activity=activity,
            observation=observation,
            catalog_cycle=visible_catalog_cycle,
            cycle_reason_code=cycle_reason_code,
            prepared_today_count=min(active_queue_count, DAILY_PENDING_CAP),
        )


def _status_from_rows(
    *,
    activity: FounderAcquisitionActivity,
    observation: Mapping[str, object] | None,
    catalog_cycle: Mapping[str, object] | None,
    cycle_reason_code: str | None,
    prepared_today_count: int,
) -> FounderAcquisitionStatus:
    if observation is None and catalog_cycle is None:
        return FounderAcquisitionStatus(
            activity=activity.activity,
            activity_since=activity.activity_since,
            prepared_today_count=prepared_today_count,
            next_run_at=activity.next_run_at,
        )
    if catalog_cycle is not None:
        last_cycle_ref = catalog_cycle["cycle_ref"]
        last_cycle_status = catalog_cycle["status"]
        last_cycle_at = catalog_cycle["updated_at"]
    else:
        assert observation is not None
        last_cycle_ref = observation["last_cycle_ref"]
        last_cycle_status = observation["last_cycle_status"]
        last_cycle_at = observation["last_cycle_at"]
    return FounderAcquisitionStatus(
        mode="ASSISTED" if observation is None else str(observation["mode"]),
        activity=activity.activity,
        activity_since=activity.activity_since,
        last_cycle_ref=(
            str(last_cycle_ref)
            if last_cycle_ref is not None
            else None
        ),
        last_cycle_at=(last_cycle_at if isinstance(last_cycle_at, dt.datetime) else None),
        last_cycle_status=(
            str(last_cycle_status)
            if last_cycle_status is not None
            else None
        ),
        last_cycle_reason_code=cycle_reason_code,
        prepared_today_count=prepared_today_count,
        next_run_at=activity.next_run_at,
    )


def _newer_catalog_cycle(
    *,
    observation: Mapping[str, object] | None,
    catalog_cycle: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if catalog_cycle is None:
        return None
    updated_at = catalog_cycle.get("updated_at")
    if not isinstance(updated_at, dt.datetime):
        return None
    if observation is None:
        return catalog_cycle
    observed_cycle_at = observation.get("last_cycle_at")
    if not isinstance(observed_cycle_at, dt.datetime):
        return catalog_cycle
    return catalog_cycle if _aware(updated_at) > _aware(observed_cycle_at) else None


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
