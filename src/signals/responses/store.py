"""Transactional response evaluation reservation, claim, replay, and finalization."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import acquisition_response_evaluation
from signals.responses.contracts import ResponseFinalization, ResponseReservation


class ResponseEvaluationConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class ReservationResult:
    row: RowMapping
    replayed: bool


@dataclass(frozen=True)
class ClaimResult:
    row: RowMapping
    claimed: bool


@dataclass(frozen=True)
class FinalizationResult:
    row: RowMapping
    replayed: bool


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value


def _semantic(value: object) -> object:
    if isinstance(value, dt.datetime):
        return (_aware(value) or value).astimezone(dt.UTC).isoformat()
    if isinstance(value, Decimal):
        return "0" if value == 0 else format(value.normalize(), "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _semantic(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [_semantic(nested) for nested in value]
    return value


def _insert(connection: Connection):
    if connection.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    elif connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        raise RuntimeError("unsupported response persistence dialect")
    return insert(acquisition_response_evaluation)


class ResponseStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, response_evaluation_id: str) -> RowMapping:
        with self._engine.connect() as connection:
            return self.get_in_transaction(connection, response_evaluation_id)

    @staticmethod
    def get_in_transaction(connection: Connection, response_evaluation_id: str) -> RowMapping:
        row = connection.execute(
            sa.select(acquisition_response_evaluation).where(
                acquisition_response_evaluation.c.response_evaluation_id
                == response_evaluation_id
            )
        ).mappings().one_or_none()
        if row is None:
            raise KeyError(response_evaluation_id)
        return row

    def reserve(self, value: ResponseReservation) -> ReservationResult:
        with self._engine.begin() as connection:
            return self.reserve_in_transaction(connection, value)

    @staticmethod
    def reserve_in_transaction(
        connection: Connection, value: ResponseReservation
    ) -> ReservationResult:
        if value.supersedes_response_evaluation_id is not None:
            previous = ResponseStore.get_in_transaction(
                connection, value.supersedes_response_evaluation_id
            )
            if (
                previous["response_ref"] != value.response_ref
                or previous["classifier_version"] == value.classifier_version
            ):
                raise ResponseEvaluationConflict(value.response_evaluation_id)
        values = value.model_dump(mode="python")
        values.update(
            input_source=value.input_source.value,
            processing_state="PLANNED",
            attempt=0,
            updated_at=value.created_at,
        )
        inserted = insert_if_absent(
            connection,
            acquisition_response_evaluation,
            values,
            index_elements=[
                acquisition_response_evaluation.c.provider_event_ref,
                acquisition_response_evaluation.c.classifier_version,
            ],
        )
        row = ResponseStore.get_in_transaction(connection, value.response_evaluation_id)
        expected = value.model_dump(mode="python")
        for key, expected_value in expected.items():
            if _semantic(row[key]) != _semantic(expected_value):
                raise ResponseEvaluationConflict(value.response_evaluation_id)
        return ReservationResult(row=row, replayed=not inserted)

    def claim(
        self,
        response_evaluation_id: str,
        *,
        worker_ref: str,
        now: dt.datetime,
        lease_duration: dt.timedelta,
    ) -> ClaimResult:
        if not worker_ref or len(worker_ref) > 64:
            raise ValueError("bounded worker_ref is required")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("claim time must be timezone-aware")
        if lease_duration <= dt.timedelta(0) or lease_duration > dt.timedelta(hours=1):
            raise ValueError("lease duration is outside the bounded range")
        eligible = sa.or_(
            acquisition_response_evaluation.c.processing_state == "PLANNED",
            sa.and_(
                acquisition_response_evaluation.c.processing_state == "RETRY_WAIT",
                acquisition_response_evaluation.c.retry_at <= now,
            ),
            sa.and_(
                acquisition_response_evaluation.c.processing_state == "IN_FLIGHT",
                acquisition_response_evaluation.c.lease_expires_at <= now,
            ),
        )
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.update(acquisition_response_evaluation)
                .where(
                    acquisition_response_evaluation.c.response_evaluation_id
                    == response_evaluation_id,
                    eligible,
                )
                .values(
                    processing_state="IN_FLIGHT",
                    attempt=acquisition_response_evaluation.c.attempt + 1,
                    lease_owner=worker_ref,
                    lease_expires_at=now + lease_duration,
                    retry_at=None,
                    failure_code=None,
                    updated_at=now,
                )
            )
            row = self.get_in_transaction(connection, response_evaluation_id)
            return ClaimResult(row=row, claimed=result.rowcount == 1)

    def mark_retry(
        self,
        response_evaluation_id: str,
        *,
        worker_ref: str,
        now: dt.datetime,
        retry_at: dt.datetime,
        failure_code: str,
    ) -> RowMapping:
        if retry_at <= now:
            raise ValueError("retry_at must be in the future")
        if not failure_code or len(failure_code) > 100:
            raise ValueError("bounded failure_code is required")
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.update(acquisition_response_evaluation)
                .where(
                    acquisition_response_evaluation.c.response_evaluation_id
                    == response_evaluation_id,
                    acquisition_response_evaluation.c.processing_state == "IN_FLIGHT",
                    acquisition_response_evaluation.c.lease_owner == worker_ref,
                )
                .values(
                    processing_state="RETRY_WAIT",
                    lease_owner=None,
                    lease_expires_at=None,
                    retry_at=retry_at,
                    failure_code=failure_code,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise ResponseEvaluationConflict(response_evaluation_id)
            return self.get_in_transaction(connection, response_evaluation_id)

    def finalize(
        self,
        response_evaluation_id: str,
        *,
        worker_ref: str,
        value: ResponseFinalization,
    ) -> FinalizationResult:
        with self._engine.begin() as connection:
            return self.finalize_in_transaction(
                connection,
                response_evaluation_id,
                worker_ref=worker_ref,
                value=value,
            )

    @staticmethod
    def finalize_in_transaction(
        connection: Connection,
        response_evaluation_id: str,
        *,
        worker_ref: str,
        value: ResponseFinalization,
    ) -> FinalizationResult:
        current = ResponseStore.get_in_transaction(connection, response_evaluation_id)
        final_values = value.model_dump(mode="python")
        final_values.update(
            input_source=value.input_source.value,
            classification=value.classification.value,
            reason_codes=[item.value for item in value.reason_codes],
            processing_state="FINALIZED",
            lease_owner=None,
            lease_expires_at=None,
            retry_at=None,
            failure_code=None,
            updated_at=value.finalized_at,
        )
        if current["processing_state"] == "FINALIZED":
            for key, expected in final_values.items():
                if _semantic(current[key]) != _semantic(expected):
                    raise ResponseEvaluationConflict(response_evaluation_id)
            return FinalizationResult(row=current, replayed=True)
        if current["processing_state"] != "IN_FLIGHT" or current["lease_owner"] != worker_ref:
            raise ResponseEvaluationConflict(response_evaluation_id)
        result = connection.execute(
            sa.update(acquisition_response_evaluation)
            .where(
                acquisition_response_evaluation.c.response_evaluation_id
                == response_evaluation_id,
                acquisition_response_evaluation.c.processing_state == "IN_FLIGHT",
                acquisition_response_evaluation.c.lease_owner == worker_ref,
            )
            .values(final_values)
        )
        if result.rowcount != 1:
            raise ResponseEvaluationConflict(response_evaluation_id)
        return FinalizationResult(
            row=ResponseStore.get_in_transaction(connection, response_evaluation_id),
            replayed=False,
        )


__all__ = [
    "ClaimResult",
    "FinalizationResult",
    "ReservationResult",
    "ResponseEvaluationConflict",
    "ResponseStore",
]
