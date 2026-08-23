"""Add immutable learning snapshots and allocation proposals.

Revision ID: 0020_hermes_learning_loop
Revises: 0019_conversion_tracking
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_hermes_learning_loop"
down_revision = "0019_conversion_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_learning_snapshot",
        sa.Column("snapshot_ref", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("learning_version", sa.String(64), nullable=False),
        sa.Column("formula_version", sa.String(64), nullable=False),
        sa.Column("formula_fingerprint", sa.String(64), nullable=False),
        sa.Column("risk_policy_version", sa.String(64), nullable=False),
        sa.Column("risk_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("cost_policy_version", sa.String(64), nullable=False),
        sa.Column("cost_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("cell_metrics", sa.JSON, nullable=False),
        sa.Column("allocation_envelope_version", sa.String(64), nullable=False),
        sa.Column("allocation_envelope_fingerprint", sa.String(64), nullable=False),
        sa.Column("current_allocation_fingerprint", sa.String(64), nullable=False),
        sa.Column("previous_applied_proposal_ref", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("window_start < window_end", name="ck_learning_snapshot_window"),
        sa.CheckConstraint("window_end <= captured_at", name="ck_learning_snapshot_capture"),
    )
    op.create_index(
        "ix_learning_snapshot_window",
        "acquisition_learning_snapshot",
        ["window_end", "captured_at"],
    )
    op.create_table(
        "acquisition_allocation_proposal",
        sa.Column("proposal_ref", sa.String(64), primary_key=True),
        sa.Column("snapshot_ref", sa.String(64), nullable=False),
        sa.Column("proposal_version", sa.String(64), nullable=False),
        sa.Column("candidate_version", sa.String(64), nullable=False),
        sa.Column("allocation_envelope_fingerprint", sa.String(64), nullable=False),
        sa.Column("baseline_authority_ref", sa.String(256), nullable=False),
        sa.Column("current_allocation_fingerprint", sa.String(64), nullable=False),
        sa.Column("proposed_allocation_fingerprint", sa.String(64), nullable=False),
        sa.Column("current_allocation", sa.JSON, nullable=False),
        sa.Column("proposed_allocation", sa.JSON, nullable=False),
        sa.Column("from_country", sa.String(2)),
        sa.Column("from_wedge", sa.String(100)),
        sa.Column("to_country", sa.String(2)),
        sa.Column("to_wedge", sa.String(100)),
        sa.Column("delta_units", sa.Integer, nullable=False),
        sa.Column("expected_score_delta", sa.Numeric(24, 8), nullable=False),
        sa.Column("reason_codes", sa.JSON, nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("selection_source", sa.String(32)),
        sa.Column("selection_reason_codes", sa.JSON),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("policy_evaluation_id", sa.String(64)),
        sa.Column("policy_action_fingerprint", sa.String(64)),
        sa.Column("policy_status", sa.String(32)),
        sa.Column("policy_counterfactual_status", sa.String(32)),
        sa.Column("decision_reason", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["snapshot_ref"],
            ["acquisition_learning_snapshot.snapshot_ref"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("delta_units IN (0, 1)", name="ck_learning_proposal_delta"),
        sa.CheckConstraint(
            "state IN ('PROPOSED', 'SHADOW_ONLY', 'POLICY_DENIED', 'APPLIED', 'REJECTED')",
            name="ck_learning_proposal_state",
        ),
        sa.CheckConstraint(
            "selection_source IS NULL OR selection_source IN ('KIVOU_NO_CHANGE', 'HERMES')",
            name="ck_learning_proposal_selection",
        ),
        sa.CheckConstraint(
            "(selection_source IS NULL AND confidence IS NULL "
            "AND selection_reason_codes IS NULL) OR "
            "(selection_source IS NOT NULL AND confidence IS NOT NULL "
            "AND selection_reason_codes IS NOT NULL)",
            name="ck_learning_proposal_selection_fields",
        ),
        sa.CheckConstraint(
            "(delta_units = 0 AND from_country IS NULL AND from_wedge IS NULL "
            "AND to_country IS NULL AND to_wedge IS NULL) OR "
            "(delta_units = 1 AND from_country IS NOT NULL AND from_wedge IS NOT NULL "
            "AND to_country IS NOT NULL AND to_wedge IS NOT NULL)",
            name="ck_learning_proposal_cells",
        ),
        sa.CheckConstraint(
            "(state = 'APPLIED' AND decided_at IS NOT NULL AND applied_at IS NOT NULL) OR "
            "(state <> 'APPLIED' AND applied_at IS NULL)",
            name="ck_learning_proposal_application",
        ),
    )
    op.create_index(
        "ix_learning_proposal_snapshot",
        "acquisition_allocation_proposal",
        ["snapshot_ref", "created_at"],
    )
    op.create_index(
        "uq_learning_snapshot_selected_proposal",
        "acquisition_allocation_proposal",
        ["snapshot_ref"],
        unique=True,
        sqlite_where=sa.text("selection_source IS NOT NULL"),
        postgresql_where=sa.text("selection_source IS NOT NULL"),
    )
    op.create_index(
        "uq_learning_applied_successor",
        "acquisition_allocation_proposal",
        ["allocation_envelope_fingerprint", "baseline_authority_ref"],
        unique=True,
        sqlite_where=sa.text("state = 'APPLIED'"),
        postgresql_where=sa.text("state = 'APPLIED'"),
    )


def downgrade() -> None:
    op.drop_table("acquisition_allocation_proposal")
    op.drop_table("acquisition_learning_snapshot")
