"""SPEC-013 closeout §1 à §10 — deux paiements ne peuvent pas naître d'un compte.

Le défaut fermé ici
───────────────────
Deux requêtes de paiement quasi simultanées passaient toutes deux le
contrôle « ce compte a-t-il un abonnement ? » — puisqu'aucun n'existe
encore — et ouvraient deux sessions Stripe. Le client qui terminait les deux
se retrouvait avec deux abonnements, donc deux factures. La contrainte
d'unicité sur `billing_subscription` rattrapait la seconde, mais **après le
débit**.

La correction inverse l'ordre : on réserve en base, on valide, ET SEULEMENT
ENSUITE on appelle Stripe. La clé primaire `account_id` de
`billing_checkout_attempt` est l'arbitre — elle tient entre processus, ce
qu'un verrou en mémoire ne ferait pas.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import (
    TEST_WEBHOOK_SECRET,
    FakeStripe,
    event_payload,
    stripe_signature,
    subscribe,
)
from fastapi.testclient import TestClient
from feed_helpers import ORIGIN, PASSWORD

from signals.api import ApiConfig, create_app
from signals.billing import attempts, checkout
from signals.billing.schema import (
    CHECKOUT_ATTEMPT_TTL_MINUTES,
    billing_checkout_attempt,
    billing_subscription,
)
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)

#: §10 F — les statuts d'abonnement qui interdisent toute nouvelle tentative.
SUBSCRIPTION_PRESENT = ("active", "incomplete", "trialing", "past_due", "unpaid", "paused")


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
def app(engine, stripe: FakeStripe, clock: Clock):
    return create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            allowed_origin=ORIGIN,
            session_ttl=dt.timedelta(days=365),
            stripe_mode="test",
            stripe_webhook_secret=TEST_WEBHOOK_SECRET,
        ),
        now_override=clock,
        stripe_gateway=stripe,
    )


@pytest.fixture
def client(app) -> TestClient:
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


def account_of(client: TestClient) -> str:
    return client.get("/me").json()["account_id"]


def start(client: TestClient, plan: str = "pro", currency: str = "chf"):
    return client.post("/billing/checkout", json={"plan": plan, "currency": currency})


def attempt_rows(engine):
    with engine.connect() as connection:
        return connection.execute(sa.select(billing_checkout_attempt)).all()


def attempt_of(engine, account_id: str):
    with engine.connect() as connection:
        return attempts.current_attempt(connection, account_id=account_id)


# ─── §1, §2 — la réservation existe et précède Stripe ─────────────────────────


def test_a_checkout_reserves_exactly_one_attempt(client, engine, stripe):
    assert start(client).status_code == 200

    rows = attempt_rows(engine)
    assert len(rows) == 1
    assert rows[0].status == "open"
    assert rows[0].plan_code == "pro"
    assert rows[0].currency == "chf"
    assert rows[0].stripe_checkout_session_id is not None
    assert len(stripe.checkout_calls) == 1


def test_the_attempt_is_reserved_before_stripe_is_called(client, engine, stripe):
    """§2 — l'ordre est la garantie. Une passerelle qui échoue laisse la trace.

    La passerelle lève au moment de créer la session : si la réservation avait
    lieu APRÈS, il n'y aurait aucune ligne. Elle a lieu avant, donc la
    tentative existe — et c'est elle qui empêchera une seconde session.
    """

    def refuse(**_: object):
        raise RuntimeError("Stripe indisponible")

    stripe.create_checkout_session = refuse
    with pytest.raises(RuntimeError):
        start(client)

    rows = attempt_rows(engine)
    assert len(rows) == 1
    assert rows[0].status == "creating"
    assert rows[0].stripe_checkout_session_id is None


def test_the_local_and_stripe_lifetimes_describe_the_same_window(client, engine, stripe):
    """§5 — une tentative locale ne doit pas survivre à la session Stripe."""
    start(client)
    call = stripe.checkout_calls[0]
    stored = attempt_of(engine, account_of(client))

    assert stored.expires_at == NOW + dt.timedelta(minutes=CHECKOUT_ATTEMPT_TTL_MINUTES)
    assert call["expires_at"] == stored.expires_at
    assert CHECKOUT_ATTEMPT_TTL_MINUTES == 30


# ─── §10 A, §9 — concurrence ──────────────────────────────────────────────────


def test_two_near_simultaneous_requests_produce_one_attempt_and_one_session(client, engine, stripe):
    """§10 A — la base arbitre, pas un verrou en mémoire."""
    first, second = start(client), start(client)

    assert {first.status_code, second.status_code} == {200, 409}
    assert len(attempt_rows(engine)) == 1
    assert len(stripe.checkout_calls) == 1


def test_the_loser_of_the_race_never_reaches_stripe(client, engine, stripe):
    start(client)
    stripe.checkout_calls.clear()

    response = start(client)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "checkout_in_progress"
    assert stripe.checkout_calls == [], "aucun appel Stripe pour le perdant"


def test_the_conflict_says_when_the_place_frees_up(client):
    start(client)
    detail = start(client).json()["detail"]
    assert (
        detail["expires_at"]
        == (NOW + dt.timedelta(minutes=CHECKOUT_ATTEMPT_TTL_MINUTES)).isoformat()
    )


def test_two_accounts_each_reserve_their_own_attempt(app, engine, stripe):
    alice = TestClient(app, headers={"Origin": ORIGIN})
    alice.post(
        "/auth/signup",
        json={
            "email": "alice@negoce-romand.ch",
            "password": PASSWORD,
            "company_name": "A",
            "locale": "fr",
        },
    )
    bob = TestClient(app, headers={"Origin": ORIGIN})
    bob.post(
        "/auth/signup",
        json={
            "email": "bob@materiaux-leman.ch",
            "password": PASSWORD,
            "company_name": "B",
            "locale": "fr",
        },
    )
    assert start(alice).status_code == 200
    assert start(bob).status_code == 200
    assert len(attempt_rows(engine)) == 2
    assert len(stripe.checkout_calls) == 2


# ─── §10 H — la base refuse la seconde tentative ──────────────────────────────


def test_the_database_refuses_two_current_attempts_for_one_account(client, engine):
    """§10 H — ce n'est pas une règle applicative qu'on peut oublier d'appeler."""
    start(client)
    account_id = account_of(client)

    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(
            sa.insert(billing_checkout_attempt).values(
                account_id=account_id,
                attempt_id="cka_forced",
                plan_code="scale",
                currency="eur",
                status="creating",
                expires_at=NOW + dt.timedelta(minutes=30),
                created_at=NOW,
                updated_at=NOW,
            )
        )
    assert len(attempt_rows(engine)) == 1


