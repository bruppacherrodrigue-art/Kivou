"""Le signal promis par le cold mail, attaché au compte qu'il a créé.

Revision ID: 0035_landing_signal
Revises: 0034_company_engagement
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_landing_signal"
down_revision = "0034_company_engagement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Table à part, pas une colonne sur `account` : sous SQLite,
    # `batch_alter_table("account")` recopierait la table, et la recopie
    # déclenche les `ON DELETE CASCADE` de toutes ses tables filles
    # (`target_icp`, `auth_user`, …), qui se videraient au passage.
    op.create_table(
        "account_landing_signal",
        sa.Column(
            "account_id",
            sa.String(64),
            sa.ForeignKey("account.account_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # Ce que le mail promettait, quand le résolveur d'attribution a pu
        # l'attacher au jeton. NULLABLE : cette ligne doit s'écrire même quand
        # ce n'est pas le cas, car c'est elle — et non `opportunity_key` — qui
        # sert à reconnaître un rejeu du même jeton (fix revue PR2b tâche 5).
        sa.Column("opportunity_key", sa.String(64), nullable=True),
        # Connue seulement une fois l'opportunité matérialisée pour un ICP de ce
        # compte. Aucune clé étrangère : un signal peut être rematérialisé ou
        # invalidé, et la promesse faite au prospect lui survit.
        sa.Column("signal_key", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("account_landing_signal")
