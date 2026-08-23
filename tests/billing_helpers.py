"""Fabriques de facturation pour les tests — hors-ligne, sans réseau, sans Stripe.

Pourquoi une fausse passerelle plutôt qu'un appel réel
─────────────────────────────────────────────────────
Un test qui appelle Stripe échoue le jour où le réseau tombe, et ne dit
alors plus rien du code. Le double implémente le protocole
`signals.billing.gateway.StripeGateway` et rend des objets de la même forme
que la vraie passerelle — c'est ce qui garantit que ces tests portent sur le
contrat réel et non sur une structure inventée pour l'occasion.

La signature de webhook, elle, est VRAIE
───────────────────────────────────────
`stripe.Webhook.construct_event` ne fait que du HMAC local : les tests
fabriquent une signature authentique avec un secret de test et exercent le
vrai code de vérification, hors-ligne. Aucune vérification cryptographique
n'est simulée — la simuler reviendrait à ne pas la tester.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import hmac
import json
from collections.abc import Iterator
from typing import Any

import sqlalchemy as sa

from signals.billing import catalogue
from signals.billing.gateway import (
    CheckoutSession,
    PlanChangePaymentFailed,
    PortalSession,
    StripeCustomer,
    StripePrice,
    StripeScheduledChange,
    StripeSubscriptionState,
)
from signals.billing.service import synchronize_subscription

#: Un secret de webhook de TEST, fabriqué pour la suite. Ce n'est pas un secret
#: Stripe : il n'ouvre rien, et n'existe que dans ce fichier.
TEST_WEBHOOK_SECRET = "whsec_" + "0" * 32

#: CLOSEOUT §3 — les URL de retour n'ont plus de défaut : une configuration de
#: facturation doit les déclarer. Celles-ci sont SYNTHÉTIQUES et n'existent que
#: pour la suite de tests ; aucun domaine de production n'apparaît ici, et rien
#: dans le code ne les connaît.
TEST_SUCCESS_URL = "https://kivou.test/checkout/success"
TEST_CANCEL_URL = "https://kivou.test/checkout/cancel"
TEST_PORTAL_RETURN_URL = "https://kivou.test/app/billing"

#: Les trois arguments à passer à `ApiConfig` pour un test qui exerce la
#: facturation. Regroupés pour qu'ajouter une quatrième URL un jour ne demande
#: pas de modifier huit fichiers de test.
BILLING_RETURN_URLS = {
    "stripe_success_url": TEST_SUCCESS_URL,
    "stripe_cancel_url": TEST_CANCEL_URL,
    "stripe_portal_return_url": TEST_PORTAL_RETURN_URL,
}


def stripe_signature(payload: bytes, *, secret: str, timestamp: int) -> str:
    """L'en-tête `Stripe-Signature` tel que Stripe le calcule.

    C'est un HMAC-SHA256 sur « horodatage.corps ». Le reproduire ici permet de
    tester la VRAIE vérification sans réseau.
    """
    signed = f"{timestamp}.".encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


#: La tolérance que Stripe applique par défaut aux horodatages de signature.
#: Elle est RECOPIÉE ici, pas modifiée : `verify_event` laisse
#: `stripe.Webhook.construct_event` utiliser son propre défaut. Les tests de
#: frontière ont besoin de la connaître pour se placer de part et d'autre.
STRIPE_SIGNATURE_TOLERANCE_SECONDS = 300


def signature_timestamp() -> int:
    """L'horodatage à mettre dans l'en-tête `Stripe-Signature`.

    Deux horloges cohabitent, et les confondre est le défaut que corrige #42.

    L'horloge MÉTIER est injectée (`now_override`) et volontairement figée à une
    date d'écriture : c'est elle qui date l'événement dans le corps, ordonne les
    mises à jour et rend les tests reproductibles.

    L'horloge de SIGNATURE, elle, n'est pas injectable : `construct_event`
    interroge `time.time()` et rejette tout horodatage antérieur de plus de
    `STRIPE_SIGNATURE_TOLERANCE_SECONDS`. Signer avec la date métier fabrique
    donc une bombe à retardement — l'en-tête n'est accepté que tant que cette
    date reste dans le futur. Signer avec l'horloge réellement consultée rend le
    test vrai à toute date, sans toucher à la tolérance.

    C'est bien CETTE horloge qui est lue, et pas `time.time()` en direct : un
    test de frontière fige la première, et la signature doit suivre.
    """
    return int(_verifier_time().time())


def _verifier_time() -> Any:
    """Le module `time` tel que `construct_event` le voit, figé ou non."""
    import stripe._webhook as webhook_module

    return webhook_module.time


class _FrozenClock:
    """Le module `time` vu par la vérification Stripe, arrêté à un instant.

    Seul `time()` est figé ; tout le reste est délégué au vrai module, pour ne
    pas transformer un outil de test en piège si le SDK consulte autre chose.
    """

    def __init__(self, instant: float, wrapped: Any) -> None:
        self._instant = instant
        self._wrapped = wrapped

    def time(self) -> float:
        return self._instant

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


@contextlib.contextmanager
def verifier_clock_at(instant: dt.datetime) -> Iterator[None]:
    """Fige l'horloge que `construct_event` consulte, le temps d'un bloc.

    Sans cela, une frontière EXACTE de tolérance est intestable : `time.time()`
    avance entre la signature et la vérification, et le test à +/-300 s
    exactement bascule au hasard. Le substitut ne vise que l'espace de noms de
    `stripe._webhook` : le module `time` global n'est pas touché.
    """
    import stripe._webhook as webhook_module

    original = webhook_module.time
    webhook_module.time = _FrozenClock(instant.timestamp(), original)
    try:
        yield
    finally:
        webhook_module.time = original


def event_payload(
    *,
    event_id: str,
    event_type: str,
    created: dt.datetime,
    data_object: dict[str, Any],
    livemode: bool = False,
) -> bytes:
    body = {
        "id": event_id,
        "type": event_type,
        "created": int(created.timestamp()),
        "livemode": livemode,
        "data": {"object": data_object},
    }
    return json.dumps(body, separators=(",", ":")).encode()


@dataclasses.dataclass
class FakeStripe:
    """Un Stripe déterministe : ce qu'on lui met, il le rend."""

    livemode: bool = False
    prices: dict[str, StripePrice] = dataclasses.field(default_factory=dict)
    subscriptions: dict[str, StripeSubscriptionState] = dataclasses.field(default_factory=dict)
    customers: dict[str, StripeCustomer] = dataclasses.field(default_factory=dict)
    #: Chaque appel enregistré : les tests vérifient l'idempotence dessus.
    customer_calls: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    checkout_calls: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    portal_calls: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    #: #29 — les changements de formule, pour que les tests lisent ce que Stripe
    #: a réellement reçu plutôt que ce qu'on espère lui avoir envoyé.
    price_changes: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    scheduled_changes: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    #: Pilotage : simule un prorata refusé par la banque.
    fail_price_change: bool = False
    _counter: int = 0
    _by_idempotency_key: dict[str, StripeCustomer] = dataclasses.field(default_factory=dict)
    _sessions_by_key: dict[str, CheckoutSession] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.prices:
            self.prices = default_prices(livemode=self.livemode)

    # ── protocole StripeGateway ──────────────────────────────────────────────

    def price_for_lookup_key(self, lookup_key: str) -> StripePrice | None:
        return self.prices.get(lookup_key)

    def create_customer(
        self, *, email: str, account_id: str, display_name: str, idempotency_key: str
    ) -> StripeCustomer:
        self.customer_calls.append(
            {"email": email, "account_id": account_id, "idempotency_key": idempotency_key}
        )
        # Stripe rend le MÊME objet pour une clé d'idempotence déjà vue : le
        # double doit se comporter pareil, sinon l'idempotence n'est pas testée.
        known = self._by_idempotency_key.get(idempotency_key)
        if known is not None:
            return known
        self._counter += 1
        customer = StripeCustomer(
            customer_id=f"cus_test_{self._counter:04d}", livemode=self.livemode
        )
        self.customers[customer.customer_id] = customer
        self._by_idempotency_key[idempotency_key] = customer
        return customer

    def create_checkout_session(self, **kwargs: Any) -> CheckoutSession:
        self.checkout_calls.append(kwargs)
        key = kwargs.get("idempotency_key")
        # Stripe rend la MÊME session pour une clé d'idempotence déjà vue :
        # c'est exactement ce qui protège une reprise après plantage (§4).
        known = self._sessions_by_key.get(key)
        if known is not None:
            return known
        self._counter += 1
        session_id = f"cs_test_{self._counter:04d}"
        session = CheckoutSession(
            session_id=session_id,
            url=f"https://checkout.stripe.test/{session_id}",
            livemode=self.livemode,
        )
        self._sessions_by_key[key] = session
        return session

    def create_portal_session(
        self, *, customer_id: str, return_url: str, configuration_id: str | None = None
    ) -> PortalSession:
        self.portal_calls.append(
            {
                "customer_id": customer_id,
                "return_url": return_url,
                "configuration_id": configuration_id,
            }
        )
        return PortalSession(url=f"https://billing.stripe.test/{customer_id}")

    def fetch_subscription(self, subscription_id: str) -> StripeSubscriptionState | None:
        return self.subscriptions.get(subscription_id)

    # ── changement de formule (#29) ──────────────────────────────────────────

    def _price_of(self, price_id: str) -> StripePrice:
        for price in self.prices.values():
            if price.price_id == price_id:
                return price
        raise AssertionError(f"prix hors catalogue de test : {price_id}")

    def change_subscription_price(
        self, *, subscription_id: str, price_id: str, idempotency_key: str
    ) -> StripeSubscriptionState:
        """Stripe REFUSE la modification si le prorata n'est pas encaissé.

        Le double reproduit ce comportement — c'est lui qui garantit qu'un
        paiement échoué n'accorde aucun droit, et le simuler autrement
        rendrait le test complaisant.
        """
        if self.fail_price_change:
            raise PlanChangePaymentFailed("prorata refusé (double de test)")
        self.price_changes.append(
            {
                "subscription_id": subscription_id,
                "price_id": price_id,
                "idempotency_key": idempotency_key,
            }
        )
        current = self.subscriptions[subscription_id]
        price = self._price_of(price_id)
        updated = dataclasses.replace(
            current,
            price_id=price.price_id,
            product_id=price.product_id,
            lookup_key=price.lookup_key,
            currency=price.currency,
        )
        self.subscriptions[subscription_id] = updated
        return updated

    def schedule_subscription_price(
        self, *, subscription_id: str, price_id: str, idempotency_key: str
    ) -> StripeScheduledChange:
        current = self.subscriptions[subscription_id]
        price = self._price_of(price_id)
        # L'échéance est la FIN de la période déjà payée : c'est exactement ce
        # que la première phase d'un `SubscriptionSchedule` porte.
        effective_at = current.current_period_end
        self.scheduled_changes = [
            {
                "subscription_id": subscription_id,
                "price_id": price_id,
                "lookup_key": price.lookup_key,
                "effective_at": effective_at,
            }
        ]
        return StripeScheduledChange(
            schedule_id=f"sub_sched_{subscription_id}",
            lookup_key=price.lookup_key,
            currency=price.currency,
            effective_at=effective_at,
            livemode=self.livemode,
        )

    def pending_plan_change(self, *, subscription_id: str) -> StripeScheduledChange | None:
        for scheduled in self.scheduled_changes:
            if scheduled["subscription_id"] == subscription_id:
                return StripeScheduledChange(
                    schedule_id=f"sub_sched_{subscription_id}",
                    lookup_key=scheduled["lookup_key"],
                    currency=self.subscriptions[subscription_id].currency,
                    effective_at=scheduled["effective_at"],
                    livemode=self.livemode,
                )
        return None

    def release_pending_plan_change(self, *, subscription_id: str) -> None:
        self.scheduled_changes = [
            s for s in self.scheduled_changes if s["subscription_id"] != subscription_id
        ]

    def verify_event(self, *, payload: bytes, signature: str, secret: str):
        from signals.billing.gateway import verify_event

        return verify_event(payload=payload, signature=signature, secret=secret)

    # ── pilotage du double ───────────────────────────────────────────────────

    def put_subscription(self, state: StripeSubscriptionState) -> StripeSubscriptionState:
        self.subscriptions[state.subscription_id] = state
        return state


