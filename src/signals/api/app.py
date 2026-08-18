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
from signals.api.routes_auth import router as auth_router
from signals.api.routes_icp import router as icp_router


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

    app.include_router(auth_router)
    app.include_router(icp_router)

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
