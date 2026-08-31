"""SPEC-013 §20 à §26 — trois signaux offerts, et un mur qui ne donne pas la piste.

Le produit de Kivou EST la piste commerciale
────────────────────────────────────────────
Quelle entreprise, sur quel marché. Un aperçu verrouillé qui laisse voir le
nom de l'attributaire, son identifiant ou l'URL de la source rend le paiement
décoratif : il suffit de lire la liste. Ces tests vérifient que le teaser
donne du contexte de conversion — un événement, une date, un pays, un ordre
de grandeur — et rien qui permette de contacter qui que ce soit.

Discovery n'est pas « trois signaux par jour »
──────────────────────────────────────────────
Ce serait un produit gratuit permanent. Ce sont trois signaux NOMMÉS,
débloqués une fois, conservés, et qui ne tournent plus.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import FakeStripe, subscribe
from fastapi.testclient import TestClient
from feed_helpers import (
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    RESEARCH_ICP_ID,
    SIMAP_RICH,
    materialize,
    materialize_boamp,
    materialize_simap,
    simap_award,
)

from signals.api import ApiConfig, create_app
from signals.billing.schema import discovery_signal_grant
from signals.persistence.database import create_database_engine, migrate_to_latest

READ_ON = dt.date(2026, 8, 25)
NOW = dt.datetime.combine(READ_ON, dt.time(9, 0), tzinfo=dt.UTC)
#: Antérieure à la parution des avis SIMAP : une décision publiée après sa
#: propre parution est refusée par la politique de fraîcheur.
AWARDED_FROM = dt.date(2026, 8, 13)

SIMAP_NAMES = ("29997-02", "33112-02", "33885-03", "34794-02", "38918-02", "41098-01", "42486-01")


class Clock:
    def __init__(self) -> None:
        self.now = NOW

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
def app(engine, clock: Clock):
    return create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            allowed_origin=ORIGIN,
            session_ttl=dt.timedelta(days=365),
            stripe_mode="test",
            stripe_webhook_secret="whsec_test",
        ),
        now_override=clock,
        stripe_gateway=FakeStripe(),
    )


def signed_up(app, email: str = "alice@negoce-romand.ch") -> TestClient:
    client = TestClient(app, headers={"Origin": ORIGIN})
    client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "company_name": "Negoce Romand SA",
            "locale": "fr",
        },
    )
    return client


@pytest.fixture
def alice(app) -> TestClient:
    return signed_up(app)


def icp_of(client: TestClient, label: str = "Intrants", **overrides) -> str:
    payload = {**COMPLETE_ICP_INPUT, **overrides}
    return client.post("/target-icps", json={"label": label, "customer_input": payload}).json()[
        "target_icp_id"
    ]


def account_of(client: TestClient) -> str:
    return client.get("/me").json()["account_id"]


def seed(engine, icp: str, *, count: int) -> list[str]:
    """`count` signaux réels, tous `recent_award` à la date de lecture."""
    keys = []
    with engine.begin() as connection:
        for index in range(count):
            event, awards = simap_award(SIMAP_NAMES[index % len(SIMAP_NAMES)])
            award = awards[0].model_copy(
                update={"award_date": AWARDED_FROM - dt.timedelta(days=index)}
            )
            keys.append(materialize(connection, event, award, target_icp_id=icp).signal_key)
    return keys


def feed(client: TestClient, **params) -> dict:
    query = "&".join(f"{name}={value}" for name, value in params.items())
    response = client.get(f"/signals?{query}" if query else "/signals")
    assert response.status_code == 200, response.text
    return response.json()


def pay(engine, client: TestClient, *, plan: str = "pro", **overrides) -> None:
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_of(client),
            plan=plan,
            subscription_id=f"sub_{account_of(client)[-8:]}",
            now=NOW,
            **overrides,
        )


# ─── §20 — exactement trois déblocages ────────────────────────────────────────


def test_a_discovery_account_unlocks_exactly_three_signals(alice, engine):
    icp = icp_of(alice)
    seed(engine, icp, count=7)

    items = feed(alice, limit=50)["items"]
    unlocked = [item for item in items if not item["locked"]]
    assert len(items) == 7
    assert len(unlocked) == 3


def test_the_three_unlocked_signals_are_the_first_of_the_default_ordering(alice, engine):
    icp = icp_of(alice)
    expected = seed(engine, icp, count=7)

    items = feed(alice, limit=50)["items"]
    unlocked = [item["signal_id"] for item in items if not item["locked"]]
    assert unlocked == [item["signal_id"] for item in items[:3]]
    assert set(unlocked) <= set(expected)


def test_the_grants_are_persisted_and_never_rotate(alice, engine, clock: Clock):
    icp = icp_of(alice)
    seed(engine, icp, count=3)
    first = {item["signal_id"] for item in feed(alice)["items"] if not item["locked"]}

    # Des signaux plus frais arrivent le lendemain ; les cadeaux ne bougent pas.
    clock.move_to(READ_ON + dt.timedelta(days=1))
    with engine.begin() as connection:
        event, awards = simap_award("41098-01")
        materialize(
            connection,
            event,
            awards[0].model_copy(update={"award_date": AWARDED_FROM}),
            target_icp_id=icp,
        )
    later = {item["signal_id"] for item in feed(alice, limit=50)["items"] if not item["locked"]}
    assert later == first
    assert len(later) == 3


def test_fewer_than_three_eligible_signals_grant_what_exists(alice, engine):
    icp = icp_of(alice)
    seed(engine, icp, count=2)

    body = feed(alice)
    assert len([item for item in body["items"] if not item["locked"]]) == 2
    assert alice.get("/billing/status").json()["discovery"]["remaining_slots"] == 1


def test_the_remaining_slots_fill_later_when_new_signals_appear(alice, engine, clock: Clock):
    icp = icp_of(alice)
    seed(engine, icp, count=1)
    assert len([item for item in feed(alice)["items"] if not item["locked"]]) == 1

    clock.move_to(READ_ON + dt.timedelta(days=2))
    with engine.begin() as connection:
        for name in ("33885-03", "34794-02"):
            event, awards = simap_award(name)
            materialize(
                connection,
                event,
                awards[0].model_copy(update={"award_date": AWARDED_FROM}),
                target_icp_id=icp,
            )
    unlocked = [item for item in feed(alice, limit=50)["items"] if not item["locked"]]
    assert len(unlocked) == 3
    assert alice.get("/billing/status").json()["discovery"]["remaining_slots"] == 0


def test_never_more_than_three_grants_exist_for_an_account(alice, engine):
    icp = icp_of(alice)
    seed(engine, icp, count=7)
    for _ in range(5):
        feed(alice, limit=50)

    with engine.connect() as connection:
        count = connection.execute(
            sa.select(sa.func.count()).select_from(discovery_signal_grant)
        ).scalar()
    assert count == 3


def test_a_granted_signal_stays_unlocked_even_when_it_grows_old(alice, engine, clock: Clock):
    """Un cadeau ne se reprend pas parce qu'il a vieilli."""
    icp = icp_of(alice)
    seed(engine, icp, count=1)
    granted = [item["signal_id"] for item in feed(alice)["items"] if not item["locked"]]
    assert len(granted) == 1

    clock.move_to(dt.date(2027, 3, 1))
    body = feed(alice, freshness="all", limit=50)
    unlocked = [item["signal_id"] for item in body["items"] if not item["locked"]]
    assert granted[0] in unlocked


