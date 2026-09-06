from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from signals.feed.object_backfill import backfill


class _Connection:
    def __init__(self) -> None:
        self.updates = []

    def execute(self, statement):
        if statement.is_update:
            self.updates.append(statement)
            return None
        return [
            SimpleNamespace(signal_key="signal-empty", title=None, cpv_main=None),
            SimpleNamespace(signal_key="signal-cpv", title=None, cpv_main="45214200"),
        ]


class _Begin:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_):
        return False


class _Engine:
    def __init__(self, connection):
        self.connection = connection

    def begin(self):
        return _Begin(self.connection)


def test_missing_objects_are_invalidated_and_cpv_labels_are_retained():
    now = dt.datetime(2026, 9, 6, tzinfo=dt.UTC)
    connection = _Connection()

    report = backfill(_Engine(connection), now=now)

    assert report == {"dematerialized": 1, "cpv_fallback": 1}
    assert len(connection.updates) == 1
    assert connection.updates[0]._values