def default_prices(*, livemode: bool = False) -> dict[str, StripePrice]:
    """Le catalogue Stripe attendu par SPEC-013 §6, en objets de test."""
    prices: dict[str, StripePrice] = {}
    for plan in catalogue.PURCHASABLE_PLANS:
        for currency in catalogue.CURRENCIES:
            lookup = catalogue.lookup_key_for(plan, currency)
            prices[lookup] = StripePrice(
                price_id=f"price_test_{plan}_{currency}",
                product_id=f"prod_test_{plan}",
                lookup_key=lookup,
                currency=currency,
                unit_amount=catalogue.amount_for(plan, currency),
                recurring_interval="month",
                livemode=livemode,
                active=True,
            )
    return prices


def subscription_state(
    *,
    subscription_id: str = "sub_test_0001",
    customer_id: str = "cus_test_0001",
    account_id: str | None = None,
    plan: str = "pro",
    currency: str = "chf",
    status: str = "active",
    period_start: dt.datetime | None = None,
    period_end: dt.datetime | None = None,
    cancel_at_period_end: bool = False,
    canceled_at: dt.datetime | None = None,
    scheduled_cancellation_at: dt.datetime | None = None,
    livemode: bool = False,
    lookup_key: str | None = None,
    coupon_id: str | None = None,
) -> StripeSubscriptionState:
    key = lookup_key if lookup_key is not None else catalogue.lookup_key_for(plan, currency)
    return StripeSubscriptionState(
        subscription_id=subscription_id,
        customer_id=customer_id,
        status=status,
        price_id=f"price_test_{plan}_{currency}",
        product_id=f"prod_test_{plan}",
        lookup_key=key,
        currency=currency,
        current_period_start=period_start,
        current_period_end=period_end,
        cancel_at_period_end=cancel_at_period_end,
        canceled_at=canceled_at,
        scheduled_cancellation_at=scheduled_cancellation_at,
        livemode=livemode,
        account_id=account_id,
        discount_coupon_id=coupon_id,
    )


def subscribe(
    connection: sa.Connection,
    *,
    account_id: str,
    plan: str = "pro",
    currency: str = "chf",
    status: str = "active",
    now: dt.datetime,
    **overrides: Any,
) -> None:
    """Abonne un compte en passant par le VRAI chemin de synchronisation.

    Écrire la ligne à la main testerait la table ; passer par
    `synchronize_subscription` teste la résolution du plan, la garde de mode et
    la règle d'antériorité d'événement — c'est-à-dire le code qui compte.
    """
    state = subscription_state(
        account_id=account_id, plan=plan, currency=currency, status=status, **overrides
    )
    synchronize_subscription(
        connection,
        state,
        account_id=account_id,
        event_created_at=now,
        expect_livemode=state.livemode,
        now=now,
    )
