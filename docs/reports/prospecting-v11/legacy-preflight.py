"""Readonly live 0058 inputs, exact candidate reconciliation in memory only.

Run using the candidate's Python environment before activating it. Output is
aggregate counts only. No notes, contacts, IDs or connection URLs are printed.
The live connection is explicitly read-only on PostgreSQL. All candidate
migrations and reconciliation writes target a separate in-memory SQLite DB.
"""

import datetime as dt
import json
import sys
from collections import Counter

import sqlalchemy as sa

from signals.accounts.schema import account
from signals.client_value.identity_audit import audit_identity_batch
from signals.companies.schema import saas_company
from signals.engagement.schema import company_contact, company_note
from signals.persistence.database import create_database_engine, migrate_to_latest


def inspect_legacy(source_engine):
    now = dt.datetime.now(dt.UTC)
    # This deliberately incomplete mirror carries public identity references,
    # not contract/source-event rows. Never disable FK checks on the live DB.
    mirror = sa.create_engine("sqlite+pysqlite:///:memory:", hide_parameters=True)
    migrate_to_latest(mirror)
    try:
        # Migration helpers restore SQLite FK enforcement after table batches.
        # Only this process-local, deliberately partial mirror needs it off.
        assert mirror.url.database == ":memory:"
        with mirror.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        # Reflect the old shape: its note/contact rows do not have revision yet.
        with source_engine.connect() as source, source.begin():
            if source.dialect.name == "postgresql":
                source.execute(sa.text("SET TRANSACTION READ ONLY"))
            legacy = sa.MetaData()
            tables = [
                sa.Table(name, legacy, autoload_with=source)
                for name in ("saas_company", "company_note", "company_contact")
            ]
            rows = {
                table.name: [
                    dict(row) for row in source.execute(sa.select(table).limit(10001)).mappings()
                ]
                for table in tables
            }
            if any(len(values) > 10000 for values in rows.values()):
                raise ValueError("preflight_input_limit")
        owners = {
            row["account_id"] for name in ("company_note", "company_contact") for row in rows[name]
        }
        with mirror.begin() as connection:
            for owner in owners:
                connection.execute(
                    sa.insert(account),
                    {
                        "account_id": owner,
                        "display_name": "Preflight",
                        "locale": "fr",
                        "onboarding_status": "account_created",
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            for table in (saas_company, company_note, company_contact):
                for row in rows[table.name]:
                    if "revision" in table.c:
                        row.setdefault("revision", 1)
                    connection.execute(sa.insert(table), row)
        result = {
            "live_read_only": True,
            "reconciliation_target": "sqlite_memory",
            "inputs": {name: len(values) for name, values in rows.items()},
            "phases": {},
        }
        for phase in ("registry", "accounts"):
            cursor = {"after_account_id": "", "after_company_key": ""}
            counts = Counter()
            review = 0
            while True:
                report = audit_identity_batch(
                    mirror, phase=phase, now=now, execute=True, limit=1000, **cursor
                )
                counts.update(report["counts"])
                review += report["needs_review"]
                cursor = report["cursor"]
                if report["complete"]:
                    break
            result["phases"][phase] = {
                "counts": dict(counts),
                "needs_review": review,
                "complete": True,
            }
        with mirror.connect() as connection:
            # Every pre-existing private row remains byte-for-byte intact.
            for table, field in ((company_note, "body"), (company_contact, "status")):
                for before in rows[table.name]:
                    after = (
                        connection.execute(
                            sa.select(table).where(
                                table.c.account_id == before["account_id"],
                                table.c.company_key == before["company_key"],
                            )
                        )
                        .mappings()
                        .one()
                    )
                    assert after[field] == before[field], "legacy_private_value_changed"
        result["legacy_values_preserved"] = True
        return result
    finally:
        mirror.dispose()


if __name__ == "__main__":
    engine = None
    try:
        engine = create_database_engine()
        print(json.dumps(inspect_legacy(engine), sort_keys=True))
    except Exception as error:  # noqa: BLE001 — CLI boundary must not expose private SQL parameters
        # A SQL exception could otherwise echo a private note as a parameter.
        print(
            json.dumps({"preflight": "failed", "error_type": type(error).__name__}), file=sys.stderr
        )
        sys.exit(2)
    finally:
        if engine is not None:
            engine.dispose()
