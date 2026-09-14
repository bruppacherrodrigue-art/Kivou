"""Populated 0058 upgrades preserve private history on SQLite and optional local PostgreSQL.

KIVOU_TEST_POSTGRES_URL opts into a disposable test database. Every test uses
its own generated schema; existing schemas are never modified.
"""

import datetime as dt
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from migration_head_helpers import CURRENT_HEAD as HEAD

from signals.client_value.company_identity import register_alias, resolve_subject
from signals.engagement import company, notes
from signals.engagement.schema import (
    signal_feedback,
    signal_workflow,
)
from signals.persistence.database import alembic_config, create_database_engine, current_revision

PREVIOUS = "0058_client_location"
NOW = dt.datetime(2026, 9, 13, 8, tzinfo=dt.UTC)


@pytest.fixture(params=["sqlite", "postgresql"])
def engine(request, tmp_path):
    if request.param == "sqlite":
        database = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'upgrade.db'}")
        yield database
        database.dispose()
        return
    url = os.getenv("KIVOU_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("KIVOU_TEST_POSTGRES_URL is not set for a disposable PostgreSQL")
    schema = f"kivou_v11_test_{uuid.uuid4().hex}"
    admin = create_database_engine(url)
    with admin.begin() as connection:
        connection.execute(sa.schema.CreateSchema(schema))
    database = create_database_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield database
    finally:
        database.dispose()
        with admin.begin() as connection:
            connection.execute(sa.schema.DropSchema(schema, cascade=True))
        admin.dispose()


def populated_0058(engine):
    command.upgrade(alembic_config(engine), PREVIOUS)
    metadata = sa.MetaData()
    tables = {
        name: sa.Table(name, metadata, autoload_with=engine)
        for name in (
            "account",
            "signal_note",
            "company_note",
            "signal_feedback",
            "company_contact",
        )
    }
    with engine.begin() as connection:
        connection.execute(
            sa.insert(tables["account"]),
            [
                {
                    "account_id": owner,
                    "display_name": owner,
                    "locale": "fr",
                    "onboarding_status": "account_created",
                    "created_at": NOW,
                    "updated_at": NOW,
                }
                for owner in ("account_a", "account_b")
            ],
        )
        connection.execute(
            sa.insert(tables["signal_note"]),
            [
                {
                    "account_id": owner,
                    "signal_key": "sig_shared",
                    "note": text,
                    "created_at": NOW,
                    "updated_at": NOW,
                }
                for owner, text in (
                    ("account_a", "  Historical\n note  "),
                    ("account_b", "Other account"),
                )
            ],
        )
        connection.execute(
            sa.insert(tables["company_note"]),
            {
                "account_id": "account_a",
                "company_key": "cmp_legacy",
                "body": "  Company\n history  ",
                "created_at": NOW,
                "updated_at": NOW,
            },
        )
        connection.execute(
            sa.insert(tables["company_contact"]),
            {
                "account_id": "account_a",
                "company_key": "cmp_legacy",
                "status": "replied",
                "contacted_at": NOW,
                "created_at": NOW,
                "updated_at": NOW,
            },
        )
        connection.execute(
            sa.insert(tables["signal_feedback"]),
            [
                {
                    "account_id": owner,
                    "signal_key": key,
                    "relevance": relevance,
                    "note": "f" * 500,
                    "contacted_at": contacted,
                    "created_at": NOW,
                    "updated_at": NOW,
                }
                for owner, key, relevance, contacted in (
                    ("account_a", "sig_saved", "relevant", None),
                    ("account_a", "sig_ignored", "not_relevant", None),
                    ("account_a", "sig_contacted", "not_relevant", NOW),
                    ("account_b", "sig_saved", "not_relevant", None),
                )
            ],
        )
        return {
            name: [dict(row) for row in connection.execute(sa.select(table)).mappings()]
            for name, table in tables.items()
        }


def test_populated_0058_upgrade_retains_notes_feedback_contacts_and_account_scope(engine):
    before = populated_0058(engine)
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD
    assert ScriptDirectory.from_config(config).get_heads() == [HEAD]
    with engine.connect() as connection:
        for name, rows in before.items():
            table = sa.Table(name, sa.MetaData(), autoload_with=connection)
            actual = [dict(row) for row in connection.execute(sa.select(table)).mappings()]
            if name in ("signal_note", "company_note"):
                assert all(row.pop("revision") == 1 for row in actual)
            assert actual == rows
        workflows = connection.execute(sa.select(signal_workflow)).mappings().all()
        assert {
            (row["account_id"], row["signal_key"]): (row["status"], row["revision"])
            for row in workflows
        } == {
            ("account_a", "sig_saved"): ("saved", 1),
            ("account_a", "sig_ignored"): ("ignored", 1),
            ("account_a", "sig_contacted"): ("contacted", 1),
            ("account_b", "sig_saved"): ("ignored", 1),
        }
        assert all(row["created_at"] == row["updated_at"] for row in workflows)
    inspector = sa.inspect(engine)
    assert {column["name"]: column for column in inspector.get_columns("signal_note")}["note"][
        "type"
    ].length == 2000
    assert {column["name"]: column for column in inspector.get_columns("signal_feedback")}["note"][
        "type"
    ].length == 500
    assert inspector.get_pk_constraint("signal_workflow")["constrained_columns"] == [
        "account_id",
        "signal_key",
    ]
    assert inspector.get_pk_constraint("account_company_alias_override")["constrained_columns"] == [
        "account_id",
        "alias_company_key",
    ]
    assert {"notice_source_snapshot", "notice_award_facts"} <= set(inspector.get_table_names())


def test_upgrade_replay_does_not_overwrite_cas_tombstones_or_reversible_workflow(engine):
    populated_0058(engine)
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    with engine.begin() as connection:
        assert (
            notes.put(
                connection,
                account_id="account_a",
                signal_key="sig_shared",
                note="x" * 2000,
                expected_revision=1,
                now=NOW,
            ).revision
            == 2
        )
        cleared = notes.put(
            connection,
            account_id="account_a",
            signal_key="sig_shared",
            note="",
            expected_revision=2,
            now=NOW,
        )
        assert cleared.note is None and cleared.revision == 3
        connection.execute(
            sa.update(signal_workflow)
            .where(
                signal_workflow.c.account_id == "account_a",
                signal_workflow.c.signal_key == "sig_contacted",
            )
            .values(status="new", revision=7)
        )
    command.upgrade(config, HEAD)
    with engine.connect() as connection:
        note = notes.get(connection, account_id="account_a", signal_key="sig_shared")
        assert note.note is None and note.revision == 3
        other = notes.get(connection, account_id="account_b", signal_key="sig_shared")
        assert other.note == "Other account" and other.revision == 1
        workflow = connection.execute(
            sa.select(signal_workflow).where(
                signal_workflow.c.account_id == "account_a",
                signal_workflow.c.signal_key == "sig_contacted",
            )
        ).one()
        assert workflow.status == "new" and workflow.revision == 7
        assert (
            connection.scalar(
                sa.select(signal_feedback.c.contacted_at).where(
                    signal_feedback.c.account_id == "account_a",
                    signal_feedback.c.signal_key == "sig_contacted",
                )
            )
            is not None
        )
    assert current_revision(engine) == HEAD


def test_archive_boundary_refuses_downgrade_without_changing_private_work(engine):
    # This is the irreversible 0060 boundary, not a claim that arbitrary later
    # migrations are transactionally undone when a downgrade reaches that guard.
    populated_0058(engine)
    config = alembic_config(engine)
    archive = "0060_boamp_notice_facts"
    command.upgrade(config, archive)
    with engine.begin() as connection:
        notes.put(
            connection,
            account_id="account_a",
            signal_key="sig_shared",
            note="x" * 2000,
            expected_revision=1,
            now=NOW,
        )
        notes.put(
            connection,
            account_id="account_a",
            signal_key="sig_shared",
            note="",
            expected_revision=2,
            now=NOW,
        )
        connection.execute(
            sa.update(signal_workflow)
            .where(
                signal_workflow.c.account_id == "account_a",
                signal_workflow.c.signal_key == "sig_contacted",
            )
            .values(status="new", revision=7)
        )
        tables = [
            sa.Table(name, sa.MetaData(), autoload_with=connection)
            for name in ("signal_note", "signal_workflow", "signal_feedback")
        ]
        before = {table.name: connection.execute(sa.select(table)).all() for table in tables}
    with pytest.raises(RuntimeError, match="without downgrading"):
        command.downgrade(config, PREVIOUS)
    assert current_revision(engine) == archive
    with engine.connect() as connection:
        assert {
            table.name: connection.execute(sa.select(table)).all() for table in tables
        } == before


def test_migrated_note_compare_and_swap_allows_only_one_concurrent_winner(engine):
    populated_0058(engine)
    command.upgrade(alembic_config(engine), HEAD)
    barrier = threading.Barrier(2)

    def write(text):
        barrier.wait(timeout=10)
        try:
            with engine.begin() as connection:
                stored = notes.put(
                    connection,
                    account_id="account_a",
                    signal_key="sig_shared",
                    note=text,
                    expected_revision=1,
                    now=NOW,
                )
                return "saved", stored.revision
        except notes.NoteRevisionError as exc:
            return exc.code, exc.revision

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ("writer one", "writer two")))
    assert sorted(results) == [("note_conflict", 2), ("saved", 2)]


