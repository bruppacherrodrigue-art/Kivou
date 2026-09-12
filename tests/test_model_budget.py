from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa

from signals.model_runtime.budget import (
    DailyModelBudgetExhausted,
    ModelBudgetStore,
)
from signals.model_runtime.config import ModelRoute
from signals.persistence.schema import model_call_journal


@pytest.fixture
def clock_value() -> list[dt.datetime]:
    return [dt.datetime(2026, 9, 12, 21, 59, tzinfo=dt.UTC)]


@pytest.fixture
def store(migrated_sqlite_engine, clock_value) -> ModelBudgetStore:
    return ModelBudgetStore(migrated_sqlite_engine, clock=lambda: clock_value[0])


def _route(cap: str = "2") -> ModelRoute:
    return ModelRoute(
        usage="enrichment_judge",
        model="mistralai/mistral-small",
        daily_budget_usd=Decimal(cap),
    )


def test_reservation_stops_before_cap_is_exceeded(store: ModelBudgetStore) -> None:
    store.reserve(route=_route(), estimated_usd=Decimal("1.60"), call_id="a")

    with pytest.raises(DailyModelBudgetExhausted) as caught:
        store.reserve(route=_route(), estimated_usd=Decimal("0.41"), call_id="b")

    assert caught.value.code == "DAILY_MODEL_BUDGET_EXHAUSTED"
    assert caught.value.usage == "enrichment_judge"
    assert caught.value.cap_usd == Decimal("2")
    summary = store.summary("enrichment_judge")
    assert summary.reserved_usd == Decimal("1.60000000")
    assert summary.actual_usd == Decimal("0E-8")
    assert [call.status for call in store.calls()] == ["reserved", "rejected_budget"]


def test_success_replaces_reservation_with_actual_cost(store: ModelBudgetStore) -> None:
    store.reserve(
        route=_route(),
        estimated_usd=Decimal("0.10"),
        call_id="a",
        siren="123456789",
        batch_id="bench-1",
    )

    store.succeed(
        call_id="a",
        actual_usd=Decimal("0.0004"),
        input_tokens=900,
        output_tokens=80,
    )

    summary = store.summary("enrichment_judge")
    assert summary.actual_usd == Decimal("0.00040000")
    assert summary.reserved_usd == Decimal("0E-8")
    call = store.calls()[0]
    assert call.status == "succeeded"
    assert call.siren == "123456789"
    assert call.batch_id == "bench-1"
    assert call.input_tokens == 900
    assert call.output_tokens == 80


def test_failure_releases_reservation_and_records_stable_error(store: ModelBudgetStore) -> None:
    store.reserve(route=_route(), estimated_usd=Decimal("0.10"), call_id="a")

    store.fail(call_id="a", error_code="PROVIDER_HTTP_503")

    assert store.summary("enrichment_judge").reserved_usd == Decimal("0E-8")
    call = store.calls()[0]
    assert call.status == "failed"
    assert call.error_code == "PROVIDER_HTTP_503"


def test_terminal_call_cannot_be_reconciled_twice(store: ModelBudgetStore) -> None:
    store.reserve(route=_route(), estimated_usd=Decimal("0.10"), call_id="a")
    store.fail(call_id="a", error_code="TIMEOUT")

    with pytest.raises(ValueError, match="not an active reservation"):
        store.succeed(
            call_id="a",
            actual_usd=Decimal("0.01"),
            input_tokens=1,
            output_tokens=1,
        )


def test_zurich_midnight_starts_a_new_daily_counter(
    store: ModelBudgetStore, clock_value: list[dt.datetime]
) -> None:
    store.reserve(route=_route(), estimated_usd=Decimal("2"), call_id="before-midnight")
    clock_value[0] = dt.datetime(2026, 9, 12, 22, 1, tzinfo=dt.UTC)

    store.reserve(route=_route(), estimated_usd=Decimal("2"), call_id="after-midnight")

    assert store.summary("enrichment_judge").usage_date == dt.date(2026, 9, 13)
    assert store.summary("enrichment_judge").reserved_usd == Decimal("2.00000000")


@pytest.mark.parametrize("amount", [Decimal("-0.01"), Decimal("NaN")])
def test_invalid_reservation_amount_fails_before_writing(
    store: ModelBudgetStore, amount: Decimal
) -> None:
    with pytest.raises(ValueError, match="estimated_usd"):
        store.reserve(route=_route(), estimated_usd=amount, call_id="invalid")

    assert store.calls() == ()


def test_two_store_instances_share_the_same_persistent_counter(
    migrated_sqlite_engine, clock_value
) -> None:
    first = ModelBudgetStore(migrated_sqlite_engine, clock=lambda: clock_value[0])
    second = ModelBudgetStore(migrated_sqlite_engine, clock=lambda: clock_value[0])
    first.reserve(route=_route(), estimated_usd=Decimal("1.25"), call_id="a")

    with pytest.raises(DailyModelBudgetExhausted):
        second.reserve(route=_route(), estimated_usd=Decimal("0.76"), call_id="b")

    with migrated_sqlite_engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(model_call_journal)).scalar_one() == 2
