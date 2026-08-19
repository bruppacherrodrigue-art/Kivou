"""Add Kivou-owned acquisition event journal and current-state projection."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_acquisition_event_store"
down_revision = "0006_award_text_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_opportunity",
        sa.Column("acquisition_opportunity_id", sa.String(64), primary_key=True),
        sa.Column("identity_key", sa.String(256), nullable=False, unique=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("stream_version", sa.Integer(), nullable=False),
        sa.Column("state_machine_version", sa.String(64), nullable=False),
        sa.Column("signal_ref", sa.String(256), nullable=False),
        sa.Column("supplier_ref", sa.String(256)),
        sa.Column("contact_ref", sa.String(256)),
        sa.Column("campaign_ref", sa.String(256)),
        sa.Column("decision", sa.String(16)),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("next_action", sa.String(100)),
        sa.Column("next_review_at", sa.DateTime(timezone=True)),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_category", sa.String(100)),
        sa.Column("policy_version", sa.String(100)),
        sa.Column("skill_version", sa.String(100)),
        sa.Column("supervisor_version", sa.String(100)),
        sa.Column("estimated_cost", sa.Numeric(18, 6)),
        sa.Column("last_event_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "stream_version >= 1", name="ck_acquisition_opportunity_stream_version"
        ),
        sa.CheckConstraint(
            "retry_count >= 0", name="ck_acquisition_opportunity_retry_count"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_acquisition_opportunity_confidence",
        ),
        sa.CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name="ck_acquisition_opportunity_estimated_cost",
        ),
    )
    op.create_index(
        "ix_acquisition_opportunity_state", "acquisition_opportunity", ["state"]
    )
    op.create_index(
        "ix_acquisition_opportunity_next_review_at",
        "acquisition_opportunity",
        ["next_review_at"],
    )
    op.create_index(
        "ix_acquisition_opportunity_retry_at",
        "acquisition_opportunity",
        ["retry_at"],
    )
    op.create_table(
        "acquisition_event",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("acquisition_opportunity_id", sa.String(64), nullable=False),
        sa.Column("stream_sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("state_machine_version", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_ref", sa.String(256)),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("semantic_fingerprint", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("causation_id", sa.String(64)),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(100)),
        sa.Column("skill_version", sa.String(100)),
        sa.Column("supervisor_version", sa.String(100)),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("estimated_cost", sa.Numeric(18, 6)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["acquisition_opportunity_id"],
            ["acquisition_opportunity.acquisition_opportunity_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "acquisition_opportunity_id",
            "stream_sequence",
            name="uq_acquisition_event_stream_sequence",
        ),
        sa.UniqueConstraint(
            "acquisition_opportunity_id",
            "idempotency_key",
            name="uq_acquisition_event_idempotency",
        ),
        sa.CheckConstraint(
            "stream_sequence >= 1", name="ck_acquisition_event_stream_sequence"
        ),
        sa.CheckConstraint(
            "schema_version >= 1", name="ck_acquisition_event_schema_version"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_acquisition_event_confidence",
        ),
        sa.CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name="ck_acquisition_event_estimated_cost",
        ),
    )
    op.create_index(
        "ix_acquisition_event_recorded_at", "acquisition_event", ["recorded_at"]
    )


def downgrade() -> None:
    op.drop_table("acquisition_event")
    op.drop_table("acquisition_opportunity")
