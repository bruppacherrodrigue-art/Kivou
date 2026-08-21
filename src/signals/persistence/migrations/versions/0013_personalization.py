"""Add immutable deterministic acquisition personalization artifacts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_personalization"
down_revision = "0012_decision_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_personalization_artifact",
        sa.Column("personalization_artifact_id", sa.String(64), primary_key=True),
        sa.Column("acquisition_opportunity_id", sa.String(64), nullable=False),
        sa.Column("supplier_ref", sa.String(64), nullable=False),
        sa.Column("contact_ref", sa.String(64), nullable=False),
        sa.Column("policy_evaluation_id", sa.String(64), nullable=False, unique=True),
        sa.Column("decision_evaluation_id", sa.String(64), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("input_version", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("eligibility_fingerprint", sa.String(64), nullable=False),
        sa.Column("need_engine_version", sa.String(64), nullable=False),
        sa.Column("selected_need_fingerprint", sa.String(64), nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("catalog_version", sa.String(64), nullable=False),
        sa.Column("language_policy_version", sa.String(64), nullable=False),
        sa.Column("proposal_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_action_fingerprint", sa.String(64), nullable=False),
        sa.Column("artifact_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("claim_map", sa.JSON(), nullable=False),
        sa.Column("subject", sa.String(90)),
        sa.Column("greeting", sa.String(80)),
        sa.Column("body", sa.String(700)),
        sa.Column("cta", sa.String(256)),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("policy_status", sa.String(32), nullable=False),
        sa.Column("policy_counterfactual_status", sa.String(32)),
        sa.Column("recorded_event_id", sa.String(64), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["acquisition_opportunity_id"], ["acquisition_opportunity.acquisition_opportunity_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_ref"], ["acquisition_supplier.supplier_ref"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_ref"], ["acquisition_contact.contact_ref"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["policy_evaluation_id"], ["policy_evaluation.evaluation_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decision_evaluation_id"], ["acquisition_decision_evaluation.decision_evaluation_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_event_id"], ["acquisition_event.event_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("language IN ('fr', 'en')", name="ck_personalization_language"),
        sa.CheckConstraint("disposition IN ('READY', 'POLICY_BLOCKED')", name="ck_personalization_disposition"),
        sa.CheckConstraint("(disposition = 'READY' AND subject IS NOT NULL AND greeting IS NOT NULL AND body IS NOT NULL AND cta IS NOT NULL AND recorded_event_id IS NOT NULL) OR (disposition = 'POLICY_BLOCKED' AND subject IS NULL AND greeting IS NULL AND body IS NULL AND cta IS NULL AND recorded_event_id IS NULL)", name="ck_personalization_content"),
    )
    op.create_index("ix_personalization_opportunity_time", "acquisition_personalization_artifact", ["acquisition_opportunity_id", "created_at"])


def downgrade() -> None:
    op.drop_table("acquisition_personalization_artifact")
