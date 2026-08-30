"""Add versioned, pre-generated card presentation artifacts.

Revision ID: 0028_card_presentation
Revises: 0027_signal_notes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_card_presentation"
down_revision = "0027_signal_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_presentation_artifact",
        sa.Column("artifact_id", sa.String(64), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(64),
            sa.ForeignKey("account.account_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "signal_key",
            sa.String(64),
            sa.ForeignKey("materialized_signal.signal_key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_icp_id",
            sa.String(128),
            sa.ForeignKey("target_icp.target_icp_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_kind", sa.String(32), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("signal_revision", sa.Integer, nullable=False),
        sa.Column("target_icp_revision", sa.Integer, nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(128)),
        sa.Column("provider", sa.String(64)),
        sa.Column("input_snapshot", sa.JSON, nullable=False),
        sa.Column("payload", sa.JSON),
        sa.Column("qa_status", sa.String(16), nullable=False),
        sa.Column("qa_reasons", sa.JSON, nullable=False),
        sa.Column("qa_model_id", sa.String(128)),
        sa.Column("qa_provider", sa.String(64)),
        sa.Column("qa_policy_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "account_id",
            "signal_key",
            "target_icp_id",
            "artifact_kind",
            "language",
            "version",
            name="uq_card_presentation_version",
        ),
        sa.CheckConstraint(
            "version >= 1 AND signal_revision >= 1 AND target_icp_revision >= 1",
            name="ck_card_presentation_version",
        ),
        sa.CheckConstraint(
            "artifact_kind IN ('AWARD_SUMMARY', 'SIGNAL_CARD')",
            name="ck_card_presentation_kind",
        ),
        sa.CheckConstraint(
            "qa_status IN ('PASS', 'REGENERATE', 'FALLBACK', 'REVIEW')",
            name="ck_card_presentation_qa_status",
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR "
            "(qa_status IN ('PASS', 'FALLBACK') AND payload IS NOT NULL)",
            name="ck_card_presentation_publishable_status",
        ),
    )
    op.create_index(
        "ix_card_presentation_artifact_account_id",
        "card_presentation_artifact",
        ["account_id"],
    )
    op.create_index(
        "ix_card_presentation_artifact_signal_key",
        "card_presentation_artifact",
        ["signal_key"],
    )
    op.create_index(
        "ix_card_presentation_artifact_target_icp_id",
        "card_presentation_artifact",
        ["target_icp_id"],
    )
    op.create_index(
        "ix_card_presentation_artifact_qa_status",
        "card_presentation_artifact",
        ["qa_status"],
    )
    op.create_index(
        "ix_card_presentation_published",
        "card_presentation_artifact",
        [
            "account_id",
            "signal_key",
            "target_icp_id",
            "artifact_kind",
            "language",
            "superseded_at",
        ],
    )


def downgrade() -> None:
    op.drop_table("card_presentation_artifact")
