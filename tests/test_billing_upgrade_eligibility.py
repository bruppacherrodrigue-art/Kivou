"""RTL-04 / #27 — `upgrade_to` ne doit promettre que ce que le paiement tient.

Le défaut corrigé ici
─────────────────────
`locked_detail()` rendait la liste FIXE `essential / pro / scale` pour tout
signal verrouillé. Or l'accès payant n'est pas « tout ou rien » : chaque plan
porte une fenêtre d'historique, et un signal de 400 jours reste verrouillé
après un paiement Essential. Recommander Essential dans ce cas, c'est encaisser
pour un déblocage qui n'aura pas lieu.

La règle et son unique source
─────────────────────────────
L'éligibilité se calcule en REJOUANT la vraie décision d'accès
(`FeedAccess.is_unlocked`) avec les droits du plan candidat. Aucune règle de
date n'est réécrite ici, ni dans React : dupliquer `within_history_window`
garantirait qu'une des deux copies devienne fausse un jour.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import FakeStripe, subscribe
from fastapi.testclient import TestClient
from feed_helpers import (
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    SIMAP_RICH,
    materialize,
    materialize_simap,
    simap_award,
)

from signals.api import ApiConfig, create_app
from signals.billing.access import eligible_upgrade_plans, feed_access
from signals.billing.schema import discovery_signal_grant
from signals.persistence.database import create_database_engine, migrate_to_latest

#: La date d'attribution de référence. Tous les âges sont fabriqués en DÉPLAÇANT
#: l'horloge de lecture, jamais en réécrivant l'histoire du signal.
AWARD_DATE = dt.date(2026, 6, 1)
#: Une attribution récente ET antérieure à la parution des avis SIMAP : une
#: décision publiée après sa propre parution est refusée par la politique de
#: fraîcheur (`invalid_award_date`) et ne figure alors dans aucun feed.
RECENT_AWARD_DATE = dt.date(2026, 8, 13)
NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)


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
            session_ttl=dt.timedelta(days=50_000),
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


def icp_of(client: TestClient) -> str:
    return client.post(
        "/target-icps", json={"label": "Intrants", "customer_input": COMPLETE_ICP_INPUT}
    ).json()["target_icp_id"]


def account_of(client: TestClient) -> str:
    return client.get("/me").json()["account_id"]


def pay(engine, client: TestClient, *, plan: str) -> None:
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_of(client),
            plan=plan,
            subscription_id=f"sub_{account_of(client)[-8:]}",
            now=NOW,
        )


#: Le nom de l'attributaire du signal fabriqué par `a_signal`, retenu au moment
#: de la matérialisation : c'est la chaîne qui ne doit JAMAIS ressortir.
WINNER_NAME: dict[str, str] = {}


def a_signal(engine, icp: str, *, award_date: dt.date = AWARD_DATE) -> str:
    with engine.begin() as connection:
        event, awards = simap_award("29997-02")
        award = awards[0].model_copy(update={"award_date": award_date})
        stored = materialize(connection, event, award, target_icp_id=icp)
    WINNER_NAME[stored.signal_key] = award.awardee_organizations()[0].legal_name
    return stored.signal_key


def detail(client: TestClient, signal_key: str) -> dict:
    response = client.get(f"/signals/{signal_key}")
    assert response.status_code == 200, response.text
    return response.json()


def upgrade_to(client: TestClient, signal_key: str) -> list[str]:
    body = detail(client, signal_key)
    assert body["locked"] is True, "ce test suppose un signal verrouillé"
    return list(body["access"]["upgrade_to"])


def read_at(clock: Clock, *, age_days: int) -> None:
    clock.move_to(AWARD_DATE + dt.timedelta(days=age_days))


# ─── Les frontières de fenêtre, plan par plan ─────────────────────────────────


@pytest.mark.parametrize(
    "age_days, expected",
    [
        (0, ["essential", "pro", "scale"]),
        (30, ["essential", "pro", "scale"]),
        (31, ["pro", "scale"]),
        (365, ["pro", "scale"]),
        (366, ["scale"]),
        (900, ["scale"]),
    ],
    ids=["today", "essential-edge", "past-essential", "pro-edge", "past-pro", "long-past"],
)
def test_only_the_plans_that_would_really_open_the_signal_are_offered(
    alice, engine, clock: Clock, age_days: int, expected: list[str]
):
    """30/31 et 365/366 : les deux frontières où une promesse devient fausse."""
    icp = icp_of(alice)
    signal = a_signal(engine, icp)
    # Les trois déblocages Discovery iraient à ce signal : on les épuise
    # ailleurs pour que celui-ci soit bien verrouillé par la FENÊTRE.
    exhaust_discovery_grants(engine, alice)
    read_at(clock, age_days=age_days)

    assert upgrade_to(alice, signal) == expected


def exhaust_discovery_grants(engine, client: TestClient) -> None:
    """Consomme les trois déblocages sur d'autres signaux que celui testé.

    Sans cela, le signal sous test serait ouvert par un CADEAU, et l'on
    mesurerait la générosité de Discovery au lieu de la fenêtre du plan.
    """
    account_id = account_of(client)
    with engine.begin() as connection:
        for index in range(3):
            connection.execute(
                sa.insert(discovery_signal_grant).values(
                    account_id=account_id,
                    signal_key=f"grant-filler-{index}",
                    granted_at=NOW,
                    created_at=NOW,
                    opportunity_key=f"opp-filler-{index}",
                )
            )


# ─── Le plan déjà payé ────────────────────────────────────────────────────────


def test_a_pro_account_is_only_offered_scale_for_a_signal_beyond_its_year(
    alice, engine, clock: Clock
):
    """Recommander Pro à un client Pro serait lui vendre ce qu'il a déjà."""
    icp = icp_of(alice)
    signal = a_signal(engine, icp)
    pay(engine, alice, plan="pro")
    read_at(clock, age_days=400)

    assert upgrade_to(alice, signal) == ["scale"]


