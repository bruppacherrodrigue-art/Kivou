"""SPEC-014 §4 à §8, §30, §35, §36 — juger un signal, et ce que ça ne change pas.

Le retour est une DONNÉE D'OBSERVATION
──────────────────────────────────────
Un « pas pertinent » ne dit rien du marché : il dit quelque chose du client.
Ces tests vérifient qu'il est stocké fidèlement — avec ce que le client
voyait au moment de juger — et qu'il ne modifie **rien** du moteur.

Juger suppose d'avoir vu
────────────────────────
Un aperçu verrouillé ne montre ni l'entreprise ni le marché. Accepter un
avis dessus ferait du formulaire de retour un oracle sur ce qu'il cache.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from engagement_helpers import (
    Clock,
    events,
    icp_of,
    make_app,
    make_engine,
    pay,
    seed,
    signed_up,
)
from feed_helpers import ORIGIN, RESEARCH_ICP_ID, materialize_boamp

from signals.engagement.schema import (
    MAXIMUM_NOTE_LENGTH,
    NEGATIVE_REASON_CODES,
    signal_feedback,
)


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


def put(client, signal_key: str, **payload):
    return client.put(f"/signals/{signal_key}/feedback", json=payload)


# ─── §36.1 à §36.6 — le vocabulaire ───────────────────────────────────────────


def test_a_relevant_judgement_needs_no_reason(alice, engine):
    key = paid_signal(engine, alice)
    response = put(alice, key, relevance="relevant")
    assert response.status_code == 200
    assert response.json()["interaction"]["relevance"] == "relevant"
    assert response.json()["interaction"]["reason"] is None


def test_a_relevant_judgement_with_a_negative_reason_is_refused(alice, engine):
    """Une raison de refus sur un signal jugé pertinent n'a rien à analyser."""
    key = paid_signal(engine, alice)
    response = put(alice, key, relevance="relevant", reason="too_late")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_feedback"


def test_a_refusal_must_say_why(alice, engine):
    key = paid_signal(engine, alice)
    response = put(alice, key, relevance="not_relevant")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_feedback"


@pytest.mark.parametrize("reason", NEGATIVE_REASON_CODES)
def test_every_declared_negative_reason_is_accepted(alice, engine, reason: str):
    key = paid_signal(engine, alice)
    response = put(alice, key, relevance="not_relevant", reason=reason)
    assert response.status_code == 200
    assert response.json()["interaction"]["reason"] == reason


def test_the_six_reasons_are_the_whole_vocabulary():
    assert NEGATIVE_REASON_CODES == (
        "already_covered",
        "done_internally",
        "wrong_customer_type",
        "too_late",
        "wrong_need",
        "other",
    )


def test_an_unknown_reason_is_refused(alice, engine):
    key = paid_signal(engine, alice)
    assert put(alice, key, relevance="not_relevant", reason="trop_cher").status_code == 422


def test_a_note_longer_than_the_limit_is_refused(alice, engine):
    key = paid_signal(engine, alice)
    too_long = "x" * (MAXIMUM_NOTE_LENGTH + 1)
    assert (
        put(alice, key, relevance="not_relevant", reason="other", note=too_long).status_code == 422
    )
    fits = "x" * MAXIMUM_NOTE_LENGTH
    assert put(alice, key, relevance="not_relevant", reason="other", note=fits).status_code == 200


def test_an_unknown_field_is_refused_rather_than_ignored(alice, engine):
    key = paid_signal(engine, alice)
    assert put(alice, key, relevance="relevant", confidence=0.9).status_code == 422


# ─── §36.7, §36.8 — changer d'avis ────────────────────────────────────────────


def test_updating_the_judgement_replaces_the_current_state(alice, engine):
    key = paid_signal(engine, alice)
    put(alice, key, relevance="relevant")
    put(alice, key, relevance="not_relevant", reason="wrong_need")

    body = alice.get(f"/signals/{key}/feedback").json()["interaction"]
    assert body["relevance"] == "not_relevant"
    assert body["reason"] == "wrong_need"
    with engine.connect() as connection:
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(signal_feedback)).scalar()
            == 1
        ), "un seul état courant"


def test_every_judgement_leaves_its_own_event_behind(alice, engine):
    """Le client change d'avis ; l'analyse garde les deux moments."""
    key = paid_signal(engine, alice)
    put(alice, key, relevance="relevant")
    put(alice, key, relevance="not_relevant", reason="already_covered")

    positive = events(engine, event_type="signal_feedback_relevant")
    negative = events(engine, event_type="signal_feedback_not_relevant")
    assert len(positive) == 1
    assert len(negative) == 1
    assert negative[0].properties["reason_code"] == "already_covered"
    assert negative[0].properties["updated"] is True


# ─── §6, §36.9, §36.10 — contacté est une action ─────────────────────────────