def test_two_accounts_receive_their_own_three_grants(app, engine):
    alice, bob = signed_up(app, "alice@negoce-romand.ch"), signed_up(app, "bob@materiaux-leman.ch")
    alice_icp, bob_icp = icp_of(alice), icp_of(bob)
    seed(engine, alice_icp, count=4)
    seed(engine, bob_icp, count=4)

    alice_unlocked = {i["signal_id"] for i in feed(alice, limit=50)["items"] if not i["locked"]}
    bob_unlocked = {i["signal_id"] for i in feed(bob, limit=50)["items"] if not i["locked"]}
    assert len(alice_unlocked) == len(bob_unlocked) == 3
    assert alice_unlocked & bob_unlocked == set()


# ─── §21 — le teaser ne donne pas la piste ────────────────────────────────────


def locked_item(alice, engine) -> dict:
    icp = icp_of(alice)
    seed(engine, icp, count=7)
    items = feed(alice, limit=50)["items"]
    return next(item for item in items if item["locked"])


def test_a_locked_teaser_never_names_the_company(alice, engine):
    item = locked_item(alice, engine)
    assert set(item) == {
        "signal_id",
        "target_icp_id",
        "locked",
        "unlock_required",
        "event",
        "context",
        "headline",
    }
    assert "presentation" not in item
    assert item["locked"] is True
    visible = json.dumps(
        {key: value for key, value in item.items() if key not in {"signal_id", "target_icp_id"}},
        ensure_ascii=False,
    )
    for forbidden in ("company", "winner", "Egli", "GmbH", "SA "):
        assert forbidden not in visible, forbidden


