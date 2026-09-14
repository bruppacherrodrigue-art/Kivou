"""Both deployed branch tips upgrade to one head without rewriting history."""

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from signals.persistence.database import alembic_config, create_database_engine, current_revision

MERGE = "0061_company_live_merge"
PARENTS = ("0058_model_call_budget", "0060_boamp_notice_facts")
MAIL_MERGE = "0064_company_mail_merge"
MAIL_PARENTS = ("0063_catalogue_mirror", "0059_prospect_mail_word_limit_v2")
NOW = dt.datetime(2026, 9, 14, tzinfo=dt.UTC)


def test_incoming_mail_branch_has_one_additive_head_without_rewriting_history():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    try:
        scripts = ScriptDirectory.from_config(alembic_config(engine))
        assert len(scripts.get_heads()) == 1
        from migration_head_helpers import CURRENT_HEAD

        assert scripts.get_heads() == [CURRENT_HEAD]
        assert scripts.get_revision(MAIL_MERGE).down_revision == MAIL_PARENTS
        assert scripts.get_revision(MERGE).down_revision == PARENTS
        assert scripts.get_revision(MAIL_PARENTS[1]).down_revision == PARENTS[0]
        assert "0056_prospect_mail_word_limit_v2" not in {
            revision.revision for revision in scripts.walk_revisions()
        }
    finally:
        engine.dispose()


def test_company_live_merge_is_the_single_head_with_both_deployed_parents():
    from migration_head_helpers import CURRENT_HEAD

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


@pytest.mark.parametrize("previous", (*PARENTS, *MAIL_PARENTS))
def test_populated_deployed_branch_upgrades_and_replays_without_losing_data(tmp_path, previous):
    from migration_head_helpers import CURRENT_HEAD

    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'merge.db'}")
    try:
        config = alembic_config(engine)
        command.upgrade(config, previous)
        assert current_revision(engine) == previous
        metadata = sa.MetaData()
        account = sa.Table("account", metadata, autoload_with=engine)
        note = sa.Table("signal_note", metadata, autoload_with=engine)
        budget_branch = previous in (PARENTS[0], MAIL_PARENTS[1])
        text = "  exact historical\n text  " if budget_branch else " " + "n" * 1998 + " "
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
            if budget_branch:
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
            directory = sa.Table("supplier_directory", metadata, autoload_with=connection)
            connection.execute(
                directory.insert(),
                {
                    "siren": "123456789",
                    "legal_name": "Mail merge fixture",
                    "legal_name_observed_at": NOW,
                    "family_keys": [],
                    "families_observed_at": NOW,
                    "directors": [],
                    "created_at": NOW,
                    "updated_at": NOW,
                },
            )
            target = sa.Table("prospect_target", metadata, autoload_with=connection)
            # 0060's historical SQLite path still batch-rebuilds supplier_directory
            # in 0058. Exercise populated mail rows once that branch is already applied.
            if previous != PARENTS[1]:
                connection.execute(
                    target.insert(),
                    {
                        "target_id": "merge_target",
                        "opportunity_key": "merge_opportunity",
                        "procedure_award_key": "merge_award",
                        "siren": "123456789",
                        "company_name": "Mail merge fixture",
                        "company_city": "Paris",
                        "company_employees": 10,
                        "vertical": "general_building",
                        "family_key": "ready_mix_concrete",
                        "family_label": "Concrete",
                        "email_address": "merge@example.invalid",
                        "email_source": "manual",
                        "email_verification_status": "mx_verified",
                        "signal_holder": "Fixture holder",
                        "signal_subject": "Fixture subject",
                        "signal_amount_minor_units": 10000,
                        "signal_currency": "eur",
                        "signal_location": "Paris",
                        "signal_decision_date": NOW.date(),
                        "signal_source_url": "https://www.boamp.fr/avis/fixture",
                        "mail_subject": "Exact stored subject",
                        "mail_text": "  Exact stored\n mail text  ",
                        "mail_html": "<p>Exact stored mail text</p>",
                        "attribution_url": "https://example.invalid/attribution",
                        "attribution_member_ref": "m" * 64,
                        "attribution_payload": {"fixture": "preserved"},
                        "attribution_token_fingerprint": "f" * 64,
                        "unsubscribe_url": "https://example.invalid/unsubscribe",
                        "mail_word_count": 110 if previous == MAIL_PARENTS[1] else 90,
                        "status": "pending_review",
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
            inspector = sa.inspect(engine)
            assert {
                "model_daily_budget",
                "model_call_journal",
                "signal_workflow",
                "notice_source_snapshot",
                "notice_award_facts",
            } <= set(inspector.get_table_names())
            assert {
                check["name"]: check["sqltext"]
                for check in inspector.get_check_constraints("prospect_target")
            }["ck_prospect_target_words"] == "mail_word_count BETWEEN 1 AND 110"
            # The incoming migration's real DB constraint survives populated mail and replay.
            if previous == PARENTS[1]:
                continue
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.execute(target.update().values(mail_word_count=110))
                    with pytest.raises(sa.exc.IntegrityError, match="ck_prospect_target_words"):
                        connection.execute(target.update().values(mail_word_count=111))
                finally:
                    transaction.rollback()
    finally:
        engine.dispose()
