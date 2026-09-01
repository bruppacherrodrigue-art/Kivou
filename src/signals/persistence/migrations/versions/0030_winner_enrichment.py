"""Add durable, asynchronous state for factual winner enrichment.

Revision ID: 0030_winner_enrichment
Revises: 0029_production_observation

The backfill is deliberately set based and offline: it classifies public facts
already stored by Kivou and performs no connector or network call.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_winner_enrichment"
down_revision = "0029_production_observation"
branch_labels = None
depends_on = None

TABLE_NAME = "winner_enrichment_job"


def upgrade() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("signal_key", sa.String(64), primary_key=True),
        sa.Column("identity_fingerprint", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("claimed_by", sa.String(64)),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["signal_key"], ["materialized_signal.signal_key"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'partial', 'failed')",
            name="ck_winner_enrichment_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3",
            name="ck_winner_enrichment_attempt_count",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND attempt_count = 0 AND started_at IS NULL "
            "AND finished_at IS NULL) OR "
            "(status = 'in_progress' AND attempt_count >= 1 AND started_at IS NOT NULL "
            "AND finished_at IS NULL) OR "
            "(status IN ('completed', 'partial', 'failed') AND attempt_count >= 1 "
            "AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="ck_winner_enrichment_lifecycle",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND claimed_by IS NULL) OR "
            "(status <> 'pending' AND claimed_by IS NOT NULL)",
            name="ck_winner_enrichment_claim",
        ),
        sa.CheckConstraint(
            "(status = 'failed' AND error_code IS NOT NULL) OR "
            "(status <> 'failed' AND error_code IS NULL)",
            name="ck_winner_enrichment_error",
        ),
    )
    op.create_index(
        "ix_winner_enrichment_status_queued",
        TABLE_NAME,
        ["status", "queued_at", "signal_key"],
    )
    op.create_index(
        "ix_winner_enrichment_identity", TABLE_NAME, ["identity_fingerprint"]
    )

    # A company row means an earlier authorised GET already projected the
    # exact public identity.  Complete requires every core factual field;
    # otherwise it is honestly partial.  An indexed winner without a company
    # row remains pending for the explicit worker introduced by Phase 1. Every
    # existing signal is queued, including unresolved identities, so the
    # migration never creates a silent hole in the enrichment state model.
    op.execute(
        sa.text(
            """
            INSERT INTO winner_enrichment_job (
                signal_key, identity_fingerprint, status, attempt_count,
                error_code, claimed_by, queued_at, started_at, finished_at,
                updated_at
            )
            SELECT
                ms.signal_key,
                ms.company_identity_fingerprint,
                CASE
                    WHEN sc.company_key IS NULL THEN 'pending'
                    WHEN TRIM(sc.official_name) <> ''
                         AND sc.official_country IS NOT NULL
                         AND sc.official_address IS NOT NULL
                         AND sc.identity_method IN ('official_identifier', 'official_domain')
                         AND sc.official_website_url IS NOT NULL
                    THEN 'completed'
                    ELSE 'partial'
                END,
                CASE WHEN sc.company_key IS NULL THEN 0 ELSE 1 END,
                NULL,
                CASE WHEN sc.company_key IS NULL THEN NULL ELSE 'migration-0030' END,
                ms.created_at,
                CASE WHEN sc.company_key IS NULL THEN NULL ELSE sc.updated_at END,
                CASE WHEN sc.company_key IS NULL THEN NULL ELSE sc.updated_at END,
                COALESCE(sc.updated_at, ms.created_at)
            FROM materialized_signal AS ms
            LEFT JOIN saas_company AS sc
              ON sc.identity_fingerprint = ms.company_identity_fingerprint
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_winner_enrichment_identity", table_name=TABLE_NAME)
    op.drop_index("ix_winner_enrichment_status_queued", table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
