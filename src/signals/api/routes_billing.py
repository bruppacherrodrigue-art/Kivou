"""Les quatre lectures et écritures de facturation.

Le catalogue est public dans son contenu, jamais dans ses identifiants : un
`price_...` n'a rien à faire dans une réponse, et le laisser sortir inviterait
un client à le renvoyer.

`POST /billing/checkout` n'accepte qu'un plan et une devise. Le prix est choisi
par le serveur, depuis une clé de recherche approuvée (§32).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from signals.api.dependencies import current_session, enforce_origin, request_now
from signals.api.errors import api_error
from signals.billing import attempts, catalogue, checkout, discovery, plan_change, service
from signals.billing import gateway as gateway_errors

router = APIRouter()
logger = logging.getLogger(__name__)

PlanChoice = Literal["essential", "pro", "scale"]
CurrencyChoice = Literal["chf", "eur"]


class PlanChangeRequest(BaseModel):
    """§32 — une FORMULE, jamais un prix.

    `extra="forbid"` : un `price_id` glissé dans le corps fait échouer la
    requête en 422 au lieu d'être ignoré en silence. Le serveur résout
    lui-même le Price autorisé depuis la formule et la devise DU CONTRAT.
    """

    model_config = ConfigDict(extra="forbid")

    plan: PlanChoice


class CheckoutRequest(BaseModel):
    """§32 — `extra="forbid"` : un `price_id` glissé dans le corps fait échouer
    la requête en 422 au lieu d'être silencieusement ignoré. Le client choisit
    un plan et une devise ; le montant n'est pas négociable côté navigateur."""

    model_config = ConfigDict(extra="forbid")

    plan: PlanChoice
    currency: CurrencyChoice


def _billing_gateway(request: Request):
    gateway = getattr(request.app.state, "stripe_gateway", None)
    if gateway is None:
        raise api_error(503, "billing_unavailable", "facturation non configurée")
    return gateway


def _configuration(request: Request) -> checkout.CheckoutConfiguration:
    config = request.app.state.config
    # CLOSEOUT §3 — sans URL de retour, on ne SAIT PAS où renvoyer le client.
    # Ouvrir quand même un paiement le laisserait au bout du parcours Stripe
    # sans chemin de retour, ou le renverrait vers le domaine qu'un défaut aurait
    # choisi à sa place. Le service se déclare indisponible : c'est exact, et
    # c'est réparable par configuration.
    if not config.billing_return_urls_configured:
        raise api_error(503, "billing_unavailable", "facturation non configurée")
    return checkout.CheckoutConfiguration(
        success_url=config.stripe_success_url,
        cancel_url=config.stripe_cancel_url,
        portal_return_url=config.stripe_portal_return_url,
        automatic_tax=config.stripe_automatic_tax,
        livemode=config.stripe_livemode,
        founding_coupon_id=config.stripe_founding_coupon_id,
        portal_configuration_id=config.stripe_portal_configuration_id,
    )


@router.get("/billing/plans")
def list_plans() -> dict[str, Any]:
    """Le catalogue public. Aucun identifiant Stripe, aucun coupon, aucun secret."""
    return {
        "catalogue_version": catalogue.CATALOGUE_VERSION,
        "billing_interval": "month",
        "currencies": list(catalogue.CURRENCIES),
        "plans": list(catalogue.public_catalogue()),
    }


