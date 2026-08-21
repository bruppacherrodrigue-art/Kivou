"""P0-03F — ce que devient la tentative quand Stripe n'ouvre pas la session.

Le défaut que ce fichier ferme
──────────────────────────────
La réservation locale précède l'appel Stripe, délibérément (§9 : la base
arbitre la concurrence, un verrou en mémoire ne tiendrait pas sur un second
worker). Mais quand l'appel Stripe échouait derrière, la réservation
survivait : le compte recevait 409 pendant trente minutes pour un échec qui
n'était même pas le sien. Constaté en vrai sur staging — 1ᵉʳ POST 500, 2ᵉ POST
409, sur un compte qui n'avait rien fait de mal.

La correction n'annule PAS la réservation avant Stripe. Elle distingue deux
situations que le code confondait :

    refus prouvé de la requête   →  aucune session n'existe  →  place libérée
    réponse jamais reçue         →  une session existe peut-être  →  place gardée

L'asymétrie est voulue. Se tromper en libérant crée un SECOND paiement ; se
tromper en gardant fait attendre trente minutes. Le doute garde donc la place.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import BILLING_RETURN_URLS, TEST_WEBHOOK_SECRET, FakeStripe
from fastapi.testclient import TestClient
from feed_helpers import ORIGIN, PASSWORD

from signals.api import ApiConfig, create_app
from signals.billing import attempts
from signals.billing.gateway import CheckoutSessionRejected, CheckoutSessionUncertain
from signals.billing.schema import billing_checkout_attempt
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

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
def stripe() -> FakeStripe:
    return FakeStripe()


@pytest.fixture
def client(engine, stripe: FakeStripe, clock: Clock) -> TestClient:
    app = create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            allowed_origin=ORIGIN,
            session_ttl=dt.timedelta(days=365),
            stripe_mode="test",
            stripe_webhook_secret=TEST_WEBHOOK_SECRET,
            **BILLING_RETURN_URLS,
        ),
        now_override=clock,
        stripe_gateway=stripe,
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
    return client


def start(client: TestClient, plan: str = "pro", currency: str = "chf"):
    return client.post("/billing/checkout", json={"plan": plan, "currency": currency})


def account_of(client: TestClient) -> str:
    return client.get("/me").json()["account_id"]


def attempt_of(engine, account_id: str):
    with engine.connect() as connection:
        return attempts.current_attempt(connection, account_id=account_id)


def rows(engine):
    with engine.connect() as connection:
        return connection.execute(sa.select(billing_checkout_attempt)).all()


def always_reject(stripe: FakeStripe) -> None:
    def refuse(**_: object):
        raise CheckoutSessionRejected("Stripe a refusé la création de la session de paiement")

    stripe.create_checkout_session = refuse


def always_uncertain(stripe: FakeStripe) -> None:
    def lose(**_: object):
        raise CheckoutSessionUncertain("réponse non concluante")

    stripe.create_checkout_session = lose


# ─── 1. refus définitif — la place est libérée tout de suite ─────────────────


def test_un_refus_definitif_marque_la_tentative_failed(client, engine, stripe):
    always_reject(stripe)

    start(client)

    stored = attempt_of(engine, account_of(client))
    assert stored.status == "failed"
    assert stored.stripe_checkout_session_id is None


def test_un_refus_definitif_ne_produit_plus_un_500_brut(client, stripe):
    always_reject(stripe)

    response = start(client)

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "checkout_rejected"


def test_la_reponse_ne_dit_rien_de_stripe(client, stripe):
    """Ni message brut, ni identifiant de requête, ni trace d'exécution."""

    def refuse(**_: object):
        raise CheckoutSessionRejected("Request req_XYZ: Tax ID collection requires…")

    stripe.create_checkout_session = refuse

    body = start(client).text

    for leaked in ("req_", "Tax ID", "Traceback", "stripe", "customer_update"):
        assert leaked not in body


def test_apres_un_refus_le_compte_peut_repartir_immediatement(client, engine, stripe):
    """Le cœur du défaut : trente minutes de blocage pour rien.

    Ni attente, ni intervention manuelle en base — un autre plan, tout de suite.
    """
    always_reject(stripe)
    assert start(client, "pro", "chf").status_code == 502

    stripe.create_checkout_session = FakeStripe.create_checkout_session.__get__(stripe)
    retry = start(client, "essential", "eur")

    assert retry.status_code == 200
    stored = attempt_of(engine, account_of(client))
    assert (stored.status, stored.plan_code, stored.currency) == ("open", "essential", "eur")
    assert len(rows(engine)) == 1


