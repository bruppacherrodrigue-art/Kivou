"""Append-only, content-free audit journal for Chief of Staff attempts."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import sqlalchemy as sa

from signals.chief_of_staff.contracts import Cadence
from signals.persistence.schema import chief_of_staff_attempt, model_call_journal

AttemptStatus = Literal[
    "PROVIDER_FAILED",
    "RESPONSE_REJECTED",
    "SEMANTICALLY_REJECTED",
    "VALIDATED_NOT_PERSISTED",
    "VALIDATED_PERSISTED",
    "IDEMPOTENT_EXISTING",
]
AttemptStage = Literal[
    "PROVIDER_CALL",
    "STRUCTURED_RESPONSE",
    "SEMANTIC_VALIDATION",
    "PERSISTENCE",
    "COMPLETE",
]
_RESULT_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,99}$")


@dataclass(frozen=True)
class StoredChiefOfStaffAttempt:
    attempt_id: str
    context_fingerprint: str
    cadence: str
    period_start: dt.datetime
    period_end: dt.datetime
    started_at: dt.datetime
    completed_at: dt.datetime
    model_route: str
    model_call_id: str | None
    reserved_usd: Decimal
    actual_usd: Decimal | None
    status: str
    stage: str
    result_code: str
    profile_version: str
    context_version: str
    expected_report_version: str
    hermes_version: str


class ChiefOfStaffAttemptStore:
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def append(
        self,
        *,
        attempt_id: str,
        context_fingerprint: str,
        cadence: Cadence,
        period_start: dt.datetime,
        period_end: dt.datetime,
        started_at: dt.datetime,
        completed_at: dt.datetime,
        model_route: str,
        model_call_id: str | None,
        status: AttemptStatus,
        stage: AttemptStage,
        result_code: str,
        profile_version: str,
        context_version: str,
        expected_report_version: str,
        hermes_version: str,
    ) -> StoredChiefOfStaffAttempt:
        for name, value in (
            ("period_start", period_start),
            ("period_end", period_end),
            ("started_at", started_at),
            ("completed_at", completed_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if period_end <= period_start or completed_at < started_at:
            raise ValueError("attempt periods and timing must be ordered")
        if not _RESULT_CODE.fullmatch(result_code):
            raise ValueError("attempt result code must use the closed code format")
        if len(attempt_id) != 36 or len(context_fingerprint) != 64:
            raise ValueError("attempt identifiers are invalid")
        if not model_route.strip() or len(model_route) > 256:
            raise ValueError("attempt model route is invalid")

        with self._engine.begin() as connection:
            call = None
            if model_call_id is not None:
                call = (
                    connection.execute(
                        sa.select(model_call_journal).where(
                            model_call_journal.c.call_id == model_call_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            effective_call_id = None
            reserved_usd = Decimal("0")
            actual_usd = None
            effective_route = model_route.strip()
            if call is not None:
                if call["usage"] != "chief_of_staff":
                    raise ValueError("attempt model call must use chief_of_staff")
                effective_call_id = str(call["call_id"])
                effective_route = str(call["model"])
                reserved_usd = Decimal(call["reserved_usd"])
                actual_usd = (
                    Decimal(call["actual_usd"])
                    if call["actual_usd"] is not None
                    else None
                )
            values = {
                "attempt_id": attempt_id,
                "context_fingerprint": context_fingerprint,
                "cadence": cadence,
                "period_start": period_start,
                "period_end": period_end,
                "started_at": started_at,
                "completed_at": completed_at,
                "model_route": effective_route,
                "model_call_id": effective_call_id,
                "reserved_usd": reserved_usd,
                "actual_usd": actual_usd,
                "status": status,
                "stage": stage,
                "result_code": result_code,
                "profile_version": profile_version,
                "context_version": context_version,
                "expected_report_version": expected_report_version,
                "hermes_version": hermes_version,
            }
            connection.execute(sa.insert(chief_of_staff_attempt).values(**values))
            row = (
                connection.execute(
                    sa.select(chief_of_staff_attempt).where(
                        chief_of_staff_attempt.c.attempt_id == attempt_id
                    )
                )
                .mappings()
                .one()
            )
        return self._record(row)

    def history(self, *, limit: int = 20) -> tuple[StoredChiefOfStaffAttempt, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("attempt history limit must be between 1 and 100")
        with self._engine.connect() as connection:
            rows = connection.execute(
                sa.select(chief_of_staff_attempt)
                .order_by(
                    chief_of_staff_attempt.c.started_at.desc(),
                    chief_of_staff_attempt.c.attempt_id.desc(),
                )
                .limit(limit)
            ).mappings()
            return tuple(self._record(row) for row in rows)

    @staticmethod
    def _record(row: sa.RowMapping) -> StoredChiefOfStaffAttempt:
        def aware(value: dt.datetime) -> dt.datetime:
            return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)

        return StoredChiefOfStaffAttempt(
            attempt_id=str(row["attempt_id"]),
            context_fingerprint=str(row["context_fingerprint"]),
            cadence=str(row["cadence"]),
            period_start=aware(row["period_start"]),
            period_end=aware(row["period_end"]),
            started_at=aware(row["started_at"]),
            completed_at=aware(row["completed_at"]),
            model_route=str(row["model_route"]),
            model_call_id=(str(row["model_call_id"]) if row["model_call_id"] else None),
            reserved_usd=Decimal(row["reserved_usd"]),
            actual_usd=(
                Decimal(row["actual_usd"]) if row["actual_usd"] is not None else None
            ),
            status=str(row["status"]),
            stage=str(row["stage"]),
            result_code=str(row["result_code"]),
            profile_version=str(row["profile_version"]),
            context_version=str(row["context_version"]),
            expected_report_version=str(row["expected_report_version"]),
            hermes_version=str(row["hermes_version"]),
        )


__all__ = [
    "AttemptStage",
    "AttemptStatus",
    "ChiefOfStaffAttemptStore",
    "StoredChiefOfStaffAttempt",
]
