"""P0-03F — le seul test qui parle VRAIMENT à Stripe. Désactivé par défaut.

Pourquoi il existe
──────────────────
2712 tests verts n'ont pas vu que Kivou ne pouvait ouvrir aucune session de
paiement. Tous passaient par un faux `StripeGateway` : un double ne peut pas
connaître les règles que Stripe applique à ses propres paramètres. Celui-ci
crée une Checkout Session RÉELLE en mode TEST, avec la combinaison exacte qui
échouait :

    Customer existant  +  tax_id_collection  +  customer_update name/address

Pourquoi il est désactivé
─────────────────────────
La CI reste hors-ligne et ne reçoit aucun secret. Ce test ne s'exécute que si
`KIVOU_STRIPE_TEST_SMOKE_KEY` est fourni — une clé **`sk_test_`** et rien
d'autre : la garde ci-dessous refuse une clé LIVE plutôt que de créer un objet
facturable par accident.

Comment l'exécuter
──────────────────
    KIVOU_STRIPE_TEST_SMOKE_KEY=sk_test_… uv run pytest \\
        tests/test_billing_stripe_test_smoke.py -v

Il crée un Customer de test et une session non payée, puis fait expirer la
session. Le second test va plus loin : il crée un abonnement TEST réel, y
programme une résiliation comme le fait le portail Kivou, et vérifie que
`subscription_state()` la voit. Tout est supprimé ensuite. Aucun débit réel,
aucun LIVE.
"""

from __future__ import annotations

import datetime as dt
import os

import pytest

from signals.billing.gateway import StripeApiGateway

SMOKE_KEY_VARIABLE = "KIVOU_STRIPE_TEST_SMOKE_KEY"

_key = os.environ.get(SMOKE_KEY_VARIABLE, "")

pytestmark = pytest.mark.skipif(
    not _key,
    reason=f"smoke Stripe TEST opt-in : définir {SMOKE_KEY_VARIABLE} (clé sk_test_ uniquement)",
)


@pytest.fixture(scope="module")
def gateway() -> StripeApiGateway:
    if not _key.startswith("sk_test_"):
        pytest.fail(f"{SMOKE_KEY_VARIABLE} doit être une clé sk_test_ ; aucun appel LIVE ici")
    return StripeApiGateway(_key)


def test_stripe_accepte_une_session_pour_un_customer_existant(gateway: StripeApiGateway) -> None:
    """Le contrat que les doubles ne peuvent pas vérifier.

    C'est littéralement l'appel qui répondait :
    « Tax ID collection requires updating business name on the customer. »
    """
    stamp = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%dT%H%M%S")
    customer = gateway.create_customer(
        email=f"smoke.{stamp}@kivou-qa.ch",
        account_id=f"acc_smoke_{stamp}",
        display_name="Kivou QA — smoke P0-03F",
        idempotency_key=f"kivou-smoke-customer:{stamp}",
    )
    assert customer.livemode is False

    price = gateway.price_for_lookup_key("kivou_pro_monthly_chf")
    assert price is not None, "le catalogue TEST doit porter kivou_pro_monthly_chf"

    session = gateway.create_checkout_session(
        customer_id=customer.customer_id,
        price_id=price.price_id,
        account_id=f"acc_smoke_{stamp}",
        success_url="https://staging.kivou.eu/checkout/success",
        cancel_url="https://staging.kivou.eu/checkout/cancel",
        automatic_tax=False,
        coupon_id=None,
        expires_at=dt.datetime.now(tz=dt.UTC) + dt.timedelta(minutes=30),
        idempotency_key=f"kivou-smoke-checkout:{stamp}",
    )

    assert session.livemode is False
    assert session.session_id.startswith("cs_test_")
    assert session.url

    # Ne rien laisser d'ouvert derrière un test.
    gateway._client.checkout.sessions.expire(session.session_id)


def test_stripe_expose_une_resiliation_programmee_que_kivou_sait_lire(
    gateway: StripeApiGateway,
) -> None:
    """P0-03G — le contrat qu'aucun double ne peut vérifier.

    Sur staging, une résiliation demandée au portail Kivou est restée invisible
    pendant six heures : Stripe l'exprimait par `cancel_at` en laissant
    `cancel_at_period_end` à `false`, et la passerelle ne lisait que le booléen.

    Ce test crée un vrai abonnement TEST, y programme une résiliation en fin de
    période — le mode exact du portail Kivou — puis RELIT l'objet courant par le
    chemin de production et vérifie ce que Kivou en conclut.
    """
    stamp = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%dT%H%M%S")
    client = gateway._client
    customer = gateway.create_customer(
        email=f"smoke.cancel.{stamp}@kivou-qa.ch",
        account_id=f"acc_smoke_cancel_{stamp}",
        display_name="Kivou QA — smoke P0-03G",
        idempotency_key=f"kivou-smoke-cancel-customer:{stamp}",
    )
    price = gateway.price_for_lookup_key("kivou_pro_monthly_chf")
    assert price is not None, "le catalogue TEST doit porter kivou_pro_monthly_chf"

    subscription_id = None
    try:
        # Une carte de test Stripe, attachée pour que l'abonnement devienne actif.
        # `attach` rend un NOUVEAU moyen de paiement : c'est son identifiant qu'il
        # faut désigner comme défaut, pas le jeton de test partagé.
        attached = client.payment_methods.attach(
            "pm_card_visa", params={"customer": customer.customer_id}
        )
        client.customers.update(
            customer.customer_id,
            params={"invoice_settings": {"default_payment_method": attached.id}},
        )
        created = client.subscriptions.create(
            params={
                "customer": customer.customer_id,
                "items": [{"price": price.price_id}],
            }
        )
        subscription_id = created.id

        avant = gateway.fetch_subscription(subscription_id)
        assert avant is not None
        assert avant.scheduled_cancellation_at is None, "aucune résiliation n'a été demandée"

        # Ce que fait le portail Kivou : `subscription_cancel.mode = at_period_end`.
        client.subscriptions.update(subscription_id, params={"cancel_at_period_end": True})

        # RELIRE l'objet courant, par le chemin de production.
        apres = gateway.fetch_subscription(subscription_id)
        assert apres is not None

        # Quelle que soit la forme choisie par Stripe — `cancel_at` ou le booléen —
        # Kivou doit en tirer une échéance, et la bonne.
        assert apres.scheduled_cancellation_at is not None, (
            "Stripe annonce une résiliation programmée que Kivou ne voit pas"
        )
        assert apres.current_period_end is not None
        assert apres.scheduled_cancellation_at == apres.current_period_end
        assert apres.cancel_at_period_end is True
        assert apres.status == "active", "l'accès reste actif jusqu'à l'échéance"
    finally:
        # Ne rien laisser derrière : abonnement résilié immédiatement, client supprimé.
        if subscription_id is not None:
            client.subscriptions.cancel(subscription_id)
        client.customers.delete(customer.customer_id)
