from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import acquisition_personalization_artifact

PREVIOUS = "0012_decision_engine"
HEAD = "0013_personalization"


def test_personalization_migration_is_linear_and_adds_one_artifact_table(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'personalization.db'}")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())

    command.upgrade(config, HEAD)

    assert set(sa.inspect(engine).get_table_names()) - before == {
        "acquisition_personalization_artifact"
    }
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS
    assert len(HEAD) <= 32


def test_personalization_schema_contains_no_separate_contact_or_model_pii_columns() -> None:
    columns = {column.name for column in acquisition_personalization_artifact.columns}

    assert {"first_name", "last_name", "display_name", "business_email", "phone", "linkedin"}.isdisjoint(columns)
    assert {"provider", "model", "raw_provider_response"}.isdisjoint(columns)
    assert {"policy_evaluation_id", "language", "subject", "greeting", "body", "cta"} <= columns
