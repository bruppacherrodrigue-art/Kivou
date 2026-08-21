"""Add suppression boundary and immutable acquisition compliance assessments."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_compliance"
down_revision = "0013_personalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_contact_suppression",
        sa.Column("suppression_id", sa.String(64), primary_key=True),
        sa.Column("identity_hmac", sa.String(64), nullable=False),
        sa.Column("identity_key_version", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(100), nullable=False),
        sa.Column("evidence_ref", sa.String(256), nullable=False),
        sa.Column("contact_ref", sa.String(64)),
        sa.Column("supplier_ref", sa.String(64)),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("minimum_retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_suppression_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_ref"], ["acquisition_contact.contact_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supplier_ref"], ["acquisition_supplier.supplier_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_suppression_id"],
            ["acquisition_contact_suppression.suppression_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("scope = 'KIVOU_ACQUISITION_EMAIL'", name="ck_suppression_scope"),
        sa.CheckConstraint(
            "source IN ('UNSUBSCRIBE', 'RECIPIENT_OBJECTION', 'MANUAL_VERIFIED', 'SYSTEM_IMPORT')",
            name="ck_suppression_source",
        ),
        sa.CheckConstraint(
            "minimum_retention_until >= received_at",
            name="ck_suppression_retention_order",
        ),
    )
    op.create_index(
        "ix_contact_suppression_identity",
        "acquisition_contact_suppression",
        ["identity_key_version", "identity_hmac", "scope"],
    )

    op.create_table(
        "acquisition_compliance_assessment",
        sa.Column("compliance_assessment_id", sa.String(64), primary_key=True),
        sa.Column("acquisition_opportunity_id", sa.String(64), nullable=False),
        sa.Column("personalization_artifact_id", sa.String(64), nullable=False),
        sa.Column("supplier_ref", sa.String(64), nullable=False),
        sa.Column("contact_ref", sa.String(64), nullable=False),
        sa.Column("policy_evaluation_id", sa.String(64), nullable=False, unique=True),
        sa.Column("jurisdiction", sa.String(64), nullable=False),
        sa.Column("jurisdiction_resolver_version", sa.String(64), nullable=False),
        sa.Column("ruleset_version", sa.String(64), nullable=False),
        sa.Column("ruleset_config_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_version", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("proposal_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_action_fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("policy_status", sa.String(32), nullable=False),
        sa.Column("policy_counterfactual_status", sa.String(32)),
        sa.Column("expected_post_policy_version", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("next_action", sa.String(100)),
        sa.Column("recorded_event_id", sa.String(64), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["acquisition_opportunity_id"],
            ["acquisition_opportunity.acquisition_opportunity_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["personalization_artifact_id"],
            ["acquisition_personalization_artifact.personalization_artifact_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_ref"], ["acquisition_supplier.supplier_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["contact_ref"], ["acquisition_contact.contact_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["policy_evaluation_id"],
            ["policy_evaluation.evaluation_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_event_id"], ["acquisition_event.event_id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "state IN ('ALLOWED', 'BLOCKED', 'REVIEW_REQUIRED', 'UNKNOWN')",
            name="ck_compliance_assessment_state",
        ),
        sa.CheckConstraint(
            "disposition IN ('RECORDED', 'POLICY_BLOCKED')",
            name="ck_compliance_assessment_disposition",
        ),
        sa.CheckConstraint(
            "(disposition = 'RECORDED' AND recorded_event_id IS NOT NULL) OR "
            "(disposition = 'POLICY_BLOCKED' AND recorded_event_id IS NULL)",
            name="ck_compliance_assessment_recorded_event",
        ),
        sa.CheckConstraint(
            "(state = 'ALLOWED' AND next_action IS NOT NULL AND "
            "next_action = 'schedule_campaign') OR "
            "(state = 'REVIEW_REQUIRED' AND next_action IS NOT NULL AND "
            "next_action = 'request_human_review') OR "
            "(state = 'UNKNOWN' AND "
            "(next_action = 'request_human_review' OR next_action IS NULL)) OR "
            "(state = 'BLOCKED' AND next_action IS NULL)",
            name="ck_compliance_assessment_next_action",
        ),
        sa.CheckConstraint(
            "(state = 'ALLOWED' AND valid_until IS NOT NULL) OR "
            "(state != 'ALLOWED' AND valid_until IS NULL)",
            name="ck_compliance_assessment_validity",
        ),
        sa.CheckConstraint(
            "expected_post_policy_version >= 2",
            name="ck_compliance_assessment_expected_version",
        ),
    )
    op.create_index(
        "ix_compliance_assessment_opportunity_time",
        "acquisition_compliance_assessment",
        ["acquisition_opportunity_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("acquisition_compliance_assessment")
    op.drop_table("acquisition_contact_suppression")
