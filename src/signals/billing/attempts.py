"""La réservation d'une tentative de paiement — avant d'appeler Stripe, jamais après.

Le défaut que ce module ferme
─────────────────────────────
Deux requêtes de paiement quasi simultanées pour un même compte passaient
toutes deux le contrôle « a-t-il déjà un abonnement ? » — puisqu'aucun
n'existe encore — et ouvraient deux sessions Stripe. Si le client terminait
les deux, Stripe créait deux abonnements, donc deux factures. La contrainte
d'unicité sur `billing_subscription` rattrapait la seconde en conflit, mais
après le débit : trop tard.

L'ordre est donc inversé, et il n'est pas négociable :

    vérifier l'abonnement  →  RÉSERVER en base  →  valider  →  appeler Stripe

La base est l'arbitre final (§9). `account_id` est la clé primaire de la
table : deux processus applicatifs sur le même VPS, deux workers, deux
requêtes — une seule insertion réussit. Un verrou en mémoire ne tiendrait
pas sur le second processus.

Le plantage entre Stripe et la base (§4)
────────────────────────────────────────
Une tentative peut rester `creating` : Stripe a créé la session, le
processus est mort avant d'enregistrer son identifiant. La reprise ne crée
surtout pas une seconde tentative — elle **rejoue la même**, avec la même
clé d'idempotence, et Stripe rend la même session. C'est pour cela que
`attempt_id` est persisté avant l'appel et jamais régénéré.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import secrets

import sqlalchemy as sa

from signals.billing.schema import (
    CHECKOUT_ATTEMPT_TTL_MINUTES,
    TERMINAL_ATTEMPT_STATUSES,
    billing_checkout_attempt,
    is_open_attempt,
)
from signals.billing.service import BillingError, aware_datetime

CHECKOUT_ATTEMPT_TTL = dt.timedelta(minutes=CHECKOUT_ATTEMPT_TTL_MINUTES)


class CheckoutInProgress(BillingError):
    """Une tentative de paiement est déjà ouverte pour ce compte.

    §8 — un changement d'avis en cours de route n'ouvre pas une seconde
    session, et la session Stripe existante n'est **pas** annulée
    automatiquement : elle expirera d'elle-même, et le compte pourra alors
    recommencer.
    """

    code = "checkout_in_progress"

    def __init__(self, attempt: StoredAttempt) -> None:
        super().__init__(
            f"un paiement est déjà en cours pour ce compte ({attempt.plan_code}/"
            f"{attempt.currency}), jusqu'à {attempt.expires_at.isoformat()}"
        )
        self.attempt = attempt


@dataclasses.dataclass(frozen=True)
class StoredAttempt:
    """La tentative de paiement courante d'un compte."""

    account_id: str
    attempt_id: str
    plan_code: str
    currency: str
    stripe_checkout_session_id: str | None
    status: str
    expires_at: dt.datetime
    created_at: dt.datetime
    updated_at: dt.datetime

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ATTEMPT_STATUSES

    def is_open(self, *, now: dt.datetime) -> bool:
        return is_open_attempt(self.status, expires_at=self.expires_at, now=now)

    @property
    def idempotency_key(self) -> str:
        """§3 — la clé Stripe appartient à la TENTATIVE, pas à l'appel.

        Elle est dérivée d'un identifiant persisté avant le premier appel, donc
        une reprise après plantage la retrouve à l'identique. En générer une
        nouvelle produirait une seconde session de paiement — exactement ce que
        tout ce module cherche à empêcher.
        """
        return f"kivou-checkout:{self.attempt_id}"

    def matches(self, *, plan_code: str, currency: str) -> bool:
        return self.plan_code == plan_code and self.currency == currency


def _row(row: sa.Row) -> StoredAttempt:
    return StoredAttempt(
        account_id=row.account_id,
        attempt_id=row.attempt_id,
        plan_code=row.plan_code,
        currency=row.currency,
        stripe_checkout_session_id=row.stripe_checkout_session_id,
        status=row.status,
        expires_at=aware_datetime(row.expires_at),
        created_at=aware_datetime(row.created_at),
        updated_at=aware_datetime(row.updated_at),
    )


def current_attempt(connection: sa.Connection, *, account_id: str) -> StoredAttempt | None:
    row = connection.execute(
        sa.select(billing_checkout_attempt).where(
            billing_checkout_attempt.c.account_id == account_id
        )
    ).first()
    return None if row is None else _row(row)


def _new_attempt_id() -> str:
    return f"cka_{base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip('=')}"


