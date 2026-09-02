"""Requeue existing numeric SIRET winners for official-name resolution.

Revision ID: 0032_requeue_siret_placeholders
Revises: 0031_french_official_company
"""

from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op

revision = "0032_requeue_siret_placeholders"
down_revision = "0031_french_official_company"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    candidates = connection.execute(
        sa.text(
            "SELECT wej.signal_key, ms.winner_name, ms.winner_identifier_value "
            "FROM winner_enrichment_job wej "
            "JOIN materialized_signal ms ON ms.signal_key = wej.signal_key "
            "WHERE wej.status = 'partial' "
            "AND upper(ms.winner_identifier_scheme) = 'SIRET'"
        )
    ).mappings()
    signal_keys = [
        row["signal_key"]
        for row in candidates
        if re.fullmatch(r"\d{14}", (row["winner_identifier_value"] or "").strip())
        and (row["winner_name"] or "").strip()
        == (row["winner_identifier_value"] or "").strip()
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