def test_concurrent_signal_contact_cannot_downgrade_company_reply(engine):
    populated_0058(engine)
    command.upgrade(alembic_config(engine), HEAD)
    barrier = threading.Barrier(2)

    def write(action):
        barrier.wait(timeout=10)
        with engine.begin() as connection:
            if action == "reply":
                company.set_contact(
                    connection,
                    account_id="account_a",
                    company_key="cmp_legacy",
                    status="replied",
                    now=NOW,
                )
            else:
                company.mark_contacted_if_pending(
                    connection, account_id="account_a", company_key="cmp_legacy", now=NOW
                )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write, ("reply", "signal_contacted")))
    with engine.connect() as connection:
        assert (
            company.get_contact(connection, account_id="account_a", company_key="cmp_legacy").status
            == "replied"
        )


def test_concurrent_exact_alias_reconciliation_preserves_one_canonical_note_and_legacy_copy(engine):
    populated_0058(engine)
    command.upgrade(alembic_config(engine), HEAD)
    with engine.begin() as connection:
        for key in ("cmp_legacy", "cmp_second_alias"):
            register_alias(connection, company_key=key, siren="331364729", now=NOW)
    barrier = threading.Barrier(2)

    def resolve(key):
        barrier.wait(timeout=10)
        with engine.begin() as connection:
            return resolve_subject(
                connection, account_id="account_a", company_key=key, now=NOW
            ).private_subject_key

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(resolve, ("cmp_legacy", "cmp_second_alias")))
    assert results == ["cmp_directory_331364729"] * 2
    with engine.connect() as connection:
        legacy = company.get_note(connection, account_id="account_a", company_key="cmp_legacy")
        canonical = company.get_note(
            connection, account_id="account_a", company_key="cmp_directory_331364729"
        )
        assert canonical.body == legacy.body == "  Company\n history  "
        assert canonical.revision == legacy.revision == 1
        assert (
            company.get_note(
                connection, account_id="account_b", company_key="cmp_directory_331364729"
            )
            is None
        )