def test_marking_contacted_is_idempotent(alice, engine, clock: Clock):
    key = paid_signal(engine, alice)
    first = alice.post(f"/signals/{key}/contacted")
    contacted_at = first.json()["interaction"]["contacted_at"]

    clock.advance(dt.timedelta(hours=3))
    second = alice.post(f"/signals/{key}/contacted")

    assert first.json()["recorded"] is True
    assert second.json()["recorded"] is False
    assert second.json()["interaction"]["contacted_at"] == contacted_at
    assert len(events(engine, event_type="signal_contacted")) == 1


def test_contacted_stays_separate_from_relevance(alice, engine):
    """Un client peut juger un signal excellent sans avoir encore appelé."""
    key = paid_signal(engine, alice)
    put(alice, key, relevance="relevant")

    interaction = alice.get(f"/signals/{key}/feedback").json()["interaction"]
    assert interaction["relevance"] == "relevant"
    assert interaction["contacted"] is False
    assert interaction["contacted_at"] is None


def test_contacting_without_judging_first_is_allowed(alice, engine):
    key = paid_signal(engine, alice)
    response = alice.post(f"/signals/{key}/contacted")
    assert response.status_code == 200
    assert response.json()["interaction"]["contacted"] is True


def test_no_response_or_meeting_is_ever_fabricated(alice, engine):
    """§6 — ces événements n'existent pas encore ; les inventer serait faux."""
    key = paid_signal(engine, alice)
    alice.post(f"/signals/{key}/contacted")
    body = str(alice.get(f"/signals/{key}/feedback").json())
    for invented in ("replied", "meeting", "won", "opportunity_won", "response"):
        assert invented not in body


# ─── §32, §36.11 — ce que le client voyait ───────────────────────────────────


def test_the_feedback_preserves_what_the_customer_actually_saw(alice, engine):
    key = paid_signal(engine, alice)
    put(alice, key, relevance="not_relevant", reason="too_late")

    with engine.connect() as connection:
        row = connection.execute(sa.select(signal_feedback)).one()
    assert row.event_status_at_feedback == "recent_award"
    assert row.event_age_days_at_feedback == 12
    assert row.signal_revision_at_feedback == 1
    assert row.opportunity_key
    assert row.target_icp_id


def test_a_too_late_judgement_stays_analysable_years_later(alice, engine, clock: Clock):
    """§32 — l'âge est FIGÉ. Recalculé aujourd'hui, il dirait autre chose."""
    key = paid_signal(engine, alice)
    put(alice, key, relevance="not_relevant", reason="too_late")

    clock.move_to(dt.date(2027, 3, 1))
    with engine.connect() as connection:
        row = connection.execute(sa.select(signal_feedback)).one()
    assert row.event_age_days_at_feedback == 12, (
        "l'âge du jour du jugement, pas celui d'aujourd'hui"
    )
    assert row.event_status_at_feedback == "recent_award"


# ─── §2, §36.12 — le moteur ne bouge pas ─────────────────────────────────────


def test_no_engine_data_changes_after_feedback(alice, engine):
    """§2 — un clic ne réécrit ni le besoin, ni le score, ni la fraîcheur."""
    from signals.persistence.schema import materialized_signal

    key = paid_signal(engine, alice)

    def snapshot():
        with engine.connect() as connection:
            return connection.execute(sa.select(materialized_signal)).all()

    before = snapshot()
    put(alice, key, relevance="not_relevant", reason="wrong_need")
    alice.post(f"/signals/{key}/contacted")
    assert snapshot() == before


def test_the_signal_detail_is_unchanged_by_the_customers_opinion(alice, engine):
    key = paid_signal(engine, alice)
    before = alice.get(f"/signals/{key}").json()
    put(alice, key, relevance="not_relevant", reason="wrong_need")
    after = alice.get(f"/signals/{key}").json()

    for section in ("contract", "event", "evidence", "analysis", "company", "source"):
        assert before[section] == after[section], section


# ─── §8 — le bloc d'interaction est séparé ───────────────────────────────────


def test_the_interaction_block_never_contaminates_the_facts(alice, engine):
    key = paid_signal(engine, alice)
    put(alice, key, relevance="relevant")
    alice.post(f"/signals/{key}/contacted")

    detail = alice.get(f"/signals/{key}").json()
    assert detail["interaction"]["relevance"] == "relevant"
    assert detail["interaction"]["contacted"] is True
    for section in ("contract", "event", "evidence", "analysis"):
        assert "relevance" not in str(detail[section])
        assert "contacted" not in str(detail[section])


def test_a_signal_without_any_judgement_carries_a_null_interaction(alice, engine):
    key = paid_signal(engine, alice)
    assert alice.get(f"/signals/{key}").json()["interaction"] is None


# ─── §30, §35 — qui a le droit de juger ──────────────────────────────────────