def test_an_essential_account_keeps_pro_and_scale_as_real_options(alice, engine, clock: Clock):
    icp = icp_of(alice)
    signal = a_signal(engine, icp)
    pay(engine, alice, plan="essential")
    read_at(clock, age_days=100)

    assert upgrade_to(alice, signal) == ["pro", "scale"]


def test_a_scale_account_has_nothing_left_to_be_sold(alice, engine, clock: Clock):
    """Scale ouvre tout l'historique persisté : plus rien n'est verrouillé."""
    icp = icp_of(alice)
    signal = a_signal(engine, icp)
    pay(engine, alice, plan="scale")
    read_at(clock, age_days=5_000)

    assert detail(alice, signal)["locked"] is False


# ─── Un déblocage Discovery est acquis, pas prêté ─────────────────────────────


def test_a_discovery_granted_signal_never_produces_a_payment_recommendation(
    alice, engine, clock: Clock
):
    """Un cadeau ne se reprend pas parce qu'il a vieilli — ni ne se refacture."""
    icp = icp_of(alice)
    # La file d'attente des déblocages est TOUJOURS le feed par défaut : un
    # signal déjà ancien n'y figure pas et ne serait jamais offert. Le cadeau
    # se fait donc quand le signal est frais — c'est ensuite qu'il vieillit.
    signal = a_signal(engine, icp, award_date=RECENT_AWARD_DATE)
    assert alice.get("/signals").status_code == 200
    assert detail(alice, signal)["locked"] is False, "le premier signal est offert"

    clock.move_to(NOW.date() + dt.timedelta(days=2_000))

    body = detail(alice, signal)
    assert body["locked"] is False
    assert "access" not in body or body.get("access", {}).get("upgrade_to") in (None, [], ())


# ─── Une date absente n'entre dans aucune fenêtre finie ───────────────────────


def test_a_signal_without_a_usable_date_is_only_opened_by_unlimited_history(alice, engine):
    """Sans date, le signal ne PEUT pas prouver qu'il tombe dans une fenêtre.

    Seul un plan à historique `all_available` l'ouvre — et c'est exactement ce
    que `upgrade_to` doit dire, plutôt que de proposer les trois plans.
    """
    icp = icp_of(alice)
    account_id = account_of(alice)
    with engine.begin() as connection:
        stored = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)
        access = feed_access(connection, account_id=account_id, as_of=NOW.date())

    from signals.feed.query import FeedSignal

    item = FeedSignal(
        signal=stored,
        recency=undated(),
        account_id=account_id,
        target_icp_label="Intrants",
    )
    assert item.event_date is None

    assert eligible_upgrade_plans(item, access=access) == ("scale",)


def undated():
    """Une évaluation de fraîcheur qu'AUCUNE date ne renseigne.

    Produite par la vraie politique plutôt qu'amputée après coup : c'est un
    état que les sources produisent réellement, pas une fiction de test.
    """
    from signals.recency.policy import assess_recency

    return assess_recency(
        award_date=None,
        contract_notification_date=None,
        publication_date=None,
        as_of=NOW.date(),
    )


# ─── Ce qu'une carte verrouillée ne révèle jamais ─────────────────────────────


def test_a_locked_detail_still_reveals_nothing_actionable(alice, engine, clock: Clock):
    """La vérité de `upgrade_to` ne doit rien acheter en confidentialité."""
    icp = icp_of(alice)
    signal = a_signal(engine, icp)
    exhaust_discovery_grants(engine, alice)
    read_at(clock, age_days=400)

    body = detail(alice, signal)
    assert body["locked"] is True
    serialized = repr(body)
    for forbidden in ("company", "winner", "evidence", "source_url", "contract", "analysis"):
        assert forbidden not in body, f"{forbidden!r} n'a rien à faire dans un détail verrouillé"
    # L'identité de l'attributaire ne doit apparaître sous AUCUNE forme.
    assert WINNER_NAME[signal]
    assert WINNER_NAME[signal] not in serialized


# ─── La propriété du compte reste la première condition ───────────────────────


def test_a_foreign_signal_is_a_404_and_never_an_upgrade_pitch(app, engine, clock: Clock):
    alice, bob = signed_up(app), signed_up(app, "bob@materiaux-leman.ch")
    alice_icp = icp_of(alice)
    icp_of(bob)
    signal = a_signal(engine, alice_icp)
    read_at(clock, age_days=400)

    assert bob.get(f"/signals/{signal}").status_code == 404
