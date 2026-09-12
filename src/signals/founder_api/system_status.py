"""Read-only host observations exposed by the Founder System page."""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, field_validator

from signals.founder_api.acquisition_status import FounderAcquisitionStatus
from signals.founder_api.contracts import FounderContract
from signals.operations.contracts import AcquisitionOperationalHealth, AutonomousReadiness

FOUNDER_SYSTEM_VERSION = "founder-system-v1"
DEFAULT_TIMER_UNITS = (
    "kivou-ingest-simap.timer",
    "kivou-ingest-boamp.timer",
    "kivou-ingest-decp.timer",
    "kivou-ingest-ted.timer",
    "kivou-tender-notices.timer",
    "kivou-alerts.timer",
    "kivou-account-purge.timer",
    "kivou-for-you.timer",
    "kivou-backup.timer",
    "kivou-disk-alert.timer",
    "kivou-disk-maintenance.timer",
    "kivou-acquisition-production.timer",
)
_TIMER_PROPERTIES = (
    "Id",
    "LoadState",
    "ActiveState",
    "LastTriggerUSec",
    "NextElapseUSecRealtime",
)
_BACKUP_PROPERTIES = (
    "Id",
    "LoadState",
    "ActiveState",
    "Result",
    "ExecMainExitTimestamp",
)
_RELEASE_SHA = re.compile(r"(?:production|staging)-([0-9a-f]{40})$")

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
HttpProbe = Callable[[str], int | None]


class DiskUsage(Protocol):
    total: int
    used: int
    free: int


DiskUsageReader = Callable[[str | os.PathLike[str]], DiskUsage]


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


class FounderSystemTimer(FounderContract):
    name: str
    state: Literal["active", "inactive", "failed", "absent", "unknown"]
    last_run_at: dt.datetime | None = None
    next_run_at: dt.datetime | None = None

    _times = field_validator("last_run_at", "next_run_at")(
        lambda value: _aware(value) if value is not None else None
    )


class FounderServiceReadiness(FounderContract):
    name: Literal["API", "Founder"]
    status: Literal["ready", "not_ready", "unavailable"]
    http_status: int | None = None
    checked_at: dt.datetime

    _checked_at = field_validator("checked_at")(_aware)


class FounderDiskStatus(FounderContract):
    path: str
    total_bytes: int = Field(ge=0)
    used_bytes: int = Field(ge=0)
    available_bytes: int = Field(ge=0)
    used_percent: Decimal = Field(ge=0, le=100)


class FounderBackupStatus(FounderContract):
    kind: Literal["local", "offsite"]
    status: Literal["success", "failed", "unavailable"]
    last_success_at: dt.datetime | None = None

    _last_success_at = field_validator("last_success_at")(
        lambda value: _aware(value) if value is not None else None
    )


class FounderSystemHostSnapshot(FounderContract):
    timers: tuple[FounderSystemTimer, ...]
    readiness: tuple[FounderServiceReadiness, ...]
    disk: FounderDiskStatus | None
    backups: tuple[FounderBackupStatus, ...]
    deployed_sha: str | None = None


class FounderProviderCost(FounderContract):
    provider: Literal["OpenRouter", "Serper", "Apollo", "Instantly"]
    unit: Literal["USD", "request", "credit"]
    today: Decimal = Field(ge=0)
    month: Decimal = Field(ge=0)


class FounderSystemPage(FounderContract):
    version: Literal["founder-system-v1"] = FOUNDER_SYSTEM_VERSION
    generated_at: dt.datetime
    read_only: Literal[True] = True
    database_access: Literal["READ_ONLY"] = "READ_ONLY"
    acquisition_status: FounderAcquisitionStatus
    health: AcquisitionOperationalHealth
    readiness: AutonomousReadiness
    timers: tuple[FounderSystemTimer, ...]
    readiness_checks: tuple[FounderServiceReadiness, ...]
    disk: FounderDiskStatus | None
    backups: tuple[FounderBackupStatus, ...]
    provider_costs: tuple[FounderProviderCost, ...]
    deployed_sha: str | None = None

    _generated_at = field_validator("generated_at")(_aware)


