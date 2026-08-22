from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_provider_event,
    acquisition_provider_operation,
)

COMPLIANCE = "0014_compliance"
PREVIOUS = "0015_scheduled_cancellation"
HEAD = "0016_campaign_factory"
LATEST = "0017_target_icp_revision"
TABLES = (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_provider_operation,
    acquisition_provider_event,
)


def test_campaign_migration_is_linear_and_adds_exactly_four_tables(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'campaigns.db'}")
    config = alembic_config(engine)
    command.upgrade(config, COMPLIANCE)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    assert set(sa.inspect(engine).get_table_names()) - before == {table.name for table in TABLES}
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [LATEST]
    assert scripts.get_revision(LATEST).down_revision == HEAD
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS
    assert scripts.get_revision(PREVIOUS).down_revision == COMPLIANCE
    versions = pathlib.Path(scripts.versions)
    assert (versions / "0015_scheduled_cancellation.py").is_file()
    assert (versions / "0016_campaign_factory.py").is_file()
    assert (versions / "0017_target_icp_revision.py").is_file()
    assert not (versions / "0015_campaign_factory.py").exists()
    assert not any(path.name.startswith("0016_merge") for path in versions.glob("*.py"))


def test_fresh_database_reaches_0016_with_scheduled_cancellation_column(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'fresh.db'}")
    config = alembic_config(engine)

    command.upgrade(config, HEAD)

    assert current_revision(engine) == HEAD
    assert "scheduled_cancellation_at" in {
        column["name"] for column in sa.inspect(engine).get_columns("billing_subscription")
    }
    assert {table.name for table in TABLES} <= set(sa.inspect(engine).get_table_names())


def test_campaign_schema_is_pii_and_secret_minimized() -> None:
    forbidden = {
        "business_email",
        "email",
        "first_name",
        "last_name",
        "display_name",
        "phone",
        "subject",
        "body",
        "html",
        "reply_text",
        "reply_html",
        "api_key",
        "webhook_secret",
        "raw_request",
        "raw_response",
        "raw_payload",
    }
    for table in TABLES:
        assert forbidden.isdisjoint(column.name for column in table.columns)

    assert {
        "campaign_group_key",
        "batch_generation",
        "membership_close_at",
        "membership_closed_at",
        "step_2_authorization_deadline",
        "lifecycle",
    } <= {column.name for column in acquisition_campaign.columns}
    assert {
        "execution_state",
        "sequence_state",
        "sequence_authorization_fingerprint",
        "sequence_timing_fingerprint",
        "policy_provenance",
        "step_2_due_at",
    } <= {column.name for column in acquisition_campaign_member.columns}


def test_campaign_upgrade_downgrade_reupgrade_and_schema_parity(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'roundtrip.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    command.upgrade(config, HEAD)
    inspector = sa.inspect(engine)

    for table in TABLES:
        assert {column["name"] for column in inspector.get_columns(table.name)} == {
            column.name for column in table.columns
        }
    assert current_revision(engine) == HEAD
    assert {item["name"] for item in inspector.get_unique_constraints("acquisition_campaign")} == {
        "uq_campaign_group_generation",
        "uq_campaign_provider_id",
    }
    assert {item["name"] for item in inspector.get_unique_constraints("acquisition_campaign_member")} >= {
        "uq_campaign_member_opportunity",
        "uq_campaign_member_provider_lead",
    }

    command.downgrade(config, PREVIOUS)
    names = set(sa.inspect(engine).get_table_names())
    assert {table.name for table in TABLES}.isdisjoint(names)
    assert current_revision(engine) == PREVIOUS
    assert "scheduled_cancellation_at" in {
        column["name"] for column in sa.inspect(engine).get_columns("billing_subscription")
    }

    command.downgrade(config, COMPLIANCE)
    assert "scheduled_cancellation_at" not in {
        column["name"] for column in sa.inspect(engine).get_columns("billing_subscription")
    }
    assert current_revision(engine) == COMPLIANCE

    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD


def test_campaign_postgresql_offline_sql_has_exactly_four_tables(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")
    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    sql = capsys.readouterr().out

    for table in TABLES:
        assert sql.count(f"CREATE TABLE {table.name} (") == 1
    assert "business_email" not in sql
    assert "raw_response" not in sql
    assert sql.count("CREATE TABLE acquisition_") == 4