def test_the_account_column_is_the_primary_key_of_the_attempt_table():
    assert [column.name for column in billing_checkout_attempt.primary_key] == ["account_id"]


# ─── §3, §4, §10 B — la clé d'idempotence appartient à la tentative ──────────


def test_the_idempotency_key_is_derived_from_the_persisted_attempt(client, engine, stripe):
    start(client)
    stored = attempt_of(engine, account_of(client))
    assert stripe.checkout_calls[0]["idempotency_key"] == f"kivou-checkout:{stored.attempt_id}"


def test_a_crash_between_stripe_and_the_database_creates_no_second_session(client, engine, stripe):
    """§10 B — Stripe a créé la session, le processus est mort avant de l'écrire."""
    account_id = account_of(client)
    real_create = stripe.create_checkout_session
    created: list = []

    def create_then_crash(**kwargs: object):
        session = real_create(**kwargs)
        created.append(session)
        raise RuntimeError("le processus meurt avant d'enregistrer la session")

    stripe.create_checkout_session = create_then_crash
    with pytest.raises(RuntimeError):
        start(client)

    interrupted = attempt_of(engine, account_id)
    assert interrupted.status == "creating"
    assert interrupted.stripe_checkout_session_id is None

    # La reprise : même tentative, donc même clé, donc même session Stripe.
    stripe.create_checkout_session = real_create
    assert start(client).status_code == 200

    resumed = attempt_of(engine, account_id)
    assert resumed.attempt_id == interrupted.attempt_id, "la tentative est REJOUÉE"
    assert resumed.stripe_checkout_session_id == created[0].session_id
    assert len({call["idempotency_key"] for call in stripe.checkout_calls}) == 1
    assert len(attempt_rows(engine)) == 1