class FounderSystemHostReader:
    """Read bounded local host state without mutating units or calling providers."""

    def __init__(
        self,
        *,
        run: CommandRunner = subprocess.run,
        http_probe: HttpProbe | None = None,
        disk_usage: DiskUsageReader = shutil.disk_usage,
        disk_path: str | os.PathLike[str] = "/srv/kivou",
        app_link: str | os.PathLike[str] = "/srv/kivou/app",
        local_backup_marker: str | os.PathLike[str] = (
            "/srv/kivou/backups/.kivou-backup-local.last-success"
        ),
        offsite_backup_marker: str | os.PathLike[str] = (
            "/srv/kivou/backups/.kivou-backup-offsite.last-success"
        ),
        timer_units: tuple[str, ...] = DEFAULT_TIMER_UNITS,
    ) -> None:
        self._run = run
        self._http_probe = http_probe or _http_probe
        self._disk_usage = disk_usage
        self._disk_path = Path(disk_path)
        self._app_link = Path(app_link)
        self._local_backup_marker = Path(local_backup_marker)
        self._offsite_backup_marker = Path(offsite_backup_marker)
        self._timer_units = timer_units

    def __call__(self, now: dt.datetime) -> FounderSystemHostSnapshot:
        now = _aware(now)
        return FounderSystemHostSnapshot(
            timers=self._timers(),
            readiness=self._readiness(now),
            disk=self._disk(),
            backups=self._backups(),
            deployed_sha=self._deployed_sha(),
        )

    def _show(self, units: tuple[str, ...], properties: tuple[str, ...]) -> str:
        try:
            completed = self._run(
                (
                    "systemctl",
                    "show",
                    *units,
                    "--no-pager",
                    *(f"--property={key}" for key in properties),
                ),
                capture_output=True,
                check=False,
                text=True,
                timeout=3,
                env={**os.environ, "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return completed.stdout

    def _timers(self) -> tuple[FounderSystemTimer, ...]:
        records = _systemd_records(self._show(self._timer_units, _TIMER_PROPERTIES))
        by_id = {record.get("Id", ""): record for record in records}
        timers: list[FounderSystemTimer] = []
        for unit in self._timer_units:
            record = by_id.get(unit, {})
            load_state = record.get("LoadState")
            active_state = record.get("ActiveState")
            if load_state == "not-found":
                state = "absent"
            elif load_state != "loaded":
                state = "unknown"
            elif active_state == "active":
                state = "active"
            elif active_state == "failed":
                state = "failed"
            elif active_state == "inactive":
                state = "inactive"
            else:
                state = "unknown"
            timers.append(
                FounderSystemTimer(
                    name=unit,
                    state=state,
                    last_run_at=_systemd_time(record.get("LastTriggerUSec")),
                    next_run_at=_systemd_time(record.get("NextElapseUSecRealtime")),
                )
            )
        return tuple(timers)

    def _readiness(self, now: dt.datetime) -> tuple[FounderServiceReadiness, ...]:
        checks = (
            ("API", "http://127.0.0.1:8000/openapi.json"),
            ("Founder", "http://127.0.0.1:8011/healthz"),
        )
        values: list[FounderServiceReadiness] = []
        for name, url in checks:
            try:
                http_status = self._http_probe(url)
            except (OSError, ValueError):
                http_status = None
            status = (
                "unavailable"
                if http_status is None
                else "ready"
                if 200 <= http_status < 300
                else "not_ready"
            )
            values.append(
                FounderServiceReadiness(
                    name=name,
                    status=status,
                    http_status=http_status,
                    checked_at=now,
                )
            )
        return tuple(values)

    def _disk(self) -> FounderDiskStatus | None:
        try:
            usage = self._disk_usage(self._disk_path)
            total = int(usage.total)
            used = int(usage.used)
            available = int(usage.free)
        except (AttributeError, OSError, TypeError, ValueError):
            return None
        used_percent = (
            (Decimal(used) * Decimal(100) / Decimal(total)).quantize(Decimal("0.1"))
            if total
            else Decimal(0)
        )
        return FounderDiskStatus(
            path=str(self._disk_path),
            total_bytes=total,
            used_bytes=used,
            available_bytes=available,
            used_percent=used_percent,
        )

    def _backups(self) -> tuple[FounderBackupStatus, ...]:
        markers = (
            ("local", self._local_backup_marker, "kivou-backup-local.service"),
            ("offsite", self._offsite_backup_marker, "kivou-backup.service"),
        )
        missing_units = tuple(unit for _, marker, unit in markers if not marker.is_file())
        records = (
            _systemd_records(self._show(missing_units, _BACKUP_PROPERTIES)) if missing_units else ()
        )
        by_id = {record.get("Id", ""): record for record in records}
        result: list[FounderBackupStatus] = []
        for kind, marker, unit in markers:
            marker_time = _marker_time(marker)
            if marker_time is not None:
                result.append(
                    FounderBackupStatus(kind=kind, status="success", last_success_at=marker_time)
                )
                continue
            record = by_id.get(unit, {})
            successful = record.get("Result") == "success"
            result.append(
                FounderBackupStatus(
                    kind=kind,
                    status=(
                        "success"
                        if successful
                        else "failed"
                        if record.get("LoadState") == "loaded"
                        else "unavailable"
                    ),
                    last_success_at=(
                        _systemd_time(record.get("ExecMainExitTimestamp")) if successful else None
                    ),
                )
            )
        return tuple(result)

    def _deployed_sha(self) -> str | None:
        try:
            target = self._app_link.resolve(strict=True)
        except OSError:
            return None
        matched = _RELEASE_SHA.search(target.name)
        return matched.group(1) if matched else None


def _http_probe(url: str) -> int | None:
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)
    except (OSError, ValueError):
        return None


def _systemd_records(output: str) -> tuple[dict[str, str], ...]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in (*output.splitlines(), ""):
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            current[key] = value
    return tuple(records)


def _systemd_time(value: str | None) -> dt.datetime | None:
    if not value or value == "n/a":
        return None
    parts = value.split()
    if len(parts) == 4:
        parts = parts[1:]
    try:
        return dt.datetime.strptime(" ".join(parts), "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def _marker_time(path: Path) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
    except OSError:
        return None


__all__ = [
    "DEFAULT_TIMER_UNITS",
    "FOUNDER_SYSTEM_VERSION",
    "FounderBackupStatus",
    "FounderDiskStatus",
    "FounderProviderCost",
    "FounderServiceReadiness",
    "FounderSystemHostReader",
    "FounderSystemHostSnapshot",
    "FounderSystemPage",
    "FounderSystemTimer",
]
