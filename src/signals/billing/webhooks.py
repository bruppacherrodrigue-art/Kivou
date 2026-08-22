"""La réception des événements Stripe — vérifiée, idempotente, insensible à l'ordre.

Trois pièges, et comment chacun est fermé
─────────────────────────────────────────
**Un événement peut être rejoué.** `stripe_event_id` est la clé primaire de
la table d'événements : la seconde livraison échoue à l'insertion et ne
rejoue rien. L'insertion précède le traitement, dans la MÊME transaction,
donc une transition partiellement appliquée n'est jamais confirmée.

**L'ordre n'est pas garanti.** Aucun enchaînement n'est supposé. Tout
événement porteur d'un abonnement déclenche une **relecture de l'objet
courant** chez Stripe : l'état courant ne dépend d'aucun ordre. Et un
événement plus ancien que celui déjà appliqué est refusé par
`synchronize_subscription`, ce qui empêche un retour en arrière.

**Le navigateur n'est pas une autorité.** Rien ici n'est déclenché par une
redirection : `success_url` est de la présentation, la source de vérité est
la signature Stripe (§14).
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.billing import attempts
from signals.billing.gateway import StripeEvent, StripeGateway
from signals.billing.schema import stripe_webhook_event
from signals.billing.service import (
    BillingSubscriptionConflict,
    StripeModeMismatch,
    payload_hash,
    synchronize_subscription,
)

#: §16 — exactement ce dont Kivou a besoin. Écouter tout Stripe reviendrait à
#: traiter du bruit et à multiplier les chemins non testés.
HANDLED_EVENT_TYPES: tuple[str, ...] = (
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
    # Closeout §6 — sans cet événement, une session abandonnée laisserait la
    # tentative locale ouverte jusqu'à son expiration.
    "checkout.session.expired",
)

#: Reconnu, journalisé, mais n'accorde rien : une action de paiement requise est
#: l'inverse d'un paiement (§16).
ACKNOWLEDGED_EVENT_TYPES: tuple[str, ...] = ("invoice.payment_action_required",)

RESULT_APPLIED = "applied"
RESULT_DUPLICATE = "duplicate"
RESULT_IGNORED = "ignored"
RESULT_UNHANDLED = "unhandled"
RESULT_REJECTED = "rejected"
#: R1 §5 — deux abonnements non terminaux pour un compte. L'événement est
#: enregistré, l'état local n'est PAS touché, et un humain doit trancher.
RESULT_CONFLICT = "conflict"


@dataclasses.dataclass(frozen=True)
class WebhookOutcome:
    """Ce qui a été fait de l'événement. Rendu au client Stripe sans détail."""

    event_id: str
    event_type: str
    result: str
    detail: str | None = None

    @property
    def accepted(self) -> bool:
        return self.result != RESULT_REJECTED


def already_processed(connection: sa.Connection, *, event_id: str) -> bool:
    return (
        connection.execute(
            sa.select(sa.func.count())
            .select_from(stripe_webhook_event)
            .where(stripe_webhook_event.c.stripe_event_id == event_id)
        ).scalar_one()
        > 0
    )


def _record(
    connection: sa.Connection,
    event: StripeEvent,
    *,
    payload: bytes,
    result: str,
    detail: str | None,
    now: dt.datetime,
) -> None:
    connection.execute(
        sa.insert(stripe_webhook_event).values(
            stripe_event_id=event.event_id,
            event_type=event.event_type,
            stripe_object_id=event.object_id,
            livemode=event.livemode,
            stripe_created_at=event.created,
            payload_hash=payload_hash(payload),
            processed_at=now,
            processing_result=result,
            detail=detail,
            created_at=now,
        )
    )


def _account_for_subscription(connection: sa.Connection, event: StripeEvent, state) -> str | None:
    """À quel compte Kivou rattacher cet abonnement.

    Trois pistes, de la plus fiable à la moins : la métadonnée portée par
    l'abonnement lui-même, la référence portée par l'événement, puis le client
    Stripe déjà associé au compte. Aucune n'est devinée : chacune est un lien
    que Kivou a lui-même écrit au moment du checkout (§12, §13).
    """
    from signals.billing.schema import billing_customer

    if state is not None and state.account_id:
        return state.account_id
    reference = event.account_reference
    if reference:
        return reference
    customer_id = state.customer_id if state is not None else None
    if customer_id is None:
        return None
    return connection.execute(
        sa.select(billing_customer.c.account_id).where(
            billing_customer.c.stripe_customer_id == customer_id
        )
    ).scalar_one_or_none()


