"""La frontière Stripe — tout ce qui sort du processus passe par ici.

    Pourquoi une passerelle plutôt que des appels directs
    ────────────────────────────────────────────────────
    Deux raisons, et aucune n'est esthétique. D'abord la suite de tests doit
    rester **hors-ligne** : un test qui appelle Stripe échoue le jour où le
    réseau tombe, et ne dit alors plus rien du code. Ensuite, le SDK rend des
    objets dynamiques dont la forme change avec la version d'API ; les traduire
    UNE fois, ici, empêche cette forme de se répandre dans le service, les
    routes et les tests.

    Ce que la passerelle NE fait pas
    ────────────────────────────────
    Elle ne décide d'aucun droit. Elle rapporte des faits de paiement : ce prix
    existe, cet abonnement est dans cet état. La traduction en plan Kivou est
    faite par `signals.billing.catalogue`, et par lui seul (§9).

La vérification de signature passe par `stripe.Webhook.construct_event` : c'est
du HMAC local, sans réseau, donc testable hors-ligne — et il n'y a aucune raison
d'écrire soi-même une vérification cryptographique.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
from typing import Any, Protocol

_LOGGER = logging.getLogger(__name__)

STRIPE_GATEWAY_VERSION = "stripe-gateway-v0.1"


class StripeGatewayError(RuntimeError):
    """Un appel Stripe a échoué. Le message reste générique côté client."""


class InvalidWebhookSignature(StripeGatewayError):
    """La signature est absente, malformée ou ne correspond pas au corps brut."""


class CheckoutSessionRejected(StripeGatewayError):
    """Stripe a refusé la requête elle-même : AUCUNE session n'existe.

    P0-03F — c'est la seule famille d'erreurs qui autorise à libérer la
    tentative locale. Elle exige une preuve : un refus portant sur la requête
    (paramètres, clé, permissions) est rendu avant toute création de ressource.
    """

    code = "checkout_rejected"


class CheckoutSessionUncertain(StripeGatewayError):
    """L'appel n'a pas abouti de façon concluante : Stripe a PEUT-ÊTRE créé la session.

    P0-03F — timeout, coupure réseau, 5xx, limite de débit, clé d'idempotence
    déjà employée. Dans tous ces cas la réponse manque, pas la session : libérer
    la place ici ouvrirait un SECOND paiement pour un client qui n'en a demandé
    qu'un. La tentative reste `creating`, et le rejeu réutilise la même clé.
    """

    code = "checkout_uncertain"


@dataclasses.dataclass(frozen=True)
class StripePrice:
    """Un prix récurrent approuvé, tel que Stripe le publie."""

    price_id: str
    product_id: str | None
    lookup_key: str | None
    currency: str
    unit_amount: int | None
    recurring_interval: str | None
    livemode: bool
    active: bool


@dataclasses.dataclass(frozen=True)
class StripeCustomer:
    customer_id: str
    livemode: bool


@dataclasses.dataclass(frozen=True)
class StripeSubscriptionState:
    """L'état d'un abonnement — la seule source de vérité sur ce qui est payé.

    Il est relu depuis Stripe plutôt que reconstitué depuis un événement : §17
    interdit de supposer un ordre de livraison, et l'objet courant, lui, ne
    dépend d'aucun ordre.
    """

    subscription_id: str
    customer_id: str
    status: str
    price_id: str | None
    product_id: str | None
    lookup_key: str | None
    currency: str | None
    current_period_start: dt.datetime | None
    current_period_end: dt.datetime | None
    cancel_at_period_end: bool
    canceled_at: dt.datetime | None
    livemode: bool
    account_id: str | None = None
    discount_coupon_id: str | None = None
    #: P0-03G — l'échéance de résiliation, en DATE et non en booléen.
    #:
    #: Stripe l'exprime de deux façons selon le `billing_mode` de l'abonnement :
    #: `cancel_at` sur les `flexible`, `cancel_at_period_end` sur les autres. Ne
    #: lire que le booléen rendait la résiliation invisible pour les premiers —
    #: constaté en vrai, deux fois, sur staging.
    #:
    #: `None` par défaut : l'absence de preuve d'échéance EST l'absence
    #: d'échéance, et c'est le seul défaut sûr.
    scheduled_cancellation_at: dt.datetime | None = None


@dataclasses.dataclass(frozen=True)
class StripeScheduledChange:
    """Un changement de formule DÉJÀ programmé chez Stripe.

    `lookup_key` plutôt que `price_id` : c'est la référence stable que le
    catalogue Kivou sait traduire en plan. Un `price_...` change avec la
    tarification et ne décrit aucun droit (§4).
    """

    schedule_id: str
    lookup_key: str | None
    currency: str | None
    effective_at: dt.datetime | None
    livemode: bool


class PlanChangePaymentFailed(StripeGatewayError):
    """Le prorata d'une montée en formule n'a pas pu être encaissé.

    Distinguer ce cas est ce qui empêche d'accorder les droits supérieurs à
    quelqu'un dont le paiement vient d'échouer.
    """


@dataclasses.dataclass(frozen=True)
class CheckoutSession:
    session_id: str
    url: str | None
    livemode: bool


@dataclasses.dataclass(frozen=True)
class PortalSession:
    url: str


@dataclasses.dataclass(frozen=True)
class StripeEvent:
    """Un événement vérifié. `payload` reste brut pour l'empreinte, jamais stocké."""

    event_id: str
    event_type: str
    created: dt.datetime
    livemode: bool
    object_id: str | None
    data_object: dict[str, Any]

    @property
    def subscription_id(self) -> str | None:
        """L'abonnement concerné, quel que soit le type d'événement.

        Un `checkout.session` porte `subscription` ; une `invoice` aussi ; un
        objet `subscription` est lui-même l'abonnement. Le service n'a donc pas
        à connaître la forme de chaque type pour savoir quoi resynchroniser.
        """
        data = self.data_object
        if self.event_type.startswith("customer.subscription."):
            identifier = data.get("id")
            return identifier if isinstance(identifier, str) else None
        subscription = data.get("subscription")
        if isinstance(subscription, str):
            return subscription
        if isinstance(subscription, dict):
            identifier = subscription.get("id")
            return identifier if isinstance(identifier, str) else None
        # Les factures d'API récentes rattachent l'abonnement à la ligne parente.
        parent = data.get("parent")
        if isinstance(parent, dict):
            details = parent.get("subscription_details")
            if isinstance(details, dict):
                identifier = details.get("subscription")
                if isinstance(identifier, str):
                    return identifier
        return None

    @property
    def account_reference(self) -> str | None:
        """Le compte Kivou porté par l'objet, s'il en porte un (§12, §13)."""
        data = self.data_object
        reference = data.get("client_reference_id")
        if isinstance(reference, str) and reference:
            return reference
        metadata = data.get("metadata")
        if isinstance(metadata, dict):
            value = metadata.get("kivou_account_id")
            if isinstance(value, str) and value:
                return value
        return None


