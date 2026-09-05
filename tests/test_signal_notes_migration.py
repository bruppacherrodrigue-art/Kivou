from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    current_revision,
)

PREVIOUS = "0026_acquisition_runtime"
HEAD = "0027_signal_notes"
CURRENT_HEAD = "0042_account_deletion"


def _engine(tmp_path, name):
    return create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")


def test_signal_note_migration_is_one_additive_table(tmp_path):
    engine = _engine(tmp_path, "signal-note.db")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())
    command.upgrade(config, HEAD)
    assert set(sa.inspect(engine).get_table_names()) - before == {"signal_note"}
    assert current_revision(engine) == HEAD
    assert ScriptDirectory.from_config(config).get_heads() == [CURRENT_HEAD]


def test_signal_note_schema_has_exact_account_scope_and_note_capacity(tmp_path):
    engine = _engine(tmp_path, "signal-note-schema.db")
    command.upgrade(alembic_config(engine), HEAD)
    inspector = sa.inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("signal_note")}

    assert set(columns) == {"account_id", "signal_key", "note", "created_at", "updated_at"}
    assert columns["account_id"]["nullable"] is False
    assert columns["signal_key"]["nullable"] is False
    assert columns["note"]["nullable"] is False
    assert columns["created_at"]["nullable"] is False
    assert columns["updated_at"]["nullable"] is False
    assert columns["note"]["type"].length == 500
    assert inspector.get_pk_constraint("signal_note")["constrained_columns"] == [
        "account_id",
        "signal_key",
    ]
    foreign_keys = inspector.get_foreign_keys("signal_note")
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["constrained_columns"] == ["account_id"]
    assert foreign_keys[0]["referred_table"] == "account"
    assert foreign_keys[0]["referred_columns"] == ["account_id"]
    assert foreign_keys[0]["options"] == {"ondelete": "CASCADE"}


def test_signal_note_migration_roundtrips_without_touching_feedback(tmp_path):
    engine = _engine(tmp_path, "signal-note-roundtrip.db")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    assert "signal_feedback" in sa.inspect(engine).get_table_names()
    command.downgrade(config, PREVIOUS)
    tables = set(sa.inspect(engine).get_table_names())
    assert "signal_note" not in tables
    assert "signal_feedback" in tables
    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD
