from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from signals.documents.portals.base import PortalDownloadResult
from signals.documents.portals.discipline import PortalDiscipline
from signals.persistence.schema import portal_capture_runtime


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime(2026, 9, 4, 8, tzinfo=dt.UTC)
        self.sleeps: list[float] = []

    def __call__(self) -> dt.datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += dt.timedelta(seconds=seconds)


def _discipline(clock: Clock) -> PortalDiscipline:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    portal_capture_runtime.create(engine)
    return PortalDiscipline(engine, clock=clock, sleep=clock.sleep)


def test_host_is_limited_to_three_folders_per_minute() -> None:
    clock = Clock()
    discipline = _discipline(clock)

    assert discipline.acquire("https://atexo.example/one") is None
    clock.now += dt.timedelta(seconds=5)
    assert discipline.acquire("https://atexo.example/two") is None

    assert clock.sleeps == [15.0]


def test_every_http_error_backs_off_and_three_open_the_circuit_for_24_hours() -> None:
    clock = Clock()
    discipline = _discipline(clock)
    url = "https://atexo.example/dce"

    for status in (429, 500, 503):
        assert discipline.acquire(url) is None
        discipline.record(url, PortalDownloadResult("download_failed", detail=f"HTTP {status}"))

    blocked = discipline.acquire(url)

    assert clock.sleeps[-3:] == [20.0, 40.0, 80.0]
    assert blocked is not None
    assert (blocked.access_status, blocked.detail) == (
        "portal_blocked",
        "host_circuit_open",
    )
    clock.now += dt.timedelta(hours=24)
    assert discipline.acquire(url) is None


def test_success_resets_consecutive_http_errors() -> None:
    clock = Clock()
    discipline = _discipline(clock)
    url = "https://atexo.example/dce"

    discipline.acquire(url)
    discipline.record(url, PortalDownloadResult("download_failed", detail="HTTP 500"))
    discipline.record(url, PortalDownloadResult("available", content=b"zip"))
    discipline.record(url, PortalDownloadResult("download_failed", detail="HTTP 500"))
    discipline.record(url, PortalDownloadResult("download_failed", detail="HTTP 500"))

    assert discipline.acquire(url) is None