@router.get("/billing/status")
def billing_status(request: Request) -> dict[str, Any]:
    """L'état de facturation du compte — un compte Discovery est un état valide."""
    now = request_now(request)
    with request.app.state.engine.connect() as connection:
        session = current_session(request, connection, now)
        state = service.billing_state(connection, account_id=session.account_id)
        # P0-03A — l'action sûre est décidée ICI. Le navigateur ne doit pas
        # avoir à recopier `TERMINAL_STATUSES` pour savoir si proposer un
        # paiement facturerait un compte qui en porte déjà un.
        action = service.billing_action(connection, account_id=session.account_id)
        grants = discovery.grants(connection, account_id=session.account_id)
        remaining = discovery.remaining_slots(connection, account_id=session.account_id)
        # #29 — l'écran doit pouvoir dire « vous descendrez le 1er » sans
        # laisser croire que c'est déjà fait : `plan_code` ci-dessus reste la
        # formule PAYÉE, celle qui ouvre les droits jusqu'au terme.
        # #29 — l'écran doit pouvoir dire « vous descendrez le 1er » sans
        # laisser croire que c'est déjà fait : `plan_code` ci-dessus reste la
        # formule PAYÉE, celle qui ouvre les droits jusqu'au terme.
        #
        # Lecture LOCALE. L'état programmé est persisté à sa création et
        # réconcilié au webhook de bascule : cette réponse ne dépend d'aucun
        # appel réseau, et le tableau de bord peut la consulter deux fois sans
        # importer la latence de Stripe dans un parcours financier.
        pending = plan_change.scheduled_plan_change(connection, account_id=session.account_id)
        over_limit = service.over_limit_icps(
            connection,
            account_id=session.account_id,
            limit=state.entitlements.max_active_icps,
        )
    return {
        "plan_code": state.plan_code,
        "offer_code": state.offer_code,
        "currency": state.currency,
        "subscription_status": state.subscription_status,
        "cancel_at_period_end": state.cancel_at_period_end,
        "current_period_end": _iso(state.current_period_end),
        # P0-03G — la DATE d'échéance, telle que Stripe la publie. Le booléen
        # ci-dessus ne la remplace pas : il ne dit que « ça tombe en fin de
        # période », ce qui est faux dès que Stripe planifie une autre date.
        "scheduled_cancellation_at": _iso(state.scheduled_cancellation_at),
        "payment_issue": state.payment_issue,
        "billing_action": action,
        "scheduled_plan_change": pending,
        "entitlements": catalogue.customer_safe_entitlements(state.entitlements),
        "discovery": {
            "granted_signal_count": len(grants),
            "remaining_slots": remaining,
            "limit": catalogue.DISCOVERY_GRANT_LIMIT,
        },
        # §23 — un compte redescendu de plan garde ses profils ; il doit
        # seulement savoir lesquels ne servent plus, et trancher lui-même.
        "target_icps_over_limit": list(over_limit),
        "policy": {"billing": service.BILLING_POLICY_VERSION},
    }


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@router.post("/billing/plan")
def change_plan(payload: PlanChangeRequest, request: Request) -> dict[str, Any]:
    """Monte ou descend la formule d'un compte DÉJÀ abonné.

    Ce n'est pas un point d'entrée d'achat : sans abonnement gérable, il refuse.
    Ouvrir un paiement ici créerait le second abonnement que tout le reste du
    module s'emploie à rendre impossible.
    """
    enforce_origin(request, request.app.state.config)
    gateway = _billing_gateway(request)
    now = request_now(request)
    config = request.app.state.config

    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        try:
            outcome = plan_change.request_plan_change(
                connection,
                gateway,
                account_id=session.account_id,
                target_plan=payload.plan,
                now=now,
                expect_livemode=config.stripe_livemode,
            )
        except gateway_errors.PlanChangePaymentFailed as error:
            # 402 — le prorata n'a pas été encaissé. Stripe a refusé la
            # modification, donc l'abonnement est resté sur son ancienne
            # formule : aucun droit supérieur n'a été accordé.
            raise api_error(
                402,
                "plan_change_payment_failed",
                "le paiement du changement de formule a échoué",
            ) from error
        except (plan_change.PlanChangeSamePlan, plan_change.PlanChangeUnavailable) as error:
            raise api_error(409, error.code, "changement de formule impossible") from error

    return outcome.as_payload()


@router.delete("/billing/plan")
def cancel_plan_change(request: Request) -> dict[str, Any]:
    """Annule un changement PROGRAMMÉ. L'abonnement, lui, reste."""
    enforce_origin(request, request.app.state.config)
    gateway = _billing_gateway(request)
    now = request_now(request)

    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        try:
            plan_change.cancel_scheduled_plan_change(
                connection, gateway, account_id=session.account_id, now=now
            )
        except (
            plan_change.PlanChangeNoneScheduled,
            plan_change.PlanChangeUnavailable,
        ) as error:
            raise api_error(409, error.code, "aucun changement à annuler") from error

    return {"cancelled": True}


