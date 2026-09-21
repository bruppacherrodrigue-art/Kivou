from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.model_runtime.budget import ModelBudgetStore
from signals.model_runtime.config import ModelRoute
from signals.persistence.database import alembic_config, create_database_engine


def test_chief_of_staff_migration_is_the_single_head(migrated_sqlite_engine) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(migrated_sqlite_engine))
    assert scripts.get_heads() == ["0073_milomail_a0_prepaid"]
    assert scripts.get_revision("0073_milomail_a0_prepaid").down_revision == (
        "0072_milomail_census_readiness"
    )
    assert scripts.get_revision("0072_milomail_census_readiness").down_revision == (
        "0071_milomail_shadow_census"
    )
    assert scripts.get_revision("0071_milomail_shadow_census").down_revision == (
        "0070_program_conversion_receipt"
    )
    assert scripts.get_revision("0070_program_conversion_receipt").down_revision == (
        "0069_milomail_suppression_scope"
    )
    assert scripts.get_revision("0069_milomail_suppression_scope").down_revision == (
        "0068_acquisition_program"
    )
    assert scripts.get_revision("0068_acquisition_program").down_revision == (
        "0067_acceptance_error_cleanup"
    )
    assert scripts.get_revision("0067_acceptance_error_cleanup").down_revision == (
        "0066_async_chief_merge"
    )
    assert scripts.get_revision("0066_async_chief_merge").down_revision == (
        "0065_async_prospect_send",
        "0065_chief_of_staff",
    )


def test_migration_creates_append_only_report_shape_and_indexes(
    migrated_sqlite_engine,
) -> None:
    inspector = sa.inspect(migrated_sqlite_engine)
    assert "chief_of_staff_report" in inspector.get_table_names()
    assert "chief_of_staff_attempt" in inspector.get_table_names()
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

    attempt_columns = {
        item["name"] for item in inspector.get_columns("chief_of_staff_attempt")
    }
    assert attempt_columns == {
        "attempt_id",
        "context_fingerprint",
        "cadence",
        "period_start",
        "period_end",
        "started_at",
        "completed_at",
        "model_route",
        "model_call_id",
        "reserved_usd",
        "actual_usd",
        "status",
        "stage",
        "result_code",
        "profile_version",
        "context_version",
        "expected_report_version",
        "hermes_version",
    }
    attempt_indexes = {
        tuple(item["column_names"])
        for item in inspector.get_indexes("chief_of_staff_attempt")
    }
    assert ("context_fingerprint", "started_at") in attempt_indexes
    assert ("status", "completed_at") in attempt_indexes


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


def test_0065_upgrades_from_previous_and_downgrades_additive_tables(tmp_path) -> None:
    engine = create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / 'chief-migration-transition.sqlite'}"
    )
    config = alembic_config(engine)
    command.upgrade(config, "0064_company_mail_merge")
    assert "chief_of_staff_attempt" not in sa.inspect(engine).get_table_names()
    command.upgrade(config, "0065_chief_of_staff")
    assert {
        "chief_of_staff_report",
        "chief_of_staff_attempt",
    }.issubset(sa.inspect(engine).get_table_names())
    command.downgrade(config, "0064_company_mail_merge")
    assert "chief_of_staff_report" not in sa.inspect(engine).get_table_names()
    assert "chief_of_staff_attempt" not in sa.inspect(engine).get_table_names()
    engine.dispose()


@pytest.mark.parametrize(
    "deployed_head",
    ("0065_async_prospect_send", "0065_chief_of_staff"),
)
def test_merge_head_upgrades_from_either_parallel_branch(tmp_path, deployed_head) -> None:
    engine = create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / f'merge-from-{deployed_head}.sqlite'}"
    )
    config = alembic_config(engine)
    command.upgrade(config, deployed_head)

    command.upgrade(config, "head")

    tables = set(sa.inspect(engine).get_table_names())
    assert {"prospect_send_request", "chief_of_staff_report"}.issubset(tables)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0073_milomail_a0_prepaid"
        )
    engine.dispose()
