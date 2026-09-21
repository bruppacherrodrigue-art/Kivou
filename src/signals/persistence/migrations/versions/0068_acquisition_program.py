"""Add configured acquisition program identity and evidence snapshots.

Revision ID: 0068_acquisition_program
Revises: 0067_acceptance_error_cleanup
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0068_acquisition_program"
down_revision = "0067_acceptance_error_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_program",
        sa.Column("program_id", sa.String(64), primary_key=True),
        sa.Column("program_key", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("config_fingerprint", sa.String(64), nullable=False),
        sa.Column("config_snapshot", sa.JSON, nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("program_key", "config_fingerprint", name="uq_acquisition_program_version"),
        sa.CheckConstraint(
            "mode IN ('SHADOW', 'ASSISTED_REVIEW', 'AUTONOMOUS_CAPPED', 'LIVE')",
            name="ck_acquisition_program_mode",
        ),
    )
    op.create_index("ix_acquisition_program_key", "acquisition_program", ["program_key"])
    op.create_table(
        "acquisition_program_eligibility",
        sa.Column("eligibility_id", sa.String(64), primary_key=True),
        sa.Column("program_id", sa.String(64), sa.ForeignKey("acquisition_program.program_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("acquisition_opportunity_id", sa.String(64), sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("supplier_ref", sa.String(64), sa.ForeignKey("acquisition_supplier.supplier_ref", ondelete="RESTRICT")),
        sa.Column("contact_ref", sa.String(64), sa.ForeignKey("acquisition_contact.contact_ref", ondelete="RESTRICT")),
        sa.Column("mail_provider", sa.String(32), nullable=False),
        sa.Column("wedge_key", sa.String(64)),
        sa.Column("provider_confidence", sa.String(16), nullable=False),
        sa.Column("provider_evidence", sa.JSON, nullable=False),
        sa.Column("recipient_capacity", sa.String(32), nullable=False),
        sa.Column("professional_evidence", sa.JSON, nullable=False),
        sa.Column("fit_score", sa.Integer, nullable=False),
        sa.Column("fit_breakdown", sa.JSON, nullable=False),
        sa.Column("mail_pain_score", sa.Integer, nullable=False),
        sa.Column("score_version", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason_codes", sa.JSON, nullable=False),
        sa.Column("policy_country", sa.String(2), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("evidence_ids", sa.JSON, nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_expires_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("program_id", "acquisition_opportunity_id", "evaluated_at", name="uq_acquisition_program_eligibility_evaluation"),
        sa.CheckConstraint("fit_score >= 0 AND fit_score <= 100", name="ck_program_fit_score"),
        sa.CheckConstraint("mail_pain_score >= 0 AND mail_pain_score <= 100", name="ck_program_mail_pain_score"),
        sa.CheckConstraint("decision IN ('SEND', 'HOLD', 'NO_SEND')", name="ck_program_eligibility_decision"),
    )
    op.create_index("ix_acquisition_program_eligibility_program_id", "acquisition_program_eligibility", ["program_id"])
    op.create_index("ix_acquisition_program_eligibility_acquisition_opportunity_id", "acquisition_program_eligibility", ["acquisition_opportunity_id"])
    op.create_index("ix_program_eligibility_decision_time", "acquisition_program_eligibility", ["program_id", "decision", "evaluated_at"])
    op.create_table(
        "acquisition_program_attribution",
        sa.Column("attribution_id", sa.String(64), primary_key=True),
        sa.Column("program_id", sa.String(64), sa.ForeignKey("acquisition_program.program_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("acquisition_opportunity_id", sa.String(64), sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("campaign_ref", sa.String(64)),
        sa.Column("opaque_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_version", sa.String(64), nullable=False),
        sa.Column("recipient_identity_hmac", sa.String(64), nullable=False),
        sa.Column("recipient_identity_key_version", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expires_at > issued_at", name="ck_program_attribution_interval"),
    )
    op.create_index("ix_acquisition_program_attribution_program_id", "acquisition_program_attribution", ["program_id"])


def downgrade() -> None:
    op.drop_index("ix_acquisition_program_attribution_program_id", table_name="acquisition_program_attribution")
    op.drop_table("acquisition_program_attribution")
    op.drop_index("ix_program_eligibility_decision_time", table_name="acquisition_program_eligibility")
    op.drop_index("ix_acquisition_program_eligibility_acquisition_opportunity_id", table_name="acquisition_program_eligibility")
    op.drop_index("ix_acquisition_program_eligibility_program_id", table_name="acquisition_program_eligibility")
    op.drop_table("acquisition_program_eligibility")
    op.drop_index("ix_acquisition_program_key", table_name="acquisition_program")
    op.drop_table("acquisition_program")
