from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from feed_helpers import SIMAP_RICH, make_account, make_icp, materialize_simap

from signals.companies.schema import saas_company
from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import METADATA, materialized_signal

PREVIOUS = "0021_reliability_operations"
HEAD = "0022_saas_company_profile"
CURRENT_HEAD = "0029_production_observation_boundary"


def test_company_migration_is_the_single_additive_head(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'company.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    assert set(sa.inspect(engine).get_table_names()) - before == {saas_company.name}
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [CURRENT_HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS
    assert (pathlib.Path(scripts.versions) / "0022_saas_company_profile.py").is_file()


def test_company_migration_roundtrip_matches_core_schema(tmp_path) -> None:
    migrated = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'migrated.db'}")
    core = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    config = alembic_config(migrated)
    command.upgrade(config, HEAD)
    METADATA.create_all(core)

    assert {column["name"] for column in sa.inspect(migrated).get_columns(saas_company.name)} == {
        column["name"] for column in sa.inspect(core).get_columns(saas_company.name)
    }

    command.downgrade(config, PREVIOUS)
    assert saas_company.name not in sa.inspect(migrated).get_table_names()
    assert current_revision(migrated) == PREVIOUS
    command.upgrade(config, HEAD)
    assert current_revision(migrated) == HEAD


def test_company_postgresql_sql_is_scoped_and_client_safe(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")
    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    sql = capsys.readouterr().out.lower()

    assert sql.count("create table saas_company (") == 1
    assert "unique (identity_fingerprint)" in sql
    assert "foreign key(source_award_key) references contract_award" in sql
    assert "foreign key(origin_signal_key) references materialized_signal" in sql
    for forbidden in (
        "apollo",
        "acquisition",
        "contact_ref",
        "supplier_ref",
        "email",
        "phone",
        "raw_payload",
        "api_key",
    ):
        assert forbidden not in sql


def test_company_migration_backfills_the_index_for_existing_signals(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'backfill.db'}")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    with engine.begin() as connection:
        account_id = make_account(connection, "company-backfill@kivou.test", "Backfill")
        icp_id = make_icp(connection, account_id)
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_id)
        assert connection.scalar(
            sa.select(materialized_signal.c.company_identity_fingerprint).where(
                materialized_signal.c.signal_key == signal.signal_key
            )
        )

    command.downgrade(config, PREVIOUS)
    assert "company_identity_fingerprint" not in {
        column["name"] for column in sa.inspect(engine).get_columns(materialized_signal.name)
    }

    command.upgrade(config, HEAD)
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(materialized_signal.c.company_identity_fingerprint).where(
                materialized_signal.c.signal_key == signal.signal_key
            )
        )
