from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision

PREVIOUS = "0033_requeue_unresolved_siret"
HEAD = "0034_company_engagement"
CURRENT_HEAD = "0041_for_you_model_fit"


def _engine(tmp_path, name):
    return create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")


def test_company_engagement_migration_adds_three_tables(tmp_path):
    engine = _engine(tmp_path, "company-engagement.db")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())
    command.upgrade(config, HEAD)
    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) - before == {
        "company_contact",
        "company_note",
        "account_visit",
    }
    assert current_revision(engine) == HEAD
    assert ScriptDirectory.from_config(config).get_heads() == [CURRENT_HEAD]


def test_company_contact_schema_is_account_scoped_with_a_closed_status(tmp_path):
    engine = _engine(tmp_path, "company-contact-schema.db")
    command.upgrade(alembic_config(engine), HEAD)
    inspector = sa.inspect(engine)
    columns = {c["name"]: c for c in inspector.get_columns("company_contact")}
    assert set(columns) == {"account_id", "company_key", "status", "contacted_at", "created_at", "updated_at"}
    assert columns["status"]["nullable"] is False
    assert columns["contacted_at"]["nullable"] is True
    assert inspector.get_pk_constraint("company_contact")["constrained_columns"] == ["account_id", "company_key"]
    fks = inspector.get_foreign_keys("company_contact")
    assert len(fks) == 1 and fks[0]["referred_table"] == "account" and fks[0]["options"] == {"ondelete": "CASCADE"}
    checks = {c["name"] for c in inspector.get_check_constraints("company_contact")}
    assert "ck_company_contact_status" in checks
    note_columns = {c["name"]: c for c in inspector.get_columns("company_note")}
    assert set(note_columns) == {"account_id", "company_key", "body", "created_at", "updated_at"}
    assert note_columns["body"]["type"].length == 2000


def test_account_visit_schema_is_a_leaf_table_scoped_to_account(tmp_path):
    engine = _engine(tmp_path, "account-visit-schema.db")
    command.upgrade(alembic_config(engine), HEAD)
    inspector = sa.inspect(engine)
    columns = {c["name"]: c for c in inspector.get_columns("account_visit")}
    assert set(columns) == {"account_id", "last_seen_at", "updated_at"}
    assert columns["last_seen_at"]["nullable"] is False
    assert columns["updated_at"]["nullable"] is False
    assert inspector.get_pk_constraint("account_visit")["constrained_columns"] == ["account_id"]
    fks = inspector.get_foreign_keys("account_visit")
    assert len(fks) == 1 and fks[0]["referred_table"] == "account" and fks[0]["options"] == {"ondelete": "CASCADE"}


def test_company_engagement_migration_roundtrips(tmp_path):
    engine = _engine(tmp_path, "company-engagement-roundtrip.db")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert "company_contact" not in tables
    assert "company_note" not in tables
    assert "account_visit" not in tables
    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD
