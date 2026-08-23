"""RTL-04 / #29 — changer de formule sans jamais créer un second abonnement.

La décision produit
───────────────────
Kivou conserve **un Product Stripe par formule** : c'est la modélisation que
Stripe recommande, et restructurer le catalogue imposerait de migrer les
abonnements LIVE. La conséquence est que le Customer Portal ne sait PAS
programmer un downgrade — il ne le fait qu'entre Prices d'un MÊME Product. Le
changement différé passe donc par un `SubscriptionSchedule` côté serveur.

Ce que ces tests garantissent, et ce qu'ils ne peuvent pas garantir
───────────────────────────────────────────────────────────────────
Ils exercent la DÉCISION : sens du changement, conservation de la devise,
résolution du Price côté serveur, refus par défaut fermé, et absence de second
abonnement. Ils ne prouvent PAS que Stripe exécute la transition — cela demande
une Test Clock et un accès TEST en écriture, et c'est la validation qui reste
due avant toute fusion.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import BILLING_RETURN_URLS, FakeStripe, subscribe, subscription_state
from fastapi.testclient import TestClient
from feed_helpers import ORIGIN, PASSWORD

from signals.api import ApiConfig, create_app
from signals.billing.schema import billing_customer, billing_subscription
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 23, 9, 0, tzinfo=dt.UTC)
PERIOD_START = dt.datetime(2026, 8, 1, 9, 0, tzinfo=dt.UTC)
PERIOD_END = dt.datetime(2026, 9, 1, 9, 0, tzinfo=dt.UTC)
CUSTOMER_ID = "cus_test_0001"
SUBSCRIPTION_ID = "sub_test_0001"


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
            stripe_webhook_secret="whsec_test",
            **BILLING_RETURN_URLS,
        ),
        now_override=Clock(),
        stripe_gateway=stripe,
    )


@pytest.fixture
def client(app) -> TestClient:
    client = TestClient(app, headers={"Origin": ORIGIN})
    client.post(
        "/auth/signup",
        json={
            "email": "alice@negoce-romand.ch",
            "password": PASSWORD,
            "company_name": "Negoce Romand SA",
            "locale": "fr",
        },
    )
    return client


def account_of(client: TestClient) -> str:
    return client.get("/me").json()["account_id"]


def paying(
    engine,
    client: TestClient,
    stripe: FakeStripe,
    *,
    plan: str = "pro",
    currency: str = "chf",
    **overrides,
):
    """Un compte réellement abonné, par le VRAI chemin de synchronisation.

    L'abonnement est posé des DEUX côtés : en base, et chez le double Stripe.
    N'écrire qu'en base testerait un état que Stripe ne connaît pas.
    """
    account_id = account_of(client)
    stripe.put_subscription(
        subscription_state(
            subscription_id=SUBSCRIPTION_ID,
            customer_id=CUSTOMER_ID,
            account_id=account_id,
            plan=plan,
            currency=currency or "chf",
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            **{k: v for k, v in overrides.items() if k != "lookup_key"},
        )
    )
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
        subscribe(
            connection,
            account_id=account_id,
            plan=plan,
            currency=currency,
            subscription_id=SUBSCRIPTION_ID,
            customer_id=CUSTOMER_ID,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            now=NOW,
            **overrides,
        )
    return account_id


def change_to(client: TestClient, plan: str):
    return client.post("/billing/plan", json={"plan": plan})


def stored_plan(engine, account_id: str) -> str | None:
    with engine.connect() as connection:
        row = connection.execute(
            sa.select(billing_subscription).where(billing_subscription.c.account_id == account_id)
        ).one()
    return row.plan_code


def subscription_count(engine) -> int:
    with engine.connect() as connection:
        return connection.execute(
            sa.select(sa.func.count()).select_from(billing_subscription)
        ).scalar()


# ─── Le sens du changement décide de l'effet ──────────────────────────────────


def test_an_upgrade_takes_effect_immediately(client, engine, stripe: FakeStripe):
    """Monter de formule ouvre le droit tout de suite — le client l'a payé."""
    account_id = paying(engine, client, stripe, plan="essential")

    response = change_to(client, "pro")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["effect"] == "immediate"
    assert body["plan_code"] == "pro"
    assert body["effective_at"] is None
    assert stored_plan(engine, account_id) == "pro"


def test_a_downgrade_is_scheduled_at_the_end_of_the_paid_period(client, engine, stripe: FakeStripe):
    """Descendre immédiatement ferait perdre la période DÉJÀ PAYÉE."""
    account_id = paying(engine, client, stripe, plan="scale")

    response = change_to(client, "essential")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["effect"] == "scheduled"
    assert body["plan_code"] == "essential"
    assert body["effective_at"] == PERIOD_END.isoformat()
    # Les droits COURANTS ne bougent pas : le client reste Scale jusqu'au terme.
    assert stored_plan(engine, account_id) == "scale"


def test_a_scheduled_downgrade_uses_a_subscription_schedule(client, engine, stripe: FakeStripe):
    """Le portail ne sait pas le faire entre Products distincts — le serveur si."""
    paying(engine, client, stripe, plan="pro")

    assert change_to(client, "essential").status_code == 200

    (scheduled,) = stripe.scheduled_changes
    assert scheduled["subscription_id"] == SUBSCRIPTION_ID
    assert scheduled["price_id"] == "price_test_essential_chf"
    assert scheduled["effective_at"] == PERIOD_END


# ─── La devise du contrat ne change jamais ────────────────────────────────────


@pytest.mark.parametrize("currency", ["chf", "eur"])
def test_the_contract_currency_is_preserved(client, engine, stripe: FakeStripe, currency: str):
    """Changer de formule n'est pas l'occasion de changer de devise."""
    paying(engine, client, stripe, plan="essential", currency=currency)

    assert change_to(client, "scale").status_code == 200

    (call,) = stripe.price_changes
    assert call["price_id"] == f"price_test_scale_{currency}"


def test_the_browser_can_never_choose_a_price(client, engine, stripe: FakeStripe):
    """§32 — un `price_id` glissé dans le corps fait échouer, jamais ignorer."""
    paying(engine, client, stripe, plan="essential")

    response = client.post("/billing/plan", json={"plan": "pro", "price_id": "price_de_mon_choix"})

    assert response.status_code == 422


def test_a_currency_absent_from_the_contract_refuses_the_change(client, engine, stripe: FakeStripe):
    """Défaut fermé : sans devise connue, aucun Price n'est résoluble."""
    paying(engine, client, stripe, plan="pro", lookup_key="kivou_pro_monthly_xxx", currency=None)

    response = change_to(client, "scale")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_change_unavailable"


# ─── Ce qui doit être refusé ──────────────────────────────────────────────────


def test_the_same_plan_is_refused_rather_than_billed(client, engine, stripe: FakeStripe):
    paying(engine, client, stripe, plan="pro")

    response = change_to(client, "pro")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_change_same_plan"


def test_a_discovery_account_is_sent_to_checkout_not_to_a_plan_change(client, engine):
    """Sans abonnement, changer de formule n'a aucun sens : il faut en ouvrir un."""
    response = change_to(client, "pro")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_change_unavailable"
    assert subscription_count(engine) == 0


@pytest.mark.parametrize("status", ["past_due", "unpaid", "incomplete"])
def test_an_unsettled_subscription_never_changes_plan(
    client, engine, stripe: FakeStripe, status: str
):
    """`billing_action` gouverne : ces états se rattrapent, ils ne se changent pas."""
    account_id = paying(engine, client, stripe, plan="pro", status=status)

    response = change_to(client, "scale")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_change_unavailable"
    assert stored_plan(engine, account_id) == "pro", "l'état payé ne bouge pas"


