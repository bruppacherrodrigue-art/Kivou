"""Ce que Kivou fait de l'état Stripe — et la seule chose qui accorde un droit.

L'ordre d'évaluation est une garantie, pas une commodité (§22)
─────────────────────────────────────────────────────────────
    propriété du compte  →  identité affichable  →  politique de signal
                         →  droit du plan  →  accès

La facturation est une condition SUPPLÉMENTAIRE. Elle ne remplace jamais les
règles de SPEC-011 et SPEC-012 : un abonnement payé ne donne pas accès à un
signal d'un autre compte, ni à un signal d'avant les comptes.

Aucune horloge n'est lue ici
───────────────────────────
`now` est toujours reçu. C'est ce qui permet de tester une fin de période,
un abonnement résilié ou un événement plus ancien sans attendre demain.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import hashlib
import secrets
from typing import Any

import sqlalchemy as sa

from signals.accounts.schema import account, auth_user, target_icp
from signals.billing import catalogue
from signals.billing.gateway import StripeGateway, StripeSubscriptionState
from signals.billing.schema import (
    PAYING_STATUSES,
    TERMINAL_STATUSES,
    billing_customer,
    billing_subscription,
    is_open_subscription,
)

BILLING_POLICY_VERSION = "kivou-billing-v0.1"


class BillingError(RuntimeError):
    """Erreur de facturation portant un code stable pour la couche HTTP."""

    code = "billing_error"


class UnknownPlanRequested(BillingError):
    code = "unknown_plan"


class PlanNotPurchasable(BillingError):
    code = "plan_not_purchasable"


class PriceNotConfigured(BillingError):
    """Le catalogue Stripe ne publie pas ce prix — on refuse plutôt que deviner."""

    code = "price_not_configured"


class AlreadySubscribed(BillingError):
    code = "already_subscribed"


class NoBillingCustomer(BillingError):
    code = "no_billing_customer"


class StripeModeMismatch(BillingError):
    """§30 — un objet de test dans une base de production, ou l'inverse."""

    code = "stripe_mode_mismatch"


class FoundingNotAvailable(BillingError):
    code = "founding_not_available"


class BillingSubscriptionConflict(BillingError):
    """R1 §5 — deux abonnements Stripe non terminaux pour un seul compte.

    Aucun n'est choisi. Les départager par plan, par prix ou par date
    reviendrait à décider seul lequel des deux le client paie — alors que dans
    les deux cas il paie DÉJÀ. Kivou refuse, conserve l'existant, et laisse un
    humain trancher. Aucun abonnement Stripe n'est résilié automatiquement :
    annuler la mauvaise facturation serait pire que de ne rien faire.
    """

    code = "billing_subscription_conflict"

    def __init__(self, *, account_id: str, current: str, incoming: str) -> None:
        super().__init__(
            f"le compte {account_id} porte déjà l'abonnement {current} ; "
            f"{incoming} arrive sans que le premier soit terminé"
        )
        self.account_id = account_id
        self.current_subscription_id = current
        self.incoming_subscription_id = incoming


@dataclasses.dataclass(frozen=True)
class StoredSubscription:
    """L'abonnement tel que Kivou l'a synchronisé."""

    account_id: str
    stripe_subscription_id: str
    stripe_customer_id: str
    plan_code: str | None
    offer_code: str | None
    currency: str | None
    status: str
    current_period_start: dt.datetime | None
    current_period_end: dt.datetime | None
    cancel_at_period_end: bool
    canceled_at: dt.datetime | None
    last_stripe_event_created_at: dt.datetime | None
    livemode: bool

    @property
    def is_open(self) -> bool:
        """L'abonnement existe-t-il encore chez Stripe ? (R1 §3)

        Distinct de `grants_paid_access` : un abonnement impayé n'ouvre aucun
        droit mais existe bel et bien, et en ouvrir un second facturerait deux
        fois le même client.
        """
        return is_open_subscription(self.status)

    @property
    def grants_paid_access(self) -> bool:
        """§10 — seul `active` ouvre l'accès, et seulement sur un plan connu.

        `cancel_at_period_end` ne retire rien : Stripe garde l'abonnement
        `active` jusqu'à la fin de la période payée, et c'est Stripe qui décide
        du moment où il cesse de l'être. Inventer une date de coupure ici
        reviendrait à retirer un accès déjà réglé.
        """
        return self.status in PAYING_STATUSES and self.plan_code in catalogue.PURCHASABLE_PLANS