class StripeGateway(Protocol):
    """Ce que Kivou demande à Stripe. Rien de plus, rien d'implicite."""

    def price_for_lookup_key(self, lookup_key: str) -> StripePrice | None: ...

    def create_customer(
        self, *, email: str, account_id: str, display_name: str, idempotency_key: str
    ) -> StripeCustomer: ...

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        account_id: str,
        success_url: str,
        cancel_url: str,
        automatic_tax: bool,
        coupon_id: str | None,
        expires_at: dt.datetime,
        idempotency_key: str,
    ) -> CheckoutSession: ...

    def create_portal_session(
        self, *, customer_id: str, return_url: str, configuration_id: str | None
    ) -> PortalSession: ...

    def fetch_subscription(self, subscription_id: str) -> StripeSubscriptionState | None: ...

    def change_subscription_price(
        self, *, subscription_id: str, price_id: str, idempotency_key: str
    ) -> StripeSubscriptionState: ...

    def schedule_subscription_price(
        self, *, subscription_id: str, price_id: str, idempotency_key: str
    ) -> StripeScheduledChange: ...

    def pending_plan_change(self, *, subscription_id: str) -> StripeScheduledChange | None: ...

    def release_pending_plan_change(self, *, subscription_id: str) -> None: ...

    def verify_event(self, *, payload: bytes, signature: str, secret: str) -> StripeEvent: ...


