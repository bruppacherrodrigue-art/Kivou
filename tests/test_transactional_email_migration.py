from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.accounts.schema import account
from signals.engagement.schema import signal_alert_delivery
from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    current_revision,
)
from signals.persistence.schema import METADATA

PREVIOUS = "0022_saas_company_profile"
#: La migration que CE fichier décrit. Elle n'est plus la tête depuis 0024,
#: mais reste un pas ADDITIF unique depuis son parent — ce que ce test prouve.
HEAD = "0023_transactional_email_runtime"
CURRENT_HEAD = "0035_landing_signal"
LEASE_TABLE = "signal_alert_job_lease"
NOW = dt.datetime(2026, 8, 23, 10, 0, tzinfo=dt.UTC)


def sqlite_engine(tmp_path: pathlib.Path):
    return create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / 'transactional-email.db'}"
    )


def require_revision(config) -> None:
    scripts = ScriptDirectory.from_config(config)
    if scripts.get_revision(HEAD) is None:
        pytest.fail(f"la migration {HEAD} n'existe pas encore")


def seeded_previous_schema(
    tmp_path: pathlib.Path, *, status: str, error: str | None = None
):
    engine = sqlite_engine(tmp_path)
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(account).values(
                account_id="acc_migration",
                display_name="Migration",
                locale="fr",
                onboarding_status="ready_for_signals",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            sa.insert(signal_alert_delivery).values(
                account_id="acc_migration",
                signal_key="sig_migration",
                status=status,
                cadence="daily",
                queued_at=NOW,
                sent_at=NOW if status == "sent" else None,
                failed_at=NOW if status != "sent" else None,
                attempt_count=1,
                provider_message_id=None,
                last_error_code=error,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    return engine


def read_delivery(engine):
    with engine.connect() as connection:
        columns_at_0023 = tuple(
            column
            for column in signal_alert_delivery.c
            if column.name != "recipient_context_fingerprint"
        )
        return connection.execute(sa.select(*columns_at_0023)).one()


def read_status(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(
            sa.text("SELECT status FROM signal_alert_delivery")
        ).scalar_one()


def test_transactional_email_migration_is_the_single_additive_head(tmp_path) -> None:
    engine = sqlite_engine(tmp_path)
    config = alembic_config(engine)
    require_revision(config)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    assert set(sa.inspect(engine).get_table_names()) - before == {LEASE_TABLE}
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [CURRENT_HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS
    assert (pathlib.Path(scripts.versions) / "0023_transactional_email_runtime.py").is_file()


def test_migrated_schema_matches_declared_delivery_runtime_schema(tmp_path) -> None:
    migrated = sqlite_engine(tmp_path)
    core = create_database_engine("sqlite+pysqlite:///:memory:")
    config = alembic_config(migrated)
    require_revision(config)
    command.upgrade(config, HEAD)
    METADATA.create_all(core)

    for table_name in (signal_alert_delivery.name, LEASE_TABLE):
        migrated_columns = {
            column["name"] for column in sa.inspect(migrated).get_columns(table_name)
        }
        declared_columns = {
            column["name"] for column in sa.inspect(core).get_columns(table_name)
        }
        if table_name == signal_alert_delivery.name:
            declared_columns.remove("recipient_context_fingerprint")
        assert migrated_columns == declared_columns

    checks = sa.inspect(migrated).get_check_constraints(signal_alert_delivery.name)
    status_check = next(check for check in checks if check["name"] == "ck_alert_delivery_status")
    assert "suppressed" in status_check["sqltext"]


@pytest.mark.parametrize("status", ["failed", "unknown_delivery_state"])
def test_historical_failures_become_terminal_without_parsing_error_codes(
    tmp_path, status: str
) -> None:
    engine = seeded_previous_schema(tmp_path, status=status, error="smtp_451")
    config = alembic_config(engine)
    require_revision(config)

    command.upgrade(config, HEAD)

    row = read_delivery(engine)
    assert row.status == status
    assert row.last_error_code == "smtp_451"
    assert row.retryable is False
    assert row.next_attempt_at is None


def test_migration_roundtrip_preserves_existing_delivery_history(tmp_path) -> None:
    engine = seeded_previous_schema(tmp_path, status="sent")
    config = alembic_config(engine)
    require_revision(config)

    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)

    assert read_status(engine) == "sent"
    assert LEASE_TABLE not in sa.inspect(engine).get_table_names()
    assert current_revision(engine) == PREVIOUS

    command.upgrade(config, HEAD)
    assert read_status(engine) == "sent"
    assert current_revision(engine) == HEAD


def test_postgresql_offline_upgrade_and_downgrade_are_scoped(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    require_revision(config)
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")

    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    upgrade_sql = capsys.readouterr().out.lower()
    command.downgrade(config, f"{HEAD}:{PREVIOUS}", sql=True)
    downgrade_sql = capsys.readouterr().out.lower()

    assert upgrade_sql.count(f"create table {LEASE_TABLE} (") == 1
    assert "add column batch_key" in upgrade_sql
    assert "add column retryable" in upgrade_sql
    assert "suppressed" in upgrade_sql
    assert f"drop table {LEASE_TABLE}" in downgrade_sql
    assert "drop column batch_key" in downgrade_sql
    for forbidden in (
        "password",
        "token",
        "recipient",
        "raw_payload",
        "apollo",
        "instantly",
        "campaign",
    ):
        assert forbidden not in upgrade_sql