def test_one_account_cannot_judge_the_signal_of_another(app, engine):
    alice, bob = signed_up(app, "alice@negoce-romand.ch"), signed_up(app, "bob@materiaux-leman.ch")
    key = paid_signal(engine, alice)
    icp_of(bob)
    pay(engine, bob, plan="scale")

    assert put(bob, key, relevance="relevant").status_code == 404
    assert bob.get(f"/signals/{key}/feedback").status_code == 404


def test_one_account_cannot_mark_another_accounts_signal_contacted(app, engine):
    alice, bob = signed_up(app, "alice@negoce-romand.ch"), signed_up(app, "bob@materiaux-leman.ch")
    key = paid_signal(engine, alice)
    icp_of(bob)
    pay(engine, bob, plan="scale")

    assert bob.post(f"/signals/{key}/contacted").status_code == 404
    with engine.connect() as connection:
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(signal_feedback)).scalar()
            == 0
        )


def test_an_unbound_signal_can_never_receive_feedback(alice, engine):
    icp_of(alice)
    pay(engine, alice, plan="scale")
    with engine.begin() as connection:
        unbound = materialize_boamp(connection, "26-80978", target_icp_id=RESEARCH_ICP_ID)

    assert put(alice, unbound.signal_key, relevance="relevant").status_code == 404
    assert alice.post(f"/signals/{unbound.signal_key}/contacted").status_code == 404


def test_a_locked_discovery_teaser_cannot_receive_feedback(alice, engine):
    """§30 — sinon le formulaire de retour devient un oracle sur le lead caché."""
    icp = icp_of(alice)
    keys = seed(engine, icp, count=5)
    items = alice.get("/signals?limit=50").json()["items"]
    locked = next(item["signal_id"] for item in items if item["locked"])
    assert locked in keys

    response = put(alice, locked, relevance="relevant")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "signal_not_accessible"
    assert alice.post(f"/signals/{locked}/contacted").status_code == 403


def test_an_unlocked_discovery_grant_can_receive_feedback(alice, engine):
    icp = icp_of(alice)
    seed(engine, icp, count=5)
    items = alice.get("/signals?limit=50").json()["items"]
    unlocked = next(item["signal_id"] for item in items if not item["locked"])

    assert put(alice, unlocked, relevance="relevant").status_code == 200
    assert alice.post(f"/signals/{unlocked}/contacted").status_code == 200


def test_a_client_supplied_account_id_is_refused(alice, engine):
    key = paid_signal(engine, alice)
    response = alice.put(
        f"/signals/{key}/feedback",
        json={"relevance": "relevant", "account_id": "acc_de_quelqu_un_dautre"},
    )
    assert response.status_code == 422


def test_feedback_writes_are_csrf_protected(alice, engine):
    key = paid_signal(engine, alice)
    foreign = {"Origin": "https://attaquant.example"}
    assert (
        alice.put(
            f"/signals/{key}/feedback", json={"relevance": "relevant"}, headers=foreign
        ).status_code
        == 403
    )
    assert alice.post(f"/signals/{key}/contacted", headers=foreign).status_code == 403


def test_an_anonymous_caller_can_neither_read_nor_write_feedback(app, engine):
    from fastapi.testclient import TestClient

    alice = signed_up(app)
    key = paid_signal(engine, alice)
    anonymous = TestClient(app, headers={"Origin": ORIGIN})
    assert anonymous.get(f"/signals/{key}/feedback").status_code == 401
    assert (
        anonymous.put(f"/signals/{key}/feedback", json={"relevance": "relevant"}).status_code == 401
    )
    assert anonymous.post(f"/signals/{key}/contacted").status_code == 401


# ─── §31 — l'export d'apprentissage ──────────────────────────────────────────


def test_the_learning_export_carries_analysis_context_and_no_personal_data(alice, engine):
    from signals.engagement.feedback import learning_export

    key = paid_signal(engine, alice)
    put(alice, key, relevance="not_relevant", reason="too_late")
    alice.post(f"/signals/{key}/contacted")

    with engine.connect() as connection:
        rows = learning_export(connection)
    assert len(rows) == 1
    row = rows[0]
    assert row.signal_key == key
    assert row.reason_code == "too_late"
    assert row.contacted is True
    assert row.event_status_at_feedback == "recent_award"
    assert row.event_age_days_at_feedback == 12

    body = str(row)
    for forbidden in ("@", "password", "token", "session", "negoce-romand"):
        assert forbidden not in body, forbidden


def test_the_learning_export_is_not_a_public_endpoint(alice, engine):
    """§31 — usage interne. Aucune route ne l'expose."""
    paid_signal(engine, alice)
    for path in ("/learning-export", "/feedback/export", "/analytics/export"):
        assert alice.get(path).status_code == 404