def test_a_resumed_attempt_never_gets_a_fresh_key(client, engine, stripe):
    """Une nouvelle clé produirait une seconde session : c'est tout le danger."""
    account_id = account_of(client)
    with engine.begin() as connection:
        first = attempts.reserve(
            connection, account_id=account_id, plan_code="pro", currency="chf", now=NOW
        )
        second = attempts.reserve(
            connection, account_id=account_id, plan_code="pro", currency="chf", now=NOW
        )
    assert first.attempt_id == second.attempt_id
    assert first.idempotency_key == second.idempotency_key


# ─── §8, §10 C — changer de plan pendant un paiement ouvert ──────────────────


def test_requesting_another_plan_while_a_checkout_is_open_is_refused(client, engine, stripe):
    """§10 C — et la session existante n'est surtout pas annulée."""
    assert start(client, plan="essential").status_code == 200
    stripe.checkout_calls.clear()

    response = start(client, plan="pro")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "checkout_in_progress"
    assert stripe.checkout_calls == []

    stored = attempt_of(engine, account_of(client))
    assert stored.plan_code == "essential", "la tentative en cours est intacte"
    assert stored.status == "open"


def test_a_different_plan_never_resumes_an_interrupted_attempt(client, engine, stripe):
    """Rejouer une clé d'idempotence avec d'autres paramètres serait une erreur Stripe."""

    def crash(**_: object):
        raise RuntimeError("mort avant enregistrement")

    stripe.create_checkout_session = crash
    with pytest.raises(RuntimeError):
        start(client, plan="essential")

    response = start(client, plan="scale")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "checkout_in_progress"


# ─── §5, §10 D — expiration ───────────────────────────────────────────────────


def test_an_expired_attempt_stops_blocking_the_account(client, engine, stripe, clock: Clock):
    """§5 — une tentative abandonnée ne bloque pas un compte indéfiniment."""
    assert start(client).status_code == 200
    assert start(client).status_code == 409

    clock.advance(dt.timedelta(minutes=CHECKOUT_ATTEMPT_TTL_MINUTES + 1))
    assert start(client, plan="scale").status_code == 200

    stored = attempt_of(engine, account_of(client))
    assert stored.plan_code == "scale"
    assert stored.status == "open"
    assert len(attempt_rows(engine)) == 1, "la table ne garde pas d'historique"
    assert len(stripe.checkout_calls) == 2


def test_the_expired_event_closes_the_attempt_without_granting_anything(
    app, client, engine, stripe
):
    """§10 D — `checkout.session.expired` ferme la tentative, et rien d'autre."""
    start(client)
    account_id = account_of(client)
    session_id = attempt_of(engine, account_id).stripe_checkout_session_id

    payload = event_payload(
        event_id="evt_expired",
        event_type="checkout.session.expired",
        created=NOW,
        data_object={"id": session_id, "customer": "cus_test_0001"},
    )
    signature = stripe_signature(
        payload, secret=TEST_WEBHOOK_SECRET, timestamp=int(NOW.timestamp())
    )
    response = TestClient(app).post(
        "/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json()["result"] == "ignored"
    assert attempt_of(engine, account_id).status == "expired"
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(billing_subscription)
            ).scalar()
            == 0
        )
    assert client.get("/billing/status").json()["plan_code"] == "discovery"


