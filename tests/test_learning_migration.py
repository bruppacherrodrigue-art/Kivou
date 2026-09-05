from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import (
    METADATA,
    acquisition_allocation_proposal,
    acquisition_learning_snapshot,
)

HEAD = "0020_hermes_learning_loop"
RELIABILITY = "0021_reliability_operations"
COMPANY = "0022_saas_company_profile"
#: Le maillon intermédiaire reste nommé : la tête n'est plus l'enfant
#: direct de COMPANY, et écraser ce lien ferait passer un test faux.
EMAIL = "0023_transactional_email_runtime"
SCHEDULED_PLAN = "0024_scheduled_plan_change"
ALERT_RECIPIENT_CONTEXT = "0025_alert_recipient_context"
RUNTIME = "0026_acquisition_runtime"
SIGNAL_NOTES = "0027_signal_notes"
#: Le maillon intermédiaire reste nommé : la tête n'est plus l'enfant
#: direct de SIGNAL_NOTES, et écraser ce lien ferait passer un test faux.
CARD_PRESENTATION = "0028_card_presentation"
PRODUCTION_OBSERVATION = "0029_production_observation"
#: Le maillon intermédiaire reste nommé : la tête n'est plus l'enfant
#: direct de PRODUCTION_OBSERVATION, et écraser ce lien ferait passer un test faux.
WINNER_ENRICHMENT = "0030_winner_enrichment"
FRENCH_OFFICIAL_COMPANY = "0031_french_official_company"
REQUEUE_SIRET_PLACEHOLDERS = "0032_requeue_siret_placeholders"
#: Le maillon intermédiaire reste nommé : la tête n'est plus l'enfant
#: direct de REQUEUE_SIRET_PLACEHOLDERS, et écraser ce lien ferait passer un test faux.
REQUEUE_UNRESOLVED_SIRET = "0033_requeue_unresolved_siret"
LATEST = "0042_account_deletion"
TABLES = {"acquisition_learning_snapshot", "acquisition_allocation_proposal"}


def test_learning_migration_is_one_linear_head_with_exactly_two_tables(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'learning.db'}")
    config = alembic_config(engine)
    command.upgrade(config, "head")

    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [LATEST]
    assert scripts.get_revision(LATEST).down_revision == "0041_for_you_model_fit"
    assert scripts.get_revision(REQUEUE_UNRESOLVED_SIRET).down_revision == REQUEUE_SIRET_PLACEHOLDERS
    assert (
        scripts.get_revision(REQUEUE_SIRET_PLACEHOLDERS).down_revision
        == FRENCH_OFFICIAL_COMPANY
    )
    assert scripts.get_revision(FRENCH_OFFICIAL_COMPANY).down_revision == WINNER_ENRICHMENT
    assert scripts.get_revision(WINNER_ENRICHMENT).down_revision == PRODUCTION_OBSERVATION
    assert scripts.get_revision(PRODUCTION_OBSERVATION).down_revision == CARD_PRESENTATION
    assert scripts.get_revision(CARD_PRESENTATION).down_revision == SIGNAL_NOTES
    assert scripts.get_revision(SIGNAL_NOTES).down_revision == RUNTIME
    assert scripts.get_revision(RUNTIME).down_revision == ALERT_RECIPIENT_CONTEXT
    assert scripts.get_revision(ALERT_RECIPIENT_CONTEXT).down_revision == SCHEDULED_PLAN
    assert scripts.get_revision(SCHEDULED_PLAN).down_revision == EMAIL
    assert scripts.get_revision(EMAIL).down_revision == COMPANY
    assert scripts.get_revision(COMPANY).down_revision == RELIABILITY
    assert scripts.get_revision(RELIABILITY).down_revision == HEAD
    assert scripts.get_revision(HEAD).down_revision == "0019_conversion_tracking"
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == LATEST
    assert TABLES.issubset(sa.inspect(engine).get_table_names())
    indexes = {
        index["name"]: index
        for index in sa.inspect(engine).get_indexes("acquisition_allocation_proposal")
    }
    assert indexes["uq_learning_snapshot_selected_proposal"]["unique"] == 1


def test_0019_upgrade_downgrade_reupgrade_and_core_parity(tmp_path) -> None:
    migrated = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'migrated.db'}")
    core = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    config = alembic_config(migrated)
    command.upgrade(config, "0019_conversion_tracking")
    assert not TABLES.intersection(sa.inspect(migrated).get_table_names())
    command.upgrade(config, HEAD)
    command.downgrade(config, "0019_conversion_tracking")
    assert not TABLES.intersection(sa.inspect(migrated).get_table_names())
    assert "acquisition_conversion_event" in sa.inspect(migrated).get_table_names()
    command.upgrade(config, HEAD)
    METADATA.create_all(core)
    for table in TABLES:
        assert {item["name"] for item in sa.inspect(migrated).get_columns(table)} == {
            item["name"] for item in sa.inspect(core).get_columns(table)
        }
    assert {
        (item["name"], item["unique"])
        for item in sa.inspect(migrated).get_indexes("acquisition_allocation_proposal")
    } == {
        (item["name"], item["unique"])
        for item in sa.inspect(core).get_indexes("acquisition_allocation_proposal")
    }


def test_learning_tables_are_pii_minimized_and_allocation_is_bounded() -> None:
    forbidden = {"email", "contact", "account", "stripe", "provider", "response_body"}
    for table in (acquisition_learning_snapshot, acquisition_allocation_proposal):
        assert not any(
            marker in column.name.casefold() for marker in forbidden for column in table.c
        )


def test_proposal_constraints_reject_unbounded_delta(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'constraints.db'}")
    command.upgrade(alembic_config(engine), HEAD)
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            sa.insert(acquisition_allocation_proposal).values(
                proposal_ref="a" * 64,
                snapshot_ref="b" * 64,
                proposal_version="learning-proposal-v1",
                candidate_version="learning-candidate-generation-v1",
                allocation_envelope_fingerprint="c" * 64,
                baseline_authority_ref="INITIAL:" + "c" * 64,
                current_allocation_fingerprint="d" * 64,
                proposed_allocation_fingerprint="e" * 64,
                current_allocation=[],
                proposed_allocation=[],
                delta_units=2,
                expected_score_delta=0,
                reason_codes=[],
                state="PROPOSED",
                created_at=sa.func.now(),
            )
        )


def test_postgresql_offline_sql_contains_two_tables_and_linear_revision(capsys) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")
    command.upgrade(config, f"0019_conversion_tracking:{HEAD}", sql=True)
    sql = capsys.readouterr().out

    assert "CREATE TABLE acquisition_learning_snapshot" in sql
    assert "CREATE TABLE acquisition_allocation_proposal" in sql
    assert "CREATE UNIQUE INDEX uq_learning_snapshot_selected_proposal" in sql
    assert "0020_hermes_learning_loop" in sql