def test_a_locked_teaser_carries_no_source_url_and_no_evidence(alice, engine):
    item = locked_item(alice, engine)
    body = str(item)
    for forbidden in ("http", "evidence", "notice_id", "procedure_id", "simap", "boamp"):
        assert forbidden not in body.lower(), forbidden


def test_a_locked_teaser_carries_no_contract_title_and_no_buyer(alice, engine):
    item = locked_item(alice, engine)
    assert "contract" not in item
    assert "title" not in str(item)
    assert "buyer" not in str(item)


def test_a_locked_teaser_carries_no_reasoning_and_no_detailed_fit(alice, engine):
    item = locked_item(alice, engine)
    body = str(item)
    for forbidden in ("reasoning", "fit", "statement", "analysis", "plausible_needs"):
        assert forbidden not in body, forbidden


def test_a_locked_teaser_gives_safe_conversion_context(alice, engine):
    item = locked_item(alice, engine)
    assert item["locked"] is True
    assert item["event"]["status"] in {
        "recent_award",
        "recently_notified_contract",
        "recently_published_award",
    }
    assert item["event"]["date"]
    assert item["context"]["country"] == "CH"
    assert item["context"]["contract_magnitude"]
    assert isinstance(item["context"]["plausible_need_count"], int)


def test_the_exact_amount_is_replaced_by_an_order_of_magnitude(alice, engine):
    """Le montant au centime identifie souvent le marché à lui seul."""
    item = locked_item(alice, engine)
    assert item["context"]["contract_magnitude"] in {
        "under_50k",
        "50k_250k",
        "250k_1m",
        "1m_5m",
        "over_5m",
    }
    assert "934877" not in str(item)


def test_the_locked_headline_names_no_company(alice, engine):
    item = locked_item(alice, engine)
    assert item["headline"] == "Un marché public vient d'être attribué."
    assert "Egli" not in item["headline"]
    # La phrase a un sujet : rendre le gabarit nommé avec un nom vide
    # produirait « vient de remporter un marché public. », sans sujet.
    assert item["headline"][0].isupper()


# ─── §21 — le détail verrouillé ───────────────────────────────────────────────


def test_the_detail_of_a_locked_signal_never_returns_the_full_card(alice, engine):
    icp = icp_of(alice)
    seed(engine, icp, count=7)
    items = feed(alice, limit=50)["items"]
    locked = next(item for item in items if item["locked"])

    detail = alice.get(f"/signals/{locked['signal_id']}").json()
    assert detail["locked"] is True
    assert detail["access"]["granted"] is False
    assert "evidence" not in detail
    assert "company" not in detail
    assert "contract" not in detail
    assert "presentation" not in detail


def test_the_detail_of_an_unlocked_signal_is_complete(alice, engine):
    icp = icp_of(alice)
    seed(engine, icp, count=7)
    unlocked = next(item for item in feed(alice, limit=50)["items"] if not item["locked"])

    detail = alice.get(f"/signals/{unlocked['signal_id']}").json()
    assert detail["locked"] is False
    assert detail["company"]["name"]
    assert detail["evidence"]["public_facts"]


def test_a_locked_detail_is_not_a_404_because_the_account_owns_it(alice, engine):
    """Confondre « pas à vous » et « pas encore payé » empêcherait de convertir."""
    icp = icp_of(alice)
    seed(engine, icp, count=7)
    locked = next(item for item in feed(alice, limit=50)["items"] if item["locked"])
    assert alice.get(f"/signals/{locked['signal_id']}").status_code == 200


# ─── §22 — la facturation ne remplace jamais la propriété ────────────────────


def test_a_paid_account_still_never_sees_a_foreign_signal(app, engine):
    alice, bob = signed_up(app, "alice@negoce-romand.ch"), signed_up(app, "bob@materiaux-leman.ch")
    alice_icp = icp_of(alice)
    icp_of(bob)
    pay(engine, bob, plan="scale")
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=alice_icp)

    assert feed(bob, freshness="all")["items"] == []
    assert bob.get(f"/signals/{signal.signal_key}").status_code == 404


