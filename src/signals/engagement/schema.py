"""Ce que le client dit d'un signal, et ce que le produit observe de lui.

Six tables, et une frontière qui traverse tout le module :

    L'AVIS DU CLIENT N'EST NI UN FAIT PUBLIC NI UNE INFÉRENCE MOTEUR
    ───────────────────────────────────────────────────────────────
    Un « pas pertinent » ne dit rien du marché : il dit quelque chose du client.
    Ces tables vivent donc à côté du signal, jamais dedans, et **rien** de ce
    qu'elles contiennent ne modifie le Need Graph, le matching, le score, la
    récence ou l'ICP. La boucle est :

        RETOUR CLIENT  →  STOCKER  →  ANALYSER  →  R&D SUPERVISÉE PLUS TARD

    et surtout pas « le client clique 👎 → le score se réécrit tout seul ».

    Ce que l'analytique ne stocke jamais (§9)
    ─────────────────────────────────────────
    Mots de passe, jetons, secrets Stripe, texte de preuve, corps de documents
    publics, adresse IP, User-Agent complet, corps de requête arbitraire.
    L'analytique enregistre un comportement produit, pas une surveillance.
"""

from __future__ import annotations

import sqlalchemy as sa

# Les clés étrangères pointent vers `account` et `target_icp` : les tables
# doivent être enregistrées dans le `METADATA` partagé avant qu'on s'y raccroche.
import signals.accounts.schema  # noqa: F401
from signals.persistence.schema import METADATA

#: §5 — le vocabulaire de jugement. Deux valeurs, et pas une de plus : une
#: échelle à cinq niveaux inviterait à moyenner des avis qui ne se moyennent pas.
RELEVANCE_VALUES: tuple[str, ...] = ("relevant", "not_relevant")

#: §5 — les six raisons du refus, alignées sur le carnet de R&D « besoin
#: résiduel post-attribution ». Élargir cette liste sans preuve produirait des
#: catégories que personne n'a jamais choisies.
NEGATIVE_REASON_CODES: tuple[str, ...] = (
    "already_covered",
    "done_internally",
    "wrong_customer_type",
    "too_late",
    "wrong_need",
    "other",
)

MAXIMUM_NOTE_LENGTH = 500

#: §10 — vocabulaire fermé. Un nom d'événement libre côté client transformerait
#: la table en dépotoir, et l'analyse en archéologie.
PRODUCT_EVENT_TYPES: tuple[str, ...] = (
    "signal_feed_viewed",
    "signal_detail_viewed",
    "signal_feedback_relevant",
    "signal_feedback_not_relevant",
    "signal_contacted",
    "alert_queued",
    "alert_sent",
    "alert_failed",
    "alert_suppressed",
    #: PR2b tâche 5 — le prospect a suivi le lien de son cold mail et a été
    #: déposé dans le produit. Ni une inscription choisie ni une activation :
    #: c'est l'arrivée, et elle se compte à part.
    "attribution_landed",
    "checkout_started",
    "subscription_activated",
    "subscription_lost",
)

#: §13 — l'activation produit. Un compte créé n'est pas un compte activé : il
#: l'est quand il a jugé un signal assez pertinent pour envisager d'agir.
ACTIVATION_EVENT_TYPES: tuple[str, ...] = ("signal_feedback_relevant", "signal_contacted")

#: §13 — l'action commerciale. Une seule, et c'est la seule qui compte.
COMMERCIAL_ACTION_EVENT = "signal_contacted"

ALERT_DELIVERY_STATUSES: tuple[str, ...] = (
    "queued",
    "sending",
    "sent",
    "failed",
    "unknown_delivery_state",
    "suppressed",
)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


signal_feedback = sa.Table(
    "signal_feedback",
    METADATA,
    # L'ÉTAT COURANT du jugement, pas son historique : un client qui change
    # d'avis remplace son avis. L'historique, s'il devient utile, se lira dans
    # `product_event`, qui est append-only par construction.
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # Pas de clé étrangère vers `materialized_signal` : un avis doit survivre à
    # une rematérialisation du signal, et la contrainte imposerait une
    # reconstruction destructive sous SQLite (même déviation qu'en SPEC-011 §9).
    sa.Column("signal_key", sa.String(64), primary_key=True),
    sa.Column("relevance", sa.String(16), nullable=False, index=True),
    sa.Column("reason_code", sa.String(32), index=True),
    sa.Column("note", sa.String(MAXIMUM_NOTE_LENGTH)),
    # §6 — une ACTION, pas une opinion. Un client peut juger un signal pertinent
    # sans avoir encore décroché son téléphone ; confondre les deux effacerait
    # justement la mesure qui compte.
    sa.Column("contacted_at", sa.DateTime(timezone=True)),
    # §32 — ce que le client VOYAIT au moment de son jugement. Sans cela, un
    # « trop tard » deviendrait inanalysable : on ne saurait plus quel âge avait
    # le signal, et le recalculer à la date du jour donnerait une autre réponse.
    sa.Column("event_status_at_feedback", sa.String(32)),
    sa.Column("event_age_days_at_feedback", sa.Integer),
    sa.Column("signal_revision_at_feedback", sa.Integer),
    sa.Column("opportunity_key", sa.String(64)),
    sa.Column("target_icp_id", sa.String(128)),
    *_timestamps(),
)


