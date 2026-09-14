"""Administrative reconciliation is bounded, resumable and never prints private values."""

import importlib
import importlib.util
import json

import pytest
import sqlalchemy as sa
from feed_helpers import SIMAP_RICH, make_account, make_icp, materialize_simap
from test_company_entity_aliases import NOW
from test_prospecting_migration import engine as database_engine  # noqa: F401

from signals.companies.schema import saas_company
from signals.companies.service import ensure_companies_for_signal_keys
from signals.engagement.prospecting_schema import (
    account_company_alias_override,
    account_company_membership,
    company_manual_contact,
    company_subject_alias,
)
from signals.engagement.schema import company_contact, company_note
from signals.persistence.database import migrate_to_latest


def audit(engine, **kwargs):
    name = "signals.client_value.identity_audit"
    assert importlib.util.find_spec(name) is not None, "bounded identity audit is missing"
    return importlib.import_module(name).audit_identity_batch(engine, now=NOW, **kwargs)


@pytest.fixture
def prepared(database_engine):  # noqa: F811 - imported parametrized pytest fixture
    engine = database_engine
    migrate_to_latest(engine)
    with engine.begin() as connection:
        one = make_account(connection, "one@audit.example", "One")
        two = make_account(connection, "two@audit.example", "Two")
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=make_icp(connection, one))
        ensure_companies_for_signal_keys(connection, signal_keys=(signal.signal_key,), now=NOW)
        row = dict(connection.execute(sa.select(saas_company)).mappings().one())
        first = row["company_key"]
        second = "cmp_bbbbbbbbbbbbbbbb"
        identifiers = [{"scheme": "siren", "value": "331364729"}]
        connection.execute(
            sa.update(saas_company).values(
                official_country="FR",
                official_identifiers=identifiers,
            )
        )
        connection.execute(
            sa.insert(saas_company),
            {
                **row,
                "company_key": second,
                "identity_fingerprint": "b" * 64,
                "official_country": "FR",
                "official_identifiers": identifiers,
            },
        )
        connection.execute(
            sa.insert(company_note),
            [
                {
                    "account_id": owner,
                    "company_key": key,
                    "body": body,
                    "revision": 1,
                    "created_at": NOW,
                    "updated_at": NOW,
                }
                for owner, key, body in (
                    (one, first, "PRIVATE_NOTE_FIRST"),
                    (one, second, "PRIVATE_NOTE_SECOND"),
                    (two, first, "PRIVATE_NOTE_OTHER_ACCOUNT"),
                )
            ],
        )
        connection.execute(
            sa.insert(company_manual_contact),
            {
                "account_id": two,
                "company_key": first,
                "name": "PRIVATE_PERSON",
                "email": "private@example.com",
                "revision": 3,
                "created_at": NOW,
                "updated_at": NOW,
            },
        )
        connection.execute(
            sa.insert(account_company_membership),
            {
                "account_id": two,
                "company_key": first,
                "origin": "user",
                "revision": 1,
                "created_at": NOW,
                "updated_at": NOW,
            },
        )
    return engine, one, two, first, second


def state(engine):
    with engine.connect() as connection:
        return {
            table.name: [dict(row) for row in connection.execute(sa.select(table)).mappings()]
            for table in (
                company_note,
                company_contact,
                company_manual_contact,
                account_company_membership,
                company_subject_alias,
                account_company_alias_override,
            )
        }


def test_registry_dry_run_rolls_back_and_execute_pages_are_idempotent(prepared):
    engine, *_ = prepared
    before = state(engine)
    preview = audit(engine, phase="registry", limit=1)
    assert preview["dry_run"] is True
    assert preview["selected"] == 1
    assert preview["complete"] is False
    assert state(engine) == before
    first = audit(engine, phase="registry", execute=True, limit=1)
    second = audit(engine, phase="registry", execute=True, limit=1, **first["cursor"])
    assert second["complete"] is True
    registered = state(engine)
    assert len(registered["company_subject_alias"]) == 3
    audit(engine, phase="registry", execute=True)
    assert state(engine) == registered