@dataclasses.dataclass(frozen=True)
class BillingState:
    """L'état de facturation d'un compte, et les droits qui en découlent."""

    account_id: str
    plan_code: str
    offer_code: str | None
    currency: str | None
    subscription_status: str | None
    cancel_at_period_end: bool
    current_period_end: dt.datetime | None
    payment_issue: str | None
    entitlements: catalogue.PlanEntitlements

    @property
    def is_discovery(self) -> bool:
        return self.plan_code == "discovery"


def _identifier(prefix: str) -> str:
    return f"{prefix}_{base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip('=')}"


def aware_datetime(value: Any) -> dt.datetime | None:
    """SQLite rend des instants nus ; tout ce qui est écrit ici est en UTC."""
    if value is None:
        return None
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def payload_hash(payload: bytes) -> str:
    """Empreinte du corps brut — assez pour tracer, rien à divulguer."""
    return hashlib.sha256(payload).hexdigest()


# ─── client Stripe du compte ──────────────────────────────────────────────────


def stripe_customer_id(connection: sa.Connection, *, account_id: str) -> str | None:
    return connection.execute(
        sa.select(billing_customer.c.stripe_customer_id).where(
            billing_customer.c.account_id == account_id
        )
    ).scalar_one_or_none()


def ensure_stripe_customer(
    connection: sa.Connection,
    gateway: StripeGateway,
    *,
    account_id: str,
    expect_livemode: bool,
    now: dt.datetime,
) -> str:
    """Le client Stripe du compte, créé une seule fois.

    L'écriture est idempotente par construction : `account_id` est la clé
    primaire de `billing_customer`, donc un second appel ne peut pas produire un
    second client Stripe pour le même compte.
    """
    existing = stripe_customer_id(connection, account_id=account_id)
    if existing is not None:
        return existing

    row = connection.execute(
        sa.select(account.c.display_name, auth_user.c.email_normalized)
        .select_from(account.join(auth_user, auth_user.c.account_id == account.c.account_id))
        .where(account.c.account_id == account_id)
        .order_by(auth_user.c.created_at, auth_user.c.user_id)
    ).first()
    if row is None:
        raise NoBillingCustomer("compte introuvable")

    customer = gateway.create_customer(
        email=row.email_normalized,
        account_id=account_id,
        display_name=row.display_name,
        # §13 — la clé d'idempotence est dérivée du compte : un double clic ne
        # peut pas créer deux clients Stripe.
        idempotency_key=f"kivou-customer-{account_id}",
    )
    require_stripe_mode(customer.livemode, expect_livemode, "customer")
    connection.execute(
        sa.insert(billing_customer).values(
            account_id=account_id,
            stripe_customer_id=customer.customer_id,
            livemode=customer.livemode,
            created_at=now,
            updated_at=now,
        )
    )
    return customer.customer_id


def require_stripe_mode(livemode: bool, expected: bool, kind: str) -> None:
    """§30 — refuse un objet Stripe du mauvais mode plutôt que de le mélanger.

    Un prix de test réglé sur une base de production, ou l'inverse, est une
    erreur de configuration qui doit s'arrêter net : la rattraper plus tard
    voudrait dire réconcilier des abonnements qui n'existent pas.
    """
    if livemode != expected:
        raise StripeModeMismatch(
            f"objet Stripe {kind} en livemode={livemode} alors que le mode configuré "
            f"attend livemode={expected}"
        )


# ─── abonnement synchronisé ───────────────────────────────────────────────────


def current_subscription(
    connection: sa.Connection, *, account_id: str
) -> StoredSubscription | None:
    """L'abonnement courant du compte — il n'y en a qu'un, par contrainte.

    R1 §2 : `account_id` est UNIQUE. Il n'y a donc rien à départager, et c'est
    voulu : choisir un « gagnant » entre deux abonnements masquerait le fait
    qu'ils sont facturés tous les deux.
    """
    row = connection.execute(
        sa.select(billing_subscription).where(billing_subscription.c.account_id == account_id)
    ).first()
    return None if row is None else _stored(row)


def _stored(row: sa.Row) -> StoredSubscription:
    return StoredSubscription(
        account_id=row.account_id,
        stripe_subscription_id=row.stripe_subscription_id,
        stripe_customer_id=row.stripe_customer_id,
        plan_code=row.plan_code,
        offer_code=row.offer_code,
        currency=row.currency,
        status=row.status,
        current_period_start=aware_datetime(row.current_period_start),
        current_period_end=aware_datetime(row.current_period_end),
        cancel_at_period_end=bool(row.cancel_at_period_end),
        canceled_at=aware_datetime(row.canceled_at),
        last_stripe_event_created_at=aware_datetime(row.last_stripe_event_created_at),
        livemode=bool(row.livemode),
    )


