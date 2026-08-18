"""SPEC-013 R1 §2 à §5 — un compte, un abonnement, et aucun gagnant choisi au tri.

ACCÈS KIVOU ≠ EXISTENCE D'UN ABONNEMENT
───────────────────────────────────────
Un abonnement impayé n'ouvre aucun droit. Il existe pourtant, il est
facturé, et Stripe continue de le relancer. En autoriser un second
facturerait deux fois un client qui n'a rien demandé de tel — et c'est une
erreur qui coûte de l'argent réel, pas seulement de la cohérence.

Le tri n'est pas une solution
────────────────────────────
Départager deux abonnements par plan, par prix ou par date reviendrait à
décider seul lequel le client paie, alors que dans les deux cas il paie
déjà. Kivou refuse, conserve l'existant, et laisse un humain trancher.
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
    subscription_state,
)
from fastapi.testclient import TestClient
from feed_helpers import ORIGIN, PASSWORD

from signals.api import ApiConfig, create_app
from signals.billing import service
from signals.billing.schema import (
    TERMINAL_STATUSES,
    billing_customer,
    billing_subscription,
    is_open_subscription,
)
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)
CUSTOMER_ID = "cus_test_0001"

#: R1 §3 — les statuts qui disent « un abonnement existe », donc « pas de second ».
CHECKOUT_BLOCKING = (
    "incomplete",
    "trialing",
    "active",
    "past_due",
    "unpaid",
    "paused",
)


class Clock:
    def __call__(self) -> dt.datetime:
        return NOW


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def stripe() -> FakeStripe:
    return FakeStripe()


@pytest.fixture
def app(engine, stripe: FakeStripe):
    return create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            allowed_origin=ORIGIN,
            session_ttl=dt.timedelta(days=365),
            stripe_mode="test",
            stripe_webhook_secret=TEST_WEBHOOK_SECRET,
        ),
        now_override=Clock(),
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


def pay(engine, client: TestClient, **overrides) -> None:
    with engine.begin() as connection:
        subscribe(connection, account_id=account_of(client), now=NOW, **overrides)


def rows(engine):
    with engine.connect() as connection:
        return connection.execute(sa.select(billing_subscription)).all()


def checkout(client: TestClient, plan: str = "pro", currency: str = "chf"):
    return client.post("/billing/checkout", json={"plan": plan, "currency": currency})


# ─── §3 — la frontière entre accès et existence ───────────────────────────────


@pytest.mark.parametrize("status", CHECKOUT_BLOCKING)
def test_every_open_status_blocks_a_second_checkout(client, engine, stripe, status: str):
    """§6 A/B/C — `past_due`, `unpaid`, `paused` donnent Discovery ET bloquent."""
    pay(engine, client, plan="pro", status=status)
    assert client.get("/billing/status").json()["subscription_status"] == status

    response = checkout(client)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_subscribed"
    assert stripe.checkout_calls == [], "aucune session Stripe n'a été ouverte"
    assert len(rows(engine)) == 1


@pytest.mark.parametrize("status", ["past_due", "unpaid", "paused", "incomplete"])
def test_an_open_but_unpaid_subscription_still_gives_only_discovery(client, engine, status: str):
    """L'accès et l'existence sont deux questions différentes."""
    pay(engine, client, plan="scale", status=status)
    body = client.get("/billing/status").json()
    assert body["plan_code"] == "discovery", "aucun droit payant"
    assert body["subscription_status"] == status, "mais l'abonnement existe"


@pytest.mark.parametrize("status", TERMINAL_STATUSES)
def test_a_terminal_status_frees_the_place(client, engine, stripe, status: str):
    """§6 D — `canceled` et `incomplete_expired` autorisent un nouvel achat."""
    pay(engine, client, plan="pro", status=status)
    assert checkout(client).status_code == 200
    assert len(stripe.checkout_calls) == 1


def test_an_unknown_stripe_status_fails_closed(client, engine, stripe):
    """§6 H — un statut que Stripe inventerait demain bloque, il n'ouvre pas."""
    pay(engine, client, plan="pro", status="quantum_superposition")

    assert client.get("/billing/status").json()["plan_code"] == "discovery"
    assert checkout(client).status_code == 409
    assert stripe.checkout_calls == []


