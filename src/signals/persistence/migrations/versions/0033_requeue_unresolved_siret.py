"""Requeue exact SIRET jobs that predate the official fallback.

Revision ID: 0033_requeue_unresolved_siret
Revises: 0032_requeue_siret_placeholders
"""

from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op

revision = "0033_requeue_unresolved_siret"
down_revision = "0032_requeue_siret_placeholders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT wej.signal_key, ms.winner_country, "
            "ms.winner_identifier_scheme, ms.winner_identifier_value "
            "FROM winner_enrichment_job wej "
            "JOIN materialized_signal ms ON ms.signal_key = wej.signal_key "
            "WHERE wej.status = 'failed'"
        )
    ).mappings()
    signal_keys = [
        row["signal_key"]
        for row in rows
        if str(row["winner_identifier_scheme"] or "").strip().casefold() == "siret"
        and str(row["winner_country"] or "FR").strip().upper() == "FR"
        and re.fullmatch(
            r"\d{14}", str(row["winner_identifier_value"] or "").strip()
        )
    ]
    if not signal_keys:
        return
    jobs = sa.table(
        "winner_enrichment_job",
        sa.column("signal_key", sa.String),
        sa.column("status", sa.String),
        sa.column("attempt_count", sa.Integer),
        sa.column("error_code", sa.String),
        sa.column("claimed_by", sa.String),
        sa.column("queued_at", sa.DateTime(timezone=True)),
        sa.column("started_at", sa.DateTime(timezone=True)),
        sa.column("finished_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = sa.func.now()
    connection.execute(
        sa.update(jobs)
        .where(jobs.c.signal_key.in_(signal_keys))
        .values(
            status="pending",
            attempt_count=0,
            error_code=None,
            claimed_by=None,
            queued_at=now,
            started_at=None,
            finished_at=None,
            updated_at=now,
        )
    )


def downgrade() -> None:
    # Queue state is operational history and cannot be reconstructed safely.
    pass
