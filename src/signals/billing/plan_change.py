"""Changer de formule — sans jamais ouvrir un second abonnement (#29).

Pourquoi un flux serveur plutôt que le Customer Portal
──────────────────────────────────────────────────────
Kivou conserve **un Product Stripe par formule** : c'est la modélisation que
Stripe recommande, et restructurer le catalogue imposerait de migrer les
abonnements LIVE. Or le Customer Portal ne programme un downgrade qu'entre
Prices d'un **même Product** — il ne peut donc pas descendre d'Essential à Pro
chez Kivou. L'activer quand même donnerait des downgrades **immédiats** : le
client perdrait la période qu'il a déjà payée.

Le sens du changement décide de l'effet
───────────────────────────────────────
    monter   →  immédiat, prorata facturé, AUCUN droit si le paiement échoue
    descendre →  programmé à la fin de la période déjà payée

Ce module ne réimplémente aucune autorité existante
───────────────────────────────────────────────────
Il ne redécide pas si un compte peut agir : `service.billing_action()` le sait
déjà, et c'est la seule autorité. Recopier ici sa clause de défaut fermé
créerait une seconde règle à maintenir, fausse le jour où Stripe ajoutera un
statut. Le Price, lui, est résolu depuis le catalogue Kivou — jamais reçu du
navigateur.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.billing import catalogue, service
from signals.billing.gateway import PlanChangePaymentFailed, StripeGateway

#: Ce que le serveur rend au client, et rien de plus : aucun identifiant Stripe.
EFFECT_IMMEDIATE = "immediate"
EFFECT_SCHEDULED = "scheduled"


class PlanChangeUnavailable(service.BillingError):
    """Ce compte ne peut pas changer de formule maintenant.

    Volontairement indistinct : `past_due`, abonnement absent, prix hors
    catalogue et devise inconnue mènent tous ici. Détailler renseignerait sur
    l'état de facturation d'un compte à qui l'on n'a rien à expliquer par ce
    canal — l'écran de facturation, lui, dit déjà quoi faire via `billing_action`.
    """

    code = "plan_change_unavailable"


class PlanChangeSamePlan(service.BillingError):
    """La formule demandée est déjà celle du contrat."""

    code = "plan_change_same_plan"


class PlanChangeNoneScheduled(service.BillingError):
    """Rien n'est programmé : il n'y a donc rien à annuler."""

    code = "plan_change_none_scheduled"


@dataclasses.dataclass(frozen=True)
class PlanChangeOutcome:
    """Le résultat d'un changement, tel que le client peut le lire."""

    effect: str
    plan_code: str
    #: `None` pour un effet immédiat : il n'y a pas d'échéance à annoncer.
    effective_at: dt.datetime | None

    def as_payload(self) -> dict[str, object]:
        return {
            "effect": self.effect,
            "plan_code": self.plan_code,
            "effective_at": None if self.effective_at is None else self.effective_at.isoformat(),
        }


def _changeable(connection: sa.Connection, *, account_id: str):
    """L'abonnement sur lequel un changement est SÛR, ou une erreur.

    L'ordre des questions est la garantie, et il délègue :
    `billing_action` a déjà tranché l'existence, le statut, le prix hors
    catalogue et l'ouvrabilité du portail.
    """
    if service.billing_action(connection, account_id=account_id) != (
        service.ACTION_MANAGE_SUBSCRIPTION
    ):
        raise PlanChangeUnavailable("aucun abonnement gérable pour ce compte")

    subscription = service.current_subscription(connection, account_id=account_id)
    if subscription is None or subscription.plan_code is None:
        # `billing_action` l'aurait déjà écarté ; la garde reste, parce qu'un
        # défaut fermé ne se repose pas sur la vigilance d'un autre module.
        raise PlanChangeUnavailable("abonnement introuvable")
    if subscription.currency not in catalogue.CURRENCIES:
        # La devise du contrat est CONSERVÉE : sans elle, aucun Price autorisé
        # n'est résoluble, et en choisir une reviendrait à changer le prix.
        raise PlanChangeUnavailable("devise du contrat inconnue")
    return subscription


