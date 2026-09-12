from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError

from signals.persistence.database import alembic_config, create_database_engine, current_revision


def _migrated_engine(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'model-budget.db'}")
    command.upgrade(alembic_config(engine), "head")
    return engine


def test_model_budget_migration_creates_persistent_ledger(tmp_path) -> None:
    engine = _migrated_engine(tmp_path)
    inspector = sa.inspect(engine)

    assert current_revision(engine) == "0058_model_call_budget"
    assert {"model_daily_budget", "model_call_journal"} <= set(inspector.get_table_names())
    budget_columns = {column["name"] for column in inspector.get_columns("model_daily_budget")}
    assert {
        "usage_date",
        "usage",
        "reserved_usd",
        "actual_usd",
        "updated_at",
    } == budget_columns
    journal_columns = {column["name"] for column in inspector.get_columns("model_call_journal")}
    assert {
        "call_id",
        "usage",
        "model",
        "siren",
        "batch_id",
        "reserved_usd",
        "actual_usd",
        "input_tokens",
        "output_tokens",
        "status",
        "error_code",
        "called_at",
        "completed_at",
    } == journal_columns
    index_columns = {
        tuple(index["column_names"]) for index in inspector.get_indexes("model_call_journal")
    }
    assert {("usage", "called_at"), ("siren", "called_at"), ("batch_id",)} <= index_columns
    supplier_columns = {column["name"] for column in inspector.get_columns("supplier_directory")}
    assert "enrichment_call_id" in supplier_columns


@pytest.mark.parametrize(
    ("table_name", "values"),
    [
        (
            "model_daily_budget",
            {
                "usage_date": dt.date(2026, 9, 12),
                "usage": "for_you",
                "reserved_usd": Decimal("-0.01"),
                "actual_usd": Decimal("0"),
                "updated_at": dt.datetime(2026, 9, 12, tzinfo=dt.UTC),
            },
        ),
        (
            "model_call_journal",
            {
                "call_id": "call-negative-cost",
                "usage": "enrichment_judge",
                "model": "mistralai/mistral-small",
                "reserved_usd": Decimal("-0.01"),
                "status": "reserved",
                "called_at": dt.datetime(2026, 9, 12, tzinfo=dt.UTC),
            },
        ),
        (
            "model_call_journal",
            {
                "call_id": "call-invalid-status",
                "usage": "enrichment_judge",
                "model": "mistralai/mistral-small",
                "reserved_usd": Decimal("0.01"),
                "status": "unknown",
                "called_at": dt.datetime(2026, 9, 12, tzinfo=dt.UTC),
            },
        ),
    ],
)
def test_model_budget_migration_rejects_invalid_ledger_rows(
    tmp_path, table_name: str, values: dict[str, object]
) -> None:
    engine = _migrated_engine(tmp_path)
    table = sa.Table(table_name, sa.MetaData(), autoload_with=engine)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(sa.insert(table).values(**values))


def test_model_calls_and_current_judgment_have_traceable_nullable_links(tmp_path) -> None:
    engine = _migrated_engine(tmp_path)
    inspector = sa.inspect(engine)
    journal_foreign_keys = inspector.get_foreign_keys("model_call_journal")
    supplier_foreign_keys = inspector.get_foreign_keys("supplier_directory")

    assert any(
        item["constrained_columns"] == ["siren"] and item["referred_table"] == "supplier_directory"
        for item in journal_foreign_keys
    )
    assert any(
        item["constrained_columns"] == ["enrichment_call_id"]
        and item["referred_table"] == "model_call_journal"
        for item in supplier_foreign_keys
    )