def _instant(value: Any) -> dt.datetime | None:
    """Un horodatage Stripe (epoch en secondes) en instant UTC conscient."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    return dt.datetime.fromtimestamp(int(value), tz=dt.UTC)


#: Les codes par lesquels Stripe dit « le paiement n'est pas allé au bout ».
#: Tout le reste remonte tel quel : avaler une erreur inconnue reviendrait à
#: décider, sans savoir, que le client peut passer.
_PAYMENT_INCOMPLETE_CODES: frozenset[str] = frozenset(
    {
        "subscription_payment_intent_requires_action",
        "invoice_payment_intent_requires_action",
        "card_declined",
    }
)


def _schedule_id(value: Any) -> str:
    """L'identifiant d'un schedule, qu'il soit développé ou non."""
    return value if isinstance(value, str) else _get(value, "id")


def _phase_price(phase: Any) -> str | None:
    """Le Price porté par une phase de schedule."""
    items = _get(phase, "items") or []
    if not items:
        return None
    price = _get(items[0], "price")
    return price if isinstance(price, str) else _get(price, "id")


#: Le Price des phases doit être DÉVELOPPÉ : sans cela Stripe ne rend qu'un
#: `price_...`, dont Kivou ne sait rien tirer — la clé de recherche est la
#: seule référence que le catalogue traduit en formule (§4).
_SCHEDULE_EXPAND: list[str] = ["phases.items.price"]


def _scheduled_change(schedule: Any) -> StripeScheduledChange | None:
    """La phase À VENIR d'un schedule, traduite. `None` s'il n'y en a pas.

    Un schedule dont il ne reste que la phase courante ne programme rien : le
    présenter comme un changement à venir mentirait à l'écran du client.
    """
    phases = _get(schedule, "phases") or []
    if len(phases) < 2:
        return None
    items = _get(phases[1], "items") or []
    price = _get(items[0], "price") if items else None
    return StripeScheduledChange(
        schedule_id=_get(schedule, "id"),
        # Un Price non développé reste un identifiant opaque : on rend `None`
        # plutôt qu'une supposition, et l'appelant refusera par défaut fermé.
        lookup_key=_get(price, "lookup_key") if not isinstance(price, str) else None,
        currency=_get(price, "currency") if not isinstance(price, str) else None,
        effective_at=_instant(_get(phases[0], "end_date")),
        livemode=bool(_get(schedule, "livemode", False)),
    )


def _first_item(subscription: Any) -> Any:
    items = _get(subscription, "items")
    data = _get(items, "data") if items is not None else None
    return data[0] if data else None


def _get(source: Any, name: str, default: Any = None) -> Any:
    """Lit indifféremment un objet du SDK ou un dictionnaire."""
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def subscription_state(subscription: Any) -> StripeSubscriptionState:
    """Traduit un abonnement Stripe en fait exploitable.

    Les dates de période ont migré de l'abonnement vers ses lignes selon la
    version d'API ; les deux emplacements sont lus, ce qui évite qu'une montée
    de version fasse silencieusement disparaître la date de fin de période.
    """
    item = _first_item(subscription)
    price = _get(item, "price")
    product = _get(price, "product")
    product_id = product if isinstance(product, str) else _get(product, "id")
    metadata = _get(subscription, "metadata") or {}
    discount = _get(subscription, "discount")
    coupon = _get(discount, "coupon") if discount is not None else None

    period_start = _get(subscription, "current_period_start") or _get(item, "current_period_start")
    period_end = _get(subscription, "current_period_end") or _get(item, "current_period_end")

    # P0-03G — l'échéance vient d'une DATE quand Stripe en donne une, sinon du
    # booléen. `canceled_at` n'entre PAS dans ce calcul : il est renseigné aussi
    # sur une résiliation immédiate, et le prendre pour un indicateur ferait
    # annoncer une échéance à des comptes qui n'en ont aucune.
    current_period_end = _instant(period_end)
    cancel_at = _instant(_get(subscription, "cancel_at"))
    cancels_at_period_end = bool(_get(subscription, "cancel_at_period_end", False))
    if cancel_at is not None:
        scheduled_cancellation_at = cancel_at
    elif cancels_at_period_end:
        scheduled_cancellation_at = current_period_end
    else:
        scheduled_cancellation_at = None
    # Le booléen ne survit que là où il dit vrai : l'échéance tombe bien sur la
    # fin de période. Une date distincte est une date distincte, et l'annoncer
    # comme une fin de période donnerait au client une échéance fausse.
    falls_on_period_end = (
        scheduled_cancellation_at is not None
        and current_period_end is not None
        and scheduled_cancellation_at == current_period_end
    )

    return StripeSubscriptionState(
        subscription_id=_get(subscription, "id"),
        customer_id=(
            _get(subscription, "customer")
            if isinstance(_get(subscription, "customer"), str)
            else _get(_get(subscription, "customer"), "id")
        ),
        status=_get(subscription, "status", "unknown"),
        price_id=_get(price, "id"),
        product_id=product_id,
        lookup_key=_get(price, "lookup_key"),
        currency=_get(price, "currency") or _get(subscription, "currency"),
        current_period_start=_instant(period_start),
        current_period_end=current_period_end,
        cancel_at_period_end=cancels_at_period_end or falls_on_period_end,
        canceled_at=_instant(_get(subscription, "canceled_at")),
        scheduled_cancellation_at=scheduled_cancellation_at,
        livemode=bool(_get(subscription, "livemode", False)),
        account_id=_get(metadata, "kivou_account_id"),
        discount_coupon_id=_get(coupon, "id"),
    )


