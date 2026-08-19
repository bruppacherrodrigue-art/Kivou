"""Narrow durable state for the one-shot production ingestion runtime."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_ingestion_runtime"
down_revision = "0004_alerts_feedback_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_checkpoint",
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("cursor", sa.JSON(), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('simap', 'boamp', 'decp', 'ted')",
            name="ck_ingestion_checkpoint_source",
        ),
        sa.PrimaryKeyConstraint("source"),
    )
    op.create_table(
        "ingestion_run",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("records_fetched", sa.Integer(), nullable=False),
        sa.Column("records_accepted", sa.Integer(), nullable=False),
        sa.Column("records_rejected", sa.Integer(), nullable=False),
        sa.Column("records_persisted", sa.Integer(), nullable=False),
        sa.Column("representations_linked", sa.Integer(), nullable=False),
        sa.Column("opportunity_conflicts", sa.Integer(), nullable=False),
        sa.Column("signals_materialized", sa.Integer(), nullable=False),
        sa.Column("rate_limited_count", sa.Integer(), nullable=False),
        sa.Column("error_category", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("checkpoint_before", sa.JSON(), nullable=True),
        sa.Column("checkpoint_after", sa.JSON(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "source IN ('simap', 'boamp', 'decp', 'ted')",
            name="ck_ingestion_run_source",
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_ingestion_run_source", "ingestion_run", ["source"], unique=False)
    op.create_index("ix_ingestion_run_status", "ingestion_run", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ingestion_run_status", table_name="ingestion_run")
    op.drop_index("ix_ingestion_run_source", table_name="ingestion_run")
    op.drop_table("ingestion_run")
    op.drop_table("ingestion_checkpoint")
