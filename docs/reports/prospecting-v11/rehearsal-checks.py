"""Candidate checks on an operator-created staging copy. No dump/CREATE/DROP.

Only KIVOU_V11_REHEARSAL_DATABASE_URL is opened. KIVOU_DATABASE_URL must name
the exact same copy as defense in depth. Output never includes private values.
The operator owns creation, restoration and OID-checked cleanup of the copy.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
import subprocess
import tempfile
import uuid
from collections import Counter
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa

from signals.accounts.data_rights import export_account
from signals.accounts.schema import account
from signals.billing.service import aware_datetime
from signals.client_value import notice_backfill, user_contacts
from signals.client_value.identity_audit import audit_identity_batch
from signals.client_value.notice_facts import load_award_notice_facts
from signals.connectors.boamp import BoampClient
from signals.engagement import company, feedback, notes, status
from signals.engagement.feedback import SignalContext
from signals.persistence.database import current_revision, migrate_to_latest
from signals.persistence.schema import contract_award, source_event

NOTICE_IDS = ("26-87113", "26-84423", "26-85899", "26-88050")
HEAD = "0060_boamp_notice_facts"
MAX_ROWS = 10000
MAX_BASELINE_BYTES = 256 * 1024 * 1024
MAX_BASELINE_ROW_BYTES = 4 * 1024 * 1024
BASELINE_BATCH_ROWS = 128
BASELINE_STREAM_ROWS = 16
MAX_AUDIT_PAGES = 1000


class RehearsalFailure(RuntimeError):
    """Closed, non-private operator failure code."""


def require(condition, code):
    if not condition:
        raise RehearsalFailure(code)


def validate_target_config(target, default, name, sha):
    require(bool(target and default and name and sha), "rehearsal_configuration_missing")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", sha)), "candidate_sha_invalid")
    require(
        bool(re.fullmatch(rf"kivou_v11_rehearsal_{sha[:12]}_[0-9a-f]{{16}}", name)),
        "rehearsal_database_name_invalid",
    )
    try:
        target_url, default_url = sa.make_url(target), sa.make_url(default)
    except (ValueError, sa.exc.ArgumentError) as error:
        raise RehearsalFailure("rehearsal_url_invalid") from error
    require(target_url.drivername in {"postgresql", "postgresql+psycopg"}, "postgresql_required")
    require(default_url.drivername in {"postgresql", "postgresql+psycopg"}, "postgresql_required")
    require(target_url.database == name, "rehearsal_database_name_mismatch")
    require(name not in {"kivou_staging", "postgres"}, "source_database_forbidden")
    require(
        target_url.set(drivername="postgresql+psycopg")
        == default_url.set(drivername="postgresql+psycopg"),
        "default_database_must_be_copy",
    )
    # A libpq query override must never redirect a checked path to another DB.
    allowed_options = {
        "sslmode",
        "sslrootcert",
        "sslcert",
        "sslkey",
        "connect_timeout",
        "application_name",
    }
    require(set(target_url.query) <= allowed_options, "rehearsal_url_options_forbidden")
    require(bool(target_url.host and target_url.username), "rehearsal_url_identity_missing")
    return target_url.set(drivername="postgresql+psycopg")


def verify_database(engine, expected_name):
    require(engine.dialect.name == "postgresql", "postgresql_required")
    with engine.connect() as connection:
        require(
            connection.scalar(sa.text("SELECT current_database()")) == expected_name,
            "connected_database_mismatch",
        )


def _typed(value, *, key=False):
    if value is None:
        return ["null", None]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        require(number.is_finite(), "baseline_nonfinite_number")
        text = format(number, "f")
        text = text.rstrip("0").rstrip(".") if "." in text else text
        text = "0" if number == 0 else text
        kind = type(value).__name__ if key else "number"
        return [kind, text]
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None and value.utcoffset() is not None:
            value = value.astimezone(dt.UTC)
        return ["datetime", value.isoformat(timespec="microseconds")]
    if isinstance(value, dt.date):
        return ["date", value.isoformat()]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, (bytes, memoryview)):
        return ["bytes", bytes(value).hex()]
    if isinstance(value, uuid.UUID):
        return ["uuid", str(value)]
    if isinstance(value, (list, tuple)):
        return ["array", [_typed(item, key=key) for item in value]]
    if isinstance(value, dict):
        require(all(isinstance(item, str) for item in value), "baseline_json_key_invalid")
        return ["object", [[item, _typed(value[item], key=key)] for item in sorted(value)]]
    raise RehearsalFailure("baseline_value_type_unsupported")


def canonical_bytes(value):
    return json.dumps(_typed(value), ensure_ascii=False, separators=(",", ":")).encode()


def _decode_key(encoded):
    decoders = {
        "str": str,
        "int": int,
        "float": float,
        "Decimal": Decimal,
        "bool": bool,
        "datetime": dt.datetime.fromisoformat,
        "date": dt.date.fromisoformat,
        "bytes": bytes.fromhex,
        "uuid": uuid.UUID,
    }
    return tuple(decoders[kind](value) for kind, value in json.loads(encoded))


class PrivateBaseline(dict):
    """Metadata in memory; private primary keys and keyed row digests on disk.

    No old row payload is retained. The SQLite file is disposable, not a backup;
    disabled journals prevent unbounded sidecars. Its page cap bounds disk use.
    """

    def __init__(
        self,
        *,
        temp_dir=None,
        max_disk_bytes=MAX_BASELINE_BYTES,
        max_row_bytes=MAX_BASELINE_ROW_BYTES,
    ):
        super().__init__()
        self._temporary = None
        self._store = None
        require(
            type(max_disk_bytes) is int and 8192 <= max_disk_bytes <= MAX_BASELINE_BYTES,
            "baseline_disk_limit_invalid",
        )
        require(
            type(max_row_bytes) is int and 1 <= max_row_bytes <= MAX_BASELINE_ROW_BYTES,
            "baseline_row_limit_invalid",
        )
        self.max_row_bytes = max_row_bytes
        self._secret = secrets.token_bytes(32)
        try:
            self._temporary = tempfile.TemporaryDirectory(
                prefix="kivou-v11-baseline-", dir=temp_dir
            )
            self.path = Path(self._temporary.name) / "fingerprints.sqlite"
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            self._store = sqlite3.connect(self.path, isolation_level=None)
            self._store.execute("PRAGMA page_size=4096")
            self._store.execute("PRAGMA journal_mode=OFF")
            self._store.execute("PRAGMA synchronous=OFF")
            self._store.execute("PRAGMA cache_size=-2048")
            self._store.execute(f"PRAGMA max_page_count={max_disk_bytes // 4096}")
            self._store.execute(
                "CREATE TABLE fingerprint (table_name TEXT NOT NULL, key_text TEXT NOT NULL, "
                "owner TEXT, digest BLOB NOT NULL, PRIMARY KEY (table_name, key_text)) WITHOUT ROWID"
            )
        except BaseException:
            self.close()
            raise

    def close(self):
        if self._store is not None:
            self._store.close()
            self._store = None
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None

    def __enter__(self):
        return self

    def __exit__(self, *_arguments):
        self.close()

    def __del__(self):
        self.close()

    def digest(self, value):
        encoded = canonical_bytes(value)
        require(len(encoded) <= self.max_row_bytes, "baseline_row_bytes_limit")
        return hmac.digest(self._secret, encoded, "sha256")

    def add(self, name, keys, row):
        require(all(row[key] is not None for key in keys), "baseline_null_primary_key")
        encoded_key = json.dumps(
            [_typed(row[key], key=True) for key in keys], separators=(",", ":")
        )
        require(len(encoded_key.encode()) <= 16384, "baseline_key_bytes_limit")
        digest = self.digest(dict(row))
        try:
            self._store.execute(
                "INSERT INTO fingerprint VALUES (?, ?, ?, ?)",
                (name, encoded_key, row.get("account_id"), digest),
            )
        except sqlite3.OperationalError as error:
            raise RehearsalFailure("baseline_bytes_limit") from error

    def batches(self, name, *, owner=None):
        require(self._store is not None, "baseline_closed")
        sql = "SELECT key_text, digest FROM fingerprint WHERE table_name = ?"
        parameters = (name,)
        if owner is not None:
            sql += " AND owner = ?"
            parameters += (owner,)
        cursor = self._store.execute(sql + " ORDER BY key_text", parameters)
        try:
            while rows := cursor.fetchmany(BASELINE_BATCH_ROWS):
                yield [(_decode_key(key), digest) for key, digest in rows]
        finally:
            cursor.close()


def capture_baseline(
    engine,
    *,
    limit=None,
    temp_dir=None,
    max_disk_bytes=MAX_BASELINE_BYTES,
    max_row_bytes=MAX_BASELINE_ROW_BYTES,
):
    # An explicit small limit is a refusal guard, never a sampling instruction.
    # The normal path reads every row and is bounded by buffers, row size and disk.
    require(
        limit is None or type(limit) is int and 1 <= limit <= MAX_ROWS, "baseline_limit_invalid"
    )
    baseline = PrivateBaseline(
        temp_dir=temp_dir, max_disk_bytes=max_disk_bytes, max_row_bytes=max_row_bytes
    )
    try:
        with engine.connect() as connection:
            inspector = sa.inspect(connection)
            metadata = sa.MetaData()
            names = inspector.get_table_names()
            private = {
                name
                for name in names
                if "account_id" in {column["name"] for column in inspector.get_columns(name)}
            }
            references = {
                name: {key["referred_table"] for key in inspector.get_foreign_keys(name)}
                for name in names
            }
            while descendants := {name for name in names if references[name] & private} - private:
                private.update(descendants)
            for name in sorted(private):
                table = sa.Table(name, metadata, autoload_with=connection)
                keys = tuple(column.name for column in table.primary_key)
                require(bool(keys), "private_table_without_primary_key")
                count = 0
                statement = (
                    sa.select(table)
                    .order_by(*table.primary_key)
                    .execution_options(
                        stream_results=True,
                        yield_per=BASELINE_STREAM_ROWS,
                    )
                )
                with connection.execute(statement) as result:
                    for row in result.mappings():
                        count += 1
                        require(limit is None or count <= limit, "baseline_limit")
                        baseline.add(name, keys, row)
                baseline[name] = {
                    "keys": keys,
                    "columns": tuple(table.c.keys()),
                    "row_count": count,
                }
        require("account" in baseline, "restored_accounts_missing")
        return baseline
    except BaseException:
        baseline.close()
        raise


def compare_baseline(engine, baseline):
    with engine.connect() as connection:
        metadata = sa.MetaData()
        for name, before in baseline.items():
            table = sa.Table(name, metadata, autoload_with=connection)
            for batch in baseline.batches(name):
                selected = dict(batch)
                statement = (
                    sa.select(*(table.c[key] for key in before["columns"]))
                    .where(
                        sa.tuple_(*(table.c[key] for key in before["keys"])).in_(list(selected)),
                    )
                    .execution_options(stream_results=True, yield_per=BASELINE_STREAM_ROWS)
                )
                count = 0
                with connection.execute(statement) as result:
                    for row in result.mappings():
                        key = tuple(row[column] for column in before["keys"])
                        require(
                            hmac.compare_digest(baseline.digest(dict(row)), selected[key]),
                            "legacy_private_value_changed",
                        )
                        count += 1
                require(count == len(selected), "legacy_private_row_missing")


def _audit(engine, phase, now):
    cursor, counts = {}, Counter()
    for _ in range(MAX_AUDIT_PAGES):
        report = audit_identity_batch(
            engine, phase=phase, now=now, execute=True, limit=100, **cursor
        )
        counts.update(report["counts"])
        if report["complete"]:
            return dict(counts)
        require(report["cursor"] != cursor, "identity_cursor_stalled")
        cursor = report["cursor"]
    raise RehearsalFailure("identity_page_limit")


def _write(engine, operation):
    with engine.begin() as connection:
        return operation(connection)


def _read(engine, operation):
    with engine.connect() as connection:
        return operation(connection)


def _reject(engine, exception, code, operation):
    try:
        _write(engine, operation)
    except exception as error:
        require(type(error) is exception, code)
        return error
    raise RehearsalFailure(code)


def _export_checked(connection, owner):
    payload = export_account(connection, account_id=owner)
    require(payload["account"]["account_id"] == owner, "export_account_mismatch")
    require(
        not {"notice_source_snapshot", "notice_award_facts"} & payload["data"].keys(),
        "raw_notice_exported",
    )
    for rows in payload["data"].values():
        for row in rows:
            require(row.get("account_id", owner) == owner, "export_account_leak")
            require(not {"password_hash", "token_hash"} & row.keys(), "export_secret_column")
    return payload


def exercise_private_contracts(engine, *, now):
    owners = tuple(f"v11_rehearsal_{uuid.uuid4().hex}" for _ in range(2))
    key = f"v11_rehearsal_{uuid.uuid4().hex}"
    _write(
        engine,
        lambda c: c.execute(
            account.insert(),
            [
                {
                    "account_id": owner,
                    "display_name": "V11 rehearsal check",
                    "locale": "fr",
                    "onboarding_status": "account_created",
                    "created_at": now,
                    "updated_at": now,
                }
                for owner in owners
            ],
        ),
    )
    for kind, put, get, column in (
        (
            "signal",
            lambda c, owner, text, rev: notes.put(
                c, account_id=owner, signal_key=key, note=text, expected_revision=rev, now=now
            ),
            lambda c, owner: notes.get(c, account_id=owner, signal_key=key),
            "note",
        ),
        (
            "company",
            lambda c, owner, text, rev: company.put_note(
                c, account_id=owner, company_key=key, body=text, expected_revision=rev, now=now
            ),
            lambda c, owner: company.get_note(c, account_id=owner, company_key=key),
            "body",
        ),
    ):
        first = _write(engine, lambda c, put=put: put(c, owners[0], "x" * 2000, 0))
        require(first.revision == 1, "note_initial_revision")
        require(
            getattr(_read(engine, lambda c, get=get: get(c, owners[0])), column) == "x" * 2000,
            "note_persistence",
        )
        require(_read(engine, lambda c, get=get: get(c, owners[1])) is None, "note_account_leak")
        second = _write(engine, lambda c, put=put: put(c, owners[0], "second", 1))
        require(second.revision == 2, "note_update_revision")
        failure = _reject(
            engine,
            notes.NoteRevisionError,
            "note_stale_writer_accepted",
            lambda c, put=put: put(c, owners[0], "stale", 1),
        )
        require(failure.revision == 2, "note_conflict_revision")
        cleared = _write(engine, lambda c, put=put: put(c, owners[0], "", 2))
        require(cleared.revision == 3 and getattr(cleared, column) is None, "note_clear_failed")
        _reject(
            engine,
            notes.NoteRevisionError,
            "note_tombstone_resurrected",
            lambda c, put=put: put(c, owners[0], "stale", 0),
        )
        _reject(
            engine,
            ValueError,
            f"{kind}_note_2001_accepted",
            lambda c, put=put: put(c, owners[0], "x" * 2001, 3),
        )
        _write(engine, lambda c, put=put: put(c, owners[1], "other account", 0))
        retained = _read(engine, lambda c, get=get: get(c, owners[0]))
        require(retained.revision == 3 and getattr(retained, column) is None, "note_account_leak")

    payload = user_contacts.ManualContactWrite(
        name="Contact de répétition", email="rehearsal@example.com", expected_revision=0
    )
    created = _write(
        engine,
        lambda c: user_contacts.put_contact(
            c, account_id=owners[0], company_key=key, payload=payload, now=now
        ),
    )
    require(created["revision"] == 1, "contact_initial_revision")
    deleted = _write(
        engine,
        lambda c: user_contacts.delete_contact(
            c, account_id=owners[0], company_key=key, expected_revision=1, now=now
        ),
    )
    require(deleted["revision"] == 2 and deleted["contact"] is None, "contact_tombstone_failed")
    _reject(
        engine,
        user_contacts.ContactConflict,
        "contact_tombstone_resurrected",
        lambda c: user_contacts.put_contact(
            c,
            account_id=owners[0],
            company_key=key,
            payload=payload.model_copy(update={"expected_revision": 1}),
            now=now,
        ),
    )
    require(
        _read(
            engine, lambda c: user_contacts.get_contact(c, account_id=owners[1], company_key=key)
        )["revision"]
        == 0,
        "contact_account_leak",
    )

    context = SignalContext(
        signal_key=key,
        opportunity_key=key,
        target_icp_id=key,
        revision=1,
        event_status="active",
        event_age_days=1,
    )
    for revision, target in enumerate(("saved", "ignored", "new", "contacted", "new")):
        workflow = _write(
            engine,
            lambda c, target=target, revision=revision: status.set_status(
                c,
                account_id=owners[0],
                context=context,
                status=target,
                expected_revision=revision,
                now=now,
            ),
        )
        require(
            workflow.revision == revision + 1 and workflow.status == target, "workflow_persistence"
        )
    _reject(
        engine,
        status.StatusConflict,
        "workflow_stale_writer_accepted",
        lambda c: status.set_status(
            c, account_id=owners[0], context=context, status="saved", expected_revision=1, now=now
        ),
    )
    workflow = _read(engine, lambda c: status.get_workflow(c, account_id=owners[0], signal_key=key))
    require(workflow.revision == 5 and workflow.status == "new", "workflow_stale_overwrite")
    historical = _read(
        engine, lambda c: feedback.get_feedback(c, account_id=owners[0], signal_key=key)
    )
    require(
        historical is not None and historical.contacted_at == now, "workflow_contact_history_lost"
    )
    require(status.unified_status(historical, workflow) == "new", "workflow_projection_stale")
    require(
        _read(engine, lambda c: status.get_workflow(c, account_id=owners[1], signal_key=key))
        is None,
        "workflow_account_leak",
    )
    for owner in owners:
        exported = _read(engine, lambda c, owner=owner: _export_checked(c, owner))
        for table in ("signal_note", "company_note"):
            require(len(exported["data"].get(table, ())) == 1, "private_note_export_missing")
        if owner == owners[0]:
            workflows = exported["data"].get("signal_workflow", ())
            require(
                len(workflows) == 1
                and workflows[0]["status"] == "new"
                and workflows[0]["revision"] == 5,
                "workflow_export_missing",
            )
            interactions = exported["data"].get("signal_feedback", ())
            require(
                len(interactions) == 1 and aware_datetime(interactions[0]["contacted_at"]) == now,
                "workflow_contact_history_export_missing",
            )
            contacts = exported["data"].get("company_manual_contact", ())
            require(
                len(contacts) == 1
                and contacts[0]["deleted_at"] is not None
                and contacts[0]["revision"] == 2,
                "contact_tombstone_export_missing",
            )
    return dict.fromkeys(
        (
            "note_cas",
            "note_tombstones",
            "note_2000_boundary",
            "account_isolation",
            "manual_contact_tombstone",
            "workflow_cas",
            "workflow_contact_history",
            "export_isolation",
        ),
        True,
    )


def verify_legacy_exports(engine, baseline):
    count = 0
    tables = {
        "signal_note",
        "company_note",
        "signal_feedback",
        "company_contact",
        "signal_workflow",
        "company_manual_contact",
        "account_company_membership",
    }
    with engine.connect() as connection:
        owner_index = baseline["account"]["keys"].index("account_id")
        for batch in baseline.batches("account"):
            for key, _digest in batch:
                owner = key[owner_index]
                exported = _export_checked(connection, owner)
                for name in tables & baseline.keys():
                    before = baseline[name]
                    exported_rows = {
                        tuple(row[k] for k in before["keys"]): row
                        for row in exported["data"].get(name, ())
                    }
                    for original_batch in baseline.batches(name, owner=owner):
                        for row_key, digest in original_batch:
                            row = exported_rows.get(row_key)
                            require(
                                row is not None and all(k in row for k in before["columns"]),
                                "legacy_export_missing",
                            )
                            require(
                                hmac.compare_digest(
                                    baseline.digest({k: row[k] for k in before["columns"]}),
                                    digest,
                                ),
                                "legacy_export_missing",
                            )
                count += 1
    return count


def migrate_and_check(engine, *, now, baseline=None):
    owns_baseline = baseline is None
    baseline = capture_baseline(engine) if owns_baseline else baseline
    try:
        migrate_to_latest(engine)
        require(current_revision(engine) == HEAD, "candidate_migration_head_mismatch")
        compare_baseline(engine, baseline)
        audit = {phase: _audit(engine, phase, now) for phase in ("registry", "accounts")}
        compare_baseline(engine, baseline)
        contracts = exercise_private_contracts(engine, now=now)
        exports = verify_legacy_exports(engine, baseline)
        compare_baseline(engine, baseline)
        return {
            "legacy_preserved": True,
            "baseline_tables": len(baseline),
            "baseline_rows": sum(table["row_count"] for table in baseline.values()),
            "legacy_accounts_exported": exports,
            "audits": audit,
            "contracts": contracts,
        }
    finally:
        if owns_baseline:
            baseline.close()


def select_boamp_events(engine):
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(source_event.c.source_notice_id, source_event.c.event_key)
            .where(
                source_event.c.source_system == "boamp",
                source_event.c.source_notice_id.in_(NOTICE_IDS),
            )
            .order_by(source_event.c.event_key)
            .limit(101)
        ).all()
    require({row.source_notice_id for row in rows} == set(NOTICE_IDS), "boamp_notice_missing")
    require(len(rows) <= 100, "boamp_event_selection_limit")
    return tuple(row.event_key for row in rows)


def validate_cursor_path(path):
    path = Path(path).absolute()
    parent = path.parent
    require(
        parent.is_dir() and not parent.is_symlink() and parent.resolve() == parent,
        "cursor_parent_invalid",
    )
    info = parent.stat()
    require(
        info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0,
        "cursor_parent_not_private",
    )
    if path.exists() or path.is_symlink():
        info = path.lstat()
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) & 0o077 == 0
            and info.st_size <= 256 * 1024,
            "cursor_file_invalid",
        )
    return path


def _coverage(engine, event_keys):
    result = {
        notice: {"awards": 0, "facts": 0, "durations": 0, "notice_cancelled": 0}
        for notice in NOTICE_IDS
    }
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(source_event.c.source_notice_id, contract_award.c.award_key)
            .join(contract_award, contract_award.c.event_key == source_event.c.event_key)
            .where(source_event.c.event_key.in_(event_keys))
        ).all()
        for notice_id, key in rows:
            item = result[notice_id]
            item["awards"] += 1
            fact = load_award_notice_facts(connection, key)
            if fact is not None:
                require(fact.source.source_notice_id == notice_id, "notice_fact_identity_mismatch")
                item["facts"] += 1
                item["durations"] += bool(
                    fact.duration or fact.initial_duration or fact.maximum_duration
                )
                item["notice_cancelled"] += fact.notice_status == "notice_cancelled"
    return result


def run_backfill_checks(engine, *, cursor_path, client, now):
    event_keys = select_boamp_events(engine)
    cursor_path = validate_cursor_path(cursor_path)
    descriptor = os.open(
        cursor_path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cursor = (
            notice_backfill.NoticeBackfillCursor.model_validate_json(cursor_path.read_text())
            if cursor_path.exists()
            else notice_backfill.NoticeBackfillCursor()
        )
        preview = notice_backfill.backfill_notice_facts(
            engine, now=now, cursor=cursor, event_keys=event_keys, dry_run=True, limit=100
        )
        cursor = preview.cursor
        counts, passes = Counter(), 0
        for _ in range(3):
            result = notice_backfill.backfill_notice_facts(
                engine,
                now=now,
                cursor=cursor,
                event_keys=event_keys,
                dry_run=False,
                client=client,
                limit=100,
                checkpoint=lambda state: notice_backfill._write_cursor(cursor_path, state),
            )
            passes += 1
            cursor = result.cursor
            counts.update(item.status for item in result.items)
            if not cursor.pending:
                break
        # Execute replay with no network reader. Completed work must create no
        # further facts/snapshots; provider retries remain strictly capped above.
        replay = notice_backfill.backfill_notice_facts(
            engine, now=now, cursor=cursor, event_keys=event_keys, dry_run=False, limit=100
        )
        idempotent = (
            replay.selected == 0
            and not cursor.pending
            and not (replay.facts_created or replay.snapshots_created)
        )
        coverage = _coverage(engine, event_keys)
        return {
            "selected_events": len(event_keys),
            "passes": passes,
            "outcomes": dict(counts),
            "terminal": cursor.terminal_count,
            "pending": len(cursor.pending),
            "idempotent": idempotent,
            "coverage": coverage,
            "all_notices_have_facts": all(
                item["awards"] > 0 and item["facts"] == item["awards"] for item in coverage.values()
            ),
        }


def main():
    engine = None
    original = None
    try:
        name = os.getenv("KIVOU_V11_REHEARSAL_DATABASE_NAME", "")
        sha = os.getenv("KIVOU_V11_CANDIDATE_SHA", "")
        target = validate_target_config(
            os.getenv("KIVOU_V11_REHEARSAL_DATABASE_URL", ""),
            os.getenv("KIVOU_DATABASE_URL", ""),
            name,
            sha,
        )
        cursor_value = os.getenv("KIVOU_V11_REHEARSAL_CURSOR", "")
        require(bool(cursor_value), "cursor_configuration_missing")
        cursor_path = validate_cursor_path(Path(cursor_value))
        checkout = Path(__file__).resolve().parents[3]
        actual_sha = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        require(actual_sha == sha, "candidate_checkout_sha_mismatch")
        engine = sa.create_engine(target, hide_parameters=True)
        verify_database(engine, name)
        original = capture_baseline(engine)
        now = dt.datetime.now(dt.UTC)
        report = migrate_and_check(engine, now=now, baseline=original)
        verify_database(engine, name)
        with BoampClient() as client:
            report["boamp"] = run_backfill_checks(
                engine, cursor_path=cursor_path, client=client, now=now
            )
        compare_baseline(engine, original)
        success = report["boamp"]["all_notices_have_facts"] and report["boamp"]["idempotent"]
        print(
            json.dumps(
                {"status": "passed" if success else "coverage_incomplete", "sha": sha, **report},
                sort_keys=True,
            )
        )
        return 0 if success else 3
    except RehearsalFailure as error:
        print(json.dumps({"status": "failed", "code": str(error)}, sort_keys=True))
        return 2
    except Exception:  # noqa: BLE001 - never log private SQL parameters/provider payloads
        print(
            json.dumps({"status": "failed", "code": "rehearsal_execution_failed"}, sort_keys=True)
        )
        return 2
    finally:
        if original is not None:
            original.close()
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
