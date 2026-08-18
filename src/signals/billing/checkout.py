"""L'ouverture d'un paiement — et tout ce que le client n'a PAS le droit de choisir.

Le client choisit un plan et une devise. Kivou choisit le prix (§32)
───────────────────────────────────────────────────────────────────
Accepter un `price_id` du navigateur reviendrait à laisser l'acheteur fixer
le montant : il suffirait d'envoyer l'identifiant d'un prix à 1 franc pour
obtenir Scale. Le schéma d'entrée n'a donc aucun champ de prix, et le
serveur résout le prix depuis une **clé de recherche** approuvée.

Les URL de retour viennent de la configuration, pas de la requête
────────────────────────────────────────────────────────────────
Une URL de succès fournie par le client transformerait le paiement en
redirection ouverte, et l'écran de retour en outil d'hameçonnage.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.billing import attempts, catalogue, service
from signals.billing.gateway import CheckoutSession, PortalSession, StripeGateway


@dataclasses.dataclass(frozen=True)
class CheckoutConfiguration:
    """Ce que Stripe exige pour ouvrir un paiement, entièrement côté serveur."""

    success_url: str
    cancel_url: str
    portal_return_url: str
    automatic_tax: bool = False
    #: §30 — le mode attendu. Un objet du mauvais mode fait échouer l'appel plutôt
    #: que de mélanger silencieusement des données de test et de production.
    livemode: bool = False
    founding_coupon_id: str | None = None
    #: R1 §9 — `None` = configuration par défaut du compte Stripe.
    portal_configuration_id: str | None = None


@dataclasses.dataclass(frozen=True)
class PreparedCheckout:
    """Une place réservée, prête à devenir une session Stripe."""

    attempt: attempts.StoredAttempt
    price_id: str
    customer_id: str
    coupon_id: str | None


def prepare_checkout(
    connection: sa.Connection,
    gateway: StripeGateway,
    configuration: CheckoutConfiguration,
    *,
    account_id: str,
    plan_code: str,
    currency: str,
    now: dt.datetime,
    founding: bool = False,
) -> PreparedCheckout:
    """Étape 1 — tout ce qui doit être fait AVANT d'appeler Stripe Checkout.

    La transaction de l'appelant doit être validée avant l'étape 2 : une
    réservation non validée ne protège de rien.
    """
    if plan_code not in catalogue.PLAN_CODES:
        raise service.UnknownPlanRequested(f"plan inconnu : {plan_code!r}")
    if plan_code not in catalogue.PURCHASABLE_PLANS:
        # Discovery est un droit interne : il n'a pas de prix à payer.
        raise service.PlanNotPurchasable(f"plan non achetable : {plan_code!r}")

    # §5 — une tentative périmée est marquée telle quelle avant tout contrôle :
    # elle ne doit pas bloquer un compte au-delà de sa propre durée de vie.
    attempts.expire_stale(connection, account_id=account_id, now=now)

    existing = service.current_subscription(connection, account_id=account_id)
    if existing is not None and existing.is_open:
        # R1 §3 — le blocage porte sur l'EXISTENCE d'un abonnement, pas sur
        # l'accès qu'il ouvre. Un abonnement impayé ne donne aucun droit, mais
        # il est facturé : en ouvrir un second facturerait deux fois un client
        # qui n'a rien demandé de tel. Seuls `canceled` et `incomplete_expired`
        # libèrent la place, et tout statut inconnu bloque (défaut fermé).
        raise service.AlreadySubscribed(
            f"le compte porte déjà un abonnement Stripe ({existing.status})"
        )

    lookup_key = catalogue.lookup_key_for(plan_code, currency)
    price = gateway.price_for_lookup_key(lookup_key)
    if price is None or not price.active:
        raise service.PriceNotConfigured(f"aucun prix actif pour la clé {lookup_key!r}")
    service.require_stripe_mode(price.livemode, configuration.livemode, "price")
    if price.currency != currency:
        raise service.PriceNotConfigured(
            f"le prix {lookup_key!r} est en {price.currency!r}, pas en {currency!r}"
        )

    coupon_id = None
    if founding:
        if plan_code != catalogue.FOUNDING_PLAN_CODE:
            raise service.FoundingNotAvailable("l'offre fondateur porte sur le plan Pro")
        if configuration.founding_coupon_id is None:
            raise service.FoundingNotAvailable("aucune remise fondateur configurée")
        if not service.founding_available(connection, account_id=account_id):
            raise service.FoundingNotAvailable("offre fondateur épuisée ou déjà utilisée")
        coupon_id = configuration.founding_coupon_id

    customer_id = service.ensure_stripe_customer(
        connection,
        gateway,
        account_id=account_id,
        expect_livemode=configuration.livemode,
        now=now,
    )
    # La réservation est la DERNIÈRE écriture avant Stripe, et la base en est
    # l'arbitre : deux requêtes concurrentes, une seule réservation (§9).
    attempt = attempts.reserve(
        connection, account_id=account_id, plan_code=plan_code, currency=currency, now=now
    )
    return PreparedCheckout(
        attempt=attempt,
        price_id=price.price_id,
        customer_id=customer_id,
        coupon_id=coupon_id,
    )


def open_checkout_session(
    gateway: StripeGateway,
    configuration: CheckoutConfiguration,
    prepared: PreparedCheckout,
    *,
    account_id: str,
) -> CheckoutSession:
    """Étape 2 — l'appel Stripe, hors transaction.

    La clé d'idempotence vient de la tentative PERSISTÉE : une reprise après
    plantage rejoue la même clé, et Stripe rend la même session plutôt que d'en
    créer une seconde (§3, §4).
    """
    return gateway.create_checkout_session(
        customer_id=prepared.customer_id,
        price_id=prepared.price_id,
        account_id=account_id,
        success_url=configuration.success_url,
        cancel_url=configuration.cancel_url,
        automatic_tax=configuration.automatic_tax,
        coupon_id=prepared.coupon_id,
        expires_at=prepared.attempt.expires_at,
        idempotency_key=prepared.attempt.idempotency_key,
    )


def open_portal(
    connection: sa.Connection,
    gateway: StripeGateway,
    configuration: CheckoutConfiguration,
    *,
    account_id: str,
) -> PortalSession:
    """Le portail Stripe du compte. Sans client Stripe, il n'y a rien à gérer."""
    customer_id = service.stripe_customer_id(connection, account_id=account_id)
    if customer_id is None:
        raise service.NoBillingCustomer("aucun client Stripe pour ce compte")
    return gateway.create_portal_session(
        customer_id=customer_id,
        return_url=configuration.portal_return_url,
        configuration_id=configuration.portal_configuration_id,
    )