def test_migrated_boamp_source_sets_append_and_latest_coverage_stops_backfill(engine):
    from test_boamp_notice_facts import linked_tender_fixture

    from signals.client_value.notice_backfill import backfill_notice_facts
    from signals.client_value.notice_facts import load_award_notice_facts, store_notice_facts
    from signals.connectors.boamp import parse_award_notice
    from signals.connectors.boamp.facts import extract_boamp_notice_facts
    from signals.persistence.materialization import persist_award_facts
    from signals.persistence.notice_schema import notice_award_facts

    populated_0058(engine)
    command.upgrade(alembic_config(engine), HEAD)
    raw, prior = linked_tender_fixture()
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    partial = extract_boamp_notice_facts(raw, event=event, awards=awards, collected_at=NOW)
    with engine.begin() as connection:
        for award in awards:
            persist_award_facts(connection, event=event, award=award, persisted_at=NOW)
        store_notice_facts(connection, partial)

    class Client:
        calls = 0

        def fetch_record(self, identity):
            assert identity == prior["idweb"]
            self.calls += 1
            return prior

    client = Client()
    result = backfill_notice_facts(engine, now=NOW, dry_run=False, client=client)
    assert result.selected == 1 and result.facts_created == 2 and client.calls == 1
    with engine.connect() as connection:
        persisted = load_award_notice_facts(connection, partial.awards[0].award_key)
        assert persisted.initial_duration.value == "12"
        rows = connection.execute(sa.select(notice_award_facts)).mappings().all()
        assert len(rows) == 4
        assert len({row["source_set_hash"] for row in rows}) == 2
    repeated = backfill_notice_facts(engine, now=NOW, dry_run=False, client=client)
    assert repeated.selected == 0 and client.calls == 1
