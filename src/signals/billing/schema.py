"""Les tables de facturation — le strict nécessaire pour rendre Stripe rejouable.

Quatre tables, enregistrées dans le `METADATA` **partagé** : une seule base, une
seule chaîne de migration.

    Ce qui n'est jamais stocké
    ──────────────────────────
    Aucun numéro de carte, aucun moyen de paiement, aucune clé, aucun secret de
    webhook, aucune charge brute d'événement. Stripe garde les données de
    paiement ; Kivou ne garde que de quoi décider d'un droit d'accès et de quoi
    prouver qu'un événement a déjà été traité.

    Pourquoi persister les événements
    ─────────────────────────────────
    Stripe indique explicitement qu'un événement peut être livré plusieurs fois
    et dans le désordre. Sans table d'événements, une seconde livraison
    rejouerait la transition — et une livraison tardive ferait reculer l'état.
    `stripe_event_id` en clé primaire rend le premier cas impossible ;
    `last_stripe_event_created_at` sur l'abonnement rend le second détectable.
"""

from __future__ import annotations

import sqlalchemy as sa

# Les clés étrangères pointent vers `account` : la table doit être enregistrée
# dans le `METADATA` partagé avant que ce module ne s'y raccroche. L'import a
# l'air inutile, il est la condition de résolution des clés étrangères.
import signals.accounts.schema  # noqa: F401
from signals.persistence.schema import METADATA

#: §10 — les statuts Stripe que Kivou sait interpréter. Tout autre statut est
#: enregistré tel quel et traité comme non payant : inventer un droit sur un
#: statut inconnu serait exactement la faute que §9 interdit.
STRIPE_SUBSCRIPTION_STATUSES: tuple[str, ...] = (
    "active",
    "past_due",
    "unpaid",
    "incomplete",
    "incomplete_expired",
    "canceled",
    "paused",
    "trialing",
)

#: Seul `active` ouvre des droits payants. `trialing` figure dans la liste des
#: statuts connus parce que Stripe peut l'émettre, mais le MVP n'offre aucun
#: essai (§10) : il ne donne donc pas accès.
PAYING_STATUSES: tuple[str, ...] = ("active",)

#: R1 §3 — les seuls états où l'abonnement a cessé d'exister chez Stripe, et où
#: un nouveau paiement est donc légitime.
#:
#:     ACCÈS KIVOU  ≠  EXISTENCE D'UN ABONNEMENT
#:
#: Un abonnement `past_due` n'ouvre aucun droit — mais il existe, il est
#: facturé, et en ouvrir un second produirait deux factures pour un client qui
#: n'en a demandé qu'une. Confondre « pas d'accès » et « pas d'abonnement » est
#: la faute qui coûte de l'argent réel au client.
TERMINAL_STATUSES: tuple[str, ...] = ("canceled", "incomplete_expired")


def is_open_subscription(status: str) -> bool:
    """L'abonnement existe-t-il encore chez Stripe ?

    **Défaut fermé** : la question porte sur l'appartenance aux états
    TERMINAUX, pas aux états ouverts. Un statut que Stripe inventerait demain
    est donc bloquant, et non permissif — c'est le seul sens sûr, puisque
    l'erreur permissive se paie en double facturation.
    """
    return status not in TERMINAL_STATUSES


PROCESSING_RESULTS: tuple[str, ...] = (
    "applied",
    "ignored",
    "duplicate",
    "unhandled",
    "rejected",
    "conflict",
)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


billing_customer = sa.Table(
    "billing_customer",
    METADATA,
    # Un compte, un client Stripe. La clé primaire porte la règle : deux clients
    # Stripe pour un compte produiraient deux abonnements irréconciliables.
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("stripe_customer_id", sa.String(128), nullable=False, unique=True),
    # §30 — le mode dans lequel l'objet a été créé. Un objet de test qui
    # remonterait dans une base de production doit se voir immédiatement.
    sa.Column("livemode", sa.Boolean, nullable=False),
    *_timestamps(),
)


billing_subscription = sa.Table(
    "billing_subscription",
    METADATA,
    sa.Column("billing_subscription_id", sa.String(64), primary_key=True),
    # R1 §2 — UN compte, UN abonnement courant. La contrainte est structurelle
    # parce qu'un « gagnant » choisi par tri masquerait le vrai problème : deux
    # abonnements Stripe, ce sont deux factures. Cette table décrit l'abonnement
    # COURANT ; le MVP n'a pas besoin d'un historique de facturation, et une
    # table dédiée pourra en tenir un le jour où il servira.
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column("stripe_subscription_id", sa.String(128), nullable=False, unique=True),
    sa.Column("stripe_customer_id", sa.String(128), nullable=False, index=True),
    sa.Column("stripe_price_id", sa.String(128)),
    sa.Column("stripe_product_id", sa.String(128)),
    # Le plan Kivou RÉSOLU depuis la clé de recherche du prix. `None` quand le
    # prix n'appartient à aucun plan connu : l'abonnement existe chez Stripe,
    # mais il n'ouvre aucun droit tant que personne n'a décidé lequel.
    sa.Column("plan_code", sa.String(32), index=True),
    sa.Column("offer_code", sa.String(32)),
    sa.Column("currency", sa.String(3)),
    sa.Column("status", sa.String(32), nullable=False, index=True),
    sa.Column("current_period_start", sa.DateTime(timezone=True)),
    sa.Column("current_period_end", sa.DateTime(timezone=True)),
    sa.Column("cancel_at_period_end", sa.Boolean, nullable=False),
    sa.Column("canceled_at", sa.DateTime(timezone=True)),
    # P0-03G — l'échéance telle que Stripe la publie. Le booléen ci-dessus ne
    # suffit pas : sur un abonnement `flexible`, Stripe le laisse à `false` et
    # n'exprime la résiliation que par une date.
    sa.Column("scheduled_cancellation_at", sa.DateTime(timezone=True)),
    # §17 — l'horodatage de l'événement Stripe qui a produit cet état. Un
    # événement plus ancien qui arrive après ne doit pas faire reculer l'état.
    sa.Column("last_stripe_event_created_at", sa.DateTime(timezone=True)),
    sa.Column("livemode", sa.Boolean, nullable=False),
    *_timestamps(),
)


