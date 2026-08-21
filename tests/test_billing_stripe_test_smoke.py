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
session. Aucun paiement, aucun abonnement, aucun débit.
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
