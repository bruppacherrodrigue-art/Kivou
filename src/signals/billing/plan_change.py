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
from signals.billing.schema import billing_subscription

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


def _idempotency_key(
    kind: str,
    *,
    subscription_id: str,
    source: str,
    target: str,
    currency: str,
    sequence: int,
) -> str:
    """L'identité d'UNE opération de changement de formule.

    Deux exigences que le seul couple (départ, cible) ne peut pas tenir
    ensemble :

    - **stable** pour une nouvelle tentative de la même action — sinon un
      double-clic, un rechargement ou une reprise après plantage facturerait
      deux prorata ;
    - **différente** pour deux changements volontairement distincts — sinon
      Scale→Pro, puis Scale→Essential, puis Scale→Pro à nouveau réutiliserait
      la clé de la première opération. Stripe rendrait sa réponse en cache
      pendant 24 h, et le client resterait sur une formule dont il ne veut
      plus, **sans aucune erreur pour le signaler**.

    Le compteur tranche : il n'est incrémenté qu'APRÈS une opération réussie,
    dans la même transaction que l'état programmé. Une transaction annulée
    laisse donc le compteur inchangé, et la tentative suivante retrouve
    exactement la même clé — c'est là, et là seulement, que l'idempotence de
    Stripe est la dernière défense.

    La clé porte l'ABONNEMENT et non le compte : `synchronize_subscription`
    supprime la ligne d'un abonnement terminé et en insère une neuve, ce qui
    remet le compteur à zéro. Un compte qui résilie, se réabonne et redemande
    la même transition dans les 24 h retomberait sinon sur la clé de son
    abonnement précédent — et rien ne serait programmé sur le nouveau. Un
    identifiant d'abonnement Stripe, lui, n'est jamais réattribué.
    """
    return f"kivou-plan-{kind}:{subscription_id}:{sequence}:{source}->{target}:{currency}"


def _record_scheduled(
    connection: sa.Connection,
    *,
    account_id: str,
    plan_code: str,
    effective_at: dt.datetime | None,
    schedule_id: str | None,
    now: dt.datetime,
) -> None:
    """Écrit l'état programmé APRÈS confirmation du schedule par Stripe."""
    connection.execute(
        sa.update(billing_subscription)
        .where(billing_subscription.c.account_id == account_id)
        .values(
            scheduled_plan_code=plan_code,
            scheduled_plan_change_at=effective_at,
            stripe_schedule_id=schedule_id,
            plan_change_sequence=billing_subscription.c.plan_change_sequence + 1,
            updated_at=now,
        )
    )


def _clear_scheduled(
    connection: sa.Connection, *, account_id: str, now: dt.datetime, advance: bool
) -> None:
    """Efface l'annonce. `advance` numérote l'opération quand il y en a une."""
    values: dict[str, object] = {
        "scheduled_plan_code": None,
        "scheduled_plan_change_at": None,
        "stripe_schedule_id": None,
        "updated_at": now,
    }
    if advance:
        values["plan_change_sequence"] = billing_subscription.c.plan_change_sequence + 1
    connection.execute(
        sa.update(billing_subscription)
        .where(billing_subscription.c.account_id == account_id)
        .values(**values)
    )


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

    # Rejeu exact d'un changement DÉJÀ programmé : rien ne part chez Stripe.
    # C'est la première défense contre le double-clic, et elle ne dépend pas de
    # la fenêtre d'idempotence de 24 h.
    if subscription.scheduled_plan_code == target_plan:
        return PlanChangeOutcome(
            EFFECT_SCHEDULED, target_plan, subscription.scheduled_plan_change_at
        )

    current_plan = subscription.plan_code
    if target_plan == current_plan:
        raise PlanChangeSamePlan(f"déjà sur la formule {target_plan}")

    currency = subscription.currency
    price_id = _authorised_price(gateway, plan_code=target_plan, currency=currency)
    sequence = subscription.plan_change_sequence

    if catalogue.plan_rank(target_plan) > catalogue.plan_rank(current_plan):
        if subscription.scheduled_plan_code is not None:
            # Une descente programmée deviendrait caduque : la laisser courir
            # ferait redescendre au terme un client qui vient de monter.
            gateway.release_pending_plan_change(subscription_id=subscription.stripe_subscription_id)
        state = gateway.change_subscription_price(
            subscription_id=subscription.stripe_subscription_id,
            price_id=price_id,
            idempotency_key=_idempotency_key(
                "change",
                subscription_id=subscription.stripe_subscription_id,
                source=current_plan,
                target=target_plan,
                currency=currency,
                sequence=sequence,
            ),
        )
        # L'état vient de la RÉPONSE de Stripe, pas d'une supposition locale :
        # même discipline que le webhook, et la seule qui n'accorde un droit
        # qu'après confirmation.
        service.synchronize_subscription(
            connection,
            state,
            account_id=account_id,
            event_created_at=now,
            expect_livemode=expect_livemode,
            now=now,
        )
        _clear_scheduled(connection, account_id=account_id, now=now, advance=True)
        return PlanChangeOutcome(EFFECT_IMMEDIATE, target_plan, None)

    scheduled = gateway.schedule_subscription_price(
        subscription_id=subscription.stripe_subscription_id,
        price_id=price_id,
        idempotency_key=_idempotency_key(
            "schedule",
            subscription_id=subscription.stripe_subscription_id,
            source=current_plan,
            target=target_plan,
            currency=currency,
            sequence=sequence,
        ),
    )
    effective_at = scheduled.effective_at if scheduled else None
    # Les droits COURANTS ne bougent pas : la formule payée tient jusqu'au
    # terme. Seule l'ANNONCE est écrite ici.
    _record_scheduled(
        connection,
        account_id=account_id,
        plan_code=target_plan,
        effective_at=effective_at,
        schedule_id=scheduled.schedule_id if scheduled else None,
        now=now,
    )
    return PlanChangeOutcome(EFFECT_SCHEDULED, target_plan, effective_at)


def cancel_scheduled_plan_change(
    connection: sa.Connection, gateway: StripeGateway, *, account_id: str, now: dt.datetime
) -> None:
    """Se raviser : la formule programmée est abandonnée, l'abonnement reste."""
    subscription = _changeable(connection, account_id=account_id)
    if subscription.scheduled_plan_code is None:
        raise PlanChangeNoneScheduled("aucun changement programmé")
    gateway.release_pending_plan_change(subscription_id=subscription.stripe_subscription_id)
    _clear_scheduled(connection, account_id=account_id, now=now, advance=True)


def scheduled_plan_change(
    connection: sa.Connection, *, account_id: str
) -> dict[str, object] | None:
    """Le changement programmé, tel que l'écran peut l'annoncer. `None` sinon.

    Lecture PUREMENT locale : `/billing/status` est consulté deux fois par le
    tableau de bord, et le faire dépendre d'un appel Stripe y importait la
    latence — et la disponibilité — d'un tiers pour afficher des droits déjà
    payés.
    """
    subscription = service.current_subscription(connection, account_id=account_id)
    if subscription is None or not subscription.is_open:
        return None
    if subscription.scheduled_plan_code is None:
        return None
    return {
        "plan_code": subscription.scheduled_plan_code,
        "effective_at": (
            None
            if subscription.scheduled_plan_change_at is None
            else subscription.scheduled_plan_change_at.isoformat()
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
