"""Transactional SQLAlchemy Core persistence for Acquisition Opportunities."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from signals.acquisition.contracts import (
    EVENT_SCHEMA_VERSION,
    STATE_MACHINE_VERSION,
    AcquisitionEvent,
    AcquisitionIdentityConflict,
    AcquisitionOpportunity,
    AcquisitionState,
    ActorType,
    Decision,
    EventType,
    IdempotencyConflict,
    OpportunityConcurrencyConflict,
    ProjectionNotFound,
    ProjectionVerification,
)
from signals.acquisition.state import reduce_event, replay
from signals.persistence.schema import acquisition_event, acquisition_opportunity


@dataclass(frozen=True)
class MutationResult:
    projection: AcquisitionOpportunity
    event: AcquisitionEvent
    replayed: bool = False


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _identifier() -> str:
    return uuid.uuid4().hex


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonical(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(nested) for nested in value]
    return value


def _fingerprint(value: dict[str, object]) -> str:
    encoded = json.dumps(
        _canonical(value),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _semantic_input(
    *,
    event_type: EventType,
    actor_type: ActorType,
    actor_ref: str | None,
    reason_codes: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    policy_version: str | None,
    skill_version: str | None,
    supervisor_version: str | None,
    confidence: Decimal | None,
    estimated_cost: Decimal | None,
    payload: dict[str, Any],
    correlation_id: str | None,
    causation_id: str | None,
    occurred_at: dt.datetime | None,
) -> dict[str, object]:
    return {
        "event_type": event_type,
        "state_machine_version": STATE_MACHINE_VERSION,
        "actor_type": actor_type,
        "actor_ref": actor_ref,
        "reason_codes": reason_codes,
        "evidence_refs": evidence_refs,
        "policy_version": policy_version,
        "skill_version": skill_version,
        "supervisor_version": supervisor_version,
        "confidence": confidence,
        "estimated_cost": estimated_cost,
        "payload": payload,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "occurred_at": occurred_at,
    }


def _event_from_row(row: RowMapping) -> AcquisitionEvent:
    values = dict(row)
    values["occurred_at"] = _aware(values["occurred_at"])
    values["recorded_at"] = _aware(values["recorded_at"])
    values["reason_codes"] = tuple(values["reason_codes"])
    values["evidence_refs"] = tuple(values["evidence_refs"])
    return AcquisitionEvent.model_validate(values)


def _projection_from_row(row: RowMapping) -> AcquisitionOpportunity:
    values = dict(row)
    for field in ("next_review_at", "retry_at", "created_at", "updated_at"):
        values[field] = _aware(values[field])
    values["reason_codes"] = tuple(values["reason_codes"])
    values["evidence_refs"] = tuple(values["evidence_refs"])
    return AcquisitionOpportunity.model_validate(values)


def _event_values(event: AcquisitionEvent) -> dict[str, object]:
    values = event.model_dump(mode="python")
    values["event_type"] = event.event_type.value
    values["actor_type"] = event.actor_type.value
    values["reason_codes"] = list(event.reason_codes)
    values["evidence_refs"] = list(event.evidence_refs)
    return values


def _projection_values(projection: AcquisitionOpportunity) -> dict[str, object]:
    values = projection.model_dump(mode="python")
    values["state"] = projection.state.value
    values["decision"] = projection.decision.value if projection.decision else None
    values["reason_codes"] = list(projection.reason_codes)
    values["evidence_refs"] = list(projection.evidence_refs)
    return values


class AcquisitionStore:
    """Owns atomic append + projection updates without exposing event mutation."""

    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], dt.datetime] = _utc_now,
        opportunity_id_factory: Callable[[], str] = _identifier,
        event_id_factory: Callable[[], str] = _identifier,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._opportunity_id_factory = opportunity_id_factory
        self._event_id_factory = event_id_factory

    def get_opportunity(self, opportunity_id: str) -> AcquisitionOpportunity:
        with self._engine.connect() as connection:
            return self._get_opportunity(connection, opportunity_id)

    def _get_opportunity(
        self, connection: Connection, opportunity_id: str
    ) -> AcquisitionOpportunity:
        row = connection.execute(
            sa.select(acquisition_opportunity).where(
                acquisition_opportunity.c.acquisition_opportunity_id == opportunity_id
            )
        ).mappings().one_or_none()
        if row is None:
            raise ProjectionNotFound(opportunity_id)
        return _projection_from_row(row)

    def resolve_target_ref(self, target_ref: str) -> tuple[str, ...]:
        """Resolve a Supervisor target against the two explicit opportunity references."""
        with self._engine.connect() as connection:
            values = connection.execute(
                sa.select(acquisition_opportunity.c.acquisition_opportunity_id).where(
                    sa.or_(
                        acquisition_opportunity.c.acquisition_opportunity_id == target_ref,
                        acquisition_opportunity.c.identity_key == target_ref,
                    )
                )
            ).scalars()
            return tuple(values)

    def list_events(self, opportunity_id: str) -> list[AcquisitionEvent]:
        with self._engine.connect() as connection:
            return self._list_events(connection, opportunity_id)

    def _list_events(
        self, connection: Connection, opportunity_id: str
    ) -> list[AcquisitionEvent]:
        rows = connection.execute(
            sa.select(acquisition_event)
            .where(acquisition_event.c.acquisition_opportunity_id == opportunity_id)
            .order_by(acquisition_event.c.stream_sequence)
        ).mappings()
        return [_event_from_row(row) for row in rows]

    def verify_projection(self, opportunity_id: str) -> ProjectionVerification:
        with self._engine.connect() as connection:
            current = self._get_opportunity(connection, opportunity_id)
            rebuilt = replay(self._list_events(connection, opportunity_id))
        if current == rebuilt:
            return ProjectionVerification.MATCH
        return ProjectionVerification.MISMATCH

    def rebuild_projection(self, opportunity_id: str) -> AcquisitionOpportunity:
        """Explicit recovery operation; never called by normal reads or writes."""
        with self._engine.begin() as connection:
            locked_row = connection.execute(
                sa.select(acquisition_opportunity)
                .where(
                    acquisition_opportunity.c.acquisition_opportunity_id
                    == opportunity_id
                )
                .with_for_update()
            ).mappings().one_or_none()
            if locked_row is None:
                raise ProjectionNotFound(opportunity_id)
            rebuilt = replay(self._list_events(connection, opportunity_id))
            values = _projection_values(rebuilt)
            values.pop("acquisition_opportunity_id")
            connection.execute(
                sa.update(acquisition_opportunity)
                .where(
                    acquisition_opportunity.c.acquisition_opportunity_id
                    == opportunity_id
                )
                .values(values)
            )
            return rebuilt

    def create_opportunity(
        self,
        *,
        identity_key: str,
        signal_ref: str,
        idempotency_key: str,
        supplier_ref: str | None = None,
        contact_ref: str | None = None,
        campaign_ref: str | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_ref: str | None = None,
        reason_codes: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        confidence: Decimal | None = None,
        policy_version: str | None = None,
        skill_version: str | None = None,
        supervisor_version: str | None = None,
        estimated_cost: Decimal | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        occurred_at: dt.datetime | None = None,
    ) -> MutationResult:
        payload = {
            "identity_key": identity_key,
            "signal_ref": signal_ref,
            "supplier_ref": supplier_ref,
            "contact_ref": contact_ref,
            "campaign_ref": campaign_ref,
        }
        semantic = _semantic_input(
            event_type=EventType.OPPORTUNITY_CREATED,
            actor_type=actor_type,
            actor_ref=actor_ref,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            policy_version=policy_version,
            skill_version=skill_version,
            supervisor_version=supervisor_version,
            confidence=confidence,
            estimated_cost=estimated_cost,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
        )
        fingerprint = _fingerprint(semantic)
        recorded_at = self._clock()
        happened_at = occurred_at or recorded_at
        with self._engine.begin() as connection:
            existing_row = connection.execute(
                sa.select(acquisition_opportunity).where(
                    acquisition_opportunity.c.identity_key == identity_key
                )
            ).mappings().one_or_none()
            if existing_row is not None:
                existing = _projection_from_row(existing_row)
                creation_row = connection.execute(
                    sa.select(acquisition_event).where(
                        acquisition_event.c.acquisition_opportunity_id
                        == existing.acquisition_opportunity_id,
                        acquisition_event.c.stream_sequence == 1,
                    )
                ).mappings().one()
                creation = _event_from_row(creation_row)
                if creation.idempotency_key != idempotency_key:
                    raise AcquisitionIdentityConflict(identity_key)
                if creation.semantic_fingerprint != fingerprint:
                    raise IdempotencyConflict(idempotency_key)
                return MutationResult(existing, creation, replayed=True)

            event = AcquisitionEvent(
                event_id=self._event_id_factory(),
                acquisition_opportunity_id=self._opportunity_id_factory(),
                stream_sequence=1,
                event_type=EventType.OPPORTUNITY_CREATED,
                schema_version=EVENT_SCHEMA_VERSION,
                state_machine_version=STATE_MACHINE_VERSION,
                occurred_at=happened_at,
                recorded_at=recorded_at,
                actor_type=actor_type,
                actor_ref=actor_ref,
                idempotency_key=idempotency_key,
                semantic_fingerprint=fingerprint,
                correlation_id=correlation_id,
                causation_id=causation_id,
                reason_codes=reason_codes,
                evidence_refs=evidence_refs,
                policy_version=policy_version,
                skill_version=skill_version,
                supervisor_version=supervisor_version,
                confidence=confidence,
                estimated_cost=estimated_cost,
                payload=payload,
            )
            projection = reduce_event(None, event)
            connection.execute(sa.insert(acquisition_opportunity).values(_projection_values(projection)))
            connection.execute(sa.insert(acquisition_event).values(_event_values(event)))
            return MutationResult(projection, event)

    def transition_state(
        self,
        opportunity_id: str,
        *,
        target_state: AcquisitionState,
        expected_version: int,
        idempotency_key: str,
        reason_codes: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        next_review_at: dt.datetime | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_ref: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        occurred_at: dt.datetime | None = None,
    ) -> MutationResult:
        payload: dict[str, Any] = {"target_state": target_state.value}
        if next_review_at is not None:
            payload["next_review_at"] = next_review_at.isoformat()
        return self._append(
            opportunity_id,
            event_type=EventType.STATE_TRANSITIONED,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            actor_type=actor_type,
            actor_ref=actor_ref,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
        )

    def record_decision(
        self,
        opportunity_id: str,
        *,
        decision: Decision,
        reason_codes: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        confidence: Decimal,
        policy_version: str,
        skill_version: str,
        estimated_cost: Decimal,
        expected_version: int,
        idempotency_key: str,
        next_review_at: dt.datetime | None = None,
        supervisor_version: str | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_ref: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        occurred_at: dt.datetime | None = None,
    ) -> MutationResult:
        payload: dict[str, Any] = {"decision": decision.value}
        if next_review_at is not None:
            payload["next_review_at"] = next_review_at.isoformat()
        return self._append(
            opportunity_id,
            event_type=EventType.DECISION_RECORDED,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            actor_type=actor_type,
            actor_ref=actor_ref,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            policy_version=policy_version,
            skill_version=skill_version,
            supervisor_version=supervisor_version,
            confidence=confidence,
            estimated_cost=estimated_cost,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
        )

    def set_next_action(
        self,
        opportunity_id: str,
        *,
        next_action: str,
        expected_version: int,
        idempotency_key: str,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_ref: str | None = None,
        occurred_at: dt.datetime | None = None,
    ) -> MutationResult:
        return self._append(
            opportunity_id,
            event_type=EventType.NEXT_ACTION_SET,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            actor_type=actor_type,
            actor_ref=actor_ref,
            payload={"next_action": next_action},
            occurred_at=occurred_at,
        )

    def schedule_retry(
        self,
        opportunity_id: str,
        *,
        retry_at: dt.datetime,
        error_category: str,
        reason_codes: tuple[str, ...],
        expected_version: int,
        idempotency_key: str,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_ref: str | None = None,
        occurred_at: dt.datetime | None = None,
    ) -> MutationResult:
        return self._append(
            opportunity_id,
            event_type=EventType.RETRY_SCHEDULED,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            actor_type=actor_type,
            actor_ref=actor_ref,
            reason_codes=reason_codes,
            payload={
                "retry_at": retry_at.isoformat(),
                "error_category": error_category,
            },
            occurred_at=occurred_at,
        )

    def record_outcome(
        self,
        opportunity_id: str,
        *,
        outcome_state: AcquisitionState,
        expected_version: int,
        idempotency_key: str,
        reason_codes: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        actor_type: ActorType = ActorType.EXTERNAL,
        actor_ref: str | None = None,
        occurred_at: dt.datetime | None = None,
    ) -> MutationResult:
        return self._append(
            opportunity_id,
            event_type=EventType.OUTCOME_RECORDED,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            actor_type=actor_type,
            actor_ref=actor_ref,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            payload={"outcome_state": outcome_state.value},
            occurred_at=occurred_at,
        )

    def record_supervisor_plan_observed(
        self,
        opportunity_id: str,
        *,
        payload: dict[str, Any],
        reason_codes: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        confidence: Decimal,
        estimated_cost: Decimal,
        supervisor_version: str,
        skill_version: str,
        expected_version: int,
        idempotency_key: str,
        occurred_at: dt.datetime,
    ) -> MutationResult:
        return self._append(
            opportunity_id,
            event_type=EventType.SUPERVISOR_PLAN_OBSERVED,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            actor_type=ActorType.HERMES,
            actor_ref="kivou-acquisition-supervisor",
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            skill_version=skill_version,
            supervisor_version=supervisor_version,
            confidence=confidence,
            estimated_cost=estimated_cost,
            payload=payload,
            occurred_at=occurred_at,
        )

    def _append(
        self,
        opportunity_id: str,
        *,
        event_type: EventType,
        expected_version: int,
        idempotency_key: str,
        payload: dict[str, Any],
        actor_type: ActorType = ActorType.SYSTEM,
        actor_ref: str | None = None,
        reason_codes: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        policy_version: str | None = None,
        skill_version: str | None = None,
        supervisor_version: str | None = None,
        confidence: Decimal | None = None,
        estimated_cost: Decimal | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        occurred_at: dt.datetime | None = None,
    ) -> MutationResult:
        semantic = _semantic_input(
            event_type=event_type,
            actor_type=actor_type,
            actor_ref=actor_ref,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            policy_version=policy_version,
            skill_version=skill_version,
            supervisor_version=supervisor_version,
            confidence=confidence,
            estimated_cost=estimated_cost,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
        )
        fingerprint = _fingerprint(semantic)
        recorded_at = self._clock()
        happened_at = occurred_at or recorded_at
        with self._engine.begin() as connection:
            current = self._get_opportunity(connection, opportunity_id)
            existing_row = connection.execute(
                sa.select(acquisition_event).where(
                    acquisition_event.c.acquisition_opportunity_id == opportunity_id,
                    acquisition_event.c.idempotency_key == idempotency_key,
                )
            ).mappings().one_or_none()
            if existing_row is not None:
                existing = _event_from_row(existing_row)
                if existing.semantic_fingerprint != fingerprint:
                    raise IdempotencyConflict(idempotency_key)
                return MutationResult(current, existing, replayed=True)
            if current.stream_version != expected_version:
                raise OpportunityConcurrencyConflict(
                    f"expected {expected_version}, found {current.stream_version}"
                )
            event = AcquisitionEvent(
                event_id=self._event_id_factory(),
                acquisition_opportunity_id=opportunity_id,
                stream_sequence=expected_version + 1,
                event_type=event_type,
                state_machine_version=STATE_MACHINE_VERSION,
                occurred_at=happened_at,
                recorded_at=recorded_at,
                actor_type=actor_type,
                actor_ref=actor_ref,
                idempotency_key=idempotency_key,
                semantic_fingerprint=fingerprint,
                correlation_id=correlation_id,
                causation_id=causation_id,
                reason_codes=reason_codes,
                evidence_refs=evidence_refs,
                policy_version=policy_version,
                skill_version=skill_version,
                supervisor_version=supervisor_version,
                confidence=confidence,
                estimated_cost=estimated_cost,
                payload=payload,
            )
            next_projection = reduce_event(current, event)
            values = _projection_values(next_projection)
            values.pop("acquisition_opportunity_id")
            result = connection.execute(
                sa.update(acquisition_opportunity)
                .where(
                    acquisition_opportunity.c.acquisition_opportunity_id == opportunity_id,
                    acquisition_opportunity.c.stream_version == expected_version,
                )
                .values(values)
            )
            if result.rowcount != 1:
                raise OpportunityConcurrencyConflict(opportunity_id)
            connection.execute(sa.insert(acquisition_event).values(_event_values(event)))
            return MutationResult(next_projection, event)

    def append_in_transaction(
        self,
        connection: Connection,
        opportunity_id: str,
        *,
        event_type: EventType,
        expected_version: int,
        idempotency_key: str,
        payload: dict[str, Any],
        actor_type: ActorType = ActorType.SYSTEM,
        actor_ref: str | None = None,
        reason_codes: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        policy_version: str | None = None,
        skill_version: str | None = None,
        supervisor_version: str | None = None,
        confidence: Decimal | None = None,
        estimated_cost: Decimal | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        occurred_at: dt.datetime | None = None,
    ) -> MutationResult:
        """Append with a caller-owned transaction for atomic cross-journal audit."""
        semantic = _semantic_input(
            event_type=event_type,
            actor_type=actor_type,
            actor_ref=actor_ref,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            policy_version=policy_version,
            skill_version=skill_version,
            supervisor_version=supervisor_version,
            confidence=confidence,
            estimated_cost=estimated_cost,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
        )
        fingerprint = _fingerprint(semantic)
        recorded_at = self._clock()
        happened_at = occurred_at or recorded_at
        current = self._get_opportunity(connection, opportunity_id)
        existing_row = connection.execute(
            sa.select(acquisition_event).where(
                acquisition_event.c.acquisition_opportunity_id == opportunity_id,
                acquisition_event.c.idempotency_key == idempotency_key,
            )
        ).mappings().one_or_none()
        if existing_row is not None:
            existing = _event_from_row(existing_row)
            if existing.semantic_fingerprint != fingerprint:
                raise IdempotencyConflict(idempotency_key)
            return MutationResult(current, existing, replayed=True)
        if current.stream_version != expected_version:
            raise OpportunityConcurrencyConflict(
                f"expected {expected_version}, found {current.stream_version}"
            )
        event = AcquisitionEvent(
            event_id=self._event_id_factory(),
            acquisition_opportunity_id=opportunity_id,
            stream_sequence=expected_version + 1,
            event_type=event_type,
            state_machine_version=STATE_MACHINE_VERSION,
            occurred_at=happened_at,
            recorded_at=recorded_at,
            actor_type=actor_type,
            actor_ref=actor_ref,
            idempotency_key=idempotency_key,
            semantic_fingerprint=fingerprint,
            correlation_id=correlation_id,
            causation_id=causation_id,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            policy_version=policy_version,
            skill_version=skill_version,
            supervisor_version=supervisor_version,
            confidence=confidence,
            estimated_cost=estimated_cost,
            payload=payload,
        )
        next_projection = reduce_event(current, event)
        values = _projection_values(next_projection)
        values.pop("acquisition_opportunity_id")
        result = connection.execute(
            sa.update(acquisition_opportunity)
            .where(
                acquisition_opportunity.c.acquisition_opportunity_id == opportunity_id,
                acquisition_opportunity.c.stream_version == expected_version,
            )
            .values(values)
        )
        if result.rowcount != 1:
            raise OpportunityConcurrencyConflict(opportunity_id)
        connection.execute(sa.insert(acquisition_event).values(_event_values(event)))
        return MutationResult(next_projection, event)