class StripeApiGateway:
    """L'implémentation réelle. Elle n'est jamais appelée par la suite de tests."""

    def __init__(self, api_key: str, *, api_version: str | None = None) -> None:
        import stripe

        self._stripe = stripe
        self._client = stripe.StripeClient(api_key, stripe_version=api_version)

    def price_for_lookup_key(self, lookup_key: str) -> StripePrice | None:
        found = self._client.prices.list(
            params={"lookup_keys": [lookup_key], "active": True, "limit": 2}
        )
        prices = list(found.data)
        if len(prices) != 1:
            # Zéro : le catalogue n'est pas configuré. Deux : il est ambigu.
            # Dans les deux cas, deviner serait pire que refuser.
            return None
        price = prices[0]
        product = _get(price, "product")
        return StripePrice(
            price_id=price.id,
            product_id=product if isinstance(product, str) else _get(product, "id"),
            lookup_key=_get(price, "lookup_key"),
            currency=_get(price, "currency"),
            unit_amount=_get(price, "unit_amount"),
            recurring_interval=_get(_get(price, "recurring"), "interval"),
            livemode=bool(_get(price, "livemode", False)),
            active=bool(_get(price, "active", False)),
        )

    def create_customer(
        self, *, email: str, account_id: str, display_name: str, idempotency_key: str
    ) -> StripeCustomer:
        customer = self._client.customers.create(
            params={
                "email": email,
                "name": display_name,
                # §12 — de quoi réconcilier, et rien de sensible.
                "metadata": {"kivou_account_id": account_id},
            },
            options={"idempotency_key": idempotency_key},
        )
        return StripeCustomer(customer_id=customer.id, livemode=bool(customer.livemode))

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        account_id: str,
        success_url: str,
        cancel_url: str,
        automatic_tax: bool,
        coupon_id: str | None,
        expires_at: dt.datetime,
        idempotency_key: str,
    ) -> CheckoutSession:
        params: dict[str, Any] = {
            "mode": "subscription",
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            # §13 — les deux chemins de réconciliation : la session porte le
            # compte, et l'abonnement qui en naîtra le portera aussi.
            "client_reference_id": account_id,
            "subscription_data": {"metadata": {"kivou_account_id": account_id}},
            "automatic_tax": {"enabled": automatic_tax},
            # §29 — collecter de quoi facturer correctement plus tard, sans
            # déduire quoi que ce soit d'une obligation fiscale ici.
            "tax_id_collection": {"enabled": True},
            # P0-03F — Stripe refuse `tax_id_collection` sur un Customer
            # EXISTANT sans autorisation explicite de compléter son nom. Kivou
            # crée toujours le Customer avant la session : sans ces deux lignes,
            # aucun client ne peut payer. `address` répercute en outre l'adresse
            # de facturation déjà rendue obligatoire ci-dessous.
            "customer_update": {"name": "auto", "address": "auto"},
            "billing_address_collection": "required",
            # Closeout §5 — la session Stripe et la tentative locale décrivent
            # la MÊME durée de vie. Sans cela, une tentative locale pourrait
            # survivre à la session qu'elle décrit et bloquer le compte.
            "expires_at": int(expires_at.timestamp()),
        }
        if coupon_id is not None:
            params["discounts"] = [{"coupon": coupon_id}]
        try:
            session = self._client.checkout.sessions.create(
                params=params, options={"idempotency_key": idempotency_key}
            )
        except (
            self._stripe.InvalidRequestError,
            self._stripe.AuthenticationError,
            self._stripe.PermissionError,
        ) as error:
            # Refus PORTANT SUR LA REQUÊTE : Stripe répond avant de créer quoi
            # que ce soit. La place peut être libérée sans risque de doublon.
            _LOGGER.warning(
                "checkout Stripe refusé (%s) : %s", type(error).__name__, error, exc_info=True
            )
            raise CheckoutSessionRejected(
                "Stripe a refusé la création de la session de paiement"
            ) from error
        except Exception as error:
            # P0-03F — défaut fermé dans le sens qui protège le client : ne
            # jamais conclure « aucune session » d'une réponse qu'on n'a pas lue.
            _LOGGER.warning(
                "checkout Stripe non concluant (%s) : %s",
                type(error).__name__,
                error,
                exc_info=True,
            )
            raise CheckoutSessionUncertain(
                "la création de la session de paiement n'a pas abouti de façon concluante"
            ) from error
        return CheckoutSession(
            session_id=session.id, url=_get(session, "url"), livemode=bool(session.livemode)
        )

    def create_portal_session(
        self, *, customer_id: str, return_url: str, configuration_id: str | None = None
    ) -> PortalSession:
        params: dict[str, Any] = {"customer": customer_id, "return_url": return_url}
        if configuration_id is not None:
            params["configuration"] = configuration_id
        session = self._client.billing_portal.sessions.create(params=params)
        return PortalSession(url=session.url)

    def fetch_subscription(self, subscription_id: str) -> StripeSubscriptionState | None:
        try:
            subscription = self._client.subscriptions.retrieve(
                subscription_id, params={"expand": ["items.data.price"]}
            )
        except self._stripe.InvalidRequestError:
            return None
        return subscription_state(subscription)

    # ── changement de formule (#29) ──────────────────────────────────────────
    #
    # Kivou garde un Product par formule — la modélisation que Stripe
    # recommande, et celle qui évite de migrer les abonnements LIVE. Le
    # Customer Portal ne sait alors PAS programmer un downgrade : il ne le fait
    # qu'entre Prices d'un MÊME Product. D'où ces quatre verbes côté serveur.

    def change_subscription_price(
        self, *, subscription_id: str, price_id: str, idempotency_key: str
    ) -> StripeSubscriptionState:
        """Monte la formule TOUT DE SUITE, en facturant le prorata.

        `payment_behavior="error_if_incomplete"` est la garantie qui compte :
        si le prorata ne peut pas être encaissé, Stripe REFUSE la modification
        et l'abonnement reste sur son ancienne formule. Sans cela, un paiement
        échoué laisserait le client avec les droits supérieurs et une facture
        impayée — exactement ce que §29 interdit.
        """
        subscription = self._client.subscriptions.retrieve(subscription_id)
        item = _first_item(subscription)
        if item is None:
            raise StripeGatewayError("abonnement sans ligne facturable")
        try:
            updated = self._client.subscriptions.update(
                subscription_id,
                params={
                    "items": [{"id": _get(item, "id"), "price": price_id}],
                    "proration_behavior": "always_invoice",
                    "payment_behavior": "error_if_incomplete",
                    "expand": ["items.data.price"],
                },
                options={"idempotency_key": idempotency_key},
            )
        except self._stripe.CardError as error:
            raise PlanChangePaymentFailed("prorata refusé") from error
        except self._stripe.InvalidRequestError as error:
            # Stripe rend `subscription_payment_intent_requires_action` ici
            # quand une authentification est nécessaire : sans elle, rien n'est
            # payé, donc rien n'est accordé.
            if _get(error, "code") in _PAYMENT_INCOMPLETE_CODES:
                raise PlanChangePaymentFailed("paiement du prorata incomplet") from error
            raise
        return subscription_state(updated)

    def schedule_subscription_price(
        self, *, subscription_id: str, price_id: str, idempotency_key: str
    ) -> StripeScheduledChange:
        """Programme la descente de formule à la FIN de la période déjà payée.

        Un `SubscriptionSchedule` créé `from_subscription` reprend la période
        courante en première phase ; la seconde porte la nouvelle formule.
        `end_behavior="release"` rend ensuite l'abonnement à lui-même : le
        schedule ne doit pas survivre à la transition qu'il existait pour faire.
        """
        subscription = self._client.subscriptions.retrieve(subscription_id)
        existing = _get(subscription, "schedule")
        schedule = (
            self._client.subscription_schedules.retrieve(
                _schedule_id(existing), params={"expand": _SCHEDULE_EXPAND}
            )
            if existing
            else self._client.subscription_schedules.create(
                params={"from_subscription": subscription_id, "expand": _SCHEDULE_EXPAND},
                options={"idempotency_key": idempotency_key},
            )
        )
        phases = _get(schedule, "phases") or []
        if not phases:
            raise StripeGatewayError("schedule sans phase courante")
        current = phases[0]
        updated = self._client.subscription_schedules.update(
            _get(schedule, "id"),
            params={
                "end_behavior": "release",
                "phases": [
                    {
                        "items": [
                            {"price": _phase_price(current), "quantity": 1},
                        ],
                        "start_date": _get(current, "start_date"),
                        "end_date": _get(current, "end_date"),
                    },
                    {"items": [{"price": price_id, "quantity": 1}], "iterations": 1},
                ],
                "expand": _SCHEDULE_EXPAND,
            },
        )
        return _scheduled_change(updated)

    def pending_plan_change(self, *, subscription_id: str) -> StripeScheduledChange | None:
        """Le changement programmé, s'il y en a un. `None` sinon — jamais une supposition."""
        try:
            subscription = self._client.subscriptions.retrieve(subscription_id)
        except self._stripe.InvalidRequestError:
            return None
        existing = _get(subscription, "schedule")
        if not existing:
            return None
        schedule = self._client.subscription_schedules.retrieve(
            _schedule_id(existing), params={"expand": _SCHEDULE_EXPAND}
        )
        return _scheduled_change(schedule)

    def release_pending_plan_change(self, *, subscription_id: str) -> None:
        """Annule le changement programmé en RELÂCHANT l'abonnement.

        `release` laisse l'abonnement en place et supprime les phases à venir.
        Annuler le schedule lui-même annulerait l'abonnement avec — la
        différence entre « je me ravise » et « je résilie ».
        """
        subscription = self._client.subscriptions.retrieve(subscription_id)
        existing = _get(subscription, "schedule")
        if not existing:
            return
        self._client.subscription_schedules.release(_schedule_id(existing))

    def verify_event(self, *, payload: bytes, signature: str, secret: str) -> StripeEvent:
        return verify_event(payload=payload, signature=signature, secret=secret)


