from __future__ import annotations

import datetime as dt
import pathlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from engagement_helpers import (
    NOW,
    Clock,
    events,
    icp_of,
    make_app,
    make_engine,
    pay,
    reconcile_discovery,
    seed,
    signed_up,
)
from fastapi.testclient import TestClient
from feed_helpers import ORIGIN

from signals.accounts.service import authenticate
from signals.api import routes_notes
from signals.api.config import SESSION_COOKIE_NAME
from signals.engagement import notes
from signals.engagement.schema import MAXIMUM_SIGNAL_NOTE_LENGTH, signal_feedback, signal_note


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    return make_engine(tmp_path)


@pytest.fixture
def app(engine, clock: Clock):
    return make_app(engine, clock)


@pytest.fixture
def alice(app):
    return signed_up(app)


def paid_signal(engine, client, *, plan: str = "pro") -> str:
    icp = icp_of(client)
    pay(engine, client, plan=plan)
    return seed(engine, icp, count=1)[0]


def test_note_roundtrip_does_not_create_feedback_or_analytics(alice, engine):
    key = paid_signal(engine, alice)
    response = alice.put(f"/signals/{key}/note", json={"note": "Appeler lundi"})
    assert response.status_code == 200
    assert response.json()["note"] == "Appeler lundi"
    assert alice.get(f"/signals/{key}/note").json()["note"] == "Appeler lundi"
    with engine.connect() as connection:
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(signal_feedback)).scalar_one()
            == 0
        )
    assert events(engine) == []


def test_empty_note_retains_a_revisioned_tombstone(alice, engine):
    key = paid_signal(engine, alice)
    alice.put(f"/signals/{key}/note", json={"note": "Temporaire"})
    cleared = alice.put(f"/signals/{key}/note", json={"note": "   ", "expected_revision": 1})
    assert cleared.status_code == 200
    assert cleared.json()["revision"] == 2
    assert cleared.json()["note"] is None
    assert alice.get(f"/signals/{key}/note").json()["note"] is None


def test_note_is_private_and_requires_unlocked_access(app, engine):
    alice = signed_up(app, "alice@example.com")
    bob = signed_up(app, "bob@example.com")
    key = paid_signal(engine, alice)
    assert alice.put(f"/signals/{key}/note", json={"note": "privé"}).status_code == 200
    assert bob.get(f"/signals/{key}/note").status_code == 404
    assert bob.put(f"/signals/{key}/note", json={"note": "vol"}).status_code == 404


def test_two_concurrent_first_notes_converge_without_feedback_or_analytics(
    alice, app, engine, monkeypatch
):
    key = paid_signal(engine, alice)
    assert alice.get(f"/signals/{key}/note").json()["note"] is None
    raw_token = alice.cookies.get(SESSION_COOKIE_NAME)
    assert raw_token is not None
    with engine.begin() as connection:
        session = authenticate(connection, raw_token=raw_token, now=NOW)
    assert session is not None

    def preserved_session(request, _connection, _now):
        assert request.cookies.get(SESSION_COOKIE_NAME) == raw_token
        return session

    monkeypatch.setattr(routes_notes, "current_session", preserved_session)
    barrier = threading.Barrier(2)
    original_conflict_insert = notes._conflict_insert

    def synchronized_conflict_insert(connection, table):
        barrier.wait(timeout=5)
        return original_conflict_insert(connection, table)

    monkeypatch.setattr(notes, "_conflict_insert", synchronized_conflict_insert)

    def write(note: str) -> tuple[int, dict]:
        with TestClient(
            app,
            headers={"Origin": ORIGIN},
        ) as concurrent:
            concurrent.cookies.update(alice.cookies)
            response = concurrent.put(
                f"/signals/{key}/note", json={"note": note, "expected_revision": 0}
            )
            return response.status_code, response.json()

    values = ("Première note", "Seconde note")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(write, values))

    assert sorted(status for status, _body in outcomes) == [200, 409]
    winner = next(body for status, body in outcomes if status == 200)
    loser = next(body for status, body in outcomes if status == 409)
    assert loser["detail"]["code"] == "note_conflict"
    assert loser["detail"]["note"] == winner["note"]
    assert alice.get(f"/signals/{key}/note").json()["note"] == winner["note"]
    with engine.connect() as connection:
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(signal_note)).scalar_one()
            == 1
        )
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(signal_feedback)).scalar_one()
            == 0
        )
    assert events(engine) == []