signal_note = sa.Table(
    "signal_note",
    METADATA,
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("signal_key", sa.String(64), primary_key=True),
    sa.Column("note", sa.String(MAXIMUM_NOTE_LENGTH), nullable=False),
    *_timestamps(),
)


#: PR1 §4 — vocabulaire fermé du suivi commercial par entreprise.
COMPANY_CONTACT_STATUSES = ("to_contact", "contacted", "replied")

MAXIMUM_COMPANY_NOTE_LENGTH = 2000


company_contact = sa.Table(
    "company_contact",
    METADATA,
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # Pas de clé étrangère vers `saas_company` : l'état d'un compte survit à une
    # reconstruction de l'identité, comme `signal_feedback` survit au signal.
    sa.Column("company_key", sa.String(64), primary_key=True),
    sa.Column("status", sa.String(16), nullable=False, index=True),
    sa.Column("contacted_at", sa.DateTime(timezone=True)),
    *_timestamps(),
    sa.CheckConstraint("status IN ('to_contact', 'contacted', 'replied')", name="ck_company_contact_status"),
)

company_note = sa.Table(
    "company_note",
    METADATA,
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("company_key", sa.String(64), primary_key=True),
    sa.Column("body", sa.String(MAXIMUM_COMPANY_NOTE_LENGTH), nullable=False),
    *_timestamps(),
)


product_event = sa.Table(
    "product_event",
    METADATA,
    sa.Column("event_id", sa.String(64), primary_key=True),
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("user_id", sa.String(64)),
    sa.Column("target_icp_id", sa.String(128)),
    sa.Column("signal_key", sa.String(64), index=True),
    sa.Column("event_type", sa.String(64), nullable=False, index=True),
    # L'instant MÉTIER, distinct de l'écriture : une reprise de traitement ne
    # doit pas déplacer un événement dans le temps.
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, index=True),
    # Propriétés contraintes par le code appelant, jamais par le client.
    sa.Column("properties", sa.JSON, nullable=False),
    _created_at(),
)


account_notification_preference = sa.Table(
    "account_notification_preference",
    METADATA,
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("email_enabled", sa.Boolean, nullable=False),
    # §17, §18 — le destinataire est au niveau du COMPTE. Il est initialisé une
    # fois depuis l'utilisateur propriétaire, puis persisté : le recalculer à
    # chaque exécution du job ferait changer le destinataire dans le dos du
    # client le jour où un second utilisateur apparaît.
    sa.Column("notification_email", sa.String(320)),
    *_timestamps(),
)


signal_alert_delivery = sa.Table(
    "signal_alert_delivery",
    METADATA,
    # §19 — un compte, un signal logique : alerté avec succès **au plus une
    # fois**. Une nouvelle révision du signal ne redéclenche pas d'e-mail ; les
    # campagnes de relance ne font pas partie de cette SPEC.
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("signal_key", sa.String(64), primary_key=True),
    sa.Column("status", sa.String(32), nullable=False, index=True),
    sa.CheckConstraint(
        "status IN ('queued', 'sending', 'sent', 'failed', "
        "'unknown_delivery_state', 'suppressed')",
        name="ck_alert_delivery_status",
    ),
    sa.Column("cadence", sa.String(16), nullable=False),
    # Empreinte du contexte destinataire au moment où le lot est créé. Elle
    # lie le lot à une adresse/préférence/droit vérifiables sans persister une
    # seconde copie de l'adresse ni journaliser les entrées de l'empreinte.
    sa.Column("recipient_context_fingerprint", sa.String(64)),
    sa.Column("batch_key", sa.String(64), index=True),
    sa.Column("delivery_message_id", sa.String(255)),
    sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("sent_at", sa.DateTime(timezone=True), index=True),
    sa.Column("failed_at", sa.DateTime(timezone=True)),
    sa.Column("attempt_count", sa.Integer, nullable=False),
    sa.Column("retryable", sa.Boolean, nullable=True),
    sa.Column("attempt_started_at", sa.DateTime(timezone=True)),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True), index=True),
    sa.Column("next_attempt_at", sa.DateTime(timezone=True), index=True),
    sa.Column("provider_message_id", sa.String(255)),
    # Un CODE, jamais une trace d'exception : une pile d'appels d'un fournisseur
    # SMTP contient parfois l'adresse, parfois l'identifiant de connexion.
    sa.Column("last_error_code", sa.String(64)),
    sa.Column("suppressed_at", sa.DateTime(timezone=True)),
    sa.Column("suppression_reason_code", sa.String(64)),
    *_timestamps(),
)

sa.Index(
    "ix_signal_alert_delivery_recipient_context_refusal",
    signal_alert_delivery.c.account_id,
    signal_alert_delivery.c.recipient_context_fingerprint,
    signal_alert_delivery.c.status,
    signal_alert_delivery.c.last_error_code,
)


signal_alert_job_lease = sa.Table(
    "signal_alert_job_lease",
    METADATA,
    sa.Column("job_name", sa.String(64), primary_key=True),
    sa.Column("owner_id", sa.String(64), nullable=False),
    sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


ENGAGEMENT_TABLES: tuple[sa.Table, ...] = (
    signal_feedback,
    signal_note,
    product_event,
    account_notification_preference,
    signal_alert_delivery,
    signal_alert_job_lease,
    company_contact,
    company_note,
)