def test_un_refus_ne_libere_pas_la_place_pour_deux_tentatives(client, engine, stripe):
    """La libération remplace la tentative, elle n'en ajoute pas une seconde."""
    always_reject(stripe)

    start(client)
    start(client)

    assert len(rows(engine)) == 1


# ─── 2. échec ambigu — la place reste tenue ──────────────────────────────────


def test_une_reponse_perdue_garde_la_tentative_creating(client, engine, stripe):
    always_uncertain(stripe)

    start(client)

    stored = attempt_of(engine, account_of(client))
    assert stored.status == "creating"
    assert stored.stripe_checkout_session_id is None


def test_une_reponse_perdue_repond_service_indisponible(client, stripe):
    always_uncertain(stripe)

    response = start(client)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "checkout_unavailable"


def test_apres_un_echec_ambigu_un_autre_plan_reste_refuse(client, stripe):
    """La protection anti-double-paiement est exactement ce qu'on préserve ici."""
    always_uncertain(stripe)
    start(client)

    other = start(client, "essential", "eur")

    assert other.status_code == 409
    assert other.json()["detail"]["code"] == "checkout_in_progress"


def test_le_rejeu_du_meme_plan_reutilise_tentative_et_cle_d_idempotence(client, engine, stripe):
    """§3, §4 — une nouvelle clé produirait une SECONDE session de paiement."""
    always_uncertain(stripe)
    start(client)
    first = attempt_of(engine, account_of(client))

    real = FakeStripe.create_checkout_session.__get__(stripe)
    seen: list[str] = []

    def record(**kwargs: object):
        seen.append(kwargs["idempotency_key"])
        return real(**kwargs)

    stripe.create_checkout_session = record
    assert start(client, "pro", "chf").status_code == 200

    second = attempt_of(engine, account_of(client))
    assert second.attempt_id == first.attempt_id
    assert seen == [first.idempotency_key]
    assert first.idempotency_key == f"kivou-checkout:{first.attempt_id}"


# ─── 3. la concurrence initiale reste protégée ───────────────────────────────


def test_deux_requetes_simultanees_ne_produisent_qu_une_tentative(client, engine, stripe):
    first, second = start(client), start(client)

    assert {first.status_code, second.status_code} == {200, 409}
    assert len(rows(engine)) == 1
    assert len(stripe.checkout_calls) == 1


# ─── 4. une erreur tardive ne peut pas fermer une tentative plus récente ─────


def test_un_ancien_attempt_id_ne_ferme_pas_la_tentative_qui_l_a_remplace(client, engine, stripe):
    """L'erreur d'un appel lent pourrait arriver après qu'une autre tentative a pris la place."""
    always_reject(stripe)
    start(client)
    account_id = account_of(client)
    ancien = attempt_of(engine, account_id)

    stripe.create_checkout_session = FakeStripe.create_checkout_session.__get__(stripe)
    assert start(client, "essential", "eur").status_code == 200
    recente = attempt_of(engine, account_id)
    assert recente.attempt_id != ancien.attempt_id

    with engine.begin() as connection:
        closed = attempts.fail_attempt(
            connection, account_id=account_id, attempt_id=ancien.attempt_id, now=NOW
        )

    assert closed is False
    assert attempt_of(engine, account_id).status == "open"


def test_une_tentative_deja_ouverte_ne_peut_pas_devenir_failed(client, engine, stripe):
    """Session créée puis erreur tardive : la session existe, on ne libère rien."""
    assert start(client).status_code == 200
    account_id = account_of(client)
    ouverte = attempt_of(engine, account_id)

    with engine.begin() as connection:
        closed = attempts.fail_attempt(
            connection, account_id=account_id, attempt_id=ouverte.attempt_id, now=NOW
        )

    assert closed is False
    assert attempt_of(engine, account_id).status == "open"


def test_fail_attempt_ne_touche_pas_le_compte_d_un_autre(client, engine, stripe):
    always_uncertain(stripe)
    start(client)
    account_id = account_of(client)
    stored = attempt_of(engine, account_id)

    with engine.begin() as connection:
        closed = attempts.fail_attempt(
            connection, account_id="acc_quelqu_un_d_autre", attempt_id=stored.attempt_id, now=NOW
        )

    assert closed is False
    assert attempt_of(engine, account_id).status == "creating"
