"""Persist the scheduled plan change, and give each change an identity.

Revision ID: 0024_scheduled_plan_change
Revises: 0023_transactional_email_runtime

Pourquoi cet état vit en base
─────────────────────────────
Annoncer « vous descendrez le 1er » demandait d'interroger Stripe à CHAQUE
lecture de `/billing/status` — un à deux appels réseau sur un écran que le
tableau de bord consulte deux fois. Attraper l'erreur évitait le plantage, pas
la latence, et laissait un parcours financier dépendre d'un tiers pour afficher
des droits déjà payés. L'état programmé est donc écrit ici, APRÈS confirmation
du schedule par Stripe, et la lecture redevient entièrement locale.

`plan_change_sequence` donne une IDENTITÉ à chaque changement
─────────────────────────────────────────────────────────────
La clé d'idempotence Stripe doit être stable pour une nouvelle tentative de la
même action, et différente pour deux changements volontairement distincts.
Composer la clé du seul couple (formule de départ, formule visée) échoue sur
A → B → A → B : la quatrième opération réutiliserait la clé de la première et
Stripe rendrait sa réponse en cache — le client ne changerait pas de formule.
Un compteur monotone par abonnement tranche sans ambiguïté.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_scheduled_plan_change"
down_revision = "0023_transactional_email_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # La formule VISÉE et son échéance. `NULL` = aucun changement programmé ;
    # les droits courants restent ceux de `plan_code`, qui ne bouge qu'au terme.
    op.add_column("billing_subscription", sa.Column("scheduled_plan_code", sa.String(32)))
    op.add_column(
        "billing_subscription",
        sa.Column("scheduled_plan_change_at", sa.DateTime(timezone=True)),
    )
    # Le schedule Stripe qui porte la transition, conservé pour la réconcilier
    # et pour ne jamais relâcher un objet qui ne serait pas le nôtre.
    op.add_column(
        "billing_subscription", sa.Column("stripe_schedule_id", sa.String(128))
    )
    # Monotone, jamais décrémenté : il numérote les changements de formule d'un
    # abonnement et donne à chacun une clé d'idempotence distincte.
    op.add_column(
        "billing_subscription",
        sa.Column(
            "plan_change_sequence",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("billing_subscription", "plan_change_sequence")
    op.drop_column("billing_subscription", "stripe_schedule_id")
    op.drop_column("billing_subscription", "scheduled_plan_change_at")
    op.drop_column("billing_subscription", "scheduled_plan_code")
