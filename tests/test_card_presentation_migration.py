from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision
from signals.persistence.schema import card_presentation_artifact

PREVIOUS = "0027_signal_notes"
HEAD = "0028_card_presentation"


def _engine(tmp_path, name):
    return create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")


def test_card_presentation_migration_is_one_additive_table(tmp_path):
    engine = _engine(tmp_path, "card-presentation.db")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    assert set(sa.inspect(engine).get_table_names()) - before == {
        card_presentation_artifact.name
    }
    assert current_revision(engine) == HEAD
    assert ScriptDirectory.from_config(config).get_heads() == [HEAD]


def test_card_presentation_schema_is_scoped_versioned_and_fail_closed(tmp_path):
    engine = _engine(tmp_path, "card-presentation-schema.db")
    command.upgrade(alembic_config(engine), HEAD)
    inspector = sa.inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns(
        card_presentation_artifact.name
    )}
    assert set(columns) == {
        "artifact_id",
        "account_id",
        "signal_key",
        "target_icp_id",
        "artifact_kind",
        "language",
        "version",
        "signal_revision",
        "target_icp_revision",
        "input_fingerprint",
        "schema_version",
        "prompt_version",
        "model_id",
        "provider",
        "input_snapshot",
        "payload",
        "qa_status",
        "qa_reasons",
        "qa_model_id",
        "qa_provider",
        "qa_policy_version",
        "created_at",
        "published_at",
        "superseded_at",
    }
    assert columns["account_id"]["nullable"] is False
    assert columns["target_icp_id"]["nullable"] is False
    assert columns["payload"]["nullable"] is True
    foreign_keys = {
        tuple(key["constrained_columns"]): (key["referred_table"], key["options"])
        for key in inspector.get_foreign_keys(card_presentation_artifact.name)
    }
    assert foreign_keys == {
        ("account_id",): ("account", {"ondelete": "CASCADE"}),
        ("signal_key",): ("materialized_signal", {"ondelete": "CASCADE"}),
        ("target_icp_id",): ("target_icp", {"ondelete": "CASCADE"}),
    }
    indexes = {
        index["name"]: index for index in inspector.get_indexes(card_presentation_artifact.name)
    }
    assert indexes["uq_card_presentation_active_publication"]["unique"] == 1


def test_card_presentation_migration_roundtrips(tmp_path):
    engine = _engine(tmp_path, "card-presentation-roundtrip.db")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    assert card_presentation_artifact.name not in sa.inspect(engine).get_table_names()
    assert current_revision(engine) == PREVIOUS
    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD


def test_card_presentation_postgresql_sql_contains_no_provider_payload(capsys):
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option("sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou")
    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    sql = capsys.readouterr().out.lower()
    assert "create table card_presentation_artifact" in sql
    assert "qa_status in ('pass', 'regenerate', 'fallback', 'review')" in sql
    assert "create unique index uq_card_presentation_active_publication" in sql
    assert "where published_at is not null and superseded_at is null" in sql
    for forbidden in ("raw_prompt", "raw_response", "api_key", "apollo", "contact_email"):
        assert forbidden not in sql
