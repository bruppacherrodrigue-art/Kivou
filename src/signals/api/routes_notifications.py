"""Les préférences de notification d'un compte — les siennes, et rien d'autre.

Le destinataire est initialisé une fois depuis l'utilisateur propriétaire, puis
persisté : le recalculer à chaque envoi le ferait changer dans le dos du client
le jour où un second utilisateur apparaît (§17, §18).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from signals.api.dependencies import current_session, enforce_origin, request_now
from signals.api.errors import api_error
from signals.engagement import notifications

router = APIRouter()


class PreferenceUpdate(BaseModel):
    """Deux champs, et aucun `account_id` : la propriété vient de la session."""

    model_config = ConfigDict(extra="forbid")

    email_enabled: bool | None = None
    notification_email: str | None = None


def _rendered(preference: notifications.NotificationPreference) -> dict[str, Any]:
    return {
        "email_enabled": preference.email_enabled,
        "notification_email": preference.notification_email,
        "updated_at": preference.updated_at.isoformat(),
    }


@router.get("/notification-preferences")
def read_preferences(request: Request) -> dict[str, Any]:
    now = request_now(request)
    # La lecture peut INITIALISER la préférence : d'où une transaction.
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        preference = notifications.preference(connection, account_id=session.account_id, now=now)
    return _rendered(preference)


@router.patch("/notification-preferences")
def update_preferences(payload: PreferenceUpdate, request: Request) -> dict[str, Any]:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        try:
            preference = notifications.update_preference(
                connection,
                account_id=session.account_id,
                email_enabled=payload.email_enabled,
                notification_email=payload.notification_email,
                now=now,
            )
        except notifications.InvalidNotificationEmail as error:
            raise api_error(422, error.code, "adresse de notification invalide") from error
    return _rendered(preference)
