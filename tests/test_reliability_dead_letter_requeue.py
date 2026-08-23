from __future__ import annotations

import datetime as dt

import pytest
from alembic import command

from signals.operations.contracts import (
    BreakerScope,
    DeadLetterExhaustion,
    DeadLetterStatus,
    WorkType,
)
from signals.operations.dead_letter import (
    DeadLetterRequeueBlocked,
    DeadLetterRequeueService,
)
from signals.operations.store import OperationsStore
from signals.persistence.database import alembic_config, create_database_engine

NOW = dt.datetime(2026, 8, 23, 12, tzinfo=dt.UTC)


class Guard:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.refs: list[str] = []

    def require_requeue_allowed(self, row, *, at) -> None:
        self.refs.append(row["dead_letter_ref"])
        if not self.allowed:
            raise DeadLetterRequeueBlocked("current safety state blocks requeue")


class Handler:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.refs: list[str] = []

    def requeue(self, row, *, at) -> bool:
        self.refs.append(row["source_state_ref"])
        return self.accepted


def _context(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'dlq.db'}")
    command.upgrade(alembic_config(engine), "head")
    store = OperationsStore(engine)
    result = store.enqueue_dead_letter(
        DeadLetterExhaustion(
            work_type=WorkType.RESPONSE_RESOLUTION,
            work_ref="response-work-ref",
            scope=BreakerScope(scope_type="CAMPAIGN", scope_ref="campaign-ref"),
            attempt_count=3,
            first_failed_at=NOW - dt.timedelta(minutes=10),
            last_failed_at=NOW,
            failure_code="RESPONSE_CONTENT_UNAVAILABLE",
            retry_policy_version="response-email-resolution-v1",
            source_component="responses",
            source_state_ref="response-evaluation-ref",
        ),
        created_at=NOW,
    )
    return store, result.row["dead_letter_ref"]


def test_explicit_requeue_reconstructs_from_refs_and_rechecks_safety(tmp_path) -> None:
    store, ref = _context(tmp_path)
    guard = Guard()
    handler = Handler()
    service = DeadLetterRequeueService(
        store,
        guard=guard,
        handlers={WorkType.RESPONSE_RESOLUTION: handler},
    )

    result = service.requeue(ref, at=NOW + dt.timedelta(minutes=1))

    assert result["status"] == DeadLetterStatus.REQUEUED
    assert guard.refs == [ref]
    assert handler.refs == ["response-evaluation-ref"]
    assert "payload" not in result
    assert "body" not in result


def test_requeue_fails_closed_for_safety_staleness_or_missing_handler(tmp_path) -> None:
    store, ref = _context(tmp_path)
    blocked = DeadLetterRequeueService(
        store,
        guard=Guard(allowed=False),
        handlers={WorkType.RESPONSE_RESOLUTION: Handler()},
    )
    with pytest.raises(DeadLetterRequeueBlocked):
        blocked.requeue(ref, at=NOW)
    assert store.get_dead_letter(ref)["status"] == DeadLetterStatus.OPEN

    stale = DeadLetterRequeueService(
        store,
        guard=Guard(),
        handlers={WorkType.RESPONSE_RESOLUTION: Handler(accepted=False)},
    )
    with pytest.raises(DeadLetterRequeueBlocked, match="stale"):
        stale.requeue(ref, at=NOW)
    assert store.get_dead_letter(ref)["status"] == DeadLetterStatus.OPEN

    missing = DeadLetterRequeueService(store, guard=Guard(), handlers={})
    with pytest.raises(DeadLetterRequeueBlocked, match="handler"):
        missing.requeue(ref, at=NOW)


def test_requeue_is_idempotent_and_history_is_not_deleted(tmp_path) -> None:
    store, ref = _context(tmp_path)
    handler = Handler()
    service = DeadLetterRequeueService(
        store,
        guard=Guard(),
        handlers={WorkType.RESPONSE_RESOLUTION: handler},
    )
    first = service.requeue(ref, at=NOW)
    replay = service.requeue(ref, at=NOW + dt.timedelta(minutes=1))

    assert first["dead_letter_ref"] == replay["dead_letter_ref"] == ref
    assert handler.refs == ["response-evaluation-ref"]
    store.resolve_dead_letter(ref, at=NOW + dt.timedelta(minutes=2))
    assert store.get_dead_letter(ref)["status"] == DeadLetterStatus.RESOLVED
