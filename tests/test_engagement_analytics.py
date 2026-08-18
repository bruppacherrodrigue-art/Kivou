"""SPEC-014 §9 à §14, §33, §34, §38 — mesurer le produit, pas surveiller le client.

L'analytique est SERVEUR
────────────────────────
Il n'existe aucun `POST /analytics/event`. Un point d'entrée où le
navigateur choisirait le nom et le contenu de l'événement produirait des
chiffres qu'un client peut fabriquer — donc une activation à laquelle on ne
pourrait plus croire.

Observation répétable ≠ action métier
─────────────────────────────────────
Ouvrir deux fois un signal, ce sont deux consultations. Marquer deux fois
« contacté », c'est UNE démarche commerciale. L'étoile polaire compte la
seconde, jamais la première.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from engagement_helpers import (
    NOW,
    Clock,
    account_of,
    events,
    icp_of,
    make_app,
    make_engine,
    pay,
    seed,
    signed_up,
)

from signals.engagement import analytics
from signals.engagement.schema import PRODUCT_EVENT_TYPES, product_event

WINDOW_START = NOW - dt.timedelta(days=30)
WINDOW_END = NOW + dt.timedelta(days=1)


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


def paid_signals(engine, client, *, count: int = 1, plan: str = "pro") -> list[str]:
    icp = icp_of(client)
    pay(engine, client, plan=plan)
    return seed(engine, icp, count=count)


def counts(engine, event_type: str) -> int:
    return len(events(engine, event_type=event_type))


# ─── §34, §38.1, §38.2 — consultations ───────────────────────────────────────


def test_one_feed_call_records_exactly_one_feed_view(alice, engine):
    paid_signals(engine, alice, count=5)
    alice.get("/signals?limit=50")

    recorded = events(engine, event_type="signal_feed_viewed")
    assert len(recorded) == 1, "une vue par appel, pas une par carte"
    assert recorded[0].properties["returned"] == 5
    assert recorded[0].properties["plan_code"] == "pro"


def test_three_feed_calls_record_three_feed_views(alice, engine):
    paid_signals(engine, alice, count=2)
    for _ in range(3):
        alice.get("/signals")
    assert counts(engine, "signal_feed_viewed") == 3


def test_one_detail_call_records_one_detail_view(alice, engine):
    key = paid_signals(engine, alice)[0]
    alice.get(f"/signals/{key}")

    recorded = events(engine, event_type="signal_detail_viewed")
    assert len(recorded) == 1
    assert recorded[0].signal_key == key
    assert recorded[0].properties["access_granted"] is True


def test_a_locked_detail_attempt_is_recorded_with_access_denied(alice, engine):
    """§34 — c'est cette mesure qui dit l'appétit derrière le mur payant."""
    icp = icp_of(alice)
    seed(engine, icp, count=5)
    items = alice.get("/signals?limit=50").json()["items"]
    locked = next(item["signal_id"] for item in items if item["locked"])

    alice.get(f"/signals/{locked}")
    recorded = [
        event
        for event in events(engine, event_type="signal_detail_viewed")
        if event.signal_key == locked
    ]
    assert len(recorded) == 1
    assert recorded[0].properties["access_granted"] is False


def test_a_foreign_signal_view_records_nothing(app, engine):
    """L'analytique ne doit pas devenir un annuaire des signaux d'autrui."""
    alice, bob = signed_up(app, "alice@negoce-romand.ch"), signed_up(app, "bob@materiaux-leman.ch")
    key = paid_signals(engine, alice)[0]
    icp_of(bob)
    pay(engine, bob, plan="pro")

    assert bob.get(f"/signals/{key}").status_code == 404
    bob_account = account_of(bob)
    recorded = [
        event
        for event in events(engine, event_type="signal_detail_viewed")
        if event.account_id == bob_account
    ]
    assert recorded == []


# ─── §38.3 à §38.6 — jugements et action commerciale ─────────────────────────


def test_a_positive_judgement_records_a_positive_event(alice, engine):
    key = paid_signals(engine, alice)[0]
    alice.put(f"/signals/{key}/feedback", json={"relevance": "relevant"})
    assert counts(engine, "signal_feedback_relevant") == 1
    assert counts(engine, "signal_feedback_not_relevant") == 0


def test_a_negative_judgement_records_its_reason(alice, engine):
    key = paid_signals(engine, alice)[0]
    alice.put(
        f"/signals/{key}/feedback",
        json={"relevance": "not_relevant", "reason": "done_internally"},
    )
    recorded = events(engine, event_type="signal_feedback_not_relevant")
    assert recorded[0].properties["reason_code"] == "done_internally"
    assert recorded[0].properties["event_status"] == "recent_award"


def test_contacting_records_one_business_action(alice, engine):
    key = paid_signals(engine, alice)[0]
    alice.post(f"/signals/{key}/contacted")
    assert counts(engine, "signal_contacted") == 1


def test_a_repeated_contact_never_double_counts_the_commercial_action(alice, engine, clock: Clock):
    """§12, §38.6 — deux clics ne font pas deux démarches."""
    key = paid_signals(engine, alice)[0]
    for _ in range(4):
        alice.post(f"/signals/{key}/contacted")
        clock.advance(dt.timedelta(minutes=5))

    assert counts(engine, "signal_contacted") == 1
    with engine.connect() as connection:
        assert (
            analytics.accounts_with_commercial_action(
                connection, start=WINDOW_START, end=WINDOW_END
            )
            == 1
        )


# ─── §13, §38.7, §38.8 — activation et étoile polaire ────────────────────────


def test_a_signup_alone_is_not_an_activation(alice, engine):
    """§13 — s'inscrire n'est pas se servir du produit."""
    paid_signals(engine, alice)
    alice.get("/signals")
    with engine.connect() as connection:
        assert analytics.activated_accounts(connection, start=WINDOW_START, end=WINDOW_END) == 0


def test_a_relevant_judgement_activates_the_account(alice, engine):
    key = paid_signals(engine, alice)[0]
    alice.put(f"/signals/{key}/feedback", json={"relevance": "relevant"})
    with engine.connect() as connection:
        assert analytics.activated_accounts(connection, start=WINDOW_START, end=WINDOW_END) == 1


def test_a_contact_activates_the_account(alice, engine):
    key = paid_signals(engine, alice)[0]
    alice.post(f"/signals/{key}/contacted")
    with engine.connect() as connection:
        assert analytics.activated_accounts(connection, start=WINDOW_START, end=WINDOW_END) == 1


def test_a_negative_judgement_alone_does_not_activate(alice, engine):
    key = paid_signals(engine, alice)[0]
    alice.put(
        f"/signals/{key}/feedback", json={"relevance": "not_relevant", "reason": "wrong_need"}
    )
    with engine.connect() as connection:
        assert analytics.activated_accounts(connection, start=WINDOW_START, end=WINDOW_END) == 0


def test_the_north_star_counts_distinct_accounts_over_thirty_days(app, engine, clock: Clock):
    alice = signed_up(app, "alice@negoce-romand.ch")
    bob = signed_up(app, "bob@materiaux-leman.ch")
    alice_keys = paid_signals(engine, alice, count=2)
    bob_keys = paid_signals(engine, bob, count=2)

    # Alice contacte deux signaux ; Bob un seul. Deux comptes, pas trois actions.
    for key in alice_keys:
        alice.post(f"/signals/{key}/contacted")
    bob.post(f"/signals/{bob_keys[0]}/contacted")

    with engine.connect() as connection:
        assert analytics.north_star(connection, as_of=NOW + dt.timedelta(seconds=1)) == 2


def test_the_north_star_forgets_an_account_after_thirty_days(alice, engine, clock: Clock):
    key = paid_signals(engine, alice)[0]
    alice.post(f"/signals/{key}/contacted")

    with engine.connect() as connection:
        assert analytics.north_star(connection, as_of=NOW + dt.timedelta(days=29)) == 1
        assert analytics.north_star(connection, as_of=NOW + dt.timedelta(days=31)) == 0


def test_the_north_star_is_never_logins_or_page_views(alice, engine):
    """§13 — ces chiffres montent tout seuls et ne disent rien."""
    paid_signals(engine, alice, count=3)
    for _ in range(10):
        alice.get("/signals")
        alice.get("/me")
    with engine.connect() as connection:
        assert analytics.north_star(connection, as_of=NOW + dt.timedelta(seconds=1)) == 0


# ─── §14, §38.9 — les répartitions ───────────────────────────────────────────


def test_the_negative_reason_breakdown_is_correct(alice, engine):
    keys = paid_signals(engine, alice, count=4)
    reasons = ["too_late", "too_late", "already_covered", "wrong_customer_type"]
    for key, reason in zip(keys, reasons, strict=True):
        alice.put(f"/signals/{key}/feedback", json={"relevance": "not_relevant", "reason": reason})

    with engine.connect() as connection:
        breakdown = analytics.negative_reason_breakdown(
            connection, start=WINDOW_START, end=WINDOW_END
        )
    assert breakdown == {"too_late": 2, "already_covered": 1, "wrong_customer_type": 1}


def test_the_breakdown_keeps_a_reason_the_customer_later_withdrew(alice, engine):
    """Un changement d'avis n'efface pas la raison donnée : elle reste analysable."""
    key = paid_signals(engine, alice)[0]
    alice.put(f"/signals/{key}/feedback", json={"relevance": "not_relevant", "reason": "too_late"})
    alice.put(f"/signals/{key}/feedback", json={"relevance": "relevant"})

    with engine.connect() as connection:
        assert analytics.negative_reason_breakdown(
            connection, start=WINDOW_START, end=WINDOW_END
        ) == {"too_late": 1}


def test_the_feedback_breakdown_counts_both_sides(alice, engine):
    keys = paid_signals(engine, alice, count=3)
    alice.put(f"/signals/{keys[0]}/feedback", json={"relevance": "relevant"})
    alice.put(f"/signals/{keys[1]}/feedback", json={"relevance": "relevant"})
    third = alice.put(
        f"/signals/{keys[2]}/feedback", json={"relevance": "not_relevant", "reason": "other"}
    )
    assert third.status_code == 200, third.text

    with engine.connect() as connection:
        assert analytics.feedback_breakdown(connection, start=WINDOW_START, end=WINDOW_END) == {
            "relevant": 2,
            "not_relevant": 1,
        }


def test_the_snapshot_answers_every_question_at_once(alice, engine):
    keys = paid_signals(engine, alice, count=2)
    alice.put(f"/signals/{keys[0]}/feedback", json={"relevance": "relevant"})
    alice.post(f"/signals/{keys[1]}/contacted")

    with engine.connect() as connection:
        snapshot = analytics.snapshot(connection, start=WINDOW_START, end=WINDOW_END)
    assert snapshot.activated_accounts == 1
    assert snapshot.accounts_with_commercial_action == 1
    assert snapshot.signals_contacted == 1
    assert snapshot.relevant_signals == 1


# ─── §9, §38.10, §38.11 — ce que l'analytique ne stocke pas ──────────────────


def test_no_analytics_row_contains_a_secret_or_a_session(alice, engine):
    keys = paid_signals(engine, alice, count=2)
    alice.get("/signals")
    alice.get(f"/signals/{keys[0]}")
    alice.put(f"/signals/{keys[0]}/feedback", json={"relevance": "relevant"})
    alice.post(f"/signals/{keys[1]}/contacted")

    with engine.connect() as connection:
        rows = connection.execute(sa.select(product_event)).all()
    assert rows
    body = str([dict(row._mapping) for row in rows])
    for forbidden in ("password", "token", "session", "kivou_session", "@", "argon2", "sk_test"):
        assert forbidden not in body, forbidden


def test_the_table_holds_no_column_for_surveillance_data():
    columns = {column.name for column in product_event.columns}
    for forbidden in ("ip", "user_agent", "referer", "headers", "body"):
        assert not any(forbidden in name for name in columns), forbidden


def test_a_forbidden_property_name_is_refused_at_write_time(engine):
    from signals.engagement.analytics import ForbiddenEventProperty

    with pytest.raises(ForbiddenEventProperty), engine.begin() as connection:
        analytics.record(
            connection,
            account_id="acc",
            event_type="signal_feed_viewed",
            occurred_at=NOW,
            properties={"ip_address": "203.0.113.4"},
        )


def test_an_unknown_event_type_is_refused(engine):
    from signals.engagement.analytics import UnknownEventType

    with pytest.raises(UnknownEventType), engine.begin() as connection:
        analytics.record(connection, account_id="acc", event_type="user_scrolled", occurred_at=NOW)


def test_no_client_facing_analytics_endpoint_exists(alice):
    """§11, §38.11 — il n'y a rien à forger, parce qu'il n'y a pas d'entrée."""
    for path in ("/analytics/event", "/events", "/track", "/analytics"):
        assert alice.post(path, json={"event_type": "subscription_activated"}).status_code in {
            404,
            405,
        }


def test_the_event_vocabulary_is_closed_and_declared():
    assert "signal_contacted" in PRODUCT_EVENT_TYPES
    assert "alert_sent" in PRODUCT_EVENT_TYPES
    assert len(PRODUCT_EVENT_TYPES) == len(set(PRODUCT_EVENT_TYPES))


# ─── §33 — la facturation reste chez Stripe ──────────────────────────────────


def test_no_revenue_accounting_lives_in_the_analytics_table():
    """§33 — Stripe reste la source des faits de paiement."""
    columns = {column.name for column in product_event.columns}
    for forbidden in ("amount", "currency", "mrr", "revenue", "invoice", "price"):
        assert not any(forbidden in name for name in columns), forbidden