@router.post("/billing/checkout")
def start_checkout(payload: CheckoutRequest, request: Request) -> dict[str, Any]:
    """Ouvre une session Stripe Checkout pour ce compte."""
    enforce_origin(request, request.app.state.config)
    gateway = _billing_gateway(request)
    now = request_now(request)
    configuration = _configuration(request)

    # Closeout §2 — DEUX transactions, et l'ordre est la garantie. La première
    # réserve la place et se valide ; seulement ensuite Stripe est appelé.
    # Réserver après l'appel laisserait deux requêtes concurrentes ouvrir deux
    # sessions, et la seconde ne serait rattrapée qu'après le débit du client.
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        account_id = session.account_id
        # §33 — l'éligibilité fondateur est une propriété du COMPTE, jamais un
        # paramètre de requête. Aucun `?founding=true` n'existe.
        founding = (
            payload.plan == catalogue.FOUNDING_PLAN_CODE
            and configuration.founding_coupon_id is not None
            and service.founding_available(connection, account_id=account_id)
            and _founding_eligible(request, account_id)
        )
        try:
            prepared = checkout.prepare_checkout(
                connection,
                gateway,
                configuration,
                account_id=account_id,
                plan_code=payload.plan,
                currency=payload.currency,
                now=now,
                founding=founding,
            )
        except service.AlreadySubscribed as error:
            raise api_error(
                409,
                error.code,
                "ce compte a déjà un abonnement actif ; utilisez le portail de facturation",
            ) from error
        except attempts.CheckoutInProgress as error:
            # §8 — la session existante n'est pas annulée : elle expirera, et le
            # compte pourra alors recommencer, éventuellement sur un autre plan.
            raise api_error(
                409,
                error.code,
                "un paiement est déjà en cours pour ce compte",
                expires_at=error.attempt.expires_at.isoformat(),
            ) from error
        except service.BillingError as error:
            raise api_error(422, error.code, "impossible d'ouvrir le paiement") from error

    try:
        created = checkout.open_checkout_session(
            gateway, configuration, prepared, account_id=account_id
        )
    except gateway_errors.CheckoutSessionRejected as error:
        # P0-03F — Stripe a refusé la REQUÊTE : aucune session n'a pu naître, la
        # place est donc libérée tout de suite. Sans cela, un défaut de
        # paramètres bloquait le compte trente minutes en 409.
        with request.app.state.engine.begin() as connection:
            attempts.fail_attempt(
                connection,
                account_id=account_id,
                attempt_id=prepared.attempt.attempt_id,
                now=now,
            )
        raise api_error(
            502, "checkout_rejected", "le prestataire de paiement a refusé d'ouvrir la session"
        ) from error
    except gateway_errors.CheckoutSessionUncertain as error:
        # La réponse manque, pas forcément la session : la tentative RESTE
        # `creating`, et un rejeu du même plan rejouera la même clé (§3, §4).
        raise api_error(
            503, "checkout_unavailable", "le paiement n'a pas pu être ouvert ; réessayez"
        ) from error

    with request.app.state.engine.begin() as connection:
        attempts.record_session(
            connection,
            account_id=account_id,
            attempt_id=prepared.attempt.attempt_id,
            stripe_checkout_session_id=created.session_id,
            now=now,
        )

    return {"checkout_url": created.url, "plan": payload.plan, "currency": payload.currency}


def _founding_eligible(request: Request, account_id: str) -> bool:
    """§33 — la liste des comptes éligibles vient de la configuration serveur.

    Aucun code promotionnel public, aucun paramètre d'URL : l'offre fondateur
    s'attribue, elle ne se réclame pas.
    """
    eligible = getattr(request.app.state, "founding_accounts", frozenset())
    return account_id in eligible


@router.post("/billing/portal")
def open_portal(request: Request) -> dict[str, Any]:
    """Une session du portail Stripe — gestion du moyen de paiement, factures,
    résiliation. Kivou ne reconstruit aucun de ces écrans."""
    enforce_origin(request, request.app.state.config)
    gateway = _billing_gateway(request)
    now = request_now(request)
    configuration = _configuration(request)

    with request.app.state.engine.connect() as connection:
        session = current_session(request, connection, now)
        try:
            portal = checkout.open_portal(
                connection, gateway, configuration, account_id=session.account_id
            )
        except service.NoBillingCustomer as error:
            raise api_error(
                409, error.code, "aucun dossier de facturation pour ce compte"
            ) from error
    return {"portal_url": portal.url}
