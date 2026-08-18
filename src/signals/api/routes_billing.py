"""Les quatre lectures et écritures de facturation.

Le catalogue est public dans son contenu, jamais dans ses identifiants : un
`price_...` n'a rien à faire dans une réponse, et le laisser sortir inviterait
un client à le renvoyer.

`POST /billing/checkout` n'accepte qu'un plan et une devise. Le prix est choisi
par le serveur, depuis une clé de recherche approuvée (§32).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from signals.api.dependencies import current_session, enforce_origin, request_now
from signals.api.errors import api_error
from signals.billing import attempts, catalogue, checkout, discovery, service

router = APIRouter()

PlanChoice = Literal["essential", "pro", "scale"]
CurrencyChoice = Literal["chf", "eur"]


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
        grants = discovery.grants(connection, account_id=session.account_id)
        remaining = discovery.remaining_slots(connection, account_id=session.account_id)
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
        "payment_issue": state.payment_issue,
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

    created = checkout.open_checkout_session(
        gateway, configuration, prepared, account_id=account_id
    )

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
