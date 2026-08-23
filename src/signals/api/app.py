"""L'application Kivou — une seule, synchrone, sans infrastructure externe.

FastAPI a été retenu parce que le dépôt est déjà en pydantic v2 : les modèles de
requête et de réponse sont écrits dans la même technologie que le modèle
canonique, et il n'y a donc pas deux façons de décrire une donnée. Le client de
test appelle l'application en direct — aucun serveur, aucun port, aucun conteneur
pour exécuter la suite.

Les points d'entrée sont **synchrones** (`def`, pas `async def`) : SQLAlchemy
Core est synchrone, et une façade asynchrone au-dessus d'un pilote bloquant
n'apporterait qu'un faux sentiment de concurrence.

    Ce que cette application n'est pas
    ──────────────────────────────────
    Ni un service d'identité séparé, ni une passerelle, ni un bus d'événements.
    Une application, une base, un proxy inverse devant. C'est ce qu'un VPS sait
    faire tourner sans orchestrateur.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from signals.api.config import ApiConfig
from signals.api.routes_attribution import router as attribution_router
from signals.api.routes_auth import router as auth_router
from signals.api.routes_billing import router as billing_router
from signals.api.routes_feedback import router as feedback_router
from signals.api.routes_icp import router as icp_router
from signals.api.routes_notifications import router as notifications_router
from signals.api.routes_signals import router as signals_router
from signals.api.routes_webhooks import router as webhooks_router
from signals.cockpit.api import router as cockpit_router
from signals.cockpit.service import WeeklyCommercialCockpitService
from signals.conversion.milestones import ConversionMilestoneService
from signals.conversion.service import ConversionAttributionService
from signals.conversion.token import AttributionTokenKeyring
from signals.operations.api import router as operations_router
from signals.operations.service import OperationsReadService


class _NullDelivery:
    """Aucune remise. Le jeton est produit, personne ne le reçoit."""

    def deliver(self, *, email: str, locale: str, reset_token: str) -> None:
        return None


def create_app(
    engine: sa.Engine,
    config: ApiConfig | None = None,
    *,
    now_override: Callable[[], dt.datetime] | None = None,
    password_reset_delivery: object | None = None,
    stripe_gateway: object | None = None,
    instantly_webhook_service: object | None = None,
    conversion_attribution_service: object | None = None,
    conversion_milestone_service: object | None = None,
    cockpit_service: object | None = None,
    operations_service: object | None = None,
    founding_accounts: frozenset[str] = frozenset(),
) -> FastAPI:
    """Construit l'application autour d'un moteur déjà configuré.

    `now_override` n'est pas une commodité de test déguisée : le temps est une
    entrée du système, et lui donner une porte explicite vaut mieux que de
    remplacer une horloge par un correctif de test.
    """
    app = FastAPI(title="Kivou", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.engine = engine
    app.state.config = config or ApiConfig.from_environment()
    app.state.now_override = now_override
    # §11 — la frontière par où sortira un jour un e-mail transactionnel.
    # Aucun fournisseur n'est intégré : par défaut, le jeton n'est remis à
    # personne, ce qui vaut mieux qu'un envoi silencieusement raté.
    app.state.password_reset_delivery = password_reset_delivery or _NullDelivery()
    # SPEC-013 — la passerelle Stripe est injectée. Absente, les points d'entrée
    # de facturation répondent 503 : mieux vaut un service annoncé indisponible
    # qu'une application qui démarre en croyant pouvoir encaisser.
    app.state.stripe_gateway = stripe_gateway
    # SPEC-026 transport ingress is injected; app construction never contacts Instantly.
    app.state.instantly_webhook_service = instantly_webhook_service
    # SPEC-028 attribution is injected and performs no provider/network I/O.
    # None is the fail-closed repository default: the public link route returns
    # a fixed not-found response and signup remains normally unattributed.
    if conversion_attribution_service is None and app.state.config.attribution_hmac_key:
        key_version = app.state.config.attribution_hmac_key_version
        if key_version is None:  # guarded by ApiConfig.from_environment; explicit configs fail closed
            raise ValueError("attribution key version is required")
        conversion_attribution_service = ConversionAttributionService(
            engine,
            AttributionTokenKeyring(
                current_key_version=key_version,
                keys={key_version: app.state.config.attribution_hmac_key},
            ),
        )
    app.state.conversion_attribution_service = conversion_attribution_service
    # Pure local reconciliation; it only reads/writes the caller's database
    # transaction and does not start a worker or contact Stripe.
    app.state.conversion_milestone_service = (
        conversion_milestone_service or ConversionMilestoneService(engine)
    )
    # SPEC-030 is a local read model. Construction performs no query, worker start,
    # provider I/O, or report persistence.
    app.state.cockpit_service = cockpit_service or WeeklyCommercialCockpitService(engine)
    # SPEC-031 is a local read model; the default observes conservative,
    # unconfigured runtime evidence and never starts Hermes or a worker.
    app.state.operations_service = operations_service or OperationsReadService(
        engine, environment_identity=app.state.config.acquisition_environment
    )
    # §33 — l'éligibilité fondateur est une liste serveur, jamais une saisie.
    app.state.founding_accounts = frozenset(founding_accounts)

    app.include_router(auth_router)
    app.include_router(attribution_router)
    app.include_router(icp_router)
    app.include_router(signals_router)
    app.include_router(billing_router)
    app.include_router(webhooks_router)
    app.include_router(feedback_router)
    app.include_router(notifications_router)
    app.include_router(cockpit_router)
    app.include_router(operations_router)

    @app.exception_handler(ValueError)
    def _value_error(request: Request, error: ValueError) -> JSONResponse:
        """Une entrée client invalide se décrit ; elle ne remonte jamais brute."""
        return JSONResponse(
            status_code=422,
            content={"code": "invalid_input", "message": str(error)},
        )

    return app


@contextmanager
def transaction(request: Request) -> Iterator[sa.Connection]:
    """Une transaction par requête modifiante — validée, ou entièrement défaite."""
    with request.app.state.engine.begin() as connection:
        yield connection


@contextmanager
def read_connection(request: Request) -> Iterator[sa.Connection]:
    with request.app.state.engine.connect() as connection:
        yield connection