def verify_event(*, payload: bytes, signature: str, secret: str) -> StripeEvent:
    """Vérifie la signature sur le corps BRUT, puis traduit l'événement.

    Le corps brut est non négociable : re-sérialiser le JSON produirait des
    octets différents et invaliderait une signature pourtant authentique.
    """
    import stripe

    if not signature:
        raise InvalidWebhookSignature("en-tête de signature absent")
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except (ValueError, stripe.SignatureVerificationError) as error:
        raise InvalidWebhookSignature("signature Stripe invalide") from error

    data_object = _get(_get(event, "data"), "object") or {}
    if not isinstance(data_object, dict):
        # `StripeObject` n'est ni un `dict` ni un mapping : `dict()` le
        # parcourrait comme une séquence, et `.items()` est intercepté par son
        # `__getattr__`. `to_dict()` est la conversion que le SDK expose.
        data_object = data_object.to_dict()
    created = _instant(_get(event, "created"))
    if created is None:
        # Aucune horloge de repli : un événement sans date ne peut pas être
        # ordonné, et §17 fait justement reposer la sûreté sur cette date.
        raise InvalidWebhookSignature("événement Stripe sans horodatage")
    return StripeEvent(
        event_id=_get(event, "id"),
        event_type=_get(event, "type"),
        created=created,
        livemode=bool(_get(event, "livemode", False)),
        object_id=data_object.get("id"),
        data_object=data_object,
    )
