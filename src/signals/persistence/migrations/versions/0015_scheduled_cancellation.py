"""Record the scheduled cancellation date Stripe actually publishes.

P0-03G — jusqu'ici Kivou ne stockait qu'un booléen, `cancel_at_period_end`. Sur
un abonnement `billing_mode: flexible`, Stripe laisse ce booléen à `false` et
exprime la résiliation par une DATE, `cancel_at`. La résiliation était donc
reçue, appliquée — et invisible.

Purement additive : une colonne nullable, aucune table touchée, aucune donnée
réécrite. Les abonnements existants la portent à `NULL`, ce qui décrit
exactement leur état : aucune échéance connue tant qu'un webhook n'en apporte
une.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_scheduled_cancellation"
down_revision = "0014_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "billing_subscription",
        sa.Column("scheduled_cancellation_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("billing_subscription", "scheduled_cancellation_at")
