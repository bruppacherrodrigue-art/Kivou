"""SPEC-012 §5, §6, §26 — le feed dit ce qui est vrai AUJOURD'HUI.

C'est la correction que SPEC-009D a rendue obligatoire. Le moteur matérialise un
constat daté ; le produit, lui, est lu des semaines plus tard. Entre les deux,
la même ligne cesse d'être une nouveauté sans que rien ne bouge en base.

Ces tests ne fabriquent donc aucune date : ils prennent un avis réel, le
matérialisent une fois, puis **avancent l'horloge de lecture**. C'est exactement
ce que fait la production, et c'est le seul protocole qui puisse attraper une
phrase qui vieillit mal.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import subscribe
from fastapi.testclient import TestClient
from feed_helpers import (
    BOAMP_AGING,
    BOAMP_PUBLICATION_ONLY,
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    RETRIEVED_AT,
    materialize,
    materialize_boamp,
)

from signals.api import ApiConfig, create_app
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import materialized_signal
from signals.recency.claim import JUST_WON_MARKERS


class Clock:
    def __init__(self) -> None:
        self.now = RETRIEVED_AT

    def __call__(self) -> dt.datetime:
        return self.now

    def move_to(self, day: dt.date) -> None:
        self.now = dt.datetime.combine(day, dt.time(9, 0), tzinfo=dt.UTC)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def client(engine, clock: Clock) -> TestClient:
    # La session doit survivre aux mois que ces tests traversent : l'objet
    # étudié ici est la fraîcheur du signal, pas l'expiration de session — que
    # SPEC-011 teste déjà pour elle-même.
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=clock,
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    assert (
        client.post(
            "/auth/signup",
            json={
                "email": "alice@negoce-romand.ch",
                "password": PASSWORD,
                "company_name": "Negoce Romand SA",
                "locale": "fr",
            },
        ).status_code
        == 201
    )
    subscribe_to_scale(engine, client)
    return client


def subscribe_to_scale(engine, client) -> None:
    """Abonne le compte à Scale — historique complet, filtres avancés.

    SPEC-013 : ces tests portent sur la FRAÎCHEUR et l'IDENTITÉ d'un signal
    débloqué. Depuis l'arrivée de la facturation, un compte Discovery ne voit
    que trois signaux offerts et verrouille le reste ; l'abonnement garde donc
    ces assertions sur leur objet. Le mur payant a ses propres tests.
    """
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="scale",
            subscription_id=f"sub_test_{account_id[-8:]}",
            now=RETRIEVED_AT,
        )


@pytest.fixture
def icp(client: TestClient) -> str:
    response = client.post(
        "/target-icps", json={"label": "Intrants", "customer_input": COMPLETE_ICP_INPUT}
    )
    return response.json()["target_icp_id"]


def feed(client: TestClient, **params) -> dict:
    query = "&".join(f"{name}={value}" for name, value in params.items())
    response = client.get(f"/signals?{query}" if query else "/signals")
    assert response.status_code == 200, response.text
    return response.json()


def only(body: dict) -> dict:
    assert len(body["items"]) == 1, body["items"]
    return body["items"][0]


# ─── §26.1, §26.2 — la même ligne cesse d'être une nouveauté ──────────────────


def test_a_recent_award_appears_in_the_default_feed(client, icp, engine, clock: Clock):
    """L'avis est attribué le 2026-07-17 ; lu le 2026-07-20, il a trois jours."""
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_AGING, target_icp_id=icp)
    clock.move_to(dt.date(2026, 7, 20))

    item = only(feed(client))
    assert item["event"]["status"] == "recent_award"
    assert item["event"]["date"] == "2026-07-17"
    assert item["event"]["age_days"] == 3
    assert item["event"]["is_new_opportunity"] is True
    assert "vient de remporter" in item["event"]["headline"]


def test_the_same_stored_signal_stops_claiming_a_win_after_thirty_days(
    client, icp, engine, clock: Clock
):
    """§26.2 — rien ne change en base ; seule la date de lecture avance."""
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_AGING, target_icp_id=icp)

    clock.move_to(dt.date(2026, 7, 20))
    assert only(feed(client))["event"]["status"] == "recent_award"

    clock.move_to(dt.date(2026, 8, 25))
    assert feed(client)["items"] == [], "ce n'est plus une nouveauté"

    aged = only(feed(client, freshness="recent_or_aging"))
    assert aged["event"]["status"] == "aging_award"
    assert aged["event"]["is_new_opportunity"] is False
    assert not any(marker in aged["event"]["headline"].lower() for marker in JUST_WON_MARKERS)


def test_a_signal_read_much_later_is_stale_and_leaves_the_default_feed(
    client, icp, engine, clock: Clock
):
    """§26.5 — `stale_award` ne doit apparaître dans aucun feed de nouveautés."""
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_AGING, target_icp_id=icp)
    clock.move_to(dt.date(2026, 12, 1))

    assert feed(client)["items"] == []
    assert feed(client, freshness="recent_or_aging")["items"] == []

    historical = only(feed(client, freshness="all"))
    assert historical["event"]["status"] == "stale_award"
    assert not any(marker in historical["event"]["headline"].lower() for marker in JUST_WON_MARKERS)
    assert "déjà attribué" in historical["event"]["headline"]


# ─── §26.3 — une notification n'est pas une victoire ──────────────────────────