def test_an_unknown_plan_is_refused_by_the_schema(client, engine, stripe: FakeStripe):
    paying(engine, client, stripe, plan="pro")
    assert change_to(client, "founding").status_code == 422
    assert change_to(client, "discovery").status_code == 422


# ─── Aucun second abonnement, jamais ──────────────────────────────────────────


def test_no_plan_change_ever_creates_a_second_subscription(client, engine, stripe: FakeStripe):
    """La règle qui protège l'argent du client : on MODIFIE, on ne crée pas."""
    paying(engine, client, stripe, plan="essential")

    assert change_to(client, "scale").status_code == 200
    assert change_to(client, "essential").status_code == 200

    assert subscription_count(engine) == 1
    assert stripe.checkout_calls == [], "aucun Checkout ne doit être ouvert"


# ─── Un paiement refusé n'accorde aucun droit ─────────────────────────────────


def test_a_failed_upgrade_payment_grants_nothing(client, engine, stripe: FakeStripe):
    """Le piège : encaisser l'échec et livrer quand même la formule supérieure."""
    account_id = paying(engine, client, stripe, plan="essential")
    stripe.fail_price_change = True

    response = change_to(client, "scale")

    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "plan_change_payment_failed"
    assert stored_plan(engine, account_id) == "essential"


# ─── Annuler un downgrade programmé ───────────────────────────────────────────


def test_a_scheduled_downgrade_can_be_cancelled(client, engine, stripe: FakeStripe):
    """Se raviser doit être possible tant que l'échéance n'est pas atteinte."""
    paying(engine, client, stripe, plan="scale")
    assert change_to(client, "essential").status_code == 200

    response = client.delete("/billing/plan")

    assert response.status_code == 200, response.text
    assert stripe.scheduled_changes == [], "le schedule doit être relâché"
    assert client.get("/billing/status").json()["scheduled_plan_change"] is None


def test_cancelling_without_a_scheduled_change_is_refused(client, engine, stripe: FakeStripe):
    paying(engine, client, stripe, plan="pro")

    response = client.delete("/billing/plan")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_change_none_scheduled"


# ─── Ce que le client voit ────────────────────────────────────────────────────


def test_the_status_exposes_a_scheduled_change_without_lying_about_rights(
    client, engine, stripe: FakeStripe
):
    """L'écran doit dire l'effet DIFFÉRÉ sans prétendre qu'il a déjà eu lieu."""
    paying(engine, client, stripe, plan="scale")
    assert change_to(client, "essential").status_code == 200

    body = client.get("/billing/status").json()

    assert body["plan_code"] == "scale", "les droits courants restent ceux payés"
    assert body["scheduled_plan_change"] == {
        "plan_code": "essential",
        "effective_at": PERIOD_END.isoformat(),
    }
    assert body["entitlements"]["history_scope"] == "all_available"


def test_the_status_carries_no_stripe_identifier(client, engine, stripe: FakeStripe):
    """Un `price_...` ou un `sub_...` n'a rien à faire dans une réponse."""
    paying(engine, client, stripe, plan="pro")
    assert change_to(client, "essential").status_code == 200

    serialized = repr(client.get("/billing/status").json())

    assert "price_" not in serialized
    assert "sub_" not in serialized
    assert "cus_" not in serialized


# ─── L'origine est exigée, comme partout ailleurs ─────────────────────────────


def test_a_plan_change_without_the_expected_origin_is_refused(app, engine, stripe: FakeStripe):
    client = TestClient(app, headers={"Origin": ORIGIN})
    client.post(
        "/auth/signup",
        json={
            "email": "bob@materiaux-leman.ch",
            "password": PASSWORD,
            "company_name": "Materiaux Leman",
            "locale": "fr",
        },
    )
    paying(engine, client, stripe, plan="essential")

    response = client.post(
        "/billing/plan", json={"plan": "pro"}, headers={"Origin": "https://ailleurs.example"}
    )

    assert response.status_code == 403
