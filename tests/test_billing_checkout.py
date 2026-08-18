"""SPEC-013 §11 à §14, §19, §32, §33 — ouvrir un paiement sans laisser le client choisir.

Le montant n'est pas négociable côté navigateur (§32)
────────────────────────────────────────────────────
Accepter un `price_id` du client reviendrait à laisser l'acheteur fixer son
prix : il suffirait d'envoyer l'identifiant d'un prix à un franc pour obtenir
Scale. Le client choisit un plan et une devise ; le serveur résout le prix.

La redirection de succès n'est pas une autorisation (§14)
────────────────────────────────────────────────────────
Le navigateur qui affiche « paiement réussi » n'a rien prouvé. Seul un état
Stripe vérifié, arrivé par webhook signé, débloque un accès.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import FakeStripe, subscribe
from fastapi.testclient import TestClient
from feed_helpers import ORIGIN, PASSWORD

from signals.api import ApiConfig, create_app
from signals.billing import catalogue
from signals.billing.schema import billing_customer, billing_subscription
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)


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


def build(engine, stripe: FakeStripe, *, founding: frozenset[str] = frozenset(), **overrides):
    config = ApiConfig(
        cookie_secure=False,
        allowed_origin=ORIGIN,
        session_ttl=dt.timedelta(days=365),
        stripe_mode="test",
        stripe_webhook_secret="whsec_test",
        **overrides,
    )
    return create_app(
        engine,
        config,
        now_override=Clock(),
        stripe_gateway=stripe,
        founding_accounts=founding,
    )


def signed_up(app, email: str = "alice@negoce-romand.ch") -> TestClient:
    client = TestClient(app, headers={"Origin": ORIGIN})
    assert (
        client.post(
            "/auth/signup",
            json={
                "email": email,
                "password": PASSWORD,
                "company_name": "Negoce Romand SA",
                "locale": "fr",
            },
        ).status_code
        == 201
    )
    return client


@pytest.fixture
def client(engine, stripe: FakeStripe) -> TestClient:
    return signed_up(build(engine, stripe))


# ─── §11 — le catalogue public ────────────────────────────────────────────────


def test_the_plan_catalogue_is_public_and_carries_no_stripe_identifier(client: TestClient):
    body = client.get("/billing/plans").json()
    assert [plan["plan_code"] for plan in body["plans"]] == [
        "discovery",
        "essential",
        "pro",
        "scale",
    ]
    assert body["billing_interval"] == "month"
    for forbidden in ("price_", "prod_", "coupon_", "whsec", "sk_test"):
        assert forbidden not in str(body), forbidden


def test_the_catalogue_marks_pro_as_recommended(client: TestClient):
    plans = {plan["plan_code"]: plan for plan in client.get("/billing/plans").json()["plans"]}
    assert plans["pro"]["recommended"] is True
    assert plans["essential"]["recommended"] is False


# ─── §32 — le prix n'est jamais choisi par le client ──────────────────────────


def test_a_price_id_in_the_request_body_is_refused_outright(client: TestClient):
    response = client.post(
        "/billing/checkout",
        json={"plan": "essential", "currency": "chf", "price_id": "price_attacker_controlled"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"plan": "discovery", "currency": "chf"},
        {"plan": "enterprise", "currency": "chf"},
        {"plan": "pro", "currency": "usd"},
        {"plan": "pro"},
        {"currency": "chf"},
    ],
)
def test_only_a_purchasable_plan_and_a_billable_currency_are_accepted(client, payload: dict):
    assert client.post("/billing/checkout", json=payload).status_code == 422


@pytest.mark.parametrize("plan", ["essential", "pro", "scale"])
@pytest.mark.parametrize("currency", ["chf", "eur"])
def test_the_server_resolves_the_price_from_its_own_lookup_key(
    client: TestClient, stripe: FakeStripe, plan: str, currency: str
):
    response = client.post("/billing/checkout", json={"plan": plan, "currency": currency})
    assert response.status_code == 200, response.text
    assert response.json()["checkout_url"].startswith("https://checkout.stripe.test/")

    call = stripe.checkout_calls[-1]
    expected = stripe.prices[catalogue.lookup_key_for(plan, currency)]
    assert call["price_id"] == expected.price_id


def test_a_checkout_is_a_state_changing_request_and_is_csrf_protected(client: TestClient):
    response = client.post(
        "/billing/checkout",
        json={"plan": "pro", "currency": "chf"},
        headers={"Origin": "https://attaquant.example"},
    )
    assert response.status_code == 403


def test_an_unauthenticated_caller_cannot_open_a_checkout(engine, stripe: FakeStripe):
    anonymous = TestClient(build(engine, stripe), headers={"Origin": ORIGIN})
    assert (
        anonymous.post("/billing/checkout", json={"plan": "pro", "currency": "chf"}).status_code
        == 401
    )


# ─── §12, §13 — un client Stripe par compte, créé une fois ────────────────────


def test_one_stripe_customer_is_created_per_account_and_only_once(
    client: TestClient, stripe: FakeStripe, engine
):
    client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    client.post("/billing/checkout", json={"plan": "scale", "currency": "eur"})

    with engine.connect() as connection:
        rows = connection.execute(sa.select(billing_customer)).all()
    assert len(rows) == 1
    assert len(stripe.customers) == 1
    assert rows[0].livemode is False


def test_the_stripe_customer_carries_the_account_for_reconciliation(
    client: TestClient, stripe: FakeStripe
):
    client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    account_id = client.get("/me").json()["account_id"]
    assert stripe.customer_calls[0]["account_id"] == account_id
    assert stripe.customer_calls[0]["idempotency_key"] == f"kivou-customer-{account_id}"


def test_two_accounts_get_two_distinct_stripe_customers(engine, stripe: FakeStripe):
    app = build(engine, stripe)
    alice = signed_up(app, "alice@negoce-romand.ch")
    bob = signed_up(app, "bob@materiaux-leman.ch")
    alice.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    bob.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})

    with engine.connect() as connection:
        customers = connection.execute(sa.select(billing_customer.c.stripe_customer_id)).scalars()
    assert len(set(customers)) == 2


def test_the_checkout_session_carries_the_account_on_both_reconciliation_paths(
    client: TestClient, stripe: FakeStripe
):
    """§13 — la session ET l'abonnement qui en naîtra portent le compte."""
    client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    account_id = client.get("/me").json()["account_id"]
    call = stripe.checkout_calls[-1]
    assert call["account_id"] == account_id
    assert call["success_url"].startswith("https://")
    assert call["cancel_url"].startswith("https://")