def reserve(
    connection: sa.Connection,
    *,
    account_id: str,
    plan_code: str,
    currency: str,
    now: dt.datetime,
) -> StoredAttempt:
    """Réserve la tentative courante du compte, ou lève.

    Trois cas, et un seul ouvre la porte :

    - **aucune tentative, ou une tentative terminée/expirée** → la place est
      libre, on réserve ;
    - **une tentative `creating` sur le MÊME plan** → Stripe a peut-être déjà
      créé la session sans qu'on ait pu l'enregistrer : on rejoue la MÊME
      tentative (§4) ;
    - **tout le reste** → `checkout_in_progress`.

    L'appelant doit VALIDER cette transaction avant d'appeler Stripe. La
    réservation qui ne serait pas validée ne protégerait de rien.
    """
    existing = current_attempt(connection, account_id=account_id)
    if existing is not None and existing.is_open(now=now):
        if existing.status == "creating" and existing.matches(
            plan_code=plan_code, currency=currency
        ):
            # Reprise : même tentative, donc même clé d'idempotence.
            return existing
        raise CheckoutInProgress(existing)

    attempt = StoredAttempt(
        account_id=account_id,
        attempt_id=_new_attempt_id(),
        plan_code=plan_code,
        currency=currency,
        stripe_checkout_session_id=None,
        status="creating",
        expires_at=now + CHECKOUT_ATTEMPT_TTL,
        created_at=now,
        updated_at=now,
    )
    values = {
        "attempt_id": attempt.attempt_id,
        "plan_code": plan_code,
        "currency": currency,
        "stripe_checkout_session_id": None,
        "status": "creating",
        "expires_at": attempt.expires_at,
        "updated_at": now,
    }

    if existing is None:
        # §9 — l'insertion EST l'arbitrage. Deux requêtes concurrentes ne
        # peuvent pas insérer la même clé primaire ; la perdante lève.
        try:
            connection.execute(
                sa.insert(billing_checkout_attempt).values(
                    account_id=account_id, created_at=now, **values
                )
            )
        except sa.exc.IntegrityError as error:
            loser = current_attempt(connection, account_id=account_id)
            if loser is None:  # pragma: no cover - la ligne vient d'être écrite
                raise
            raise CheckoutInProgress(loser) from error
        return attempt

    # La tentative précédente est terminée ou expirée : elle est remplacée.
    # `WHERE` reprend l'identifiant observé, pour qu'une réservation
    # concurrente qui aurait déjà pris la place ne soit pas écrasée.
    updated = connection.execute(
        sa.update(billing_checkout_attempt)
        .where(
            billing_checkout_attempt.c.account_id == account_id,
            billing_checkout_attempt.c.attempt_id == existing.attempt_id,
        )
        .values(**values)
    )
    if updated.rowcount == 0:
        winner = current_attempt(connection, account_id=account_id)
        raise CheckoutInProgress(winner or existing)
    return attempt


def record_session(
    connection: sa.Connection,
    *,
    account_id: str,
    attempt_id: str,
    stripe_checkout_session_id: str,
    now: dt.datetime,
) -> None:
    """Enregistre la session Stripe rendue, et passe la tentative à `open`."""
    connection.execute(
        sa.update(billing_checkout_attempt)
        .where(
            billing_checkout_attempt.c.account_id == account_id,
            billing_checkout_attempt.c.attempt_id == attempt_id,
        )
        .values(
            stripe_checkout_session_id=stripe_checkout_session_id,
            status="open",
            updated_at=now,
        )
    )


def close_attempt(
    connection: sa.Connection,
    *,
    stripe_checkout_session_id: str,
    status: str,
    now: dt.datetime,
) -> bool:
    """Ferme la tentative que désigne cette session Stripe. Rend `True` si trouvée.

    Sert à `checkout.session.completed` (§7) et `checkout.session.expired` (§6).
    Aucun droit n'en découle : fermer une tentative ne dit rien d'un paiement,
    seule la synchronisation de l'abonnement fait autorité.
    """
    result = connection.execute(
        sa.update(billing_checkout_attempt)
        .where(billing_checkout_attempt.c.stripe_checkout_session_id == stripe_checkout_session_id)
        .values(status=status, updated_at=now)
    )
    return result.rowcount > 0


def expire_stale(connection: sa.Connection, *, account_id: str, now: dt.datetime) -> bool:
    """Marque `expired` une tentative dont l'heure est passée.

    §5 — une tentative périmée ne doit pas bloquer un compte. Le nettoyage est
    explicite plutôt que déduit à la lecture, pour que l'état stocké et l'état
    lu ne divergent pas.
    """
    result = connection.execute(
        sa.update(billing_checkout_attempt)
        .where(
            billing_checkout_attempt.c.account_id == account_id,
            billing_checkout_attempt.c.expires_at <= now,
            billing_checkout_attempt.c.status.notin_(TERMINAL_ATTEMPT_STATUSES),
        )
        .values(status="expired", updated_at=now)
    )
    return result.rowcount > 0
