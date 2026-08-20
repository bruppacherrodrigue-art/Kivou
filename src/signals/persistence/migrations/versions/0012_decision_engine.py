"""Add append-only deterministic acquisition decision evaluation audit."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_decision_engine"
down_revision = "0011_company_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_decision_evaluation",
        sa.Column("decision_evaluation_id", sa.String(64), primary_key=True),
        sa.Column("acquisition_opportunity_id", sa.String(64), nullable=False),
        sa.Column("policy_evaluation_id", sa.String(64), nullable=False, unique=True),
        sa.Column("decision_input_version", sa.String(64), nullable=False),
        sa.Column("decision_input_fingerprint", sa.String(64), nullable=False),
        sa.Column("decision_input", sa.JSON(), nullable=False),
        sa.Column("company_prebuild_fingerprint", sa.String(64), nullable=False),
        sa.Column("representative_award_key", sa.String(256), nullable=False),
        sa.Column("recency_basis", sa.String(32), nullable=False),
        sa.Column("recency_date", sa.Date()),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("age_days", sa.Integer()),
        sa.Column("decision_policy_version", sa.String(64), nullable=False),
        sa.Column("decision_policy_config_fingerprint", sa.String(64), nullable=False),
        sa.Column("proposed_decision", sa.String(16), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("proposed_next_action", sa.String(100)),
        sa.Column("proposed_next_review_at", sa.DateTime(timezone=True)),
        sa.Column("proposal_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_status", sa.String(32), nullable=False),
        sa.Column("policy_counterfactual_status", sa.String(32)),
        sa.Column("expected_post_policy_version", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("recorded_event_id", sa.String(64), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["acquisition_opportunity_id"],
            ["acquisition_opportunity.acquisition_opportunity_id"],
            ondelete="RESTRICT",
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
            "proposed_decision IN ('SEND', 'REVIEW', 'NO_SEND')",
            name="ck_decision_eval_decision",
        ),
        sa.CheckConstraint(
            "disposition IN ('POLICY_BLOCKED', 'RECORDED')",
            name="ck_decision_eval_disposition",
        ),
        sa.CheckConstraint(
            "(disposition = 'RECORDED' AND recorded_event_id IS NOT NULL) OR "
            "(disposition = 'POLICY_BLOCKED' AND recorded_event_id IS NULL)",
            name="ck_decision_eval_recorded_event",
        ),
        sa.CheckConstraint(
            "(recency_basis = 'UNRESOLVED' AND recency_date IS NULL AND age_days IS NULL) OR "
            "(recency_basis IN ('AWARD_DATE', 'CONTRACT_NOTIFICATION_DATE', "
            "'PUBLICATION_DATE') AND recency_date IS NOT NULL AND age_days IS NOT NULL)",
            name="ck_decision_eval_recency",
        ),
        sa.CheckConstraint(
            "(proposed_decision = 'SEND' AND proposed_next_action = 'prepare_campaign') OR "
            "(proposed_decision = 'REVIEW' AND "
            "proposed_next_action = 'request_human_review') OR "
            "(proposed_decision = 'NO_SEND' AND proposed_next_action IS NULL)",
            name="ck_decision_eval_next_action",
        ),
        sa.CheckConstraint(
            "proposed_next_review_at IS NULL", name="ck_decision_eval_no_hold_v1"
        ),
        sa.CheckConstraint(
            "expected_post_policy_version >= 2", name="ck_decision_eval_expected_version"
        ),
    )
    op.create_index(
        "ix_acquisition_decision_evaluation_disposition",
        "acquisition_decision_evaluation",
        ["disposition"],
    )
    op.create_index(
        "ix_decision_evaluation_opportunity_time",
        "acquisition_decision_evaluation",
        ["acquisition_opportunity_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("acquisition_decision_evaluation")