def test_the_open_test_is_written_against_terminal_states_not_open_ones():
    """La forme du code EST la garantie de défaut fermé.

    Tester l'appartenance aux états ouverts laisserait un statut inconnu passer
    à travers ; tester l'appartenance aux états TERMINAUX le bloque par
    construction.
    """
    assert is_open_subscription("un_statut_qui_n_existe_pas_encore") is True
    for terminal in TERMINAL_STATUSES:
        assert is_open_subscription(terminal) is False


# ─── §2, §6 F — la contrainte est structurelle ────────────────────────────────


def test_the_database_refuses_two_current_subscriptions_for_one_account(client, engine):
    """§6 F — ce n'est pas une règle applicative qu'on peut oublier d'appeler."""
    pay(engine, client, plan="pro", status="active")
    account_id = account_of(client)

    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(
            sa.insert(billing_subscription).values(
                billing_subscription_id="bsub_forced",
                account_id=account_id,
                stripe_subscription_id="sub_second",
                stripe_customer_id=CUSTOMER_ID,
                status="active",
                cancel_at_period_end=False,
                livemode=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    assert len(rows(engine)) == 1


def test_the_account_column_carries_a_uniqueness_constraint():
    assert billing_subscription.c.account_id.unique is True


def test_reading_the_current_subscription_needs_no_tie_break(client, engine):
    """R1 §2 — il n'y a rien à départager : la base n'en garde qu'un."""
    pay(engine, client, plan="pro")
    account_id = account_of(client)
    with engine.connect() as connection:
        first = service.current_subscription(connection, account_id=account_id)
        second = service.current_subscription(connection, account_id=account_id)
    assert first == second
    assert len(rows(engine)) == 1


# ─── §5 — le conflit est explicite ────────────────────────────────────────────


def test_a_second_open_subscription_raises_an_explicit_conflict(client, engine):
    """§6 E — aucun gagnant, aucun écrasement, aucune résiliation automatique."""
    pay(engine, client, plan="pro", status="active", subscription_id="sub_first")
    account_id = account_of(client)

    with pytest.raises(service.BillingSubscriptionConflict) as raised, engine.begin() as connection:
        service.synchronize_subscription(
            connection,
            subscription_state(subscription_id="sub_second", plan="scale", status="active"),
            account_id=account_id,
            event_created_at=NOW,
            expect_livemode=False,
            now=NOW,
        )

    assert raised.value.current_subscription_id == "sub_first"
    assert raised.value.incoming_subscription_id == "sub_second"
    assert raised.value.code == "billing_subscription_conflict"

    stored = rows(engine)
    assert len(stored) == 1
    assert stored[0].stripe_subscription_id == "sub_first"
    assert stored[0].plan_code == "pro", "le plan le plus cher ne l'emporte pas"


def test_a_conflict_never_grants_the_more_expensive_plan(client, engine):
    pay(engine, client, plan="essential", status="active", subscription_id="sub_first")
    account_id = account_of(client)

    with pytest.raises(service.BillingSubscriptionConflict), engine.begin() as connection:
        service.synchronize_subscription(
            connection,
            subscription_state(subscription_id="sub_second", plan="scale"),
            account_id=account_id,
            event_created_at=NOW,
            expect_livemode=False,
            now=NOW,
        )
    assert client.get("/billing/status").json()["plan_code"] == "essential"


@pytest.mark.parametrize("status", TERMINAL_STATUSES)
def test_a_terminal_subscription_is_replaced_by_its_successor(client, engine, status: str):
    """§6 D — S1 terminé, S2 légitime : la ligne courante devient S2."""
    pay(engine, client, plan="pro", status=status, subscription_id="sub_first")
    account_id = account_of(client)

    with engine.begin() as connection:
        service.synchronize_subscription(
            connection,
            subscription_state(subscription_id="sub_second", plan="scale", status="active"),
            account_id=account_id,
            event_created_at=NOW,
            expect_livemode=False,
            now=NOW,
        )

    stored = rows(engine)
    assert len(stored) == 1
    assert stored[0].stripe_subscription_id == "sub_second"
    assert client.get("/billing/status").json()["plan_code"] == "scale"


def test_the_webhook_records_a_conflict_without_touching_the_current_state(
    app, client, engine, stripe
):
    pay(engine, client, plan="pro", status="active", subscription_id="sub_first")
    account_id = account_of(client)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(billing_customer).values(
                account_id=account_id,
                stripe_customer_id=CUSTOMER_ID,
                livemode=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    stripe.put_subscription(
        subscription_state(
            subscription_id="sub_second",
            customer_id=CUSTOMER_ID,
            account_id=account_id,
            plan="scale",
        )
    )

    payload = event_payload(
        event_id="evt_conflict",
        event_type="customer.subscription.created",
        created=NOW,
        data_object={
            "id": "sub_second",
            "customer": CUSTOMER_ID,
            "status": "active",
            "metadata": {"kivou_account_id": account_id},
        },
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
    assert response.json()["result"] == "conflict"
    stored = rows(engine)
    assert len(stored) == 1
    assert stored[0].stripe_subscription_id == "sub_first"
    assert stored[0].plan_code == "pro"


def test_no_stripe_subscription_is_ever_cancelled_automatically():
    """§5 — annuler la mauvaise facturation serait pire que de ne rien faire."""
    import inspect

    from signals.billing import checkout as checkout_module
    from signals.billing import service as service_module
    from signals.billing import webhooks as webhooks_module

    for module in (service_module, webhooks_module, checkout_module):
        source = inspect.getsource(module)
        for forbidden in ("subscriptions.cancel", "DeleteSubscriptions", ".cancel("):
            assert forbidden not in source, f"{module.__name__} : {forbidden}"


# ─── §4 — reprises et concurrence ─────────────────────────────────────────────


def test_two_identical_checkout_calls_are_one_logical_operation(client, stripe):
    """§6 G — deux clics identiques n'ouvrent qu'UNE session de paiement.

    Le closeout final durcit la réponse : la seconde requête ne rappelle plus
    Stripe du tout, elle se heurte à la tentative déjà réservée. Une seule
    session existe, ce qui reste la propriété qui compte.
    """
    first, second = checkout(client), checkout(client)
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "checkout_in_progress"
    assert len(stripe.checkout_calls) == 1, "un seul appel Stripe"


def test_a_second_checkout_after_synchronization_is_blocked(client, engine, stripe):
    """Le chemin réel : la session s'ouvre, le webhook synchronise, puis c'est fermé."""
    assert checkout(client).status_code == 200
    pay(engine, client, plan="pro", status="active")

    assert checkout(client, plan="scale").status_code == 409
    assert len({call["price_id"] for call in stripe.checkout_calls}) == 1


def test_the_customer_is_created_once_even_across_repeated_attempts(client, engine, stripe):
    for plan in ("pro", "scale", "essential"):
        checkout(client, plan=plan)
    with engine.connect() as connection:
        customers = connection.execute(sa.select(billing_customer)).all()
    assert len(customers) == 1
    assert len(stripe.customers) == 1


def test_two_concurrent_completions_cannot_both_persist(client, engine, stripe):
    """La course perdue reste visible : elle lève, elle ne s'écrase pas.

    Kivou ne peut pas empêcher un client déterminé de terminer deux sessions
    ouvertes dans le même instant — Stripe créerait alors deux abonnements. Ce
    qu'il garantit, c'est qu'aucun chemin SILENCIEUX n'existe : la seconde
    synchronisation lève un conflit explicite, à trancher par un humain.
    """
    account_id = account_of(client)
    with engine.begin() as connection:
        service.synchronize_subscription(
            connection,
            subscription_state(subscription_id="sub_race_a", plan="pro"),
            account_id=account_id,
            event_created_at=NOW,
            expect_livemode=False,
            now=NOW,
        )
    with pytest.raises(service.BillingSubscriptionConflict), engine.begin() as connection:
        service.synchronize_subscription(
            connection,
            subscription_state(subscription_id="sub_race_b", plan="pro"),
            account_id=account_id,
            event_created_at=NOW,
            expect_livemode=False,
            now=NOW,
        )
    assert len(rows(engine)) == 1
