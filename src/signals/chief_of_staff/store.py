"""Append-only persistence and bounded reads for validated Chief reports."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

from signals.chief_of_staff.context import context_fingerprint
from signals.chief_of_staff.contracts import Cadence, ChiefOfStaffContext, ChiefOfStaffReport
from signals.persistence.schema import chief_of_staff_report


@dataclass(frozen=True)
class StoredChiefOfStaffReport:
    report: ChiefOfStaffReport
    captured_at: dt.datetime
    business_memory_version: str
    profile_version: str
    supervisor_version: str
    model_route: str
    usage_metadata: dict[str, Any]
    estimated_cost: Decimal
    actual_cost: Decimal | None
    model_call_id: str | None


class ChiefOfStaffReportStore:
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def append(
        self,
        *,
        report: ChiefOfStaffReport,
        context: ChiefOfStaffContext,
        captured_at: dt.datetime,
        model_route: str,
        usage_metadata: dict[str, Any],
        estimated_cost: Decimal,
        actual_cost: Decimal | None,
        model_call_id: str | None,
    ) -> tuple[StoredChiefOfStaffReport, bool]:
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        if estimated_cost < 0 or (actual_cost is not None and actual_cost < 0):
            raise ValueError("model costs must be non-negative")
        fingerprint = context_fingerprint(context)
        values = {
            "report_ref": report.report_ref,
            "report_version": report.report_version,
            "cadence": report.cadence,
            "period_start": report.period_start,
            "period_end": report.period_end,
            "created_at": report.created_at,
            "captured_at": captured_at,
            "context_fingerprint": fingerprint,
            "business_memory_version": context.business_memory_version,
            "profile_version": report.profile_version,
            "supervisor_version": report.supervisor_version,
            "model_route": model_route,
            "validated_report": report.model_dump(mode="json"),
            "usage_metadata": usage_metadata,
            "estimated_cost": estimated_cost,
            "actual_cost": actual_cost,
            "model_call_id": model_call_id,
        }
        inserted = False
        with self._engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                statement = postgresql.insert(chief_of_staff_report).values(**values)
                result = connection.execute(
                    statement.on_conflict_do_nothing(
                        constraint="uq_chief_of_staff_report_semantic"
                    ).returning(chief_of_staff_report.c.report_ref)
                )
                inserted = result.scalar_one_or_none() is not None
            elif connection.dialect.name == "sqlite":
                statement = sqlite.insert(chief_of_staff_report).values(**values)
                result = connection.execute(
                    statement.on_conflict_do_nothing(
                        index_elements=(
                            chief_of_staff_report.c.context_fingerprint,
                            chief_of_staff_report.c.report_version,
                            chief_of_staff_report.c.business_memory_version,
                            chief_of_staff_report.c.profile_version,
                            chief_of_staff_report.c.supervisor_version,
                        )
                    )
                )
                inserted = result.rowcount == 1
            else:
                try:
                    connection.execute(sa.insert(chief_of_staff_report).values(**values))
                    inserted = True
                except sa.exc.IntegrityError:
                    inserted = False
            row = (
                connection.execute(
                    sa.select(chief_of_staff_report).where(
                        chief_of_staff_report.c.context_fingerprint == fingerprint,
                        chief_of_staff_report.c.report_version == report.report_version,
                        chief_of_staff_report.c.business_memory_version
                        == context.business_memory_version,
                        chief_of_staff_report.c.profile_version == report.profile_version,
                        chief_of_staff_report.c.supervisor_version == report.supervisor_version,
                    )
                )
                .mappings()
                .one()
            )
        return self._record(row), inserted

    def latest(self, *, cadence: Cadence | None = None) -> StoredChiefOfStaffReport | None:
        statement = sa.select(chief_of_staff_report)
        if cadence is not None:
            statement = statement.where(chief_of_staff_report.c.cadence == cadence)
        statement = statement.order_by(
            chief_of_staff_report.c.captured_at.desc(),
            chief_of_staff_report.c.report_ref.desc(),
        ).limit(1)
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else self._record(row)

    def history(
        self, *, cadence: Cadence | None = None, limit: int = 20
    ) -> tuple[StoredChiefOfStaffReport, ...]:
        if not 1 <= limit <= 50:
            raise ValueError("history limit must be between 1 and 50")
        statement = sa.select(chief_of_staff_report)
        if cadence is not None:
            statement = statement.where(chief_of_staff_report.c.cadence == cadence)
        statement = statement.order_by(
            chief_of_staff_report.c.captured_at.desc(),
            chief_of_staff_report.c.report_ref.desc(),
        ).limit(limit)
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings()
            return tuple(self._record(row) for row in rows)

    @staticmethod
    def _record(row: sa.RowMapping) -> StoredChiefOfStaffReport:
        payload = json.dumps(row["validated_report"], ensure_ascii=False)
        return StoredChiefOfStaffReport(
            report=ChiefOfStaffReport.model_validate_json(payload),
            captured_at=row["captured_at"],
            business_memory_version=str(row["business_memory_version"]),
            profile_version=str(row["profile_version"]),
            supervisor_version=str(row["supervisor_version"]),
            model_route=str(row["model_route"]),
            usage_metadata=dict(row["usage_metadata"]),
            estimated_cost=Decimal(row["estimated_cost"]),
            actual_cost=(
                Decimal(row["actual_cost"]) if row["actual_cost"] is not None else None
            ),
            model_call_id=(str(row["model_call_id"]) if row["model_call_id"] else None),
        )


__all__ = ["ChiefOfStaffReportStore", "StoredChiefOfStaffReport"]
