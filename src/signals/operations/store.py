"""Replay-safe persistence for operational incidents and dead letters."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from signals.operations.contracts import (
    BREAKER_VERSION,
    BreakerScope,
    DeadLetterExhaustion,
    DeadLetterStatus,
    IncidentState,
    IncidentTrigger,
)
from signals.persistence.schema import acquisition_dead_letter, acquisition_operational_incident


class OperationsConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class SaveResult:
    row: RowMapping
    replayed: bool


def _insert(connection: Connection, table: sa.Table):
    if connection.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    elif connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        raise RuntimeError("unsupported operations persistence dialect")
    return insert(table)


class OperationsStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def open_incident(self, trigger: IncidentTrigger) -> SaveResult:
        values = {
            "incident_ref": trigger.incident_ref,
            "trigger_fingerprint": trigger.trigger_fingerprint,
            "incident_version": BREAKER_VERSION,
            "incident_type": trigger.incident_type.value,
            "severity": trigger.severity.value,
            "scope_type": trigger.scope.scope_type.value,
            "scope_ref": trigger.scope.scope_ref,
            "source_state_ref": trigger.source_state_ref,
            "triggered_at": trigger.triggered_at,
            "observed_value": trigger.observed_value,
            "threshold_value": trigger.threshold_value,
            "metric_version": trigger.metric_version,
            "reason_codes": list(trigger.reason_codes),
            "state": IncidentState.OPEN.value,
            "human_review_required": trigger.human_review_required,
            "pause_required": trigger.pause_required,
            "policy_control_before": trigger.policy_control_before,
            "policy_control_after": trigger.policy_control_after,
            "campaign_ref": trigger.campaign_ref,
            "mailbox_ref": trigger.mailbox_ref,
            "wedge": trigger.wedge,
            "country": trigger.country,
            "acknowledged_at": None,
            "resolved_at": None,
            "created_at": trigger.triggered_at,
            "updated_at": trigger.triggered_at,
        }
        with self.engine.begin() as connection:
            result = connection.execute(
                _insert(connection, acquisition_operational_incident)
                .values(values)
                .on_conflict_do_nothing(
                    index_elements=[acquisition_operational_incident.c.trigger_fingerprint]
                )
            )
            row = self._incident(connection, trigger.incident_ref)
            self._require_same(
                row,
                values,
                exclude={
                    "state",
                    "triggered_at",
                    "acknowledged_at",
                    "resolved_at",
                    "policy_control_before",
                    "policy_control_after",
                    "created_at",
                    "updated_at",
                },
            )
            return SaveResult(row=row, replayed=result.rowcount == 0)

    def get_incident(self, incident_ref: str) -> RowMapping:
        with self.engine.connect() as connection:
            return self._incident(connection, incident_ref)

    def list_incidents(self, *, unresolved_only: bool = False, limit: int = 100) -> tuple[RowMapping, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("incident limit must be between 1 and 500")
        statement = sa.select(acquisition_operational_incident)
        if unresolved_only:
            statement = statement.where(acquisition_operational_incident.c.state != "RESOLVED")
        statement = statement.order_by(
            acquisition_operational_incident.c.triggered_at.desc(),
            acquisition_operational_incident.c.incident_ref,
        ).limit(limit)
        with self.engine.connect() as connection:
            return tuple(connection.execute(statement).mappings().all())

    def acknowledge_incident(self, incident_ref: str, *, at: dt.datetime) -> RowMapping:
        with self.engine.begin() as connection:
            row = self._incident(connection, incident_ref)
            if row["state"] == IncidentState.RESOLVED.value:
                return row
            if row["state"] == IncidentState.OPEN.value:
                connection.execute(
                    sa.update(acquisition_operational_incident)
                    .where(acquisition_operational_incident.c.incident_ref == incident_ref)
                    .values(state="ACKNOWLEDGED", acknowledged_at=at, updated_at=at)
                )
            return self._incident(connection, incident_ref)

    def resolve_incident(self, incident_ref: str, *, at: dt.datetime) -> RowMapping:
        with self.engine.begin() as connection:
            row = self._incident(connection, incident_ref)
            if row["state"] != IncidentState.RESOLVED.value:
                values: dict[str, object] = {
                    "state": "RESOLVED",
                    "resolved_at": at,
                    "updated_at": at,
                }
                if row["acknowledged_at"] is None:
                    values["acknowledged_at"] = at
                connection.execute(
                    sa.update(acquisition_operational_incident)
                    .where(acquisition_operational_incident.c.incident_ref == incident_ref)
                    .values(values)
                )
            return self._incident(connection, incident_ref)

    def bind_incident_policy_controls(
        self,
        incident_ref: str,
        *,
        before_ref: str,
        after_ref: str,
        at: dt.datetime,
    ) -> RowMapping:
        """Bind the first authoritative downgrade lineage without later overwrite."""
        with self.engine.begin() as connection:
            row = self._incident(connection, incident_ref)
            values: dict[str, object] = {"updated_at": at}
            if row["policy_control_before"] is None:
                values["policy_control_before"] = before_ref
            elif row["policy_control_before"] != before_ref and row["policy_control_after"] is None:
                raise OperationsConflict("incident Policy predecessor conflicts")
            if row["policy_control_after"] is None:
                values["policy_control_after"] = after_ref
            elif row["policy_control_after"] != after_ref:
                # A replay observes the already-applied successor as its current
                # control. Historical lineage remains first-write authoritative.
                return row
            connection.execute(
                sa.update(acquisition_operational_incident)
                .where(acquisition_operational_incident.c.incident_ref == incident_ref)
                .values(values)
            )
            return self._incident(connection, incident_ref)

    def has_open_breaker(self, scope: BreakerScope) -> bool:
        with self.engine.connect() as connection:
            count = connection.scalar(
                sa.select(sa.func.count())
                .select_from(acquisition_operational_incident)
                .where(
                    acquisition_operational_incident.c.state != "RESOLVED",
                    acquisition_operational_incident.c.severity.in_(("HIGH", "CRITICAL")),
                    sa.or_(
                        sa.and_(
                            acquisition_operational_incident.c.scope_type == "GLOBAL",
                            acquisition_operational_incident.c.scope_ref == "acquisition",
                        ),
                        sa.and_(
                            acquisition_operational_incident.c.scope_type == scope.scope_type.value,
                            acquisition_operational_incident.c.scope_ref == scope.scope_ref,
                        ),
                    ),
                )
            )
        return bool(count)

    def enqueue_dead_letter(
        self, exhaustion: DeadLetterExhaustion, *, created_at: dt.datetime
    ) -> SaveResult:
        values = {
            "dead_letter_ref": exhaustion.dead_letter_ref,
            "exhaustion_fingerprint": exhaustion.exhaustion_fingerprint,
            "work_type": exhaustion.work_type.value,
            "work_ref": exhaustion.work_ref,
            "scope_type": exhaustion.scope.scope_type.value,
            "scope_ref": exhaustion.scope.scope_ref,
            "attempt_count": exhaustion.attempt_count,
            "first_failed_at": exhaustion.first_failed_at,
            "last_failed_at": exhaustion.last_failed_at,
            "failure_code": exhaustion.failure_code,
            "retry_policy_version": exhaustion.retry_policy_version,
            "source_component": exhaustion.source_component,
            "source_state_ref": exhaustion.source_state_ref,
            "status": DeadLetterStatus.OPEN.value,
            "requeued_at": None,
            "resolved_at": None,
            "created_at": created_at,
            "updated_at": created_at,
        }
        with self.engine.begin() as connection:
            result = connection.execute(
                _insert(connection, acquisition_dead_letter)
                .values(values)
                .on_conflict_do_nothing(
                    index_elements=[acquisition_dead_letter.c.exhaustion_fingerprint]
                )
            )
            row = self._dead_letter(connection, exhaustion.dead_letter_ref)
            self._require_same(
                row,
                values,
                exclude={"status", "requeued_at", "resolved_at", "created_at", "updated_at"},
            )
            return SaveResult(row=row, replayed=result.rowcount == 0)

    def get_dead_letter(self, dead_letter_ref: str) -> RowMapping:
        with self.engine.connect() as connection:
            return self._dead_letter(connection, dead_letter_ref)

    def list_dead_letters(self, *, status: DeadLetterStatus | None = None, limit: int = 100) -> tuple[RowMapping, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("dead-letter limit must be between 1 and 500")
        statement = sa.select(acquisition_dead_letter)
        if status is not None:
            statement = statement.where(acquisition_dead_letter.c.status == status.value)
        statement = statement.order_by(
            acquisition_dead_letter.c.created_at.desc(), acquisition_dead_letter.c.dead_letter_ref
        ).limit(limit)
        with self.engine.connect() as connection:
            return tuple(connection.execute(statement).mappings().all())

    def mark_dead_letter_requeued(self, dead_letter_ref: str, *, at: dt.datetime) -> RowMapping:
        with self.engine.begin() as connection:
            row = self._dead_letter(connection, dead_letter_ref)
            if row["status"] == DeadLetterStatus.OPEN.value:
                connection.execute(
                    sa.update(acquisition_dead_letter)
                    .where(acquisition_dead_letter.c.dead_letter_ref == dead_letter_ref)
                    .values(status="REQUEUED", requeued_at=at, updated_at=at)
                )
            elif row["status"] != DeadLetterStatus.REQUEUED.value:
                raise OperationsConflict("resolved dead letter cannot be requeued")
            return self._dead_letter(connection, dead_letter_ref)

    def resolve_dead_letter(self, dead_letter_ref: str, *, at: dt.datetime) -> RowMapping:
        with self.engine.begin() as connection:
            row = self._dead_letter(connection, dead_letter_ref)
            if row["status"] != DeadLetterStatus.RESOLVED.value:
                connection.execute(
                    sa.update(acquisition_dead_letter)
                    .where(acquisition_dead_letter.c.dead_letter_ref == dead_letter_ref)
                    .values(status="RESOLVED", resolved_at=at, updated_at=at)
                )
            return self._dead_letter(connection, dead_letter_ref)

    @staticmethod
    def _incident(connection: Connection, incident_ref: str) -> RowMapping:
        row = connection.execute(
            sa.select(acquisition_operational_incident).where(
                acquisition_operational_incident.c.incident_ref == incident_ref
            )
        ).mappings().one_or_none()
        if row is None:
            raise KeyError(incident_ref)
        return row

    @staticmethod
    def _dead_letter(connection: Connection, dead_letter_ref: str) -> RowMapping:
        row = connection.execute(
            sa.select(acquisition_dead_letter).where(
                acquisition_dead_letter.c.dead_letter_ref == dead_letter_ref
            )
        ).mappings().one_or_none()
        if row is None:
            raise KeyError(dead_letter_ref)
        return row

    @staticmethod
    def _require_same(
        row: RowMapping, expected: dict[str, object], *, exclude: set[str]
    ) -> None:
        for key, value in expected.items():
            if key in exclude:
                continue
            actual = row[key]
            if isinstance(value, dt.datetime) and isinstance(actual, dt.datetime):
                if actual.tzinfo is None:
                    actual = actual.replace(tzinfo=dt.UTC)
                if value.tzinfo is None:
                    value = value.replace(tzinfo=dt.UTC)
                actual = actual.astimezone(dt.UTC)
                value = value.astimezone(dt.UTC)
            if actual != value:
                raise OperationsConflict(f"conflicting replay for {key}")
