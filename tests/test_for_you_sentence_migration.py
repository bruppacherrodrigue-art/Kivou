from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision

PREVIOUS = "0038_landing_journey"
HEAD = "0039_for_you_sentence"


def test_for_you_migration_adds_durable_bounded_generation_queue(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'for-you.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)

    command.upgrade(config, HEAD)

    inspector = sa.inspect(engine)
    assert current_revision(engine) == HEAD
    assert ScriptDirectory.from_config(config).get_heads() == [HEAD]
    columns = {column["name"] for column in inspector.get_columns("for_you_sentence")}
    assert columns == {
        "for_you_id", "signal_key", "target_icp_id", "signal_fingerprint",
        "profile_fingerprint", "policy_version", "sentence", "fallback_sentence",
        "provenance", "state", "validation_reason", "validation_detail",
        "attempt_day", "lease_owner", "lease_expires_at", "input_snapshot",
        "provider_usage", "created_at", "updated_at", "completed_at",
    }
    uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("for_you_sentence")}
    assert ("signal_key", "target_icp_id", "signal_fingerprint", "profile_fingerprint", "policy_version") in uniques


def test_for_you_migration_roundtrips(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'roundtrip.db'}")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    assert "for_you_sentence" not in sa.inspect(engine).get_table_names()