def test_a_checkout_may_restart_after_the_expired_event(app, client, engine, stripe):
    start(client)
    session_id = attempt_of(engine, account_of(client)).stripe_checkout_session_id
    payload = event_payload(
        event_id="evt_expired_2",
        event_type="checkout.session.expired",
        created=NOW,
        data_object={"id": session_id},
    )
    TestClient(app).post(
        "/webhooks/stripe",
        content=payload,
        headers={
            "Stripe-Signature": stripe_signature(
                payload, secret=TEST_WEBHOOK_SECRET, timestamp=int(NOW.timestamp())
            ),
            "Content-Type": "application/json",
        },
    )
    assert start(client, plan="scale").status_code == 200


# ─── §7, §10 E — complétion ───────────────────────────────────────────────────


def test_the_completed_event_closes_the_attempt_but_grants_nothing_by_itself(
    app, client, engine, stripe
):
    """§10 E — terminer un paiement n'est pas être abonné."""
    start(client)
    account_id = account_of(client)
    session_id = attempt_of(engine, account_id).stripe_checkout_session_id

    payload = event_payload(
        event_id="evt_completed",
        event_type="checkout.session.completed",
        created=NOW,
        data_object={"id": session_id, "client_reference_id": account_id},
    )
    response = TestClient(app).post(
        "/webhooks/stripe",
        content=payload,
        headers={
            "Stripe-Signature": stripe_signature(
                payload, secret=TEST_WEBHOOK_SECRET, timestamp=int(NOW.timestamp())
            ),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    assert attempt_of(engine, account_id).status == "completed"
    # Aucun abonnement rattaché à la session : rien n'est accordé.
    assert client.get("/billing/status").json()["plan_code"] == "discovery"
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(billing_subscription)
            ).scalar()
            == 0
        )


def test_visiting_the_success_url_still_grants_nothing(client, engine):
    """La redirection reste de la présentation, closeout ou pas."""
    start(client)
    client.get("/billing/success?session_id=cs_test_0001")
    assert client.get("/billing/status").json()["plan_code"] == "discovery"
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(billing_subscription)
            ).scalar()
            == 0
        )


# ─── §10 F, §10 G — un abonnement existant interdit toute tentative ──────────


@pytest.mark.parametrize("status", SUBSCRIPTION_PRESENT)
def test_an_existing_subscription_prevents_any_attempt(client, engine, stripe, status: str):
    """§10 F — ni tentative, ni appel Stripe."""
    with engine.begin() as connection:
        subscribe(connection, account_id=account_of(client), plan="pro", status=status, now=NOW)

    response = start(client, plan="scale")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_subscribed"
    assert attempt_rows(engine) == []
    assert stripe.checkout_calls == []


def test_an_unknown_subscription_status_prevents_any_attempt(client, engine, stripe):
    """§10 G — défaut fermé, jusque dans la réservation."""
    with engine.begin() as connection:
        subscribe(connection, account_id=account_of(client), plan="pro", status="inconnu", now=NOW)

    assert start(client).status_code == 409
    assert attempt_rows(engine) == []
    assert stripe.checkout_calls == []


@pytest.mark.parametrize("status", ["canceled", "incomplete_expired"])
def test_a_terminal_subscription_allows_a_fresh_attempt(client, engine, stripe, status: str):
    with engine.begin() as connection:
        subscribe(connection, account_id=account_of(client), plan="pro", status=status, now=NOW)

    assert start(client).status_code == 200
    assert len(attempt_rows(engine)) == 1
    assert len(stripe.checkout_calls) == 1


# ─── l'ordre des opérations, vérifié sur le code ──────────────────────────────


def test_the_stripe_call_lives_outside_the_reservation_transaction():
    """§2 — appeler Stripe dans la transaction de réservation la garderait
    ouverte pendant un appel réseau, et un échec annulerait la réservation qui
    protège justement contre la seconde session."""
    import inspect

    source = inspect.getsource(checkout.prepare_checkout)
    assert "create_checkout_session" not in source
    assert "attempts.reserve" in source
    assert "create_checkout_session" in inspect.getsource(checkout.open_checkout_session)
