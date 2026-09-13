"""Real PostgreSQL interleavings for public quarantine and private reconciliation."""

import datetime as dt
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa

from signals.accounts.schema import account
from signals.client_value.company_identity import register_alias, resolve_subject
from signals.engagement.prospecting_schema import (
    account_company_alias_override,
    account_company_membership,
    company_manual_contact,
    company_subject_alias,
)
from signals.engagement.schema import company_contact, company_note, signal_workflow
from signals.persistence.database import create_database_engine

NOW = dt.datetime(2026, 9, 13, tzinfo=dt.UTC)
A, B, C = "cmp_review_a", "cmp_review_b", "cmp_review_c"
OWNER, OTHER_OWNER = "review_account", "review_other_account"
CANONICAL = "cmp_directory_331364729"


@pytest.fixture
def db():
    url = os.getenv("KIVOU_TEST_POSTGRES_URL") or os.getenv("KIVOU_TEST_POSTGRES_DSN")
    if not url:
        pytest.skip("a disposable PostgreSQL URL is required for identity interleavings")
    schema = f"kivou_identity_lock_{uuid.uuid4().hex}"
    admin = create_database_engine(url)
    with admin.begin() as connection:
        connection.execute(sa.schema.CreateSchema(schema))
    engine = create_database_engine(
        url,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=6000 -cstatement_timeout=8000",
        },
    )
    try:
        for table in (
            account,
            company_subject_alias,
            account_company_alias_override,
            company_note,
            company_contact,
            company_manual_contact,
            account_company_membership,
            signal_workflow,
        ):
            table.create(engine)
        with engine.begin() as connection:
            for owner in (OWNER, OTHER_OWNER):
                connection.execute(
                    account.insert().values(
                        account_id=owner,
                        display_name="Synthetic review",
                        locale="fr",
                        onboarding_status="account_created",
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
            for key, siren in ((A, "331364729"), (B, "331364729"), (C, "732829320")):
                register_alias(connection, company_key=key, siren=siren, now=NOW)
            connection.execute(
                company_note.insert().values(
                    account_id=OWNER,
                    company_key=B,
                    body="Synthetic private history",
                    revision=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(sa.schema.DropSchema(schema, cascade=True))
        admin.dispose()


def _wait_for_advisory_wait(engine, pid, done):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if done.is_set():
            return False
        with engine.connect() as connection:
            waiting = connection.scalar(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks "
                    "WHERE pid = :pid AND locktype = 'advisory' AND NOT granted)"
                ),
                {"pid": pid},
            )
        if waiting:
            return True
        done.wait(0.01)
    return False


def test_quarantine_waits_for_the_complete_inflight_private_reconciliation(db):
    group_read, release_reader = threading.Event(), threading.Event()
    writer_started, writer_done = threading.Event(), threading.Event()
    writer_pid = []

    def hold_group_read(connection, cursor, statement, parameters, context, executemany):
        if "WHERE company_subject_alias.canonical_company_key =" in statement:
            group_read.set()
            assert release_reader.wait(8), "test reader was not released"

    def read():
        with db.begin() as connection:
            sa.event.listen(connection, "after_cursor_execute", hold_group_read)
            result = resolve_subject(connection, account_id=OWNER, company_key=A, now=NOW)
            sa.event.remove(connection, "after_cursor_execute", hold_group_read)
            return result

    def quarantine():
        try:
            with db.begin() as connection:
                writer_pid.append(connection.scalar(sa.text("SELECT pg_backend_pid()")))
                writer_started.set()
                register_alias(connection, company_key=B, siren="732829320", now=NOW)
                return resolve_subject(connection, account_id=OWNER, company_key=B, now=NOW)
        finally:
            writer_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(read)
        try:
            assert group_read.wait(5)
            writer = pool.submit(quarantine)
            assert writer_started.wait(5)
            blocked = _wait_for_advisory_wait(db, writer_pid[0], writer_done)
        finally:
            release_reader.set()
        first = reader.result(timeout=10)
        second = writer.result(timeout=10)
    assert blocked, "quarantine committed while another alias still reconciled the old group"
    assert first.private_subject_key == CANONICAL
    assert second.resolution == "unresolved" and second.private_subject_key == B
    with db.connect() as connection:
        assert (
            connection.scalar(
                sa.select(company_subject_alias.c.resolution_status).where(
                    company_subject_alias.c.alias_company_key == B
                )
            )
            == "unresolved"
        )


def test_reconciliation_waits_for_pending_quarantine_and_excludes_its_private_values(db):
    quarantined, release_writer = threading.Event(), threading.Event()
    reader_started, reader_done = threading.Event(), threading.Event()
    reader_pid = []

    def quarantine():
        with db.begin() as connection:
            register_alias(connection, company_key=B, siren="732829320", now=NOW)
            quarantined.set()
            assert release_writer.wait(8), "test writer was not released"

    def read():
        try:
            with db.begin() as connection:
                reader_pid.append(connection.scalar(sa.text("SELECT pg_backend_pid()")))
                reader_started.set()
                return resolve_subject(connection, account_id=OWNER, company_key=A, now=NOW)
        finally:
            reader_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(quarantine)
        try:
            assert quarantined.wait(5)
            reader = pool.submit(read)
            assert reader_started.wait(5)
            blocked = _wait_for_advisory_wait(db, reader_pid[0], reader_done)
        finally:
            release_writer.set()
        writer.result(timeout=10)
        result = reader.result(timeout=10)
    assert blocked, "private reconciliation did not wait for the pending public contradiction"
    assert result.private_subject_key == CANONICAL
    with db.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(company_note)
                .where(company_note.c.company_key == CANONICAL)
            )
            == 0
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(company_note)
                .where(company_note.c.company_key == B)
            )
            == 1
        )