def test_a_recent_notification_never_borrows_the_wording_of_a_win(
    client, icp, engine, clock: Clock
):
    """Un contrat notifié hier, décidé il y a longtemps : deux horloges, une phrase."""
    from feed_helpers import boamp_award

    event, awards = boamp_award(BOAMP_AGING)
    notified = awards[0].model_copy(
        update={"award_date": None, "contract_notification_date": dt.date(2026, 8, 20)}
    )
    with engine.begin() as connection:
        materialize(connection, event, notified, target_icp_id=icp)
    clock.move_to(dt.date(2026, 8, 25))

    item = only(feed(client))
    assert item["event"]["status"] == "recently_notified_contract"
    assert item["event"]["clock"] == "notification"
    assert item["event"]["date"] == "2026-08-20"
    assert "vient d'être notifié" in item["event"]["headline"]
    assert not any(marker in item["event"]["headline"].lower() for marker in JUST_WON_MARKERS)
    assert "notification récente" in item["event"]["why_now"].lower()


# ─── §26.4 — une parution récente sans date de décision ───────────────────────


def test_a_recent_publication_without_an_award_date_uses_publication_wording(
    client, icp, engine, clock: Clock
):
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_PUBLICATION_ONLY, target_icp_id=icp)
    clock.move_to(dt.date(2026, 8, 25))

    item = only(feed(client))
    assert item["event"]["status"] == "recently_published_award"
    assert item["event"]["clock"] == "publication"
    assert item["contract"]["dates"]["award"] is None
    assert "vient d'être publiée" in item["event"]["headline"]
    assert "date de décision est inconnue" in item["event"]["why_now"]


# ─── §26.6 — l'instantané d'audit ne bouge pas ────────────────────────────────


def test_the_materialized_snapshot_is_never_rewritten_by_a_later_read(
    client, icp, engine, clock: Clock
):
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_AGING, target_icp_id=icp)

    def snapshot() -> tuple:
        with engine.connect() as connection:
            return connection.execute(
                sa.select(
                    materialized_signal.c.materialized_recency_status,
                    materialized_signal.c.materialized_as_of,
                    materialized_signal.c.materialized_award_age_days,
                    materialized_signal.c.revision,
                )
            ).one()

    before = snapshot()
    clock.move_to(dt.date(2026, 12, 1))
    feed(client, freshness="all")
    assert snapshot() == before


def test_the_materialized_snapshot_is_not_part_of_the_customer_answer(
    client, icp, engine, clock: Clock
):
    """§6 — l'exposer laisserait croire que l'instantané est la vérité du jour."""
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_AGING, target_icp_id=icp)
    clock.move_to(dt.date(2026, 12, 1))

    body = str(feed(client, freshness="all"))
    for forbidden in ("materialized_recency_status", "materialized_as_of", "materialized_at"):
        assert forbidden not in body, forbidden


# ─── §26.7 — la date de lecture est explicite ─────────────────────────────────


def test_the_feed_states_the_date_it_was_read_at(client, icp, engine, clock: Clock):
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_AGING, target_icp_id=icp)
    clock.move_to(dt.date(2026, 9, 3))

    body = feed(client, freshness="all")
    assert body["read_at"] == "2026-09-03"
    assert only(body)["event"]["age_days"] == 48


def test_no_hidden_clock_exists_in_the_feed_layer():
    """§26 — une horloge cachée rendrait ces tests faux dès le lendemain."""
    import inspect

    from signals.feed import query, view

    for module in (query, view):
        source = inspect.getsource(module)
        for forbidden in ("date.today()", "datetime.now(", "utcnow("):
            assert forbidden not in source, f"{module.__name__} : {forbidden}"


def test_the_reading_date_drives_the_result_not_the_materialization_date(
    client, icp, engine, clock: Clock
):
    """Deux lectures du MÊME signal, deux vérités — c'est le comportement voulu."""
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_AGING, target_icp_id=icp)

    clock.move_to(dt.date(2026, 7, 20))
    early = only(feed(client, freshness="all"))
    clock.move_to(dt.date(2026, 10, 1))
    late = only(feed(client, freshness="all"))

    assert early["signal_id"] == late["signal_id"]
    assert early["event"]["status"] != late["event"]["status"]
    assert early["contract"]["dates"] == late["contract"]["dates"], "les faits ne bougent pas"


# ─── §5 — l'ordre met l'actionnable devant ────────────────────────────────────


def test_the_feed_puts_the_currently_actionable_event_first(client, icp, engine, clock: Clock):
    """Une parution récente ne passe pas devant une décision récente.

    La date d'attribution reste antérieure à la parution de l'avis : une
    décision postérieure à sa propre publication est refusée par la politique
    de fraîcheur, et le fixture publie le 2026-08-18.
    """
    from feed_helpers import boamp_award

    event, awards = boamp_award(BOAMP_AGING)
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_PUBLICATION_ONLY, target_icp_id=icp)
        materialize(
            connection,
            event,
            awards[0].model_copy(update={"award_date": dt.date(2026, 8, 17)}),
            target_icp_id=icp,
        )
    clock.move_to(dt.date(2026, 8, 25))

    statuses = [item["event"]["status"] for item in feed(client)["items"]]
    assert statuses == ["recent_award", "recently_published_award"]


def test_two_signals_of_the_same_status_are_ordered_by_date_descending(
    client, icp, engine, clock: Clock
):
    from feed_helpers import boamp_award

    event, awards = boamp_award(BOAMP_AGING)
    with engine.begin() as connection:
        for day, lot in ((dt.date(2026, 8, 10), 0), (dt.date(2026, 8, 17), 1)):
            materialize(
                connection,
                event,
                awards[lot].model_copy(update={"award_date": day}),
                target_icp_id=icp,
            )
    clock.move_to(dt.date(2026, 8, 25))

    dates = [item["event"]["date"] for item in feed(client)["items"]]
    assert dates == ["2026-08-17", "2026-08-10"]