def handle_event(
    connection: sa.Connection,
    gateway: StripeGateway,
    event: StripeEvent,
    *,
    payload: bytes,
    expect_livemode: bool,
    now: dt.datetime,
    conversion_milestone_service: object | None = None,
) -> WebhookOutcome:
    """Traite un événement DÉJÀ vérifié. Idempotent, insensible à l'ordre.

    L'enregistrement de l'événement et l'application de la transition partagent
    la transaction de l'appelant : si la transition échoue, l'événement n'est pas
    marqué traité, et Stripe pourra le relivrer.
    """
    if already_processed(connection, event_id=event.event_id):
        return WebhookOutcome(event.event_id, event.event_type, RESULT_DUPLICATE)

    if event.livemode != expect_livemode:
        _record(
            connection,
            event,
            payload=payload,
            result=RESULT_REJECTED,
            detail="livemode incompatible avec le mode configuré",
            now=now,
        )
        return WebhookOutcome(
            event.event_id, event.event_type, RESULT_REJECTED, "livemode incompatible"
        )

    if event.event_type in ACKNOWLEDGED_EVENT_TYPES:
        _record(
            connection,
            event,
            payload=payload,
            result=RESULT_IGNORED,
            detail="reconnu, sans effet sur l'accès",
            now=now,
        )
        return WebhookOutcome(event.event_id, event.event_type, RESULT_IGNORED)

    if event.event_type not in HANDLED_EVENT_TYPES:
        _record(connection, event, payload=payload, result=RESULT_UNHANDLED, detail=None, now=now)
        return WebhookOutcome(event.event_id, event.event_type, RESULT_UNHANDLED)

    # Closeout §6, §7 — la tentative de paiement suit sa session, et n'accorde
    # RIEN par elle-même : terminer un paiement n'est pas être abonné, seule la
    # synchronisation de l'abonnement fait autorité.
    if event.event_type in {"checkout.session.expired", "checkout.session.completed"}:
        session_id = event.data_object.get("id")
        if isinstance(session_id, str):
            attempts.close_attempt(
                connection,
                stripe_checkout_session_id=session_id,
                status="expired" if event.event_type.endswith("expired") else "completed",
                now=now,
            )
    if event.event_type == "checkout.session.expired":
        # Une session expirée ne porte aucun abonnement : il n'y a rien à
        # synchroniser, et surtout aucun droit à accorder.
        _record(
            connection,
            event,
            payload=payload,
            result=RESULT_IGNORED,
            detail="tentative de paiement expirée",
            now=now,
        )
        return WebhookOutcome(event.event_id, event.event_type, RESULT_IGNORED)

    subscription_id = event.subscription_id
    if subscription_id is None:
        _record(
            connection,
            event,
            payload=payload,
            result=RESULT_IGNORED,
            detail="aucun abonnement rattaché",
            now=now,
        )
        return WebhookOutcome(event.event_id, event.event_type, RESULT_IGNORED)

    # §17 — on relit l'OBJET COURANT plutôt que de croire la charge de
    # l'événement : l'objet courant ne dépend pas de l'ordre de livraison.
    state = gateway.fetch_subscription(subscription_id)
    if state is None:
        _record(
            connection,
            event,
            payload=payload,
            result=RESULT_IGNORED,
            detail="abonnement introuvable chez Stripe",
            now=now,
        )
        return WebhookOutcome(event.event_id, event.event_type, RESULT_IGNORED)

    account_id = _account_for_subscription(connection, event, state)
    if account_id is None:
        _record(
            connection,
            event,
            payload=payload,
            result=RESULT_IGNORED,
            detail="aucun compte Kivou rattachable",
            now=now,
        )
        return WebhookOutcome(event.event_id, event.event_type, RESULT_IGNORED)

    try:
        stored, action = synchronize_subscription(
            connection,
            state,
            account_id=account_id,
            event_created_at=event.created,
            expect_livemode=expect_livemode,
            now=now,
        )
        if conversion_milestone_service is not None:
            conversion_milestone_service.observe_billing_in_transaction(
                connection,
                account_id=account_id,
                subscription=stored,
                observed_at=now,
            )
    except StripeModeMismatch as error:
        _record(
            connection, event, payload=payload, result=RESULT_REJECTED, detail=str(error), now=now
        )
        return WebhookOutcome(event.event_id, event.event_type, RESULT_REJECTED, str(error))
    except BillingSubscriptionConflict as error:
        # L'événement est marqué traité — le relivrer produirait le même
        # conflit — mais l'abonnement courant reste intact. Rien n'est choisi,
        # rien n'est écrasé, rien n'est résilié chez Stripe.
        _record(
            connection, event, payload=payload, result=RESULT_CONFLICT, detail=str(error), now=now
        )
        return WebhookOutcome(event.event_id, event.event_type, RESULT_CONFLICT, str(error))

    result = RESULT_IGNORED if action == "stale_event_ignored" else RESULT_APPLIED
    _record(connection, event, payload=payload, result=result, detail=action, now=now)
    return WebhookOutcome(event.event_id, event.event_type, result, action)