def test_the_return_urls_never_come_from_the_client(client: TestClient, stripe: FakeStripe):
    """Une URL de succès fournie par le client serait une redirection ouverte."""
    response = client.post(
        "/billing/checkout",
        json={"plan": "pro", "currency": "chf", "success_url": "https://attaquant.example"},
    )
    assert response.status_code == 422
    assert stripe.checkout_calls == []


def test_repeating_the_same_checkout_reuses_the_same_idempotency_key(
    client: TestClient, stripe: FakeStripe
):
    """§13 — deux clics ne doivent pas produire deux paiements."""
    client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    keys = {call["idempotency_key"] for call in stripe.checkout_calls}
    assert len(keys) == 1


def test_automatic_tax_is_off_unless_configuration_says_otherwise(
    client: TestClient, stripe: FakeStripe
):
    """§29 — la fiscalité est une décision, pas un défaut."""
    client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    assert stripe.checkout_calls[-1]["automatic_tax"] is False


def test_automatic_tax_can_be_switched_on_by_configuration(engine, stripe: FakeStripe):
    client = signed_up(build(engine, stripe, stripe_automatic_tax=True))
    client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    assert stripe.checkout_calls[-1]["automatic_tax"] is True


# ─── §11 — pas de second abonnement ───────────────────────────────────────────


