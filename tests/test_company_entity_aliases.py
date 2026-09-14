"""Exact legal identity never joins two accounts' private work by name."""

import datetime as dt

import pytest
import sqlalchemy as sa

from signals.accounts.schema import account
from signals.client_value.company_identity import (
    exact_french_siren,
    register_alias,
    resolve_subject,
)
from signals.engagement.prospecting_schema import (
    account_company_alias_override,
    company_subject_alias,
)
from signals.engagement.schema import company_note
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 9, 13, tzinfo=dt.UTC)
A = "cmp_aaaaaaaaaaaaaaaa"
B = "cmp_bbbbbbbbbbbbbbbb"


@pytest.fixture
def db(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'aliases.db'}")
    migrate_to_latest(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(account),
            [
                {
                    "account_id": key,
                    "display_name": key,
                    "locale": "fr",
                    "onboarding_status": "account_created",
                    "created_at": NOW,
                    "updated_at": NOW,
                }
                for key in ("account_a", "account_b")
            ],
        )
    return engine


def test_exact_identifiers_only_and_contradictions_are_rejected():
    assert (
        exact_french_siren([{"scheme": "SIREN", "value": "331364729"}], country="FR") == "331364729"
    )
    assert (
        exact_french_siren([{"scheme": "SIRET", "value": "73282932000074"}], country="FR")
        == "732829320"
    )
    assert (
        exact_french_siren([{"scheme": "SIRET", "value": "73282932000075"}], country="FR") is None
    )
    assert exact_french_siren([{"scheme": "SIREN", "value": "331364729"}], country="CH") is None
    assert (
        exact_french_siren(
            [
                {"scheme": "SIREN", "value": "331364729"},
                {"scheme": "SIREN", "value": "732829320"},
            ],
            country="FR",
        )
        is None
    )
    assert exact_french_siren([{"scheme": "name", "value": "331364729"}], country="FR") is None


def aliases(connection):
    for key in (A, B):
        register_alias(connection, company_key=key, siren="331364729", now=NOW)


def note(connection, owner, key, text):
    connection.execute(
        sa.insert(company_note),
        {
            "account_id": owner,
            "company_key": key,
            "body": text,
            "created_at": NOW,
            "updated_at": NOW,
            "revision": 1,
        },
    )


def test_exact_aliases_share_private_subject_without_implicit_follow(db):
    with db.begin() as connection:
        aliases(connection)
        note(connection, "account_a", A, "Rappeler mardi")
        one = resolve_subject(connection, account_id="account_a", company_key=A, now=NOW)
        two = resolve_subject(connection, account_id="account_a", company_key=B, now=NOW)
        assert one.private_subject_key == two.private_subject_key
        assert one.canonical_company_key == two.canonical_company_key
        assert (
            connection.execute(
                sa.select(company_note.c.body).where(
                    company_note.c.account_id == "account_a",
                    company_note.c.company_key == one.private_subject_key,
                )
            ).scalar_one()
            == "Rappeler mardi"
        )
        # Legacy copy is retained for provenance / rollback, never discarded.
        assert (
            connection.execute(
                sa.select(company_note.c.body).where(company_note.c.company_key == A)
            ).scalar_one()
            == "Rappeler mardi"
        )


def test_conflicting_notes_isolate_only_the_affected_account(db):
    with db.begin() as connection:
        aliases(connection)
        note(connection, "account_a", A, "Texte A")
        note(connection, "account_a", B, "Texte B")
        note(connection, "account_b", A, "Texte de B")
        a1 = resolve_subject(connection, account_id="account_a", company_key=A, now=NOW)
        a2 = resolve_subject(connection, account_id="account_a", company_key=B, now=NOW)
        b1 = resolve_subject(connection, account_id="account_b", company_key=A, now=NOW)
        b2 = resolve_subject(connection, account_id="account_b", company_key=B, now=NOW)
        assert a1.canonical_company_key == a2.canonical_company_key == b1.canonical_company_key
        assert a1.private_subject_key != a2.private_subject_key
        assert b1.private_subject_key == b2.private_subject_key
        isolated = (
            connection.execute(
                sa.select(account_company_alias_override).where(
                    account_company_alias_override.c.mode == "isolated",
                )
            )
            .mappings()
            .all()
        )
        assert {row["account_id"] for row in isolated} == {"account_a"}
        assert {
            row["body"]
            for row in connection.execute(
                sa.select(company_note).where(
                    company_note.c.account_id == "account_a",
                )
            ).mappings()
        } == {"Texte A", "Texte B"}


def test_unresolved_aliases_remain_distinct(db):
    with db.begin() as connection:
        one = resolve_subject(connection, account_id="account_a", company_key=A, now=NOW)
        two = resolve_subject(connection, account_id="account_a", company_key=B, now=NOW)
        assert one.private_subject_key != two.private_subject_key


def test_changed_exact_binding_quarantines_even_previously_resolved_private_work(db):
    with db.begin() as connection:
        aliases(connection)
        note(connection, "account_a", A, "Historical alias note")
        resolved = resolve_subject(connection, account_id="account_a", company_key=A, now=NOW)
        canonical = resolved.private_subject_key
        connection.execute(
            company_note.update()
            .where(company_note.c.company_key == canonical)
            .values(body="Canonical company work")
        )
        assert register_alias(connection, company_key=A, siren="732829320", now=NOW) == A
        subject = resolve_subject(connection, account_id="account_a", company_key=A, now=NOW)
        assert subject.resolution == "unresolved"
        assert subject.private_subject_key == subject.canonical_company_key == A
        stored = (
            connection.execute(
                sa.select(company_subject_alias).where(
                    company_subject_alias.c.alias_company_key == A
                )
            )
            .mappings()
            .one()
        )
        assert stored["canonical_company_key"] == canonical
        assert stored["resolution_status"] == "unresolved"
        # Returning old evidence cannot silently release a reviewed conflict.
        assert register_alias(connection, company_key=A, siren="331364729", now=NOW) == A
        assert (
            resolve_subject(connection, account_id="account_a", company_key=A, now=NOW).resolution
            == "unresolved"
        )
        assert (
            connection.scalar(
                sa.select(company_note.c.body).where(company_note.c.company_key == canonical)
            )
            == "Canonical company work"
        )


def test_quarantined_alias_is_excluded_from_other_exact_alias_reconciliation(db):
    with db.begin() as connection:
        aliases(connection)
        note(connection, "account_b", A, "Must stay on ambiguous alias")
        register_alias(connection, company_key=A, siren="732829320", now=NOW)
        other = resolve_subject(connection, account_id="account_b", company_key=B, now=NOW)
        assert other.resolution == "resolved"
        assert (
            connection.scalar(
                sa.select(company_note.c.body).where(
                    company_note.c.company_key == other.private_subject_key
                )
            )
            is None
        )
        assert (
            connection.scalar(sa.select(company_note.c.body).where(company_note.c.company_key == A))
            == "Must stay on ambiguous alias"
        )
