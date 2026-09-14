"""V11: authoritative note revisions and reversible signal workflow."""

from __future__ import annotations

import datetime as dt
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from engagement_helpers import Clock, events, icp_of, make_app, make_engine, pay, seed, signed_up

from signals.engagement import company, feedback, notes, status
from signals.engagement.schema import company_note, signal_feedback, signal_note, signal_workflow


@pytest.fixture
def engine(tmp_path):
    return make_engine(tmp_path)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def app(engine, clock):
    return make_app(engine, clock)


@pytest.fixture
def client(app, engine):
    client = signed_up(app)
    pay(engine, client, plan="pro")
    return client


@pytest.fixture
def signal(client, engine):
    return seed(engine, icp_of(client), count=1)[0]


def test_signal_note_accepts_2000_without_expanding_feedback(client, signal):
    accepted = client.put(f"/signals/{signal}/note", json={"note": "é" * 2000})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["revision"] == 1
    rejected = client.put(
        f"/signals/{signal}/note", json={"note": "x" * 2001, "expected_revision": 1}
    )
    assert rejected.status_code == 422
    feedback = client.put(
        f"/signals/{signal}/feedback", json={"relevance": "relevant", "note": "x" * 501}
    )
    assert feedback.status_code == 422


def test_note_revision_conflict_clear_and_late_writer(client, signal, engine):
    path = f"/signals/{signal}/note"
    assert client.get(path).json()["revision"] == 0
    first = client.put(path, json={"note": "première", "expected_revision": 0})
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 1
    legacy = client.put(path, json={"note": "ancien onglet"})
    assert legacy.status_code == 409
    assert legacy.json()["detail"]["code"] == "note_revision_required"
    conflict = client.put(path, json={"note": "conflit", "expected_revision": 0})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["note"] == "première"
    assert conflict.json()["detail"]["revision"] == 1
    cleared = client.put(path, json={"note": "  ", "expected_revision": 1})
    assert cleared.status_code == 200
    assert cleared.json()["note"] is None
    assert cleared.json()["revision"] == 2
    assert client.put(path, json={"note": "retard", "expected_revision": 1}).status_code == 409
    assert client.get(path).json()["note"] is None
    assert client.get(path).json()["revision"] == 2
    with engine.connect() as connection:
        row = connection.execute(sa.select(signal_note)).one()
    assert row.note == "" and row.revision == 2


@pytest.mark.parametrize("revision", [-1, True, 1.5, "1"])
def test_note_rejects_malformed_revision(client, signal, revision):
    response = client.put(
        f"/signals/{signal}/note", json={"note": "texte", "expected_revision": revision}
    )
    assert response.status_code == 422


def test_company_note_service_has_identical_cas_and_account_isolation(client, engine, clock):
    account = client.get("/me").json()["account_id"]
    other = signed_up(client.app, "other@revision.example")
    other_account = other.get("/me").json()["account_id"]
    with engine.begin() as connection:
        first = company.put_note(
            connection,
            account_id=account,
            company_key="cmp_shared",
            body="texte privé",
            expected_revision=0,
            now=clock.now,
        )
        assert first.revision == 1
        company.put_note(
            connection,
            account_id=other_account,
            company_key="cmp_shared",
            body="autre compte",
            expected_revision=0,
            now=clock.now,
        )
    with engine.begin() as connection:
        with pytest.raises(notes.NoteRevisionError) as caught:
            company.put_note(
                connection,
                account_id=account,
                company_key="cmp_shared",
                body="perdu",
                expected_revision=0,
                now=clock.now,
            )
        assert caught.value.revision == 1
    with engine.begin() as connection:
        cleared = company.put_note(
            connection,
            account_id=account,
            company_key="cmp_shared",
            body="",
            expected_revision=1,
            now=clock.now,
        )
        assert cleared.body is None and cleared.revision == 2
        assert (
            company.get_note(connection, account_id=other_account, company_key="cmp_shared").body
            == "autre compte"
        )
        assert connection.scalar(sa.select(sa.func.count()).select_from(company_note)) == 2


