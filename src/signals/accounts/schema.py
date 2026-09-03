"""Comptes, authentification et ICP client — les tables de SPEC-011.

Elles s'enregistrent dans le **même** `METADATA` que la persistance de
SPEC-010 : une seule base, une seule chaîne de migrations, un seul endroit où
lire le schéma complet. Aucune table de SPEC-010 n'est modifiée.

    Account 1 ─── N AuthUser
    Account 1 ─── N TargetICP 1 ─── N MaterializedSignal

    Ce qui n'est PAS stocké
    ───────────────────────
    Aucun mot de passe en clair, aucun jeton de session en clair, aucun jeton de
    réinitialisation en clair. La base ne contient que des empreintes : un vol de
    dump ne donne ni accès ni identité.
"""

from __future__ import annotations

import sqlalchemy as sa

from signals.persistence.schema import METADATA

#: §15 — français et anglais, et rien d'autre tant que le produit n'en parle pas.
SUPPORTED_LOCALES: tuple[str, ...] = ("fr", "en")

#: §14 — trois états déterministes, pas un moteur de workflow.
ONBOARDING_STATES: tuple[str, ...] = (
    "account_created",
    "icp_incomplete",
    "ready_for_signals",
)

#: Un ICP est `active` quand son entrée client se traduit en `TargetICP` valide.
TARGET_ICP_STATUSES: tuple[str, ...] = ("draft", "active")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


account = sa.Table(
    "account",
    METADATA,
    sa.Column("account_id", sa.String(64), primary_key=True),
    sa.Column("display_name", sa.String(256), nullable=False),
    sa.Column("locale", sa.String(8), nullable=False),
    sa.Column("onboarding_status", sa.String(32), nullable=False),
    *_timestamps(),
)


#: PR1 §4/§5 — la dernière visite du tableau de bord, dans une table à part.
#: Une colonne sur `account` exigerait `batch_alter_table` sous SQLite, dont la
#: recopie de table déclenche les `ON DELETE CASCADE` de toutes les tables
#: filles (`target_icp`, `auth_user`, …) et les vide. Absence de ligne = compte
#: jamais vu (§5 : `previous_seen` est alors `null`).
account_visit = sa.Table(
    "account_visit",
    METADATA,
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


#: PR2b tâche 5 — le signal PROMIS par le cold mail qui a créé ce compte.
#: Table à part pour la même raison qu'`account_visit` : sous SQLite,
#: `batch_alter_table("account")` recopie la table et la recopie déclenche les
#: `ON DELETE CASCADE` de ses filles.
#:
#: `opportunity_key` est connue dès que le jeton en porte une — ce que le mail
#: promettait. Elle reste NULLABLE : un jeton dont le résolveur d'attribution
#: n'a rien pu attacher (opportunité introuvable au moment de l'émission, par
#: exemple) doit quand même écrire cette ligne, car c'est ELLE — pas
#: `opportunity_key` — que `landed_account_in_transaction` utilise pour
#: reconnaître un rejeu du même jeton. La rendre obligatoire aurait fait
#: échouer silencieusement la reconnaissance de rejeu chaque fois que la
#: résolution de l'opportunité échoue, un cas qui n'a rien d'un jeton
#: falsifié ou périmé.
#: `signal_key` ne l'est qu'une fois l'opportunité MATÉRIALISÉE pour un ICP de
#: ce compte, ce qui n'arrive pas au premier clic : un compte neuf n'a encore
#: aucun profil actif. La colonne reste donc nulle jusque-là, et l'atterrissage
#: retombe sur le feed plutôt que d'inventer une page.
account_landing_signal = sa.Table(
    "account_landing_signal",
    METADATA,
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("opportunity_key", sa.String(64), nullable=True),
    sa.Column("signal_key", sa.String(64)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)


auth_user = sa.Table(
    "auth_user",
    METADATA,
    sa.Column("user_id", sa.String(64), primary_key=True),
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    # Une seule forme de l'adresse est conservée : la forme normalisée. Garder
    # la casse saisie n'apporterait rien au produit — Kivou n'affiche jamais
    # l'adresse à un tiers — et créerait deux vérités pour une même identité.
    sa.Column("email_normalized", sa.String(320), nullable=False, unique=True),
    # Empreinte Argon2id, jamais le mot de passe.
    sa.Column("password_hash", sa.Text, nullable=False),
    sa.Column("is_active", sa.Boolean, nullable=False),
    sa.Column("last_login_at", sa.DateTime(timezone=True)),
    *_timestamps(),
)


auth_session = sa.Table(
    "auth_session",
    METADATA,
    sa.Column("session_id", sa.String(64), primary_key=True),
    sa.Column(
        "user_id",
        sa.String(64),
        sa.ForeignKey("auth_user.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    # Le navigateur détient le jeton ; la base n'en détient que l'empreinte.
    sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
)


password_reset = sa.Table(
    "password_reset",
    METADATA,
    sa.Column("reset_id", sa.String(64), primary_key=True),
    sa.Column(
        "user_id",
        sa.String(64),
        sa.ForeignKey("auth_user.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    # Usage unique : renseigné une fois, jamais remis à zéro.
    sa.Column("used_at", sa.DateTime(timezone=True)),
)


target_icp = sa.Table(
    "target_icp",
    METADATA,
    # C'est cet identifiant que `materialized_signal.target_icp_id` désigne.
    sa.Column("target_icp_id", sa.String(128), primary_key=True),
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("label", sa.String(256), nullable=False),
    sa.Column("status", sa.String(16), nullable=False, index=True),
    # La révision ne suit que les critères utilisés par le moteur. Renommer le
    # profil ou modifier sa description libre ne change donc pas cette valeur.
    sa.Column("matching_revision", sa.Integer, nullable=False),
    # Une limite de plan n'efface ni ne tronque la saisie. Elle rend le profil
    # explicitement non exploitable jusqu'au choix du client.
    sa.Column("plan_limit_code", sa.String(64), index=True),
    sa.Column("plan_limited_at", sa.DateTime(timezone=True)),
    # L'entrée CLIENT, dans son vocabulaire. C'est la source de vérité : la
    # représentation moteur en est dérivée déterministement, jamais l'inverse.
    sa.Column("customer_input", sa.JSON, nullable=False),
    *_timestamps(),
    sa.CheckConstraint("matching_revision >= 1", name="ck_target_icp_matching_revision"),
)
