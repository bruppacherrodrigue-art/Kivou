"""Account-owned, reversible workflow, separate from historical feedback.

All workflow and legacy interaction writers acquire the same database row lock.
The legacy feedback fallback remains readable while the migration is rolled out.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Callable, Mapping

import sqlalchemy as sa

from signals.billing.service import aware_datetime
from signals.engagement import analytics, feedback
from signals.engagement.feedback import SignalContext, StoredFeedback
from signals.engagement.schema import signal_workflow
from signals.persistence.conflicts import _conflict_insert

UNIFIED_STATUSES = ("new", "saved", "ignored", "contacted")
#: Le filtre par défaut de `GET /signals` : tout sauf `ignored`.
DEFAULT_LISTING_STATUSES = frozenset({"new", "saved", "contacted"})


@dataclasses.dataclass(frozen=True)
class StoredWorkflow:
    account_id: str
    signal_key: str
    status: str
    revision: int
    created_at: dt.datetime
    updated_at: dt.datetime


class StatusConflict(ValueError):
    def __init__(self, current: StoredWorkflow):
        super().__init__("le statut a été modifié depuis sa lecture")
        self.status = current.status
        self.revision = current.revision
        self.updated_at = current.updated_at


def _stored(row) -> StoredWorkflow:
    return StoredWorkflow(
        account_id=row["account_id"],
        signal_key=row["signal_key"],
        status=row["status"],
        revision=row["revision"],
        created_at=aware_datetime(row["created_at"]),
        updated_at=aware_datetime(row["updated_at"]),
    )


def get_workflow(connection, *, account_id: str, signal_key: str) -> StoredWorkflow | None:
    row = (
        connection.execute(
            sa.select(signal_workflow).where(
                signal_workflow.c.account_id == account_id,
                signal_workflow.c.signal_key == signal_key,
            )
        )
        .mappings()
        .first()
    )
    return _stored(row) if row is not None else None


def workflow_by_signal(connection, *, account_id: str) -> dict[str, StoredWorkflow]:
    rows = connection.execute(
        sa.select(signal_workflow).where(
            signal_workflow.c.account_id == account_id,
        )
    ).mappings()
    return {row["signal_key"]: _stored(row) for row in rows}


def unified_status(feedback: StoredFeedback | None, workflow: StoredWorkflow | None = None) -> str:
    """Workflow courant ; à défaut seulement, contact historique puis jugement."""
    if workflow is not None:
        return workflow.status
    if feedback is None:
        return "new"
    if feedback.contacted_at is not None:
        return "contacted"
    if feedback.relevance == "not_relevant":
        return "ignored"
    if feedback.relevance == "relevant":
        return "saved"
    return "new"


def status_resolver(
    feedback_by_key: Mapping[str, StoredFeedback],
    workflow_by_key: Mapping[str, StoredWorkflow] | None = None,
) -> Callable[[str], str]:
    """Une fonction `signal_key -> status`, fermée sur une lecture groupée."""
    workflows = workflow_by_key or {}
    return lambda signal_key: unified_status(
        feedback_by_key.get(signal_key), workflows.get(signal_key)
    )


def _locked_workflow(connection, *, account_id, signal_key, now):
    historical = feedback.get_feedback(connection, account_id=account_id, signal_key=signal_key)
    statement = (
        _conflict_insert(connection, signal_workflow)
        .values(
            account_id=account_id,
            signal_key=signal_key,
            status=unified_status(historical),
            revision=1,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["account_id", "signal_key"])
    )
    row = connection.execute(statement.returning(*signal_workflow.c)).mappings().first()
    if row is not None:
        return _stored(row), True
    # A conflicting insertion waits for the winning transaction on PostgreSQL;
    # FOR UPDATE then serializes later writers before touching historical data.
    row = (
        connection.execute(
            sa.select(signal_workflow)
            .where(
                signal_workflow.c.account_id == account_id,
                signal_workflow.c.signal_key == signal_key,
            )
            .with_for_update()
        )
        .mappings()
        .one()
    )
    return _stored(row), False


def _set_current(connection, *, current, created, target, context, now, user_id):
    if current.status == target:
        return current
    row = (
        connection.execute(
            sa.update(signal_workflow)
            .where(
                signal_workflow.c.account_id == current.account_id,
                signal_workflow.c.signal_key == current.signal_key,
            )
            .values(
                status=target,
                revision=current.revision if created else current.revision + 1,
                updated_at=now,
            )
            .returning(*signal_workflow.c)
        )
        .mappings()
        .one()
    )
    stored = _stored(row)
    analytics.record(
        connection,
        account_id=current.account_id,
        user_id=user_id,
        target_icp_id=context.target_icp_id,
        signal_key=current.signal_key,
        event_type="signal_status_updated",
        occurred_at=now,
        properties={
            "status": target,
            "previous_status": current.status,
            "revision": stored.revision,
        },
    )
    return stored


def set_status(
    connection,
    *,
    account_id: str,
    context: SignalContext,
    status: str,
    expected_revision: int,
    now: dt.datetime,
    user_id: str | None = None,
) -> StoredWorkflow:
    """CAS mutation; caller must roll back its transaction on a conflict."""
    if status not in UNIFIED_STATUSES:
        raise ValueError("invalid_status")
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("invalid_revision")
    current, created = _locked_workflow(
        connection,
        account_id=account_id,
        signal_key=context.signal_key,
        now=now,
    )
    actual_revision = 0 if created else current.revision
    if expected_revision != actual_revision:
        raise StatusConflict(dataclasses.replace(current, revision=actual_revision))
    if status == "contacted":
        feedback._mark_contacted(
            connection,
            account_id=account_id,
            context=context,
            now=now,
            user_id=user_id,
        )
    return _set_current(
        connection,
        current=current,
        created=created,
        target=status,
        context=context,
        now=now,
        user_id=user_id,
    )


def record_feedback(
    connection,
    *,
    account_id,
    context,
    relevance,
    reason_code,
    note,
    now,
    user_id=None,
):
    feedback.validate(relevance, reason_code, note)
    current, created = _locked_workflow(
        connection,
        account_id=account_id,
        signal_key=context.signal_key,
        now=now,
    )
    stored = feedback._put_feedback(
        connection,
        account_id=account_id,
        context=context,
        relevance=relevance,
        reason_code=reason_code,
        note=note,
        now=now,
        user_id=user_id,
    )
    _set_current(
        connection,
        current=current,
        created=created,
        target=unified_status(stored),
        context=context,
        now=now,
        user_id=user_id,
    )
    return stored


def record_contacted(connection, *, account_id, context, now, user_id=None):
    current, created = _locked_workflow(
        connection,
        account_id=account_id,
        signal_key=context.signal_key,
        now=now,
    )
    stored, recorded = feedback._mark_contacted(
        connection,
        account_id=account_id,
        context=context,
        now=now,
        user_id=user_id,
    )
    _set_current(
        connection,
        current=current,
        created=created,
        target="contacted",
        context=context,
        now=now,
        user_id=user_id,
    )
    return stored, recorded