def test_an_account_that_already_pays_cannot_open_a_second_checkout(
    client: TestClient, engine, stripe: FakeStripe
):
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(connection, account_id=account_id, plan="pro", now=NOW)

    response = client.post("/billing/checkout", json={"plan": "scale", "currency": "chf"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_subscribed"
    assert stripe.checkout_calls == []


def test_an_account_whose_subscription_lapsed_may_subscribe_again(
    client: TestClient, engine, stripe: FakeStripe
):
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(connection, account_id=account_id, plan="pro", status="canceled", now=NOW)

    assert (
        client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"}).status_code == 200
    )


# ─── §14 — la redirection de succès ne débloque rien ──────────────────────────


def test_visiting_the_success_url_grants_nothing(client: TestClient, engine, stripe: FakeStripe):
    """§14 — le navigateur n'est pas une autorité de paiement."""
    client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})

    # Ce que ferait un navigateur revenant de Stripe : appeler l'application.
    for path in ("/billing/status", "/billing/plans", "/signals"):
        client.get(path)
    # Et même une tentative directe sur l'URL de succès configurée.
    client.get("/billing/success?session_id=cs_test_0002")

    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(billing_subscription)
            ).scalar()
            == 0
        )
    assert client.get("/billing/status").json()["plan_code"] == "discovery"


def test_no_endpoint_can_set_a_plan_from_a_client_request(client: TestClient):
    """Aucune route n'accepte un plan comme état à écrire."""
    for payload in ({"plan_code": "pro"}, {"plan": "pro"}, {"subscription_status": "active"}):
        assert client.post("/billing/status", json=payload).status_code in {404, 405, 422}


# ─── §19 — portail client ─────────────────────────────────────────────────────


def test_the_portal_needs_an_existing_stripe_customer(client: TestClient):
    response = client.post("/billing/portal")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_billing_customer"


def test_the_portal_returns_a_hosted_url_with_a_configured_return_url(
    client: TestClient, stripe: FakeStripe
):
    client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    response = client.post("/billing/portal")
    assert response.status_code == 200
    assert response.json()["portal_url"].startswith("https://billing.stripe.test/")
    assert stripe.portal_calls[-1]["return_url"].startswith("https://")


def test_the_portal_is_csrf_protected(client: TestClient, stripe: FakeStripe):
    client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    response = client.post("/billing/portal", headers={"Origin": "https://attaquant.example"})
    assert response.status_code == 403


def test_one_account_never_opens_the_portal_of_another(engine, stripe: FakeStripe):
    app = build(engine, stripe)
    alice, bob = signed_up(app, "alice@negoce-romand.ch"), signed_up(app, "bob@materiaux-leman.ch")
    alice.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})

    assert bob.post("/billing/portal").status_code == 409
    alice_url = alice.post("/billing/portal").json()["portal_url"]
    assert alice_url.endswith(next(iter(stripe.customers)))


# ─── §33 — l'offre fondateur ne se réclame pas ────────────────────────────────


def test_founding_is_never_applied_to_an_ordinary_account(client: TestClient, stripe: FakeStripe):
    client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    assert stripe.checkout_calls[-1]["coupon_id"] is None


def test_a_query_parameter_can_never_request_the_founding_offer(
    client: TestClient, stripe: FakeStripe
):
    client.post("/billing/checkout?founding=true", json={"plan": "pro", "currency": "chf"})
    assert stripe.checkout_calls[-1]["coupon_id"] is None
    assert (
        client.post(
            "/billing/checkout", json={"plan": "pro", "currency": "chf", "founding": True}
        ).status_code
        == 422
    )


def test_an_eligible_account_receives_the_founding_discount(engine, stripe: FakeStripe):
    app_holder = {}

    def make(eligible: frozenset[str]):
        return build(engine, stripe, founding=eligible, stripe_founding_coupon_id="coupon_test_f")

    client = signed_up(make(frozenset()))
    account_id = client.get("/me").json()["account_id"]
    app_holder["app"] = make(frozenset({account_id}))

    eligible_client = TestClient(app_holder["app"], headers={"Origin": ORIGIN})
    eligible_client.cookies = client.cookies
    eligible_client.post("/billing/checkout", json={"plan": "pro", "currency": "chf"})
    assert stripe.checkout_calls[-1]["coupon_id"] == "coupon_test_f"


def test_the_founding_discount_never_applies_to_another_plan(engine, stripe: FakeStripe):
    app = build(engine, stripe, stripe_founding_coupon_id="coupon_test_f")
    client = signed_up(app)
    account_id = client.get("/me").json()["account_id"]
    app.state.founding_accounts = frozenset({account_id})

    client.post("/billing/checkout", json={"plan": "scale", "currency": "chf"})
    assert stripe.checkout_calls[-1]["coupon_id"] is None
