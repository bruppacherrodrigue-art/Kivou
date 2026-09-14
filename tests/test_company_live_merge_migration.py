"""Both deployed branch tips upgrade to one head without rewriting history."""

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from migration_head_helpers import CURRENT_HEAD

from signals.persistence.database import alembic_config, create_database_engine, current_revision

MERGE = "0061_company_live_merge"
PARENTS = ("0058_model_call_budget", "0060_boamp_notice_facts")
NOW = dt.datetime(2026, 9, 14, tzinfo=dt.UTC)


def test_company_live_merge_is_the_single_head_with_both_deployed_parents():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    try:
        scripts = ScriptDirectory.from_config(alembic_config(engine))
        assert scripts.get_heads() == [CURRENT_HEAD]
        assert MERGE in {revision.revision for revision in scripts.walk_revisions()}
        assert scripts.get_revision(MERGE).down_revision == PARENTS
        assert scripts.get_revision(PARENTS[0]).down_revision == "0057_directory_contact_keys"
        assert scripts.get_revision(PARENTS[1]).down_revision == "0059_prospecting_state"
    finally:
        engine.dispose()


@pytest.mark.parametrize("previous", PARENTS)
def test_populated_deployed_branch_upgrades_and_replays_without_losing_data(tmp_path, previous):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'merge.db'}")
    try:
        config = alembic_config(engine)
        command.upgrade(config, previous)
        assert current_revision(engine) == previous
        metadata = sa.MetaData()
        account = sa.Table("account", metadata, autoload_with=engine)
        note = sa.Table("signal_note", metadata, autoload_with=engine)
        text = "  exact historical\n text  " if previous == PARENTS[0] else " " + "n" * 1998 + " "
        with engine.begin() as connection:
            connection.execute(
                account.insert(),
                {
                    "account_id": "merge_owner",
                    "display_name": "Merge fixture",
                    "locale": "fr",
                    "onboarding_status": "account_created",
                    "created_at": NOW,
                    "updated_at": NOW,
                },
            )
            values = {
                "account_id": "merge_owner",
                "signal_key": "merge_signal",
                "note": text,
                "created_at": NOW,
                "updated_at": NOW,
            }
            if "revision" in note.c:
                values["revision"] = 9
            connection.execute(note.insert(), values)
            if previous == PARENTS[0]:
                budget = sa.Table("model_daily_budget", metadata, autoload_with=connection)
                connection.execute(
                    budget.insert(),
                    {
                        "usage_date": NOW.date(),
                        "usage": "for_you",
                        "reserved_usd": Decimal("0.125"),
                        "actual_usd": Decimal("0.0625"),
                        "updated_at": NOW,
                    },
                )
            else:
                workflow = sa.Table("signal_workflow", metadata, autoload_with=connection)
                connection.execute(
                    workflow.insert(),
                    {
                        "account_id": "merge_owner",
                        "signal_key": "merge_signal",
                        "status": "new",
                        "revision": 7,
                        "created_at": NOW,
                        "updated_at": NOW,
                    },
                )
            originals = {
                table.name: (table, list(connection.execute(sa.select(table)).mappings()))
                for table in metadata.tables.values()
            }
        for _ in range(2):
            command.upgrade(config, "head")
            assert current_revision(engine) == CURRENT_HEAD
            with engine.connect() as connection:
                for table, rows in originals.values():
                    assert list(connection.execute(sa.select(table)).mappings()) == rows
                assert connection.scalar(sa.text("PRAGMA foreign_keys")) == 1
                assert connection.execute(sa.text("PRAGMA foreign_key_check")).all() == []
                assert (
                    connection.scalar(
                        sa.text(
                            "SELECT name FROM sqlite_master WHERE type='trigger' "
                            "AND name='trg_company_contact_lookup_directory_change'"
                        )
                    )
                    == "trg_company_contact_lookup_directory_change"
                )
            assert {
                "model_daily_budget",
                "model_call_journal",
                "signal_workflow",
                "notice_source_snapshot",
                "notice_award_facts",
            } <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()
