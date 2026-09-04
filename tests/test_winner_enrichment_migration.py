"""The winner-enrichment queue is additive, durable and fact-only."""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from feed_helpers import make_account, make_icp, materialize_simap
from sqlalchemy.exc import IntegrityError

from signals.companies.schema import saas_company, winner_enrichment_job
from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import METADATA, materialized_signal

PREVIOUS = "0029_production_observation"
HEAD = "0030_winner_enrichment"
FRENCH_OFFICIAL_COMPANY = "0031_french_official_company"
REQUEUE_SIRET_PLACEHOLDERS = "0032_requeue_siret_placeholders"
#: Le maillon intermédiaire reste nommé : la tête n'est plus l'enfant
#: direct de REQUEUE_SIRET_PLACEHOLDERS, et écraser ce lien ferait passer un test faux.
REQUEUE_UNRESOLVED_SIRET = "0033_requeue_unresolved_siret"
LATEST = "0038_landing_journey"


def _engine(path: pathlib.Path):
    return create_database_engine(f"sqlite+pysqlite:///{path}")


def test_migration_is_the_single_additive_head(tmp_path) -> None:
    engine = _engine(tmp_path / "migration.db")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    assert set(sa.inspect(engine).get_table_names()) - before == {
        winner_enrichment_job.name
    }
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [LATEST]
    assert scripts.get_revision(LATEST).down_revision == "0037_portal_capture_runtime"
    assert scripts.get_revision(REQUEUE_UNRESOLVED_SIRET).down_revision == REQUEUE_SIRET_PLACEHOLDERS
    assert (
        scripts.get_revision(REQUEUE_SIRET_PLACEHOLDERS).down_revision
        == FRENCH_OFFICIAL_COMPANY
    )
    assert scripts.get_revision(FRENCH_OFFICIAL_COMPANY).down_revision == HEAD
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS
    assert (pathlib.Path(scripts.versions) / "0030_winner_enrichment.py").is_file()


def test_migration_roundtrip_matches_core_schema(tmp_path) -> None:
    migrated = _engine(tmp_path / "migrated.db")
    core = _engine(tmp_path / "core.db")
    config = alembic_config(migrated)
    command.upgrade(config, HEAD)
    METADATA.create_all(core)

    expected = {
        "signal_key",
        "identity_fingerprint",
        "status",
        "attempt_count",
        "error_code",
        "claimed_by",
        "queued_at",
        "started_at",
        "finished_at",
        "updated_at",
    }
    assert {
        column["name"]
        for column in sa.inspect(migrated).get_columns(winner_enrichment_job.name)
    } == expected
    assert expected == {
        column["name"]
        for column in sa.inspect(core).get_columns(winner_enrichment_job.name)
    }

    command.downgrade(config, PREVIOUS)
    assert winner_enrichment_job.name not in sa.inspect(migrated).get_table_names()
    assert current_revision(migrated) == PREVIOUS
    command.upgrade(config, HEAD)
    assert current_revision(migrated) == HEAD


def test_backfill_classifies_existing_company_without_network(tmp_path) -> None:
    engine = _engine(tmp_path / "backfill.db")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    observed_at = dt.datetime(2026, 8, 18, 9, 0, tzinfo=dt.UTC)
    with engine.begin() as connection:
        account_id = make_account(connection, "winner-migration@kivou.eu", "Winner")
        icp_id = make_icp(connection, account_id)
        completed_signal = materialize_simap(
            connection, "33112-02", target_icp_id=icp_id
        )
        pending_signal = materialize_simap(
            connection, "29997-02", target_icp_id=icp_id
        )
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == pending_signal.signal_key)
            .values(company_identity_fingerprint=None)
        )
        completed = connection.execute(
            sa.select(
                materialized_signal.c.company_identity_fingerprint,
                materialized_signal.c.materialization_award_key,
            ).where(materialized_signal.c.signal_key == completed_signal.signal_key)
        ).one()
        assert completed.company_identity_fingerprint
        connection.execute(
            sa.insert(saas_company).values(
                company_key="cmp_existing_company_1234",
                identity_fingerprint=completed.company_identity_fingerprint,
                identity_method="official_identifier",
                identity_validation={"source": "fixture"},
                source_award_key=completed.materialization_award_key,
                origin_signal_key=completed_signal.signal_key,
                official_name="Entreprise publiée SA",
                official_country="CH",
                official_address="Rue publiée 1, Lausanne",
                official_identifiers=[{"scheme": "UID", "value": "CHE-100.000.001"}],
                official_website_url="https://winner.example.ch",
                official_observed_at=observed_at,
                created_at=observed_at,
                updated_at=observed_at,
            )
        )

    command.downgrade(config, PREVIOUS)
    command.upgrade(config, HEAD)

    with engine.connect() as connection:
        rows = {
            row.signal_key: row
            for row in connection.execute(sa.select(winner_enrichment_job))
        }
    assert rows[completed_signal.signal_key].status == "completed"
    assert rows[completed_signal.signal_key].attempt_count == 1
    assert rows[completed_signal.signal_key].finished_at is not None
    assert rows[pending_signal.signal_key].status == "pending"
    assert rows[pending_signal.signal_key].identity_fingerprint is None
    assert rows[pending_signal.signal_key].attempt_count == 0
    assert rows[pending_signal.signal_key].started_at is None


def test_database_rejects_an_impossible_state(tmp_path) -> None:
    engine = _engine(tmp_path / "constraints.db")
    command.upgrade(alembic_config(engine), HEAD)
    with engine.begin() as connection:
        account_id = make_account(connection, "winner-constraint@kivou.eu", "Winner")
        icp_id = make_icp(connection, account_id)
        signal = materialize_simap(connection, "33112-02", target_icp_id=icp_id)
        connection.execute(
            sa.delete(winner_enrichment_job).where(
                winner_enrichment_job.c.signal_key == signal.signal_key
            )
        )
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                sa.insert(winner_enrichment_job).values(
                    signal_key=signal.signal_key,
                    status="completed",
                    attempt_count=0,
                    queued_at=dt.datetime.now(dt.UTC),
                    updated_at=dt.datetime.now(dt.UTC),
                )
            )


def test_postgresql_sql_contains_only_the_additive_queue(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")
    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    sql = capsys.readouterr().out.lower()

    assert sql.count("create table winner_enrichment_job (") == 1
    assert "foreign key(signal_key) references materialized_signal" in sql
    assert "insert into winner_enrichment_job" in sql
    assert "drop table saas_company" not in sql
    for forbidden in ("apollo", "hermes", "acquisition", "http", "provider", "prompt"):
        assert forbidden not in sql
