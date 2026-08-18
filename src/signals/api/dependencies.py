"""Ce que chaque requête traverse : origine, session, propriété du compte.

CSRF (§8)
─────────
L'authentification passe par un cookie, donc un site tiers pourrait faire
émettre une requête authentifiée par le navigateur de la victime. La
protection retenue est la **validation stricte de l'origine** sur toute
requête modifiante, doublée d'un cookie `SameSite=Lax`.

Pourquoi celle-là plutôt qu'un jeton anti-CSRF : elle n'exige aucun état
supplémentaire, aucun échange préalable, et elle ne peut pas être
contournée par un formulaire cross-site — un navigateur pose `Origin`
lui-même et une page tierce ne peut pas le falsifier.

Son coût est assumé : un client non navigateur doit envoyer un en-tête
`Origin`. Le MVP sert un frontend web ; le jour où une intégration
machine-à-machine existera, elle aura ses propres identifiants et n'utilisera
pas de cookie.

Une requête modifiante SANS origine est refusée. Accepter l'absence
reviendrait à offrir le contournement en clair.
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import urlparse

import sqlalchemy as sa
from fastapi import Request

from signals.accounts.service import AuthenticatedSession, authenticate
from signals.api.config import SESSION_COOKIE_NAME, ApiConfig
from signals.api.errors import api_error

STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def request_now(request: Request) -> dt.datetime:
    """L'instant de la requête, posé UNE fois et transmis explicitement ensuite.

    Le cœur du service ne lit jamais l'horloge : il reçoit `now`. La frontière
    HTTP est le seul endroit où le temps entre dans le système, et les tests
    peuvent le remplacer.
    """
    override = request.app.state.now_override
    return override() if override is not None else dt.datetime.now(tz=dt.UTC)


def enforce_origin(request: Request, config: ApiConfig) -> None:
    """Refuse une requête modifiante dont l'origine n'est pas celle attendue."""
    if request.method not in STATE_CHANGING_METHODS:
        return
    if config.allowed_origin is None:
        return

    origin = request.headers.get("origin")
    if origin is None:
        referer = request.headers.get("referer")
        if referer:
            parsed = urlparse(referer)
            origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else None
    if origin != config.allowed_origin:
        raise api_error(403, "csrf_origin_rejected", "origine de la requête refusée")


def current_session(
    request: Request, connection: sa.Connection, now: dt.datetime
) -> AuthenticatedSession:
    """La session portée par le cookie, ou un refus indistinct.

    Cookie absent, jeton inconnu, session expirée ou révoquée : une seule
    réponse. Le client n'a pas à apprendre laquelle des quatre.
    """
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    session = authenticate(connection, raw_token=raw, now=now) if raw else None
    if session is None:
        raise api_error(401, "not_authenticated", "authentification requise")
    return session