stripe_webhook_event = sa.Table(
    "stripe_webhook_event",
    METADATA,
    # L'identifiant Stripe EST la clé primaire : la deuxième livraison du même
    # événement ne peut structurellement pas s'insérer deux fois.
    sa.Column("stripe_event_id", sa.String(128), primary_key=True),
    sa.Column("event_type", sa.String(128), nullable=False, index=True),
    sa.Column("stripe_object_id", sa.String(128)),
    sa.Column("livemode", sa.Boolean, nullable=False),
    sa.Column("stripe_created_at", sa.DateTime(timezone=True), nullable=False),
    # Une empreinte, jamais la charge : le corps d'un événement contient des
    # données client dont Kivou n'a aucun besoin, et qu'il n'a pas à conserver.
    sa.Column("payload_hash", sa.String(64), nullable=False),
    sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("processing_result", sa.String(32), nullable=False),
    sa.Column("detail", sa.Text),
    _created_at(),
)


discovery_signal_grant = sa.Table(
    "discovery_signal_grant",
    METADATA,
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # Pas de clé étrangère vers `materialized_signal` : un déblocage doit
    # survivre à une rematérialisation, et la contrainte forcerait une
    # reconstruction destructive de table sous SQLite (déviation déjà reportée
    # en SPEC-011 §9 pour la même raison).
    sa.Column("signal_key", sa.String(64), primary_key=True),
    sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
    # L'opportunité derrière le signal débloqué, conservée pour l'audit : elle
    # dit QUEL marché a été offert, même si le signal est refait plus tard.
    sa.Column("opportunity_key", sa.String(64), nullable=False),
    _created_at(),
)


#: Closeout §1 — les états d'une tentative de paiement. Les trois derniers sont
#: TERMINAUX : ils libèrent la place pour une nouvelle tentative.
CHECKOUT_ATTEMPT_STATUSES: tuple[str, ...] = (
    "creating",
    "open",
    "completed",
    "expired",
    "failed",
)
TERMINAL_ATTEMPT_STATUSES: tuple[str, ...] = ("completed", "expired", "failed")

#: §5 — durée de vie d'une tentative, locale et Stripe. Trente minutes est le
#: minimum que Stripe accepte pour `expires_at` ; aligner les deux évite qu'une
#: tentative locale survive à la session qu'elle décrit et bloque le compte.
CHECKOUT_ATTEMPT_TTL_MINUTES = 30


billing_checkout_attempt = sa.Table(
    "billing_checkout_attempt",
    METADATA,
    # Closeout §1, §9 — `account_id` en CLÉ PRIMAIRE : la base garantit qu'un
    # compte n'a qu'une tentative courante, quel que soit le nombre de processus
    # applicatifs. Un verrou en mémoire ne tiendrait pas sur un second worker.
    #
    # La table ne garde PAS d'historique : elle décrit la tentative courante, et
    # une tentative terminée est remplacée par la suivante.
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # L'identité de la tentative. C'est d'elle que dérive la clé d'idempotence
    # Stripe, et c'est pourquoi elle doit survivre à un plantage : une nouvelle
    # clé produirait une seconde session de paiement (§3, §4).
    sa.Column("attempt_id", sa.String(64), nullable=False, unique=True),
    sa.Column("plan_code", sa.String(32), nullable=False),
    sa.Column("currency", sa.String(3), nullable=False),
    # `None` tant que Stripe n'a pas répondu — c'est exactement la fenêtre de
    # plantage que §4 demande de couvrir.
    sa.Column("stripe_checkout_session_id", sa.String(255), unique=True),
    sa.Column("status", sa.String(16), nullable=False, index=True),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    *_timestamps(),
)


BILLING_TABLES: tuple[sa.Table, ...] = (
    billing_customer,
    billing_subscription,
    stripe_webhook_event,
    discovery_signal_grant,
    billing_checkout_attempt,
)


def is_open_attempt(status: str, *, expires_at, now) -> bool:
    """La tentative bloque-t-elle encore le compte ?

    Non si elle est terminée, non si elle a expiré. Le second cas est ce qui
    empêche une tentative abandonnée de bloquer un compte indéfiniment (§5) :
    une session que Stripe a laissée mourir ne doit pas survivre localement.
    """
    if status in TERMINAL_ATTEMPT_STATUSES:
        return False
    return expires_at > now