@pytest.mark.parametrize("other_owner", [OWNER, OTHER_OWNER])
def test_opposed_alias_and_group_order_finishes_without_deadlock(db, other_owner):
    barrier = threading.Barrier(2)

    def page(owner, order):
        barrier.wait(timeout=5)
        with db.begin() as connection:
            resolved = []
            # Repeated lock acquisition is transaction-reentrant. Opposing
            # multi-group audit pages must not retain incompatible group locks.
            for key in (*order, *order):
                siren = "732829320" if key == C else "331364729"
                register_alias(connection, company_key=key, siren=siren, now=NOW)
                resolved.append(
                    resolve_subject(
                        connection, account_id=owner, company_key=key, now=NOW
                    ).private_subject_key
                )
            return resolved

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(page, OWNER, (A, B, C))
        second = pool.submit(page, other_owner, (C, B, A))
        results = [first.result(timeout=10), second.result(timeout=10)]
    assert all(set(row) == {CANONICAL, "cmp_directory_732829320"} for row in results)


def test_preexisting_workflow_foreign_key_lock_does_not_deadlock_identity_reader(db):
    workflow_written, reader_locked, writer_resolving = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    def writer():
        with db.begin() as connection:
            # The contacted route writes workflow before resolving the holder.
            # This INSERT retains PostgreSQL's KEY SHARE lock on the account.
            connection.execute(
                signal_workflow.insert().values(
                    account_id=OWNER,
                    signal_key="review_signal",
                    status="contacted",
                    revision=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            workflow_written.set()
            assert reader_locked.wait(5)
            writer_resolving.set()
            return resolve_subject(connection, account_id=OWNER, company_key=C, now=NOW)

    def hold_identity_lock(connection, cursor, statement, parameters, context, executemany):
        if "SELECT pg_advisory_xact_lock(" in statement:
            reader_locked.set()
            assert writer_resolving.wait(5)

    def reader():
        assert workflow_written.wait(5)
        with db.begin() as connection:
            sa.event.listen(connection, "after_cursor_execute", hold_identity_lock)
            try:
                return resolve_subject(connection, account_id=OWNER, company_key=A, now=NOW)
            finally:
                sa.event.remove(connection, "after_cursor_execute", hold_identity_lock)

    with ThreadPoolExecutor(max_workers=2) as pool:
        written = pool.submit(writer)
        read = pool.submit(reader)
        assert read.result(timeout=12).private_subject_key == CANONICAL
        assert written.result(timeout=12).private_subject_key == "cmp_directory_732829320"
    with db.connect() as connection:
        assert (
            connection.scalar(
                sa.select(signal_workflow.c.status).where(
                    signal_workflow.c.account_id == OWNER,
                    signal_workflow.c.signal_key == "review_signal",
                )
            )
            == "contacted"
        )


def test_sqlite_legacy_read_transaction_blocks_quarantine_until_reconciliation(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'identity.db'}")
    group_read, release_reader = threading.Event(), threading.Event()
    try:
        for table in (
            account,
            company_subject_alias,
            account_company_alias_override,
            company_note,
            company_contact,
            company_manual_contact,
            account_company_membership,
        ):
            table.create(engine)
        with engine.begin() as connection:
            connection.execute(
                account.insert().values(
                    account_id=OWNER,
                    display_name="Synthetic review",
                    locale="fr",
                    onboarding_status="account_created",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            for key in (A, B):
                register_alias(connection, company_key=key, siren="331364729", now=NOW)
            connection.execute(
                company_note.insert().values(
                    account_id=OWNER,
                    company_key=B,
                    body="Synthetic private history",
                    revision=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )

        def hold_after_group(connection, cursor, statement, parameters, context, executemany):
            # Pause after the exact group's cursor is fully consumed, before
            # starting the next SELECT: no cursor-level SQLite read lock remains.
            if "FROM company_note" in statement:
                group_read.set()
                assert release_reader.wait(8)

        def reader():
            with engine.begin() as connection:
                sa.event.listen(connection, "before_cursor_execute", hold_after_group)
                try:
                    return resolve_subject(connection, account_id=OWNER, company_key=A, now=NOW)
                finally:
                    sa.event.remove(connection, "before_cursor_execute", hold_after_group)

        with ThreadPoolExecutor(max_workers=1) as pool:
            read = pool.submit(reader)
            try:
                assert group_read.wait(5)
                # A short database busy timeout observes the actual SQLite lock;
                # it is not a timing sleep or a mocked transaction boundary.
                with (
                    pytest.raises(sa.exc.OperationalError, match="database is locked"),
                    engine.begin() as connection,
                ):
                    connection.exec_driver_sql("PRAGMA busy_timeout=100")
                    register_alias(connection, company_key=B, siren="732829320", now=NOW)
            finally:
                release_reader.set()
            assert read.result(timeout=10).private_subject_key == CANONICAL
        with engine.begin() as connection:
            register_alias(connection, company_key=B, siren="732829320", now=NOW)
            subject = resolve_subject(connection, account_id=OWNER, company_key=B, now=NOW)
            assert subject.resolution == "unresolved" and subject.private_subject_key == B
    finally:
        engine.dispose()
