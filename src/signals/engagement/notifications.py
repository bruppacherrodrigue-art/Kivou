"""À qui Kivou écrit — décidé une fois, puis persisté.

Le destinataire est au niveau du COMPTE (§17, §18)
─────────────────────────────────────────────────
Le schéma admet plusieurs utilisateurs par compte, et le MVP n'en crée
qu'un. Envoyer l'alerte à chaque utilisateur produirait des doublons le jour
où un second arrive ; le destinataire est donc une propriété du compte.

Il est initialisé une fois, PUIS FIGÉ
────────────────────────────────────
Le déduire à chaque exécution du job ferait changer l'adresse dans le dos du
client dès qu'un autre utilisateur devient « le premier » — par une
suppression, un tri différent, une reprise. Une fois écrite, l'adresse est
la vérité, et seul le client la change.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.accounts.schema import auth_user
from signals.billing.service import BillingError, aware_datetime
from signals.engagement.schema import account_notification_preference


class InvalidNotificationEmail(BillingError):
    code = "invalid_notification_email"


@dataclasses.dataclass(frozen=True)
class NotificationPreference:
    account_id: str
    email_enabled: bool
    notification_email: str | None
    created_at: dt.datetime
    updated_at: dt.datetime

    @property
    def can_receive_email(self) -> bool:
        return self.email_enabled and bool(self.notification_email)


def _row(row: sa.Row) -> NotificationPreference:
    return NotificationPreference(
        account_id=row.account_id,
        email_enabled=bool(row.email_enabled),
        notification_email=row.notification_email,
        created_at=aware_datetime(row.created_at),
        updated_at=aware_datetime(row.updated_at),
    )


def _owner_email(connection: sa.Connection, *, account_id: str) -> str | None:
    """L'utilisateur propriétaire au sens MVP : le premier créé, sans ambiguïté."""
    return connection.execute(
        sa.select(auth_user.c.email_normalized)
        .where(auth_user.c.account_id == account_id)
        .order_by(auth_user.c.created_at, auth_user.c.user_id)
        .limit(1)
    ).scalar_one_or_none()


def preference(
    connection: sa.Connection, *, account_id: str, now: dt.datetime
) -> NotificationPreference:
    """La préférence du compte, initialisée à la première demande.

    Défaut : e-mail activé, adresse reprise du propriétaire. L'initialisation
    est ÉCRITE, pas seulement rendue — c'est ce qui la rend stable.
    """
    row = connection.execute(
        sa.select(account_notification_preference).where(
            account_notification_preference.c.account_id == account_id
        )
    ).first()
    if row is not None:
        return _row(row)

    connection.execute(
        sa.insert(account_notification_preference).values(
            account_id=account_id,
            email_enabled=True,
            notification_email=_owner_email(connection, account_id=account_id),
            created_at=now,
            updated_at=now,
        )
    )
    return preference(connection, account_id=account_id, now=now)


def validate_email(address: str) -> str:
    """La même validation que l'authentification — pas une seconde règle.

    Deux validateurs d'adresse finiraient par diverger, et l'un des deux
    laisserait passer ce que l'autre refuse.
    """
    from pydantic import TypeAdapter, ValidationError
    from pydantic.networks import EmailStr

    from signals.accounts.service import normalize_email

    try:
        TypeAdapter(EmailStr).validate_python(address)
    except ValidationError as error:
        raise InvalidNotificationEmail("adresse de notification invalide") from error
    return normalize_email(address)


def update_preference(
    connection: sa.Connection,
    *,
    account_id: str,
    email_enabled: bool | None,
    notification_email: str | None,
    now: dt.datetime,
) -> NotificationPreference:
    """Change ce que le client demande, et rien d'autre."""
    # L'appel initialise la préférence si elle n'existe pas encore : on ne met
    # pas à jour une ligne absente.
    current = preference(connection, account_id=account_id, now=now)
    requested_enabled = (
        current.email_enabled if email_enabled is None else email_enabled
    )
    requested_email = (
        current.notification_email
        if notification_email is None
        else validate_email(notification_email)
    )
    if (
        requested_enabled == current.email_enabled
        and requested_email == current.notification_email
    ):
        return current
    connection.execute(
        sa.update(account_notification_preference)
        .where(account_notification_preference.c.account_id == account_id)
        .values(
            email_enabled=requested_enabled,
            notification_email=requested_email,
            updated_at=now,
        )
    )
    return preference(connection, account_id=account_id, now=now)