def resolve_plan(state: StripeSubscriptionState) -> tuple[str | None, str | None]:
    """`(plan_code, currency)` d'un abonnement Stripe, ou `(None, None)`.

    §9 — un prix hors catalogue ne rend AUCUN plan. Pas de repli sur Pro, pas de
    lecture de métadonnée Stripe : l'autorisation reste du code Kivou.
    """
    resolved = catalogue.plan_for_lookup_key(state.lookup_key)
    if resolved is None:
        return None, state.currency
    return resolved


def synchronize_subscription(
    connection: sa.Connection,
    state: StripeSubscriptionState,
    *,
    account_id: str,
    event_created_at: dt.datetime | None,
    expect_livemode: bool,
    now: dt.datetime,
) -> tuple[StoredSubscription, str]:
    """Écrit l'état Stripe dans Kivou. Rend l'état stocké et ce qui a été fait.

    §17 — l'ordre de livraison n'est pas garanti. La synchronisation part donc
    de l'OBJET COURANT relu chez Stripe, et refuse un événement **plus ancien**
    que celui déjà appliqué : une notification tardive ne peut pas ressusciter
    un état périmé.
    """
    require_stripe_mode(state.livemode, expect_livemode, "subscription")
    plan_code, currency = resolve_plan(state)
    offer_code = (
        "founding"
        if state.discount_coupon_id is not None and plan_code == catalogue.FOUNDING_PLAN_CODE
        else None
    )

    existing = connection.execute(
        sa.select(billing_subscription).where(billing_subscription.c.account_id == account_id)
    ).first()
    if existing is not None and existing.stripe_subscription_id != state.subscription_id:
        # R1 §5 — un SECOND abonnement pour un compte qui en a déjà un.
        if is_open_subscription(existing.status):
            raise BillingSubscriptionConflict(
                account_id=account_id,
                current=existing.stripe_subscription_id,
                incoming=state.subscription_id,
            )
        # L'ancien est terminé : le nouveau le remplace. Règle explicite, et la
        # seule qui n'invente rien — un abonnement résilié ne facture plus.
        existing = None
        connection.execute(
            sa.delete(billing_subscription).where(
                billing_subscription.c.account_id == account_id,
                billing_subscription.c.status.in_(TERMINAL_STATUSES),
            )
        )

    values: dict[str, Any] = {
        "account_id": account_id,
        "stripe_subscription_id": state.subscription_id,
        "stripe_customer_id": state.customer_id,
        "stripe_price_id": state.price_id,
        "stripe_product_id": state.product_id,
        "plan_code": plan_code,
        "offer_code": offer_code,
        "currency": currency,
        "status": state.status,
        "current_period_start": state.current_period_start,
        "current_period_end": state.current_period_end,
        "cancel_at_period_end": state.cancel_at_period_end,
        "canceled_at": state.canceled_at,
        "last_stripe_event_created_at": event_created_at,
        "livemode": state.livemode,
        "updated_at": now,
    }

    if existing is None:
        connection.execute(
            sa.insert(billing_subscription).values(
                billing_subscription_id=_identifier("bsub"), created_at=now, **values
            )
        )
        return _fetch(connection, state.subscription_id), "created"

    previous = aware_datetime(existing.last_stripe_event_created_at)
    if event_created_at is not None and previous is not None and event_created_at < previous:
        # Un événement antérieur à celui déjà appliqué : il décrit un passé, pas
        # le présent. L'appliquer ferait reculer l'état.
        return _stored(existing), "stale_event_ignored"

    connection.execute(
        sa.update(billing_subscription)
        .where(billing_subscription.c.stripe_subscription_id == state.subscription_id)
        .values(**values)
    )
    return _fetch(connection, state.subscription_id), "updated"


def _fetch(connection: sa.Connection, stripe_subscription_id: str) -> StoredSubscription:
    row = connection.execute(
        sa.select(billing_subscription).where(
            billing_subscription.c.stripe_subscription_id == stripe_subscription_id
        )
    ).one()
    return _stored(row)


# ─── droits ───────────────────────────────────────────────────────────────────