@pytest.mark.parametrize("before", ["new", "saved", "contacted", "ignored"])
@pytest.mark.parametrize("after", ["new", "saved", "contacted", "ignored"])
def test_all_signal_workflow_transitions_preserve_contact_history(
    client,
    signal,
    engine,
    before,
    after,
):
    path = f"/signals/{signal}/status"
    first = client.put(path, json={"status": before, "expected_revision": 0})
    assert first.status_code == 200, first.text
    changed = client.put(
        path, json={"status": after, "expected_revision": first.json()["revision"]}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["status"] == after
    assert changed.json()["revision"] == first.json()["revision"] + (before != after)
    repeated = client.put(
        path, json={"status": after, "expected_revision": changed.json()["revision"]}
    )
    assert repeated.status_code == 200
    assert repeated.json()["revision"] == changed.json()["revision"]
    account = client.get("/me").json()["account_id"]
    with engine.connect() as connection:
        workflow = status.get_workflow(connection, account_id=account, signal_key=signal)
        assert workflow.status == after
        historical = connection.execute(sa.select(signal_feedback)).first()
    if before == "contacted" or after == "contacted":
        assert historical.contacted_at is not None
        assert len(events(engine, event_type="signal_contacted")) == 1
    if before == after == "new":
        assert historical is None


def test_workflow_reset_retains_feedback_reason_note_and_first_contact(client, signal, engine):
    response = client.put(
        f"/signals/{signal}/feedback",
        json={"relevance": "not_relevant", "reason": "too_late", "note": "raison historique"},
    )
    assert response.status_code == 200
    contact = client.post(f"/signals/{signal}/contacted")
    assert contact.status_code == 200
    revision = contact.json()["revision"]
    reset = client.put(
        f"/signals/{signal}/status", json={"status": "new", "expected_revision": revision}
    )
    assert reset.status_code == 200, reset.text
    with engine.connect() as connection:
        row = connection.execute(sa.select(signal_feedback)).one()
    assert row.relevance == "not_relevant" and row.reason_code == "too_late"
    assert row.note == "raison historique" and row.contacted_at is not None
    assert len(events(engine, event_type="signal_contacted")) == 1


@pytest.mark.parametrize("value", ["new", "saved", "contacted", "ignored"])
def test_identical_workflow_write_preserves_revision_timestamp_and_event_count(
    client,
    signal,
    engine,
    clock,
    value,
):
    path = f"/signals/{signal}/status"
    first = client.put(path, json={"status": value, "expected_revision": 0})
    assert first.status_code == 200
    previous = first.json()
    event_count = len(events(engine, event_type="signal_status_updated"))
    clock.advance(dt.timedelta(minutes=5))
    repeated = client.put(path, json={"status": value, "expected_revision": previous["revision"]})
    assert repeated.status_code == 200
    assert repeated.json() == previous
    assert len(events(engine, event_type="signal_status_updated")) == event_count


def test_status_conflict_and_other_account_cannot_mutate(client, signal, app, engine):
    first = client.put(
        f"/signals/{signal}/status", json={"status": "saved", "expected_revision": 0}
    )
    assert first.status_code == 200
    conflict = client.put(
        f"/signals/{signal}/status", json={"status": "ignored", "expected_revision": 0}
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["status"] == "saved"
    assert conflict.json()["detail"]["revision"] == first.json()["revision"]
    other = signed_up(app, "stranger@revision.example")
    denied = other.put(
        f"/signals/{signal}/status", json={"status": "ignored", "expected_revision": 1}
    )
    assert denied.status_code == 404


def test_company_pending_advance_never_reads_a_stale_status(client, engine, clock, monkeypatch):
    account = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        company.set_contact(
            connection,
            account_id=account,
            company_key="cmp_concurrent",
            status="replied",
            now=clock.now,
        )
    # Simulate a stale application read while the database already contains replied.
    monkeypatch.setattr(company, "get_contact", lambda *args, **kwargs: None)
    with engine.begin() as connection:
        assert (
            company.mark_contacted_if_pending(
                connection,
                account_id=account,
                company_key="cmp_concurrent",
                now=clock.now + dt.timedelta(days=1),
            )
            is False
        )


@pytest.mark.parametrize("revision", [None, -1, True, 1.5, "1"])
def test_status_requires_a_strict_non_negative_revision(client, signal, revision):
    payload = {"status": "saved"}
    if revision is not None:
        payload["expected_revision"] = revision
    response = client.put(f"/signals/{signal}/status", json=payload)
    assert response.status_code == 422


def test_conflict_on_never_written_workflow_does_not_leave_state(client, signal, engine):
    response = client.put(
        f"/signals/{signal}/status", json={"status": "contacted", "expected_revision": 8}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["revision"] == 0
    assert response.json()["detail"]["status"] == "new"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(signal_workflow)) == 0
        assert connection.scalar(sa.select(sa.func.count()).select_from(signal_feedback)) == 0
    assert events(engine) == []


def test_concurrent_legacy_contacts_record_one_historical_action(
    client, signal, engine, clock, monkeypatch
):
    account = client.get("/me").json()["account_id"]
    context = feedback.SignalContext(signal, "opp_test", icp_of(client), 1, "fresh", 1)
    barrier = threading.Barrier(2)
    original = status._conflict_insert

    def synchronized_insert(connection, table):
        barrier.wait(timeout=10)
        return original(connection, table)

    monkeypatch.setattr(status, "_conflict_insert", synchronized_insert)

    def contact(_):
        with engine.begin() as connection:
            return feedback.mark_contacted(
                connection, account_id=account, context=context, now=clock.now
            )[1]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(contact, range(2)))
    assert sorted(results) == [False, True]
    assert len(events(engine, event_type="signal_contacted")) == 1
    with engine.connect() as connection:
        current = status.get_workflow(connection, account_id=account, signal_key=signal)
        assert current.status == "contacted" and current.revision == 1


def test_account_export_contains_only_own_notes_workflow_and_no_secret_columns(
    client, signal, app, engine, clock
):
    own_account = client.get("/me").json()["account_id"]
    other = signed_up(app, "export-other@revision.example")
    other_account = other.get("/me").json()["account_id"]
    client.put(f"/signals/{signal}/note", json={"note": "my signal note"})
    client.put(f"/signals/{signal}/status", json={"status": "saved", "expected_revision": 0})
    with engine.begin() as connection:
        company.put_note(
            connection,
            account_id=own_account,
            company_key="cmp_export",
            body="my company note",
            now=clock.now,
        )
        company.put_note(
            connection,
            account_id=other_account,
            company_key="cmp_export",
            body="other account secret",
            now=clock.now,
        )
    response = client.get("/account/export")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["signal_note"][0]["note"] == "my signal note"
    assert data["company_note"][0]["body"] == "my company note"
    assert data["signal_workflow"][0]["status"] == "saved"
    assert data["signal_workflow"][0]["revision"] == 1
    assert "other account secret" not in response.text
    for rows in data.values():
        for row in rows:
            assert row["account_id"] == own_account
            assert "password_hash" not in row and "token_hash" not in row


def test_simultaneous_workflow_writers_have_one_winner(client, signal, engine, clock, monkeypatch):
    account = client.get("/me").json()["account_id"]
    context = feedback.SignalContext(signal, "opp_test", icp_of(client), 1, "fresh", 1)
    barrier = threading.Barrier(2)
    original = status._conflict_insert

    def synchronized_insert(connection, table):
        barrier.wait(timeout=10)
        return original(connection, table)

    monkeypatch.setattr(status, "_conflict_insert", synchronized_insert)

    def change(target):
        try:
            with engine.begin() as connection:
                stored = status.set_status(
                    connection,
                    account_id=account,
                    context=context,
                    status=target,
                    expected_revision=0,
                    now=clock.now,
                )
            return "written", stored.status, stored.revision
        except status.StatusConflict as error:
            return "conflict", error.status, error.revision

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(change, ("saved", "ignored")))
    assert sorted(outcome[0] for outcome in outcomes) == ["conflict", "written"]
    assert outcomes[0][1:] == outcomes[1][1:]
    assert len(events(engine, event_type="signal_status_updated")) == 1


def test_simultaneous_company_reply_and_signal_contact_never_downgrades(client, engine, clock):
    account = client.get("/me").json()["account_id"]
    barrier = threading.Barrier(2)

    def change(target):
        with engine.begin() as connection:
            barrier.wait(timeout=10)
            if target == "replied":
                company.set_contact(
                    connection,
                    account_id=account,
                    company_key="cmp_parallel",
                    status=target,
                    now=clock.now,
                )
            else:
                company.mark_contacted_if_pending(
                    connection,
                    account_id=account,
                    company_key="cmp_parallel",
                    now=clock.now,
                )

    with ThreadPoolExecutor(max_workers=2) as pool:
        tuple(pool.map(change, ("replied", "contacted")))
    with engine.connect() as connection:
        contact = company.get_contact(
            connection,
            account_id=account,
            company_key="cmp_parallel",
        )
        assert contact.status == "replied"