def test_account_audit_preserves_collisions_and_other_accounts_and_redacts_report(prepared):
    engine, one, two, first, second = prepared
    audit(engine, phase="registry", execute=True)
    before = state(engine)
    preview = audit(engine, phase="accounts")
    assert preview["selected"] >= 3
    assert any(item["status"] == "isolated" for item in preview["items"])
    assert state(engine) == before
    assert "PRIVATE_NOTE" not in json.dumps(preview)
    assert "PRIVATE_PERSON" not in json.dumps(preview)
    assert "private@example.com" not in json.dumps(preview)
    cursor = {}
    processed = []
    for _ in range(12):
        report = audit(engine, phase="accounts", execute=True, limit=1, **cursor)
        assert report["selected"] <= 1
        processed.extend(report["items"])
        cursor = report["cursor"]
        if report["complete"]:
            break
    assert report["complete"]
    assert {item["account_id"] for item in processed} == {one, two}
    after = state(engine)
    conflicts = [
        row for row in after["account_company_alias_override"] if row["mode"] == "isolated"
    ]
    assert {row["account_id"] for row in conflicts} == {one}
    assert {row["private_subject_key"] for row in conflicts} >= {first, second}
    copied = [
        row for row in after["company_note"] if row["company_key"] == "cmp_directory_331364729"
    ]
    assert [(row["account_id"], row["body"]) for row in copied] == [
        (two, "PRIVATE_NOTE_OTHER_ACCOUNT")
    ]
    assert all(row in after["company_note"] for row in before["company_note"])
    assert all(row in after["company_manual_contact"] for row in before["company_manual_contact"])
    assert all(
        row in after["account_company_membership"] for row in before["account_company_membership"]
    )
    audit(engine, phase="accounts", execute=True)
    assert state(engine) == after


def test_registry_reports_changed_exact_binding_without_overwrite(prepared):
    engine, *_ = prepared
    audit(engine, phase="registry", execute=True)
    with engine.begin() as connection:
        connection.execute(
            sa.update(saas_company).values(
                official_identifiers=[{"scheme": "siren", "value": "732829320"}],
            )
        )
    before = state(engine)
    report = audit(engine, phase="registry", execute=True)
    assert {item["status"] for item in report["items"]} == {"conflict"}
    assert {item["reason"] for item in report["items"]} == {"public_alias_binding_conflict"}
    after = state(engine)
    assert after["company_note"] == before["company_note"]
    assert after["company_manual_contact"] == before["company_manual_contact"]
    for prior in before["company_subject_alias"]:
        current = next(
            row
            for row in after["company_subject_alias"]
            if row["alias_company_key"] == prior["alias_company_key"]
        )
        assert current["canonical_company_key"] == prior["canonical_company_key"]
        if not prior["alias_company_key"].startswith("cmp_directory_"):
            assert current["resolution_status"] == "unresolved"
    accounts = audit(engine, phase="accounts", execute=True)
    assert all(item["status"] == "unresolved" for item in accounts["items"])
    assert state(engine)["company_note"] == before["company_note"]


@pytest.mark.parametrize("limit", [0, 1001, True])
def test_audit_rejects_unbounded_or_malformed_limits(prepared, limit):
    engine, *_ = prepared
    with pytest.raises(ValueError, match="limit"):
        audit(engine, phase="registry", limit=limit)


def test_cli_defaults_to_read_only_and_returns_only_safe_json(prepared, monkeypatch, capsys):
    engine, *_ = prepared
    name = "signals.client_value.identity_audit"
    assert importlib.util.find_spec(name) is not None, "administrative CLI is missing"
    module = importlib.import_module(name)
    monkeypatch.setattr(module, "create_database_engine", lambda: engine)
    before = state(engine)
    assert module.main(["--phase", "registry", "--limit", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert "PRIVATE_NOTE" not in json.dumps(report)
    assert state(engine) == before
