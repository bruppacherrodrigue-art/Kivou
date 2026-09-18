"""Bounded Founder trigger for one assisted acquisition runtime cycle."""

from __future__ import annotations

import datetime as dt
import fcntl
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.persistence.schema import prospect_target
from signals.prospection_actions.preparation import DAILY_PENDING_CAP


class WaitableProcess(Protocol):
    def wait(self) -> int: ...


PopenFactory = Callable[..., WaitableProcess]


@dataclass(frozen=True)
class FounderAcquisitionLaunch:
    accepted: bool
    prepared_today_count: int
    daily_pending_cap: int = DAILY_PENDING_CAP


class FounderAcquisitionLaunchError(RuntimeError):
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class FounderAcquisitionLauncher:
    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
        lock_path: Path = Path("/run/kivou/acquisition.lock"),
        disabled_path: Path = Path("/etc/kivou/acquisition.disabled"),
        command: Sequence[str] | None = None,
        popen: PopenFactory = subprocess.Popen,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._lock_path = lock_path
        self._disabled_path = disabled_path
        self._command = tuple(
            command
            or (
                sys.executable,
                "-m",
                "signals.acquisition_runtime",
                "prepare-queue",
            )
        )
        self._popen = popen

    def prepare(self) -> FounderAcquisitionLaunch:
        prepared = self._active_queue_count()
        if prepared >= DAILY_PENDING_CAP:
            raise FounderAcquisitionLaunchError(
                status_code=429,
                code="DAILY_PENDING_CAP_REACHED",
                message="La file du jour a atteint son plafond de 25 cibles.",
            )
        if self._disabled_path.exists():
            raise FounderAcquisitionLaunchError(
                status_code=423,
                code="ACQUISITION_DISABLED",
                message="La préparation est suspendue par le coupe-circuit.",
            )

        lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise FounderAcquisitionLaunchError(
                    status_code=409,
                    code="ACQUISITION_ALREADY_RUNNING",
                    message="Une préparation est déjà en cours.",
                ) from error
            try:
                process = self._popen(
                    self._command,
                    pass_fds=(lock_fd,),
                    close_fds=True,
                    start_new_session=True,
                )
            except OSError as error:
                raise FounderAcquisitionLaunchError(
                    status_code=503,
                    code="ACQUISITION_START_UNAVAILABLE",
                    message="La préparation ne peut pas démarrer pour le moment.",
                ) from error
            threading.Thread(target=process.wait, daemon=True).start()
        finally:
            os.close(lock_fd)
        return FounderAcquisitionLaunch(
            accepted=True,
            prepared_today_count=prepared,
        )

    def _active_queue_count(self) -> int:
        with self._engine.connect() as connection:
            return int(
                connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(prospect_target)
                    .where(
                        prospect_target.c.status.in_(("pending_review", "approved")),
                    )
                )
                or 0
            )


__all__ = [
    "FounderAcquisitionLaunch",
    "FounderAcquisitionLaunchError",
    "FounderAcquisitionLauncher",
]
