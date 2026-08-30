"""Add versioned Card Intelligence presentation artifacts.

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
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("signal_key", sa.String(64), nullable=False),
        sa.Column("signal_revision", sa.Integer, nullable=False),
        sa.Column("target_icp_id", sa.String(128), nullable=False),
        sa.Column("target_icp_revision", sa.Integer, nullable=False),
        sa.Column("artifact_kind", sa.String(32), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(none_as_null=True)),
        sa.Column("payload_variant", sa.String(32)),
        sa.Column("qa_status", sa.String(16), nullable=False),
        sa.Column("qa_reasons", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("qa_policy_version", sa.String(128), nullable=False),
        sa.Column("generator_version", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(128)),
        sa.Column("model_id", sa.String(256)),
        sa.Column("provider", sa.String(128)),
        sa.Column("qa_model_id", sa.String(256)),
        sa.Column("qa_provider", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.account_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_key"],
            ["materialized_signal.signal_key"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_icp_id"],
            ["target_icp.target_icp_id"],
            ondelete="RESTRICT",
        ),
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
            sa.column("artifact_id").regexp_match(r"^[0-9a-f]{64}$"),
            name="ck_card_presentation_artifact_id",
        ),
        sa.CheckConstraint(
            sa.column("input_fingerprint").regexp_match(r"^[0-9a-f]{64}$"),
            name="ck_card_presentation_input_fingerprint",
        ),
        sa.CheckConstraint(
            "signal_revision >= 1",
            name="ck_card_presentation_signal_revision",
        ),
        sa.CheckConstraint(
            "target_icp_revision >= 1",
            name="ck_card_presentation_target_icp_revision",
        ),
        sa.CheckConstraint("version >= 1", name="ck_card_presentation_version"),
        sa.CheckConstraint(
            "artifact_kind = 'CARD_PRESENTATION'",
            name="ck_card_presentation_artifact_kind",
        ),
        sa.CheckConstraint(
            "language IN ('fr', 'en')",
            name="ck_card_presentation_language",
        ),
        sa.CheckConstraint(
            "qa_status IN ('PASS', 'REGENERATE', 'FALLBACK', 'REVIEW')",
            name="ck_card_presentation_qa_status",
        ),
        sa.CheckConstraint(
            sa.and_(
                sa.func.length(sa.column("qa_policy_version")).between(1, 128),
                sa.column("qa_policy_version").regexp_match(r"[0-9A-Za-z]"),
            ),
            name="ck_card_presentation_qa_policy_version",
        ),
        sa.CheckConstraint(
            sa.and_(
                sa.func.length(sa.column("generator_version")).between(1, 128),
                sa.column("generator_version").regexp_match(r"[0-9A-Za-z]"),
            ),
            name="ck_card_presentation_generator_version",
        ),
        sa.CheckConstraint(
            "payload_variant IS NULL OR "
            "payload_variant IN ('FULL', 'FACTUAL_FALLBACK')",
            name="ck_card_presentation_payload_variant",
        ),
        sa.CheckConstraint(
            "payload_variant IS NULL OR payload IS NOT NULL",
            name="ck_card_presentation_payload_binding",
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR "
            "(payload IS NOT NULL AND payload_variant IS NOT NULL AND "
            "((qa_status = 'PASS' AND payload_variant = 'FULL') OR "
            "(qa_status = 'FALLBACK' AND payload_variant = 'FACTUAL_FALLBACK')))",
            name="ck_card_presentation_publishable_pair",
        ),
        sa.CheckConstraint(
            "qa_status <> 'FALLBACK' OR "
            "(provider IS NULL AND model_id IS NULL AND prompt_version IS NULL "
            "AND qa_provider IS NULL AND qa_model_id IS NULL)",
            name="ck_card_presentation_fallback_offline",
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR created_at <= published_at",
            name="ck_card_presentation_created_published_order",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR "
            "(published_at IS NOT NULL AND published_at <= superseded_at)",
            name="ck_card_presentation_published_superseded_order",
        ),
    )
    op.create_index(
        "ix_card_presentation_tenant_read",
        "card_presentation_artifact",
        [
            "account_id",
            "language",
            "artifact_kind",
            "signal_key",
            "signal_revision",
            "target_icp_revision",
        ],
    )
    op.create_index(
        "uq_card_presentation_active_publication",
        "card_presentation_artifact",
        [
            "account_id",
            "signal_key",
            "target_icp_id",
            "artifact_kind",
            "language",
        ],
        unique=True,
        sqlite_where=sa.text("published_at IS NOT NULL AND superseded_at IS NULL"),
        postgresql_where=sa.text("published_at IS NOT NULL AND superseded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("card_presentation_artifact")
