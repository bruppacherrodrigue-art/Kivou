"""Cadence humaine et circuit-breaker persistant par hébergeur."""

from __future__ import annotations

import datetime as dt
import re
import time
from collections.abc import Callable
from urllib.parse import urlparse

import sqlalchemy as sa

from signals.documents.portals.base import PortalDownloadResult
from signals.persistence.schema import portal_capture_runtime

_HTTP_ERROR = re.compile(r"^HTTP ([45][0-9]{2})$")


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.UTC)


class PortalDiscipline:
    def __init__(
        self,
        engine: sa.Engine,
        *,
        min_interval_seconds: float = 20.0,
        block_after: int = 3,
        block_for: dt.timedelta = dt.timedelta(hours=24),
        clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.engine = engine
        self.min_interval_seconds = max(20.0, min_interval_seconds)
        self.block_after = block_after
        self.block_for = block_for
        self.clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self.sleep = sleep

    @staticmethod
    def _host(url: str) -> str:
        return (urlparse(url).hostname or "").casefold()

    def acquire(self, url: str) -> PortalDownloadResult | None:
        host = self._host(url)
        now = self.clock()
        with self.engine.begin() as connection:
            row = connection.execute(
                sa.select(portal_capture_runtime).where(
                    portal_capture_runtime.c.host == host
                )
            ).one_or_none()
            if row is not None:
                blocked_until = _aware(row.blocked_until)
                if blocked_until is not None and blocked_until > now:
                    return PortalDownloadResult(
                        "portal_blocked", detail="host_circuit_open"
                    )
                last_request = _aware(row.last_request_at)
                if last_request is not None:
                    remaining = self.min_interval_seconds - (
                        now - last_request
                    ).total_seconds()
                    if remaining > 0:
                        self.sleep(remaining)
                        now = self.clock()
                connection.execute(
                    sa.update(portal_capture_runtime)
                    .where(portal_capture_runtime.c.host == host)
                    .values(last_request_at=now, updated_at=now)
                )
            else:
                connection.execute(
                    sa.insert(portal_capture_runtime).values(
                        host=host,
                        consecutive_errors=0,
                        last_request_at=now,
                        blocked_until=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
        return None

    def record(self, url: str, result: PortalDownloadResult) -> None:
        host = self._host(url)
        now = self.clock()
        backoff = None
        with self.engine.begin() as connection:
            row = connection.execute(
                sa.select(portal_capture_runtime).where(
                    portal_capture_runtime.c.host == host
                )
            ).one_or_none()
            if row is None:
                connection.execute(
                    sa.insert(portal_capture_runtime).values(
                        host=host,
                        consecutive_errors=0,
                        last_request_at=None,
                        blocked_until=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                errors = 0
            else:
                errors = int(row.consecutive_errors)
            if result.access_status == "available":
                connection.execute(
                    sa.update(portal_capture_runtime)
                    .where(portal_capture_runtime.c.host == host)
                    .values(consecutive_errors=0, blocked_until=None, updated_at=now)
                )
            elif result.detail and _HTTP_ERROR.match(result.detail):
                errors += 1
                backoff = self.min_interval_seconds * (2 ** (errors - 1))
                blocked_until = (
                    now + dt.timedelta(seconds=backoff) + self.block_for
                    if errors >= self.block_after
                    else None
                )
                connection.execute(
                    sa.update(portal_capture_runtime)
                    .where(portal_capture_runtime.c.host == host)
                    .values(
                        consecutive_errors=errors,
                        blocked_until=blocked_until,
                        updated_at=now,
                    )
                )
        if backoff is not None:
            self.sleep(backoff)