def _authorised_price(gateway: StripeGateway, *, plan_code: str, currency: str) -> str:
    """Le Price Kivou de cette formule dans CETTE devise. Jamais celui du client.

    Le navigateur n'envoie qu'un nom de formule ; la clé de recherche vient du
    catalogue versionné, et Stripe n'a le droit de rendre que le prix qu'elle
    désigne. Un prix absent est un refus, pas un repli.
    """
    lookup_key = catalogue.lookup_key_for(plan_code, currency)
    price = gateway.price_for_lookup_key(lookup_key)
    if price is None or not price.active:
        raise PlanChangeUnavailable(f"aucun prix actif pour {lookup_key}")
    return price.price_id


def request_plan_change(
    connection: sa.Connection,
    gateway: StripeGateway,
    *,
    account_id: str,
    target_plan: str,
    now: dt.datetime,
    expect_livemode: bool,
) -> PlanChangeOutcome:
    """Monte ou descend la formule d'un compte déjà abonné."""
    subscription = _changeable(connection, account_id=account_id)
    current_plan = subscription.plan_code
    if target_plan == current_plan:
        raise PlanChangeSamePlan(f"déjà sur la formule {target_plan}")

    currency = subscription.currency
    price_id = _authorised_price(gateway, plan_code=target_plan, currency=currency)
    going_up = catalogue.plan_rank(target_plan) > catalogue.plan_rank(current_plan)

    if going_up:
        # La clé d'idempotence porte la CIBLE : deux clics sur « passer à Pro »
        # ne facturent qu'un prorata, alors qu'un changement d'avis vers Scale
        # reste une opération distincte.
        state = gateway.change_subscription_price(
            subscription_id=subscription.stripe_subscription_id,
            price_id=price_id,
            idempotency_key=f"plan-change:{account_id}:{target_plan}:{currency}",
        )
        # L'état vient de la RÉPONSE de Stripe, pas d'une supposition locale :
        # c'est la même discipline que le webhook, et la seule qui n'accorde un
        # droit qu'après confirmation.
        service.synchronize_subscription(
            connection,
            state,
            account_id=account_id,
            event_created_at=now,
            expect_livemode=expect_livemode,
            now=now,
        )
        return PlanChangeOutcome(EFFECT_IMMEDIATE, target_plan, None)

    scheduled = gateway.schedule_subscription_price(
        subscription_id=subscription.stripe_subscription_id,
        price_id=price_id,
        idempotency_key=f"plan-schedule:{account_id}:{target_plan}:{currency}",
    )
    # Rien n'est écrit localement : les droits COURANTS restent ceux de la
    # formule payée jusqu'au terme. C'est le webhook de bascule qui les changera.
    return PlanChangeOutcome(
        EFFECT_SCHEDULED, target_plan, scheduled.effective_at if scheduled else None
    )


def cancel_scheduled_plan_change(
    connection: sa.Connection, gateway: StripeGateway, *, account_id: str
) -> None:
    """Se raviser : la formule programmée est abandonnée, l'abonnement reste."""
    subscription = _changeable(connection, account_id=account_id)
    if scheduled_plan_change(connection, gateway, account_id=account_id) is None:
        raise PlanChangeNoneScheduled("aucun changement programmé")
    gateway.release_pending_plan_change(subscription_id=subscription.stripe_subscription_id)


def scheduled_plan_change(
    connection: sa.Connection, gateway: StripeGateway, *, account_id: str
) -> dict[str, object] | None:
    """Le changement programmé, tel que l'écran peut l'annoncer. `None` sinon.

    Traduit par le catalogue Kivou : une clé de recherche inconnue ne rend
    AUCUNE formule, et l'écran n'annonce alors rien plutôt qu'une supposition.
    """
    subscription = service.current_subscription(connection, account_id=account_id)
    if subscription is None or not subscription.is_open:
        return None
    scheduled = gateway.pending_plan_change(subscription_id=subscription.stripe_subscription_id)
    if scheduled is None:
        return None
    resolved = catalogue.plan_for_lookup_key(scheduled.lookup_key)
    if resolved is None:
        return None
    plan_code, _currency = resolved
    return {
        "plan_code": plan_code,
        "effective_at": (
            None if scheduled.effective_at is None else scheduled.effective_at.isoformat()
        ),
    }


__all__ = [
    "EFFECT_IMMEDIATE",
    "EFFECT_SCHEDULED",
    "PlanChangeNoneScheduled",
    "PlanChangeOutcome",
    "PlanChangePaymentFailed",
    "PlanChangeSamePlan",
    "PlanChangeUnavailable",
    "cancel_scheduled_plan_change",
    "request_plan_change",
    "scheduled_plan_change",
]
