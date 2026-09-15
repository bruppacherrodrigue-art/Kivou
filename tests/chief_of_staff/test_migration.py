from __future__ import annotations

import datetime as dt
from decimal import Decimal

import sqlalchemy as sa
from alembic.script import ScriptDirectory

from signals.model_runtime.budget import ModelBudgetStore
from signals.model_runtime.config import ModelRoute
from signals.persistence.database import alembic_config


def test_chief_of_staff_migration_is_the_single_head(migrated_sqlite_engine) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(migrated_sqlite_engine))
    assert scripts.get_heads() == ["0065_chief_of_staff"]
    assert scripts.get_revision("0065_chief_of_staff").down_revision == "0064_company_mail_merge"


def test_migration_creates_append_only_report_shape_and_indexes(
    migrated_sqlite_engine,
) -> None:
    inspector = sa.inspect(migrated_sqlite_engine)
    assert "chief_of_staff_report" in inspector.get_table_names()
    columns = {item["name"] for item in inspector.get_columns("chief_of_staff_report")}
    assert columns == {
        "report_ref",
        "report_version",
        "cadence",
        "period_start",
        "period_end",
        "created_at",
        "captured_at",
        "context_fingerprint",
        "business_memory_version",
        "profile_version",
        "supervisor_version",
        "model_route",
        "validated_report",
        "evidence_facts",
        "usage_metadata",
        "estimated_cost",
        "actual_cost",
        "model_call_id",
    }
    indexes = {
        tuple(item["column_names"])
        for item in inspector.get_indexes("chief_of_staff_report")
    }
    assert ("cadence", "captured_at") in indexes
    assert ("captured_at",) in indexes


def test_model_budget_accepts_distinct_chief_of_staff_usage(migrated_sqlite_engine) -> None:
    now = dt.datetime(2026, 9, 15, 5, 30, tzinfo=dt.UTC)
    store = ModelBudgetStore(migrated_sqlite_engine, clock=lambda: now)
    store.reserve(
        route=ModelRoute(
            usage="chief_of_staff",
            model="anthropic/claude-sonnet-4.6",
            daily_budget_usd=Decimal("1"),
        ),
        estimated_usd=Decimal("0.01"),
        call_id="chief-model-call",
    )
    store.fail(call_id="chief-model-call", error_code="OFFLINE_FIXTURE")
    assert store.calls()[0].usage == "chief_of_staff"