def test_existing_note_update_is_one_atomic_revision_guarded_write(alice, engine):
    key = paid_signal(engine, alice)
    assert alice.put(f"/signals/{key}/note", json={"note": "Initiale"}).status_code == 200
    statements: list[str] = []

    def capture_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        if "signal_note" in statement.lower():
            statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        response = alice.put(
            f"/signals/{key}/note", json={"note": "Mise à jour", "expected_revision": 1}
        )
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture_statement)

    assert response.status_code == 200
    assert response.json()["note"] == "Mise à jour"
    assert len(statements) == 1
    normalized = " ".join(statements[0].upper().split())
    assert normalized.startswith("UPDATE SIGNAL_NOTE")
    assert "SIGNAL_NOTE.REVISION =" in normalized
    assert "RETURNING ACCOUNT_ID, SIGNAL_KEY, NOTE, REVISION" in normalized
    with engine.connect() as connection:
        row = connection.execute(
            sa.select(signal_note).where(signal_note.c.signal_key == key)
        ).one()
    assert row.note == "Mise à jour"


def test_note_update_preserves_created_at_and_advances_authoritative_updated_at(
    alice, engine, clock: Clock
):
    key = paid_signal(engine, alice)
    first = alice.put(f"/signals/{key}/note", json={"note": "Initiale"})
    assert first.status_code == 200
    with engine.connect() as connection:
        before = connection.execute(
            sa.select(signal_note.c.created_at, signal_note.c.updated_at).where(
                signal_note.c.signal_key == key
            )
        ).one()

    clock.advance(dt.timedelta(minutes=5))
    updated = alice.put(f"/signals/{key}/note", json={"note": "Révisée", "expected_revision": 1})
    assert updated.status_code == 200
    with engine.connect() as connection:
        after = connection.execute(
            sa.select(signal_note.c.created_at, signal_note.c.updated_at).where(
                signal_note.c.signal_key == key
            )
        ).one()

    assert after.created_at == before.created_at
    assert after.updated_at > before.updated_at
    assert updated.json()["note"] == "Révisée"
    assert updated.json()["updated_at"] == clock.now.isoformat()


def test_browser_account_id_is_rejected_without_altering_the_note(alice, engine):
    key = paid_signal(engine, alice)
    assert alice.put(f"/signals/{key}/note", json={"note": "Privée"}).status_code == 200

    rejected = alice.put(
        f"/signals/{key}/note",
        json={"note": "Détournée", "account_id": "acc_attacker"},
    )

    assert rejected.status_code == 422
    assert alice.get(f"/signals/{key}/note").json()["note"] == "Privée"


def test_locked_anonymous_foreign_origin_and_long_notes_fail_closed(alice, app, engine):
    icp = icp_of(alice)
    keys = seed(engine, icp, count=5)
    assert len(reconcile_discovery(engine, alice, signal_keys=keys)) == 3
    items = alice.get("/signals?limit=50").json()["items"]
    locked = next(item["signal_id"] for item in items if item["locked"])
    unlocked = next(item["signal_id"] for item in items if not item["locked"])

    assert alice.get(f"/signals/{locked}/note").status_code == 403
    assert alice.put(f"/signals/{locked}/note", json={"note": "interdit"}).status_code == 403
    assert (
        alice.put(
            f"/signals/{unlocked}/note", json={"note": "x" * (MAXIMUM_SIGNAL_NOTE_LENGTH + 1)}
        ).status_code
        == 422
    )
    assert (
        alice.put(
            f"/signals/{unlocked}/note",
            json={"note": "attaque"},
            headers={"Origin": "https://attacker.example"},
        ).status_code
        == 403
    )

    anonymous = TestClient(app, headers={"Origin": ORIGIN})
    assert anonymous.get(f"/signals/{unlocked}/note").status_code == 401
    assert anonymous.put(f"/signals/{unlocked}/note", json={"note": "anonyme"}).status_code == 401
