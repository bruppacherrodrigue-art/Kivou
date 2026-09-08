"""An upgrade preserves identities without manufacturing proof of possession."""
import datetime as dt

import sqlalchemy as sa
from alembic import command
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signals.accounts.email_verification import email_identity, is_verified_recipient
from signals.accounts.schema import auth_user
from signals.accounts.service import sign_up
from signals.persistence.database import alembic_config, create_database_engine, migrate_to_latest


def test_existing_users_survive_upgrade_but_remain_unverified(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    command.upgrade(alembic_config(engine), "0043_qa_landing")
    now = dt.datetime(2026, 9, 7, tzinfo=dt.UTC)
    with engine.begin() as connection:
        session = sign_up(connection, email="existing@example.com", password="Migration-proof-2026!",
                          company_name="Existing", locale="fr", now=now,
                          session_ttl=dt.timedelta(days=1))
    migrate_to_latest(engine)
    migrate_to_latest(engine)
    with engine.connect() as connection:
        assert connection.scalar(sa.select(auth_user.c.email_normalized)) == "existing@example.com"
        assert connection.scalar(sa.select(sa.func.count()).select_from(email_identity)) == 0
        assert not is_verified_recipient(connection, account_id=session.account_id,
                                         email="existing@example.com")
    engine.dispose()


def test_email_proof_schema_compiles_for_production_postgresql():
    ddl = str(CreateTable(email_identity).compile(dialect=postgresql.dialect()))
    assert "TIMESTAMP WITH TIME ZONE" in ddl
    assert "ON DELETE CASCADE" in ddl
    assert "UNIQUE (token_hash)" in ddl