#: §28 — les statuts qui décrivent un problème de paiement, dits tels quels.
_PAYMENT_ISSUES: dict[str, str] = {
    "past_due": "payment_past_due",
    "unpaid": "payment_unpaid",
    "incomplete": "payment_incomplete",
    "incomplete_expired": "payment_incomplete_expired",
}


def billing_state(connection: sa.Connection, *, account_id: str) -> BillingState:
    """L'état de facturation et les droits qui en découlent.

    Aucun abonnement, un abonnement résilié, un prix inconnu, un statut
    inattendu : tous mènent à Discovery. Le repli est **restrictif** par
    construction — c'est le seul défaut sûr.
    """
    subscription = current_subscription(connection, account_id=account_id)
    if subscription is None:
        return BillingState(
            account_id=account_id,
            plan_code="discovery",
            offer_code=None,
            currency=None,
            subscription_status=None,
            cancel_at_period_end=False,
            current_period_end=None,
            payment_issue=None,
            entitlements=catalogue.DISCOVERY,
        )

    paid = subscription.grants_paid_access
    plan_code = subscription.plan_code if paid else "discovery"
    return BillingState(
        account_id=account_id,
        plan_code=plan_code,
        offer_code=subscription.offer_code if paid else None,
        currency=subscription.currency,
        subscription_status=subscription.status,
        cancel_at_period_end=subscription.cancel_at_period_end,
        current_period_end=subscription.current_period_end,
        payment_issue=_PAYMENT_ISSUES.get(subscription.status),
        entitlements=catalogue.entitlements_for(plan_code),
    )


def entitlements(connection: sa.Connection, *, account_id: str) -> catalogue.PlanEntitlements:
    return billing_state(connection, account_id=account_id).entitlements


# ─── offre fondateur ──────────────────────────────────────────────────────────


def founding_accounts(connection: sa.Connection) -> int:
    """Combien de comptes DISTINCTS ont déjà obtenu l'offre fondateur.

    §7 — `max_redemptions` chez Stripe compte des utilisations de coupon, pas
    des clients. Kivou compte donc lui-même, sur sa propre notion de compte.
    """
    return connection.execute(
        sa.select(sa.func.count(sa.distinct(billing_subscription.c.account_id))).where(
            billing_subscription.c.offer_code == "founding"
        )
    ).scalar_one()


def founding_available(connection: sa.Connection, *, account_id: str) -> bool:
    """Reste-t-il une place, et ce compte ne l'a-t-il pas déjà prise ?"""
    already = connection.execute(
        sa.select(sa.func.count())
        .select_from(billing_subscription)
        .where(
            billing_subscription.c.account_id == account_id,
            billing_subscription.c.offer_code == "founding",
        )
    ).scalar_one()
    if already:
        return False
    return founding_accounts(connection) < catalogue.FOUNDING_MAXIMUM_ACCOUNTS


# ─── limites d'ICP ────────────────────────────────────────────────────────────


def active_icp_count(connection: sa.Connection, *, account_id: str) -> int:
    return connection.execute(
        sa.select(sa.func.count())
        .select_from(target_icp)
        .where(target_icp.c.account_id == account_id, target_icp.c.status == "active")
    ).scalar_one()


def feedable_target_icps(
    connection: sa.Connection, *, account_id: str, limit: int
) -> tuple[str, ...]:
    """Le sous-ensemble d'ICP actifs qui alimente le feed, plafonné par le plan.

    §23 — la règle est la plus simple qui soit **stable** : les plus anciens
    d'abord, par date de création puis par identifiant. Rien n'est supprimé,
    rien n'est désactivé ; un compte qui redescend de plan garde toutes ses
    données et voit simplement moins de profils servir.
    """
    rows = connection.execute(
        sa.select(target_icp.c.target_icp_id)
        .where(target_icp.c.account_id == account_id, target_icp.c.status == "active")
        .order_by(target_icp.c.created_at, target_icp.c.target_icp_id)
        .limit(max(0, limit))
    ).all()
    return tuple(row.target_icp_id for row in rows)


def over_limit_icps(connection: sa.Connection, *, account_id: str, limit: int) -> tuple[str, ...]:
    """Les ICP actifs au-delà du plafond du plan — à faire trancher par le client."""
    rows = connection.execute(
        sa.select(target_icp.c.target_icp_id)
        .where(target_icp.c.account_id == account_id, target_icp.c.status == "active")
        .order_by(target_icp.c.created_at, target_icp.c.target_icp_id)
    ).all()
    return tuple(row.target_icp_id for row in rows[max(0, limit) :])
