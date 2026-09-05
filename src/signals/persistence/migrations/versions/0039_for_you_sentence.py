"""Add durable asynchronous for-you sentence cache.

Revision ID: 0039_for_you_sentence
Revises: 0038_landing_journey
"""

import sqlalchemy as sa
from alembic import op

revision = "0039_for_you_sentence"
down_revision = "0038_landing_journey"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "for_you_sentence",
        sa.Column("for_you_id", sa.String(64), primary_key=True),
        sa.Column("signal_key", sa.String(64), sa.ForeignKey("materialized_signal.signal_key", ondelete="CASCADE"), nullable=False),
        sa.Column("target_icp_id", sa.String(128), sa.ForeignKey("target_icp.target_icp_id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_fingerprint", sa.String(64), nullable=False),
        sa.Column("profile_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("sentence", sa.Text, nullable=False),
        sa.Column("fallback_sentence", sa.Text, nullable=False),
        sa.Column("provenance", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("validation_reason", sa.String(32)),
        sa.Column("validation_detail", sa.String(256)),
        sa.Column("attempt_day", sa.Date),
        sa.Column("lease_owner", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("input_snapshot", sa.JSON, nullable=False),
        sa.Column("provider_usage", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("signal_key", "target_icp_id", "signal_fingerprint", "profile_fingerprint", "policy_version", name="uq_for_you_pair_version"),
        sa.CheckConstraint("state IN ('pending', 'running', 'completed')", name="ck_for_you_state"),
        sa.CheckConstraint("provenance IN ('fallback', 'generated')", name="ck_for_you_provenance"),
        sa.CheckConstraint("validation_reason IS NULL OR validation_reason IN ('provider_unavailable', 'invalid_shape', 'too_many_words', 'exclamation', 'superlative', 'invented_number', 'invented_date', 'invented_name_or_place')", name="ck_for_you_validation_reason"),
    )
    op.create_index("ix_for_you_sentence_signal_key", "for_you_sentence", ["signal_key"])
    op.create_index("ix_for_you_sentence_target_icp_id", "for_you_sentence", ["target_icp_id"])
    op.create_index("ix_for_you_sentence_state", "for_you_sentence", ["state"])
    op.create_index("ix_for_you_sentence_attempt_day", "for_you_sentence", ["attempt_day"])
    op.create_index("ix_for_you_sentence_lease_expires_at", "for_you_sentence", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_table("for_you_sentence")
