"""Add the append-auditable SPEC-027 response evaluation.

Revision ID: 0018_response_intelligence
Revises: 0017_target_icp_revision
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_response_intelligence"
down_revision = "0017_target_icp_revision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_response_evaluation",
        sa.Column("response_evaluation_id", sa.String(64), primary_key=True),
        sa.Column("response_ref", sa.String(64), nullable=False),
        sa.Column("provider_event_ref", sa.String(64), nullable=False),
        sa.Column("campaign_ref", sa.String(64), nullable=False),
        sa.Column("member_ref", sa.String(64), nullable=False),
        sa.Column("acquisition_opportunity_id", sa.String(64), nullable=False),
        sa.Column("contact_ref", sa.String(64), nullable=False),
        sa.Column("provider_email_id", sa.String(128)),
        sa.Column("provider_thread_id", sa.String(128)),
        sa.Column("input_source", sa.String(32), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("content_fingerprint", sa.String(64)),
        sa.Column("content_fingerprint_version", sa.String(64)),
        sa.Column("content_fingerprint_key_version", sa.String(64)),
        sa.Column("resolver_version", sa.String(64), nullable=False),
        sa.Column("normalizer_version", sa.String(64), nullable=False),
        sa.Column("safety_version", sa.String(64), nullable=False),
        sa.Column("taxonomy_version", sa.String(64), nullable=False),
        sa.Column("classifier_version", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(100)),
        sa.Column("model_version", sa.String(100)),
        sa.Column("human_response_confirmed", sa.Boolean),
        sa.Column("classification", sa.String(32)),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("reason_codes", sa.JSON),
        sa.Column("hot_lead", sa.Boolean),
        sa.Column("review_required", sa.Boolean),
        sa.Column("next_action", sa.String(100)),
        sa.Column("policy_evaluation_id", sa.String(64)),
        sa.Column("policy_action_fingerprint", sa.String(64)),
        sa.Column("policy_status", sa.String(32)),
        sa.Column("estimated_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("actual_cost", sa.Numeric(18, 6)),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("processing_state", sa.String(16), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("lease_owner", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(100)),
        sa.Column("disposition", sa.String(64)),
        sa.Column("outcome_event_ref", sa.String(64)),
        sa.Column("next_action_event_ref", sa.String(64)),
        sa.Column("suppression_ref", sa.String(64)),
        sa.Column("supersedes_response_evaluation_id", sa.String(64)),
        sa.Column("reclassification_reason", sa.String(100)),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True)),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_event_ref"],
            ["acquisition_provider_event.provider_event_ref"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_ref"], ["acquisition_campaign.campaign_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["member_ref"],
            ["acquisition_campaign_member.member_ref"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_opportunity_id"],
            ["acquisition_opportunity.acquisition_opportunity_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["contact_ref"], ["acquisition_contact.contact_ref"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["policy_evaluation_id"], ["policy_evaluation.evaluation_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["outcome_event_ref"], ["acquisition_event.event_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["next_action_event_ref"], ["acquisition_event.event_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["suppression_ref"],
            ["acquisition_contact_suppression.suppression_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_response_evaluation_id"],
            ["acquisition_response_evaluation.response_evaluation_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "provider_event_ref", "classifier_version", name="uq_response_event_classifier"
        ),
        sa.UniqueConstraint(
            "response_ref", "classifier_version", name="uq_response_ref_classifier"
        ),
        sa.CheckConstraint(
            "input_source IN ('WEBHOOK_V2', 'INSTANTLY_EMAIL_V2')",
            name="ck_response_input_source",
        ),
        sa.CheckConstraint(
            "processing_state IN ('PLANNED', 'IN_FLIGHT', 'RETRY_WAIT', 'FINALIZED')",
            name="ck_response_processing_state",
        ),
        sa.CheckConstraint(
            "classification IS NULL OR classification IN "
            "('POSITIVE', 'NEGATIVE', 'UNSUBSCRIBE', 'WRONG_PERSON', 'REFERRAL', "
            "'OUT_OF_OFFICE', 'AUTO_REPLY', 'COMPLAINT', 'SENSITIVE', 'AMBIGUOUS')",
            name="ck_response_classification",
        ),
        sa.CheckConstraint(
            "hot_lead IS NULL OR hot_lead IS FALSE OR "
            "(classification = 'POSITIVE' AND confidence >= 0.85 "
            "AND human_response_confirmed IS TRUE AND review_required IS TRUE "
            "AND next_action = 'request_human_review')",
            name="ck_response_hot_invariant",
        ),
        sa.CheckConstraint(
            "classification IS NULL OR classification NOT IN ('AUTO_REPLY', 'OUT_OF_OFFICE') OR "
            "(human_response_confirmed IS FALSE AND hot_lead IS FALSE "
            "AND outcome_event_ref IS NULL)",
            name="ck_response_machine_invariant",
        ),
        sa.CheckConstraint(
            "next_action IS NULL OR next_action = 'request_human_review'",
            name="ck_response_next_action",
        ),
        sa.CheckConstraint(
            "(content_fingerprint IS NULL AND content_fingerprint_version IS NULL "
            "AND content_fingerprint_key_version IS NULL) OR "
            "(content_fingerprint IS NOT NULL AND content_fingerprint_version IS NOT NULL "
            "AND content_fingerprint_key_version IS NOT NULL)",
            name="ck_response_content_fingerprint",
        ),
        sa.CheckConstraint(
            "(processing_state = 'FINALIZED' AND classification IS NOT NULL "
            "AND confidence IS NOT NULL AND reason_codes IS NOT NULL "
            "AND hot_lead IS NOT NULL AND review_required IS NOT NULL "
            "AND human_response_confirmed IS NOT NULL AND disposition IS NOT NULL "
            "AND evaluated_at IS NOT NULL AND finalized_at IS NOT NULL "
            "AND lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(processing_state <> 'FINALIZED' AND classification IS NULL "
            "AND confidence IS NULL AND reason_codes IS NULL AND hot_lead IS NULL "
            "AND review_required IS NULL AND human_response_confirmed IS NULL "
            "AND disposition IS NULL AND evaluated_at IS NULL AND finalized_at IS NULL)",
            name="ck_response_finalization",
        ),
        sa.CheckConstraint(
            "attempt >= 0 AND estimated_cost >= 0 "
            "AND (actual_cost IS NULL OR actual_cost >= 0) "
            "AND (input_tokens IS NULL OR input_tokens >= 0) "
            "AND (output_tokens IS NULL OR output_tokens >= 0)",
            name="ck_response_usage",
        ),
        sa.CheckConstraint(
            "(supersedes_response_evaluation_id IS NULL AND reclassification_reason IS NULL) OR "
            "(supersedes_response_evaluation_id IS NOT NULL "
            "AND reclassification_reason IS NOT NULL)",
            name="ck_response_reclassification",
        ),
    )
    op.create_index(
        "ix_response_claim",
        "acquisition_response_evaluation",
        ["processing_state", "retry_at", "lease_expires_at"],
    )
    op.create_index(
        "ix_response_member_received",
        "acquisition_response_evaluation",
        ["member_ref", "received_at"],
    )


def downgrade() -> None:
    op.drop_table("acquisition_response_evaluation")
