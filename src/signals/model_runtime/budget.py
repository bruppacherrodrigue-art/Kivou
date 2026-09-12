"""Transactional reservation and reconciliation for model safety budgets."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

from signals.model_runtime.config import MODEL_TIMEZONE, ModelRoute, ModelUsage
from signals.persistence.schema import model_call_journal, model_daily_budget

_ZONE = ZoneInfo(MODEL_TIMEZONE)
_ZERO = Decimal("0")


class DailyModelBudgetExhausted(RuntimeError):
    code = "DAILY_MODEL_BUDGET_EXHAUSTED"

    def __init__(
        self,
        *,
        usage: ModelUsage,
        cap_usd: Decimal,
        actual_usd: Decimal,
        reserved_usd: Decimal,
        requested_usd: Decimal,
    ) -> None:
        super().__init__(
            f"{self.code}: {usage} cap={cap_usd} actual={actual_usd} "
            f"reserved={reserved_usd} requested={requested_usd}"
        )
        self.usage = usage
        self.cap_usd = cap_usd
        self.actual_usd = actual_usd
        self.reserved_usd = reserved_usd
        self.requested_usd = requested_usd


@dataclass(frozen=True)
class ModelBudgetSummary:
    usage_date: dt.date
    usage: str
    reserved_usd: Decimal
    actual_usd: Decimal
    updated_at: dt.datetime | None


@dataclass(frozen=True)
class ModelCallRecord:
    call_id: str
    usage: str
    model: str
    siren: str | None
    batch_id: str | None
    reserved_usd: Decimal
    actual_usd: Decimal | None
    input_tokens: int | None
    output_tokens: int | None
    status: str
    error_code: str | None
    called_at: dt.datetime
    completed_at: dt.datetime | None


class ModelBudgetStore:
    def __init__(
        self,
        engine: sa.Engine,
        *,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._engine = engine
        self._clock = clock

    def _now(self) -> dt.datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("model budget clock must be timezone-aware")
        return value

    @staticmethod
    def _day(value: dt.datetime) -> dt.date:
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.UTC)
        return value.astimezone(_ZONE).date()

    @staticmethod
    def _amount(value: Decimal, *, name: str) -> Decimal:
        if not value.is_finite() or value < 0:
            raise ValueError(f"{name} must be a finite non-negative decimal")
        return value

    @staticmethod
    def _ensure_counter(
        connection: sa.Connection, *, usage_date: dt.date, usage: str, now: dt.datetime
    ) -> None:
        values = {
            "usage_date": usage_date,
            "usage": usage,
            "reserved_usd": _ZERO,
            "actual_usd": _ZERO,
            "updated_at": now,
        }
        if connection.dialect.name == "postgresql":
            statement = postgresql.insert(model_daily_budget).values(**values)
            connection.execute(statement.on_conflict_do_nothing())
        elif connection.dialect.name == "sqlite":
            statement = sqlite.insert(model_daily_budget).values(**values)
            connection.execute(statement.on_conflict_do_nothing())
        else:
            try:
                connection.execute(sa.insert(model_daily_budget).values(**values))
            except sa.exc.IntegrityError:
                pass

    def reserve(
        self,
        *,
        route: ModelRoute,
        estimated_usd: Decimal,
        call_id: str,
        siren: str | None = None,
        batch_id: str | None = None,
    ) -> None:
        amount = self._amount(estimated_usd, name="estimated_usd")
        now = self._now()
        usage_date = self._day(now)
        exhausted: DailyModelBudgetExhausted | None = None
        with self._engine.begin() as connection:
            self._ensure_counter(
                connection, usage_date=usage_date, usage=route.usage, now=now
            )
            counter = connection.execute(
                sa.select(model_daily_budget)
                .where(
                    model_daily_budget.c.usage_date == usage_date,
                    model_daily_budget.c.usage == route.usage,
                )
                .with_for_update()
            ).mappings().one()
            actual = Decimal(counter["actual_usd"])
            reserved = Decimal(counter["reserved_usd"])
            if actual + reserved + amount > route.daily_budget_usd:
                status = "rejected_budget"
                completed_at = now
                exhausted = DailyModelBudgetExhausted(
                    usage=route.usage,
                    cap_usd=route.daily_budget_usd,
                    actual_usd=actual,
                    reserved_usd=reserved,
                    requested_usd=amount,
                )
            else:
                status = "reserved"
                completed_at = None
                connection.execute(
                    sa.update(model_daily_budget)
                    .where(
                        model_daily_budget.c.usage_date == usage_date,
                        model_daily_budget.c.usage == route.usage,
                    )
                    .values(reserved_usd=reserved + amount, updated_at=now)
                )
            connection.execute(
                sa.insert(model_call_journal).values(
                    call_id=call_id,
                    usage=route.usage,
                    model=route.model,
                    siren=siren,
                    batch_id=batch_id,
                    reserved_usd=amount,
                    status=status,
                    error_code=(exhausted.code if exhausted else None),
                    called_at=now,
                    completed_at=completed_at,
                )
            )
        if exhausted is not None:
            raise exhausted

    def _active_call(
        self, connection: sa.Connection, call_id: str
    ) -> sa.RowMapping:
        row = connection.execute(
            sa.select(model_call_journal)
            .where(model_call_journal.c.call_id == call_id)
            .with_for_update()
        ).mappings().one_or_none()
        if row is None or row["status"] != "reserved":
            raise ValueError(f"model call {call_id!r} is not an active reservation")
        return row

    def succeed(
        self,
        *,
        call_id: str,
        actual_usd: Decimal,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        actual = self._amount(actual_usd, name="actual_usd")
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("model token counts must be non-negative")
        now = self._now()
        with self._engine.begin() as connection:
            call = self._active_call(connection, call_id)
            usage_date = self._day(call["called_at"])
            counter = connection.execute(
                sa.select(model_daily_budget)
                .where(
                    model_daily_budget.c.usage_date == usage_date,
                    model_daily_budget.c.usage == call["usage"],
                )
                .with_for_update()
            ).mappings().one()
            connection.execute(
                sa.update(model_daily_budget)
                .where(
                    model_daily_budget.c.usage_date == usage_date,
                    model_daily_budget.c.usage == call["usage"],
                )
                .values(
                    reserved_usd=Decimal(counter["reserved_usd"])
                    - Decimal(call["reserved_usd"]),
                    actual_usd=Decimal(counter["actual_usd"]) + actual,
                    updated_at=now,
                )
            )
            connection.execute(
                sa.update(model_call_journal)
                .where(model_call_journal.c.call_id == call_id)
                .values(
                    actual_usd=actual,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    status="succeeded",
                    completed_at=now,
                )
            )

    def fail(self, *, call_id: str, error_code: str) -> None:
        if not error_code.strip() or len(error_code) > 128:
            raise ValueError("error_code must contain between 1 and 128 characters")
        now = self._now()
        with self._engine.begin() as connection:
            call = self._active_call(connection, call_id)
            usage_date = self._day(call["called_at"])
            counter = connection.execute(
                sa.select(model_daily_budget)
                .where(
                    model_daily_budget.c.usage_date == usage_date,
                    model_daily_budget.c.usage == call["usage"],
                )
                .with_for_update()
            ).mappings().one()
            connection.execute(
                sa.update(model_daily_budget)
                .where(
                    model_daily_budget.c.usage_date == usage_date,
                    model_daily_budget.c.usage == call["usage"],
                )
                .values(
                    reserved_usd=Decimal(counter["reserved_usd"])
                    - Decimal(call["reserved_usd"]),
                    updated_at=now,
                )
            )
            connection.execute(
                sa.update(model_call_journal)
                .where(model_call_journal.c.call_id == call_id)
                .values(status="failed", error_code=error_code, completed_at=now)
            )

    def summary(self, usage: ModelUsage) -> ModelBudgetSummary:
        usage_date = self._day(self._now())
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(model_daily_budget).where(
                    model_daily_budget.c.usage_date == usage_date,
                    model_daily_budget.c.usage == usage,
                )
            ).mappings().one_or_none()
        if row is None:
            return ModelBudgetSummary(usage_date, usage, _ZERO, _ZERO, None)
        return ModelBudgetSummary(
            usage_date=row["usage_date"],
            usage=row["usage"],
            reserved_usd=Decimal(row["reserved_usd"]),
            actual_usd=Decimal(row["actual_usd"]),
            updated_at=row["updated_at"],
        )

    def calls(self) -> tuple[ModelCallRecord, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                sa.select(model_call_journal).order_by(model_call_journal.c.called_at)
            ).mappings()
            return tuple(
                ModelCallRecord(
                    call_id=row["call_id"],
                    usage=row["usage"],
                    model=row["model"],
                    siren=row["siren"],
                    batch_id=row["batch_id"],
                    reserved_usd=Decimal(row["reserved_usd"]),
                    actual_usd=(
                        Decimal(row["actual_usd"])
                        if row["actual_usd"] is not None
                        else None
                    ),
                    input_tokens=row["input_tokens"],
                    output_tokens=row["output_tokens"],
                    status=row["status"],
                    error_code=row["error_code"],
                    called_at=row["called_at"],
                    completed_at=row["completed_at"],
                )
                for row in rows
            )


__all__ = [
    "DailyModelBudgetExhausted",
    "ModelBudgetStore",
    "ModelBudgetSummary",
    "ModelCallRecord",
]
