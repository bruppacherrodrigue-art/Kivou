"""SPEC-012 §2, §25 — le feed part du compte, jamais de la table des signaux.

Un feed qui commencerait par `SELECT * FROM materialized_signal` puis filtrerait
sur le compte laisserait passer exactement ce que SPEC-011 a déclaré interdit :
les signaux d'avant les comptes, dont personne ne peut prouver le propriétaire.
La requête part donc des TargetICP du compte authentifié et descend.

L'autre moitié de ces tests porte sur ce que l'API ne dit pas. Un signal
étranger et un signal inexistant doivent être indiscernables, sinon l'API
devient un oracle qu'on interroge une clé à la fois.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
from fastapi.testclient import TestClient
from feed_helpers import (
    BOAMP_AGING,
    ORIGIN,
    PASSWORD,
    RESEARCH_ICP_ID,
    RETRIEVED_AT,
    SIMAP_RICH,
    materialize_boamp,
    materialize_simap,
)

from signals.api import ApiConfig, create_app
from signals.persistence.database import create_database_engine, migrate_to_latest


class Clock:
    def __init__(self, start: dt.datetime = RETRIEVED_AT) -> None:
        self.now = start

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, delta: dt.timedelta) -> None:
        self.now += delta


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
        engine, ApiConfig(cookie_secure=False, allowed_origin=ORIGIN), now_override=clock
    )


def client_for(app, email: str, company: str) -> TestClient:
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={"email": email, "password": PASSWORD, "company_name": company, "locale": "fr"},
    )
    assert response.status_code == 201, response.text
    return client


@pytest.fixture
def alice(app) -> TestClient:
    return client_for(app, "alice@negoce-romand.ch", "Negoce Romand SA")


@pytest.fixture
def bob(app) -> TestClient:
    return client_for(app, "bob@materiaux-leman.ch", "Materiaux Leman SA")


def icp_of(client: TestClient, label: str = "Intrants") -> str:
    from feed_helpers import COMPLETE_ICP_INPUT

    response = client.post(
        "/target-icps", json={"label": label, "customer_input": COMPLETE_ICP_INPUT}
    )
    assert response.status_code == 201, response.text
    return response.json()["target_icp_id"]


# ─── §25.1 — l'anonyme ne voit rien ────────────────────────────────────────────


def test_the_feed_refuses_an_unauthenticated_caller(app):
    anonymous = TestClient(app, headers={"Origin": ORIGIN})
    assert anonymous.get("/signals").status_code == 401
    assert anonymous.get("/signals/quelconque").status_code == 401


# ─── §25.2, §25.3 — un compte ne voit que le sien ─────────────────────────────


def test_one_account_never_lists_the_signals_of_another(alice, bob, engine):
    alice_icp, bob_icp = icp_of(alice), icp_of(bob)
    with engine.begin() as connection:
        materialize_simap(connection, SIMAP_RICH, target_icp_id=alice_icp)
        materialize_boamp(connection, BOAMP_AGING, target_icp_id=bob_icp)

    alice_items = alice.get("/signals?freshness=all").json()["items"]
    bob_items = bob.get("/signals?freshness=all").json()["items"]

    assert len(alice_items) == 1
    assert len(bob_items) == 1
    assert {item["target_icp_id"] for item in alice_items} == {alice_icp}
    assert {item["target_icp_id"] for item in bob_items} == {bob_icp}


def test_one_account_cannot_open_the_signal_of_another_by_its_key(alice, bob, engine):
    alice_icp = icp_of(alice)
    icp_of(bob)
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=alice_icp)

    assert alice.get(f"/signals/{signal.signal_key}").status_code == 200
    assert bob.get(f"/signals/{signal.signal_key}").status_code == 404


def test_a_foreign_signal_is_indistinguishable_from_a_missing_one(alice, bob, engine):
    """§25.6 — sinon l'API devient un annuaire qu'on parcourt clé par clé."""
    alice_icp = icp_of(alice)
    icp_of(bob)
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=alice_icp)

    foreign = bob.get(f"/signals/{signal.signal_key}")
    missing = bob.get("/signals/sig_qui_n_existe_pas")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


# ─── §25.4 — le signal d'avant les comptes n'entre jamais ─────────────────────


def test_a_pre_saas_signal_never_appears_in_a_customer_feed(alice, engine):
    alice_icp = icp_of(alice)
    with engine.begin() as connection:
        mine = materialize_simap(connection, SIMAP_RICH, target_icp_id=alice_icp)
        unbound = materialize_boamp(connection, BOAMP_AGING, target_icp_id=RESEARCH_ICP_ID)

    keys = {item["signal_id"] for item in alice.get("/signals?freshness=all").json()["items"]}
    assert keys == {mine.signal_key}
    assert unbound.signal_key not in keys
    assert alice.get(f"/signals/{unbound.signal_key}").status_code == 404


# ─── §25.5 — filtrer par l'ICP d'autrui ne donne rien ─────────────────────────


def test_the_icp_of_another_account_cannot_be_used_as_a_filter(alice, bob, engine):
    alice_icp, bob_icp = icp_of(alice), icp_of(bob)
    with engine.begin() as connection:
        materialize_simap(connection, SIMAP_RICH, target_icp_id=alice_icp)

    response = bob.get(f"/signals?target_icp_id={alice_icp}&freshness=all")
    assert response.status_code == 404
    assert response.json() == bob.get("/signals?target_icp_id=ticp_inexistant").json()
    assert bob_icp != alice_icp


def test_filtering_by_an_own_icp_narrows_the_feed(alice, engine, clock: Clock):
    """SPEC-013 — deux profils actifs demandent un plan qui les autorise : un
    compte Discovery n'en sert qu'un, et le test porterait alors sur autre
    chose que le filtre."""
    from billing_helpers import subscribe

    with engine.begin() as connection:
        subscribe(connection, account_id=alice.get("/me").json()["account_id"], now=clock.now)
    first = icp_of(alice, "Gros œuvre")
    clock.advance(dt.timedelta(minutes=1))
    second = icp_of(alice, "Second œuvre")
    with engine.begin() as connection:
        one = materialize_simap(connection, SIMAP_RICH, target_icp_id=first)
        materialize_boamp(connection, BOAMP_AGING, target_icp_id=second)

    items = alice.get(f"/signals?target_icp_id={first}&freshness=all").json()["items"]
    assert [item["signal_id"] for item in items] == [one.signal_key]


# ─── §25.7, §25.8, §18 — états vides ordinaires ───────────────────────────────


def test_an_account_without_any_icp_gets_an_empty_feed_not_an_error(alice):
    response = alice.get("/signals")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_an_account_with_only_a_draft_icp_gets_an_empty_feed(alice, engine):
    draft = alice.post(
        "/target-icps",
        json={"label": "Brouillon", "customer_input": {"offers": ["materials_and_components"]}},
    ).json()
    assert draft["status"] == "draft"
    with engine.begin() as connection:
        materialize_simap(connection, SIMAP_RICH, target_icp_id=draft["target_icp_id"])

    assert alice.get("/signals?freshness=all").json()["items"] == []
    assert alice.get("/me").json()["onboarding_status"] == "icp_incomplete"


def test_an_active_icp_without_any_signal_is_an_ordinary_empty_answer(alice):
    icp_of(alice)
    body = alice.get("/signals").json()
    assert body["items"] == []
    assert body["total_returned"] == 0


def test_ownership_is_derived_only_through_the_target_icp(alice, engine):
    """§25.8 — la seule chaîne : session → compte → target_icp → signal."""
    from signals.accounts.ownership import account_for_materialized_signal

    alice_icp = icp_of(alice)
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=alice_icp)

    account_id = alice.get("/me").json()["account_id"]
    with engine.connect() as connection:
        assert account_for_materialized_signal(connection, signal_key=signal.signal_key) == (
            account_id
        )
