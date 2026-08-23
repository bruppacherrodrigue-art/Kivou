"""Explicit, typed DLQ requeue boundary; no arbitrary payload replay."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Protocol

from sqlalchemy.engine import RowMapping

from signals.operations.circuit_breakers import (
    AcquisitionCircuitOpen,
    AcquisitionExecutionGuard,
)
from signals.operations.contracts import BreakerScope, DeadLetterStatus, WorkType
from signals.operations.store import OperationsStore
from signals.policy.contracts import PolicyControlUnavailable
from signals.policy.store import PolicyStore


class DeadLetterRequeueBlocked(RuntimeError):
    pass


class DeadLetterRequeueGuard(Protocol):
    def require_requeue_allowed(self, row: RowMapping, *, at: dt.datetime) -> None: ...


class DeadLetterHandler(Protocol):
    def requeue(self, row: RowMapping, *, at: dt.datetime) -> bool: ...


class PolicyCircuitRequeueGuard:
    """Current controls are mandatory before a component reconstructs work."""

    def __init__(self, store: OperationsStore) -> None:
        self._policy = PolicyStore(store.engine)
        self._circuits = AcquisitionExecutionGuard(store)

    def require_requeue_allowed(self, row: RowMapping, *, at: dt.datetime) -> None:
        try:
            control = self._policy.get_effective_control(at)
        except PolicyControlUnavailable as exc:
            raise DeadLetterRequeueBlocked("Policy control unavailable") from exc
        if control.kill_switch or control.read_only:
            raise DeadLetterRequeueBlocked("hard safety control blocks requeue")
        try:
            self._circuits.require_allowed(
                BreakerScope(scope_type=row["scope_type"], scope_ref=row["scope_ref"])
            )
        except AcquisitionCircuitOpen as exc:
            raise DeadLetterRequeueBlocked("execution circuit blocks requeue") from exc


class DeadLetterRequeueService:
    def __init__(
        self,
        store: OperationsStore,
        *,
        guard: DeadLetterRequeueGuard,
        handlers: Mapping[WorkType, DeadLetterHandler],
    ) -> None:
        self._store = store
        self._guard = guard
        self._handlers = dict(handlers)

    def requeue(self, dead_letter_ref: str, *, at: dt.datetime) -> RowMapping:
        row = self._store.get_dead_letter(dead_letter_ref)
        if row["status"] == DeadLetterStatus.REQUEUED.value:
            return row
        if row["status"] == DeadLetterStatus.RESOLVED.value:
            raise DeadLetterRequeueBlocked("resolved dead letter cannot be requeued")
        self._guard.require_requeue_allowed(row, at=at)
        work_type = WorkType(row["work_type"])
        handler = self._handlers.get(work_type)
        if handler is None:
            raise DeadLetterRequeueBlocked("typed requeue handler is unconfigured")
        if not handler.requeue(row, at=at):
            raise DeadLetterRequeueBlocked("durable work is stale or cannot be reconstructed")
        return self._store.mark_dead_letter_requeued(dead_letter_ref, at=at)


__all__ = [
    "DeadLetterRequeueBlocked",
    "DeadLetterRequeueService",
    "PolicyCircuitRequeueGuard",
]
