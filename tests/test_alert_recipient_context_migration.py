from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.engagement.schema import signal_alert_delivery
from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    current_revision,
)

PREVIOUS = "0024_scheduled_plan_change"
HEAD = "0025_alert_recipient_context"
RUNTIME = "0026_acquisition_runtime"
SIGNAL_NOTES = "0027_signal_notes"
#: Le maillon intermédiaire reste nommé : la tête n'est plus l'enfant
#: direct de SIGNAL_NOTES, et écraser ce lien ferait passer un test faux.
CARD_PRESENTATION = "0028_card_presentation"
LATEST = "0029_production_observation"
COLUMN = "recipient_context_fingerprint"
INDEX = "ix_signal_alert_delivery_recipient_context_refusal"
NOW = dt.datetime(2026, 8, 25, 10, 0, tzinfo=dt.UTC)


def engine_at_previous(tmp_path: pathlib.Path) -> sa.Engine:
    engine = create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / 'alert-recipient-context.db'}"
    )
    command.upgrade(alembic_config(engine), PREVIOUS)
    serialized_now = NOW.isoformat()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO account (
                    account_id, display_name, locale, onboarding_status,
                    created_at, updated_at
                ) VALUES (
                    :account_id, 'Migration', 'fr', 'ready_for_signals',
                    :now, :now
                )
                """
            ),
            {"account_id": "acc_migration", "now": serialized_now},
        )
        for index, (status, retryable, error_code, attempts) in enumerate(
            (
                ("queued", None, None, 0),
                ("sent", False, None, 1),
                ("failed", False, "smtp_recipient_refused", 7),
                ("unknown_delivery_state", True, "unknown_delivery_state", 2),
            )
        ):
            connection.execute(
                sa.text(
                    """
                    INSERT INTO signal_alert_delivery (
                        account_id, signal_key, status, cadence, queued_at,
                        sent_at, failed_at, attempt_count, retryable,
                        provider_message_id, last_error_code, created_at, updated_at
                    ) VALUES (
                        :account_id, :signal_key, :status, 'daily', :now,
                        :sent_at, :failed_at, :attempt_count, :retryable,
                        NULL, :last_error_code, :now, :now
                    )
                    """
                ),
                {
                    "account_id": "acc_migration",
                    "signal_key": f"sig_{index}",
                    "status": status,
                    "now": serialized_now,
                    "sent_at": serialized_now if status == "sent" else None,
                    "failed_at": (
                        serialized_now
                        if status in {"failed", "unknown_delivery_state"}
                        else None
                    ),
                    "attempt_count": attempts,
                    "retryable": retryable,
                    "last_error_code": error_code,
                },
            )
    return engine


def history(engine: sa.Engine) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                sa.text(
                    """
                    SELECT signal_key, status, attempt_count, retryable,
                           last_error_code, queued_at, sent_at, failed_at
                    FROM signal_alert_delivery
                    ORDER BY signal_key
                    """
                )
            )
        ]


def test_0025_is_additive_and_precedes_the_runtime_head(tmp_path) -> None:
    engine = engine_at_previous(tmp_path)
    before = history(engine)
    config = alembic_config(engine)

    command.upgrade(config, HEAD)

    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [LATEST]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS
    assert scripts.get_revision(LATEST).down_revision == CARD_PRESENTATION
    assert scripts.get_revision(CARD_PRESENTATION).down_revision == SIGNAL_NOTES
    assert scripts.get_revision(SIGNAL_NOTES).down_revision == RUNTIME
    assert scripts.get_revision(RUNTIME).down_revision == HEAD
    assert current_revision(engine) == HEAD
    inspector = sa.inspect(engine)
    columns = {item["name"] for item in inspector.get_columns(signal_alert_delivery.name)}
    assert COLUMN in columns
    assert columns == {column.name for column in signal_alert_delivery.columns}
    indexes = {item["name"]: item for item in inspector.get_indexes(signal_alert_delivery.name)}
    assert indexes[INDEX]["column_names"] == [
        "account_id",
        COLUMN,
        "status",
        "last_error_code",
    ]
    with engine.connect() as connection:
        fingerprints = connection.execute(
            sa.text(f"SELECT {COLUMN} FROM signal_alert_delivery")
        ).scalars()
        assert list(fingerprints) == [None, None, None, None]
    assert history(engine) == before


def test_sqlite_downgrade_and_reupgrade_preserve_all_history(tmp_path) -> None:
    engine = engine_at_previous(tmp_path)
    before = history(engine)
    config = alembic_config(engine)
    command.upgrade(config, HEAD)

    command.downgrade(config, PREVIOUS)

    assert current_revision(engine) == PREVIOUS
    assert COLUMN not in {
        item["name"] for item in sa.inspect(engine).get_columns(signal_alert_delivery.name)
    }
    assert history(engine) == before

    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD
    assert history(engine) == before


def test_postgresql_offline_sql_is_additive_and_never_classifies_history(
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = alembic_config(create_database_engine("sqlite+pysqlite:///:memory:"))
    config.set_main_option(
        "sqlalchemy.url", "postgresql://kivou:placeholder@localhost/kivou"
    )

    command.upgrade(config, f"{PREVIOUS}:{HEAD}", sql=True)
    upgrade_sql = capsys.readouterr().out.lower()
    command.downgrade(config, f"{HEAD}:{PREVIOUS}", sql=True)
    downgrade_sql = capsys.readouterr().out.lower()

    assert f"add column {COLUMN}" in upgrade_sql
    assert f"create index {INDEX}" in upgrade_sql
    assert "update signal_alert_delivery" not in upgrade_sql
    assert "last_error_code =" not in upgrade_sql
    assert f"drop index {INDEX}" in downgrade_sql
    assert f"drop column {COLUMN}" in downgrade_sql
    for forbidden in ("@kivou", "smtp_recipient_refused", "token", "password"):
        assert forbidden not in upgrade_sql