def test_a_paid_account_still_never_sees_an_unbound_signal(alice, engine):
    icp = icp_of(alice)
    pay(engine, alice, plan="scale")
    with engine.begin() as connection:
        mine = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)
        unbound = materialize_boamp(connection, "26-80978", target_icp_id=RESEARCH_ICP_ID)

    keys = {item["signal_id"] for item in feed(alice, freshness="all", limit=50)["items"]}
    assert keys == {mine.signal_key}
    assert alice.get(f"/signals/{unbound.signal_key}").status_code == 404


def test_paying_unlocks_everything_within_the_plan_scope(alice, engine):
    icp = icp_of(alice)
    seed(engine, icp, count=7)
    assert len([i for i in feed(alice, limit=50)["items"] if not i["locked"]]) == 3

    pay(engine, alice, plan="scale")
    items = feed(alice, limit=50)["items"]
    assert all(item["locked"] is False for item in items)
    assert len(items) == 7


# ─── §25 — l'historique ───────────────────────────────────────────────────────


def old_and_new(engine, icp: str) -> tuple[str, str]:
    """Un signal d'il y a douze jours, et un d'il y a plus de cent jours."""
    with engine.begin() as connection:
        fresh_event, fresh_awards = simap_award("29997-02")
        fresh = materialize(
            connection,
            fresh_event,
            fresh_awards[0].model_copy(update={"award_date": AWARDED_FROM}),
            target_icp_id=icp,
        )
        old_event, old_awards = simap_award("33112-02")
        old = materialize(
            connection,
            old_event,
            old_awards[0].model_copy(update={"award_date": dt.date(2026, 5, 1)}),
            target_icp_id=icp,
        )
    return fresh.signal_key, old.signal_key


def test_essential_unlocks_thirty_days_of_history(alice, engine):
    icp = icp_of(alice)
    fresh, old = old_and_new(engine, icp)
    pay(engine, alice, plan="essential")

    items = {i["signal_id"]: i for i in feed(alice, freshness="all", limit=50)["items"]}
    assert items[fresh]["locked"] is False
    assert items[old]["locked"] is True, "116 jours dépassent la fenêtre de 30 jours"


def test_pro_unlocks_a_year_of_history(alice, engine):
    icp = icp_of(alice)
    fresh, old = old_and_new(engine, icp)
    pay(engine, alice, plan="pro")

    items = {i["signal_id"]: i for i in feed(alice, freshness="all", limit=50)["items"]}
    assert items[fresh]["locked"] is False
    assert items[old]["locked"] is False


def test_scale_unlocks_all_the_history_that_exists(alice, engine, clock: Clock):
    icp = icp_of(alice)
    fresh, old = old_and_new(engine, icp)
    pay(engine, alice, plan="scale")
    clock.move_to(dt.date(2027, 6, 1))

    items = {i["signal_id"]: i for i in feed(alice, freshness="all", limit=50)["items"]}
    assert all(not item["locked"] for item in items.values())
    assert {fresh, old} <= set(items)


def test_a_history_window_never_authorises_recent_wording_on_an_old_signal(alice, engine):
    """§25 — payer plus n'autorise pas à mentir sur la date."""
    icp = icp_of(alice)
    _, old = old_and_new(engine, icp)
    pay(engine, alice, plan="scale")

    item = {i["signal_id"]: i for i in feed(alice, freshness="all", limit=50)["items"]}[old]
    assert item["event"]["status"] == "stale_award"
    assert item["event"]["is_new_opportunity"] is False
    assert "vient de remporter" not in item["event"]["headline"]


# ─── §26 — les filtres ────────────────────────────────────────────────────────


def test_a_filter_beyond_the_plan_is_refused_rather_than_ignored(alice, engine):
    """L'ignorer rendrait une page qui ne correspond pas à la demande."""
    icp_of(alice)
    response = alice.get("/signals?winner=Egli")
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "filter_not_entitled"
    assert detail["filter"] == "winner"
    assert detail["required_level"] == "advanced"


def test_discovery_may_still_filter_by_its_own_icp(alice, engine):
    icp = icp_of(alice)
    seed(engine, icp, count=2)
    assert alice.get(f"/signals?target_icp_id={icp}").status_code == 200


def test_essential_may_filter_by_country_but_not_by_winner(alice, engine):
    icp_of(alice)
    pay(engine, alice, plan="essential")
    assert alice.get("/signals?country=CH").status_code == 200
    assert alice.get("/signals?winner=Egli").status_code == 403


def test_pro_may_use_every_filter(alice, engine):
    icp_of(alice)
    pay(engine, alice, plan="pro")
    assert (
        alice.get("/signals?winner=Egli&country=CH&primary_event=recent_award").status_code == 200
    )
